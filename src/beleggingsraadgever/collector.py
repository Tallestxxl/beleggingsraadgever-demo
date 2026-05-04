"""Public-data collector for draft company snapshots."""

from __future__ import annotations

import csv
import html as html_lib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.error import URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from .importer import load_company_snapshot, validate_company_snapshot, write_snapshot_template
from .real_data import DRAFTS_DIR


FetchText = Callable[[str], str]

AMSTERDAM_ALIASES = {
    "ABNAMRO": "ABN",
    "ASM": "ASM",
    "ASMI": "ASM",
    "ASML": "ASML",
    "ADYEN": "ADYEN",
    "BESI": "BESI",
    "FUGRO": "FUR",
    "ING": "INGA",
    "KPN": "KPN",
    "SHELL": "SHELL",
}


@dataclass(frozen=True)
class MarketData:
    provider: str
    provider_symbol: str
    source_url: str
    as_of: str
    close_price: float
    currency: str
    momentum_12m: Optional[float]
    volatility_1y: Optional[float]
    statistics_url: Optional[str] = None
    company_name: Optional[str] = None
    description: Optional[str] = None
    period_end: Optional[str] = None
    period_type: Optional[str] = None
    revenue: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    free_cash_flow: Optional[float] = None
    debt: Optional[float] = None
    cash: Optional[float] = None
    shares_outstanding: Optional[float] = None
    dividend_per_share: Optional[float] = None
    pe_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None
    fcf_yield: Optional[float] = None
    dividend_yield: Optional[float] = None


@dataclass(frozen=True)
class StockAnalysisCandidate:
    provider_symbol: str
    source_url: str
    statistics_url: str
    financials_url: str


@dataclass(frozen=True)
class CollectionResult:
    symbol: str
    path: Path
    updated_fields: List[str] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def collect_snapshot_data(symbol: str, path: Optional[Path] = None, fetch_text: Optional[FetchText] = None) -> CollectionResult:
    """Collect public market data and prefill a draft snapshot."""

    normalized_symbol = symbol.strip().upper()
    destination = Path(path) if path else DRAFTS_DIR / f"{normalized_symbol.lower()}.json"
    if not destination.exists():
        write_snapshot_template(normalized_symbol, destination)

    fetcher = fetch_text or _fetch_url_text
    messages: List[str] = []
    try:
        market_data = collect_market_data(normalized_symbol, fetcher)
    except DataCollectionError as error:
        errors = [str(error)]
        errors.extend(validate_company_snapshot(load_company_snapshot(destination)))
        return CollectionResult(symbol=normalized_symbol, path=destination, messages=messages, errors=errors)

    updated_fields = update_snapshot_with_market_data(destination, market_data)
    messages.append(
        f"Marktdata opgehaald via {market_data.provider} ({market_data.provider_symbol}) t/m {market_data.as_of}."
    )
    errors = validate_company_snapshot(load_company_snapshot(destination))
    return CollectionResult(
        symbol=normalized_symbol,
        path=destination,
        updated_fields=updated_fields,
        messages=messages,
        errors=errors,
    )


def collect_market_data(symbol: str, fetch_text: Optional[FetchText] = None) -> MarketData:
    """Collect latest EOD market data for a symbol from public sources."""

    fetcher = fetch_text or _fetch_url_text
    errors: List[str] = []
    tried_stockanalysis_urls = set()
    for candidate in _stockanalysis_candidates(symbol):
        tried_stockanalysis_urls.add(candidate.source_url)
        try:
            overview_html = fetcher(candidate.source_url)
            if _is_stockanalysis_not_found(overview_html):
                raise DataCollectionError(f"StockAnalysis {candidate.provider_symbol}: pagina niet gevonden.")
            statistics_html = ""
            try:
                fetched_statistics_html = fetcher(candidate.statistics_url)
                if not _is_stockanalysis_not_found(fetched_statistics_html):
                    statistics_html = fetched_statistics_html
            except (DataCollectionError, OSError, URLError):
                statistics_html = ""
            financials_html = ""
            try:
                fetched_financials_html = fetcher(candidate.financials_url)
                if not _is_stockanalysis_not_found(fetched_financials_html):
                    financials_html = fetched_financials_html
            except (DataCollectionError, OSError, URLError):
                financials_html = ""
            return _market_data_from_stockanalysis(candidate, overview_html, statistics_html, financials_html)
        except DataCollectionError as error:
            errors.append(str(error))
        except (OSError, URLError) as error:
            errors.append(f"StockAnalysis {candidate.provider_symbol}: {error}")

    try:
        lookup_html = fetcher(_stockanalysis_lookup_url(symbol))
        lookup_candidates = [
            candidate
            for candidate in _stockanalysis_lookup_candidates(lookup_html)
            if candidate.source_url not in tried_stockanalysis_urls
        ]
    except (OSError, URLError, DataCollectionError) as error:
        lookup_candidates = []
        errors.append(f"StockAnalysis symbol lookup: {error}")

    for candidate in lookup_candidates:
        tried_stockanalysis_urls.add(candidate.source_url)
        try:
            overview_html = fetcher(candidate.source_url)
            if _is_stockanalysis_not_found(overview_html):
                raise DataCollectionError(f"StockAnalysis {candidate.provider_symbol}: pagina niet gevonden.")
            statistics_html = ""
            try:
                fetched_statistics_html = fetcher(candidate.statistics_url)
                if not _is_stockanalysis_not_found(fetched_statistics_html):
                    statistics_html = fetched_statistics_html
            except (DataCollectionError, OSError, URLError):
                statistics_html = ""
            financials_html = ""
            try:
                fetched_financials_html = fetcher(candidate.financials_url)
                if not _is_stockanalysis_not_found(fetched_financials_html):
                    financials_html = fetched_financials_html
            except (DataCollectionError, OSError, URLError):
                financials_html = ""
            return _market_data_from_stockanalysis(candidate, overview_html, statistics_html, financials_html)
        except DataCollectionError as error:
            errors.append(str(error))
        except (OSError, URLError) as error:
            errors.append(f"StockAnalysis {candidate.provider_symbol}: {error}")

    for provider_symbol in _stooq_candidates(symbol):
        url = _stooq_url(provider_symbol)
        try:
            rows = _parse_stooq_csv(fetcher(url))
            if rows:
                return _market_data_from_rows(
                    provider="Stooq",
                    provider_symbol=provider_symbol,
                    source_url=url,
                    currency="EUR",
                    rows=rows,
                )
        except DataCollectionError as error:
            errors.append(str(error))
        except (OSError, URLError) as error:
            errors.append(f"Stooq {provider_symbol}: {error}")

    raise DataCollectionError("Geen publieke marktdata gevonden. " + " | ".join(errors[:3]))


def update_snapshot_with_market_data(path: Path, market_data: MarketData) -> List[str]:
    """Write collected market data into an existing draft snapshot."""

    data = load_company_snapshot(path)
    financial = data.setdefault("financial_snapshot", {})
    market = data.setdefault("market_snapshot", {})
    market["as_of"] = market_data.as_of
    market["close_price"] = round(market_data.close_price, 4)
    market["currency"] = market_data.currency

    updated_fields = ["as_of", "close_price", "currency"]
    financial_updates = {
        "period_end": market_data.period_end,
        "period_type": market_data.period_type,
        "revenue": market_data.revenue,
        "gross_margin": market_data.gross_margin,
        "operating_margin": market_data.operating_margin,
        "net_margin": market_data.net_margin,
        "free_cash_flow": market_data.free_cash_flow,
        "debt": market_data.debt,
        "cash": market_data.cash,
        "shares_outstanding": market_data.shares_outstanding,
        "dividend_per_share": market_data.dividend_per_share,
    }
    for field_name, value in financial_updates.items():
        if value is None:
            continue
        financial[field_name] = round(value, 6) if isinstance(value, float) else value
        updated_fields.append(field_name)

    market_updates = {
        "pe_ratio": market_data.pe_ratio,
        "ev_ebitda": market_data.ev_ebitda,
        "fcf_yield": market_data.fcf_yield,
        "dividend_yield": market_data.dividend_yield,
    }
    for field_name, value in market_updates.items():
        if value is None:
            continue
        market[field_name] = round(value, 6)
        updated_fields.append(field_name)

    if market_data.momentum_12m is not None:
        market["momentum_12m"] = round(market_data.momentum_12m, 4)
        updated_fields.append("momentum_12m")
    if market_data.volatility_1y is not None:
        market["volatility_1y"] = round(market_data.volatility_1y, 4)
        updated_fields.append("volatility_1y")

    data["data_sources"] = _merge_data_sources(
        data.get("data_sources", []),
        _market_data_sources(market_data),
    )
    data["documents"] = _update_summary_document(
        str(data.get("symbol", "")).upper(),
        data.get("documents", []),
        market_data,
    )
    data["documents"] = _update_market_document(
        str(data.get("symbol", "")).upper(),
        data.get("documents", []),
        market_data,
    )

    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return updated_fields


class DataCollectionError(RuntimeError):
    """Raised when public data collection fails."""


def _fetch_url_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "beleggingsraadgever/0.1"})
    with urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8")


def _stockanalysis_candidates(symbol: str) -> Iterable[StockAnalysisCandidate]:
    normalized_symbol = symbol.strip().upper()
    candidates: List[tuple[str, str]] = []

    if ":" in normalized_symbol:
        exchange, ticker = normalized_symbol.split(":", 1)
        if exchange == "AMS" and ticker:
            candidates.append((f"AMS:{ticker}", f"quote/ams/{ticker}/"))
    elif normalized_symbol.endswith(".AS"):
        ticker = normalized_symbol[:-3]
        candidates.append((f"AMS:{ticker}", f"quote/ams/{ticker}/"))
    else:
        alias = AMSTERDAM_ALIASES.get(normalized_symbol)
        if alias:
            candidates.append((f"AMS:{alias}", f"quote/ams/{alias}/"))
        candidates.append((normalized_symbol, f"stocks/{normalized_symbol.lower()}/"))
        candidates.append((f"AMS:{normalized_symbol}", f"quote/ams/{normalized_symbol}/"))

    seen = set()
    for provider_symbol, path in candidates:
        if path in seen:
            continue
        seen.add(path)
        base_url = f"https://stockanalysis.com/{path}"
        yield StockAnalysisCandidate(
            provider_symbol=provider_symbol,
            source_url=base_url,
            statistics_url=f"{base_url}statistics/",
            financials_url=f"{base_url}financials/",
        )


def _stockanalysis_lookup_url(symbol: str) -> str:
    return f"https://stockanalysis.com/symbol-lookup/?q={quote_plus(symbol.strip())}"


def _stockanalysis_lookup_candidates(raw_html: str) -> Iterable[StockAnalysisCandidate]:
    seen = set()
    for lookup_symbol in _parse_stockanalysis_lookup_symbols(raw_html):
        candidate = _stockanalysis_candidate_from_lookup_symbol(lookup_symbol)
        if candidate is None or candidate.source_url in seen:
            continue
        seen.add(candidate.source_url)
        yield candidate


def _parse_stockanalysis_lookup_symbols(raw_html: str) -> List[str]:
    symbols: List[str] = []
    for match in re.finditer(r'\{s:"([^"]+)",n:"(?:\\.|[^"])*",t:"Stock"', raw_html):
        symbols.append(_decode_js_string(match.group(1)))
    for match in re.finditer(r'href="/(stocks/[A-Za-z0-9.\-]+/|quote/[a-z]+/[A-Za-z0-9.\-]+/)"', raw_html):
        path = match.group(1)
        if path.startswith("stocks/"):
            symbols.append(path.removeprefix("stocks/").strip("/").upper())
        else:
            _, exchange, ticker = path.strip("/").split("/", 2)
            symbols.append(f"@{exchange}/{ticker.strip('/')}")
    return symbols


def _stockanalysis_candidate_from_lookup_symbol(lookup_symbol: str) -> Optional[StockAnalysisCandidate]:
    symbol = lookup_symbol.strip()
    if not symbol:
        return None
    if symbol.startswith("@") and "/" in symbol:
        exchange, ticker = symbol[1:].split("/", 1)
        exchange = exchange.strip().lower()
        ticker = ticker.strip().upper()
        if not exchange or not ticker:
            return None
        return _stockanalysis_candidate_from_path(f"{exchange.upper()}:{ticker}", f"quote/{exchange}/{ticker}/")
    if ":" in symbol:
        exchange, ticker = symbol.split(":", 1)
        exchange = exchange.strip().lower()
        ticker = ticker.strip().upper()
        if not exchange or not ticker:
            return None
        return _stockanalysis_candidate_from_path(f"{exchange.upper()}:{ticker}", f"quote/{exchange}/{ticker}/")
    ticker = symbol.upper()
    return _stockanalysis_candidate_from_path(ticker, f"stocks/{ticker.lower()}/")


def _stockanalysis_candidate_from_path(provider_symbol: str, path: str) -> StockAnalysisCandidate:
    base_url = f"https://stockanalysis.com/{path}"
    return StockAnalysisCandidate(
        provider_symbol=provider_symbol,
        source_url=base_url,
        statistics_url=f"{base_url}statistics/",
        financials_url=f"{base_url}financials/",
    )


def _stooq_candidates(symbol: str) -> Iterable[str]:
    normalized_symbol = symbol.strip().upper()
    bases = []
    alias = AMSTERDAM_ALIASES.get(normalized_symbol)
    if alias:
        bases.append(alias)
    bases.append(normalized_symbol)

    seen = set()
    for base in bases:
        stooq_symbol = f"{base.lower()}.nl"
        if stooq_symbol not in seen:
            seen.add(stooq_symbol)
            yield stooq_symbol


def _stooq_url(provider_symbol: str) -> str:
    start = (date.today() - timedelta(days=370)).strftime("%Y%m%d")
    return f"https://stooq.com/q/d/l/?s={provider_symbol}&d1={start}&i=d"


def _parse_stooq_csv(raw_csv: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(StringIO(raw_csv))
    rows: List[Dict[str, Any]] = []
    for row in reader:
        if not row or row.get("Close") in {None, "", "N/D"}:
            continue
        try:
            rows.append(
                {
                    "date": date.fromisoformat(str(row["Date"])),
                    "close": float(str(row["Close"]).replace(",", ".")),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not rows:
        raise DataCollectionError("Stooq gaf geen bruikbare koersregels terug.")
    return sorted(rows, key=lambda item: item["date"])


def _market_data_from_rows(
    *,
    provider: str,
    provider_symbol: str,
    source_url: str,
    currency: str,
    rows: List[Dict[str, Any]],
) -> MarketData:
    latest = rows[-1]
    latest_date = latest["date"]
    latest_close = float(latest["close"])
    one_year_ago = latest_date - timedelta(days=365)
    window = [row for row in rows if row["date"] >= one_year_ago]
    first_close = float(window[0]["close"]) if window else None
    momentum = (latest_close / first_close - 1.0) if first_close else None

    returns: List[float] = []
    previous_close: Optional[float] = None
    for row in window:
        close = float(row["close"])
        if previous_close and previous_close > 0 and close > 0:
            returns.append(math.log(close / previous_close))
        previous_close = close
    volatility = _annualized_volatility(returns)

    return MarketData(
        provider=provider,
        provider_symbol=provider_symbol,
        source_url=source_url,
        as_of=latest_date.isoformat(),
        close_price=latest_close,
        currency=currency,
        momentum_12m=momentum,
        volatility_1y=volatility,
    )


def _market_data_from_stockanalysis(
    candidate: StockAnalysisCandidate,
    overview_html: str,
    statistics_html: str,
    financials_html: str,
) -> MarketData:
    quote_block = _extract_simple_object(overview_html, "quote")
    rows = _parse_stockanalysis_chart_rows(overview_html)
    daily_rows = _daily_chart_rows(rows)
    currency = (
        _extract_string_from_block(_extract_simple_object(overview_html, "curr"), "price")
        or _extract_string_from_block(_extract_simple_object(overview_html, "curr"), "main")
        or "EUR"
    )

    if daily_rows:
        base = _market_data_from_rows(
            provider="StockAnalysis",
            provider_symbol=candidate.provider_symbol,
            source_url=candidate.source_url,
            currency=currency,
            rows=daily_rows,
        )
    else:
        close_price = _extract_number_from_block(quote_block, "cl") or _extract_number_from_block(quote_block, "p")
        as_of = _extract_string_from_block(quote_block, "td") or date.today().isoformat()
        if close_price is None:
            raise DataCollectionError(f"StockAnalysis {candidate.provider_symbol}: geen bruikbare slotkoers gevonden.")
        base = MarketData(
            provider="StockAnalysis",
            provider_symbol=candidate.provider_symbol,
            source_url=candidate.source_url,
            as_of=as_of,
            close_price=close_price,
            currency=currency,
            momentum_12m=_metric_percent(statistics_html, "ch1y")
            or _extract_percent_from_key(overview_html, "ch1y"),
            volatility_1y=None,
        )

    data_html = statistics_html or overview_html
    revenue = _metric_number(data_html, "revenue") or _extract_scaled_string_from_key(overview_html, "revenue")
    free_cash_flow = _metric_number(data_html, "fcf")
    period_end = _extract_last_trailing_date(financials_html) or (base.as_of if revenue is not None else None)
    return MarketData(
        provider=base.provider,
        provider_symbol=base.provider_symbol,
        source_url=base.source_url,
        as_of=base.as_of,
        close_price=base.close_price,
        currency=base.currency,
        momentum_12m=base.momentum_12m or _metric_percent(data_html, "ch1y"),
        volatility_1y=base.volatility_1y,
        statistics_url=candidate.statistics_url if statistics_html else None,
        company_name=_extract_string_from_block(_extract_simple_object(overview_html, "info"), "nameFull")
        or _extract_json_ld_name(overview_html),
        description=_extract_string_from_key(overview_html, "description"),
        period_end=period_end,
        period_type="TTM" if revenue is not None else None,
        revenue=revenue,
        gross_margin=_metric_percent(data_html, "grossMargin"),
        operating_margin=_metric_percent(data_html, "operatingMargin"),
        net_margin=_metric_percent(data_html, "profitMargin"),
        free_cash_flow=free_cash_flow,
        debt=_metric_number(data_html, "debt"),
        cash=_metric_number(data_html, "totalcash"),
        shares_outstanding=_metric_number(data_html, "sharesout")
        or _extract_scaled_string_from_key(overview_html, "sharesOut"),
        dividend_per_share=_metric_number(data_html, "dps"),
        pe_ratio=_metric_number(data_html, "pe") or _extract_scaled_string_from_key(overview_html, "peRatio"),
        ev_ebitda=_metric_number(data_html, "evEbitda"),
        fcf_yield=_metric_percent(data_html, "fcfYield")
        or _fcf_yield_from_values(free_cash_flow, _metric_number(data_html, "marketcap")),
        dividend_yield=_metric_percent(data_html, "dividendYield")
        or _extract_percent_from_key(overview_html, "dividendYield"),
    )


def _annualized_volatility(returns: List[float]) -> Optional[float]:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)


def _market_data_sources(market_data: MarketData) -> List[Dict[str, str]]:
    market_common = {
        "source_name": f"{market_data.provider} quote en koersen",
        "source_url": market_data.source_url,
        "source_date": market_data.as_of,
        "source_quality": "marktdata",
    }
    sources = [
        {
            "field_name": "close_price",
            "value_label": f"Slotkoers {market_data.currency} {market_data.close_price:,.2f}",
            **market_common,
            "note": "Automatisch opgehaald als end-of-day koerspunt.",
        }
    ]
    if market_data.momentum_12m is not None:
        sources.append(
            {
                "field_name": "momentum_12m",
                "value_label": f"12-maands momentum {market_data.momentum_12m:.2%}",
                **market_common,
                "note": "Automatisch berekend uit de eerste en laatste beschikbare slotkoers in het 1-jaars venster.",
            }
        )
    if market_data.volatility_1y is not None:
        sources.append(
            {
                "field_name": "volatility_1y",
                "value_label": f"1-jaars volatiliteit {market_data.volatility_1y:.2%}",
                **market_common,
                "note": "Automatisch berekend uit dagelijkse log-rendementen en geannualiseerd met 252 handelsdagen.",
            }
        )

    valuation_common = {
        "source_name": f"{market_data.provider} waarderingsstatistieken",
        "source_url": market_data.statistics_url or market_data.source_url,
        "source_date": market_data.as_of,
        "source_quality": "waardering",
    }
    valuation_fields = [
        ("pe_ratio", market_data.pe_ratio, "Koers-winstverhouding", "{:.2f}"),
        ("ev_ebitda", market_data.ev_ebitda, "EV/EBITDA", "{:.2f}"),
        ("fcf_yield", market_data.fcf_yield, "FCF-yield", "{:.2%}"),
        ("dividend_yield", market_data.dividend_yield, "Dividendrendement", "{:.2%}"),
    ]
    for field_name, value, label, formatter in valuation_fields:
        if value is None:
            continue
        sources.append(
            {
                "field_name": field_name,
                "value_label": f"{label} {formatter.format(value)}",
                **valuation_common,
                "note": "Automatisch opgehaald uit publieke waarderingsstatistieken; handmatige controle blijft gewenst.",
            }
        )

    fundamentals_common = {
        "source_name": f"{market_data.provider} financiële statistieken",
        "source_url": market_data.statistics_url or market_data.source_url,
        "source_date": market_data.period_end or market_data.as_of,
        "source_quality": "fundamentals",
    }
    fundamental_fields = [
        ("revenue", market_data.revenue, "Omzet", _format_amount),
        ("gross_margin", market_data.gross_margin, "Brutomarge", _format_percent),
        ("operating_margin", market_data.operating_margin, "Operationele marge", _format_percent),
        ("net_margin", market_data.net_margin, "Nettomarge", _format_percent),
        ("free_cash_flow", market_data.free_cash_flow, "Vrije kasstroom", _format_amount),
        ("debt", market_data.debt, "Schuld", _format_amount),
        ("cash", market_data.cash, "Cash", _format_amount),
        ("shares_outstanding", market_data.shares_outstanding, "Uitstaande aandelen", _format_count),
        ("dividend_per_share", market_data.dividend_per_share, "Dividend per aandeel", _format_amount),
    ]
    for field_name, value, label, formatter in fundamental_fields:
        if value is None:
            continue
        sources.append(
            {
                "field_name": field_name,
                "value_label": f"{label} {formatter(value, market_data.currency)}",
                **fundamentals_common,
                "note": "Automatisch opgehaald uit publieke financiële statistieken; verifieer met jaarverslag/kwartaalbericht.",
            }
        )
    return sources


def _merge_data_sources(existing_sources: List[Dict[str, str]], new_sources: List[Dict[str, str]]) -> List[Dict[str, str]]:
    by_field = {source.get("field_name"): source for source in existing_sources if isinstance(source, dict)}
    for source in new_sources:
        by_field[source["field_name"]] = source
    return list(by_field.values())


def _update_market_document(symbol: str, documents: List[Dict[str, object]], market_data: MarketData) -> List[Dict[str, object]]:
    title = f"{symbol} automatisch opgehaalde marktdata"
    raw_text = (
        f"Automatisch opgehaalde marktdata voor {symbol} via {market_data.provider} "
        f"({market_data.provider_symbol}) tot en met {market_data.as_of}. "
        f"Slotkoers: {market_data.currency} {market_data.close_price:,.2f}. "
        f"12-maands momentum: {_format_optional_percent(market_data.momentum_12m)}. "
        f"1-jaars volatiliteit: {_format_optional_percent(market_data.volatility_1y)}. "
        "Fundamentele cijfers, waardering, concurrentiepositie en managementsignalen moeten nog apart worden gecontroleerd."
    )
    document = {
        "title": title,
        "source_type": "public_market_data",
        "author": "Beleggingsraadgever datacollector",
        "publication_date": market_data.as_of,
        "source_path": market_data.source_url,
        "tags": [symbol, "marktdata", "momentum", "volatiliteit"],
        "raw_text": raw_text,
    }
    return [doc for doc in documents if not isinstance(doc, dict) or doc.get("title") != title] + [document]


def _update_summary_document(symbol: str, documents: List[Dict[str, object]], market_data: MarketData) -> List[Dict[str, object]]:
    title = f"{symbol} eerste snapshot"
    facts = [
        f"Datacollector-snapshot voor {symbol}"
        + (f" ({market_data.company_name})" if market_data.company_name else "")
        + f" via {market_data.provider} ({market_data.provider_symbol}).",
        f"Koersdata tot en met {market_data.as_of}: {market_data.currency} {market_data.close_price:,.2f}.",
    ]
    if market_data.description:
        facts.append(f"Bedrijfsomschrijving uit bron: {market_data.description}")
    if market_data.revenue is not None:
        facts.append(f"Omzet ({market_data.period_type or 'periode'}): {_format_amount(market_data.revenue, market_data.currency)}.")
    if market_data.operating_margin is not None:
        facts.append(f"Operationele marge: {_format_percent(market_data.operating_margin, market_data.currency)}.")
    if market_data.free_cash_flow is not None:
        facts.append(f"Vrije kasstroom: {_format_amount(market_data.free_cash_flow, market_data.currency)}.")
    if market_data.debt is not None or market_data.cash is not None:
        facts.append(
            "Balans: "
            f"schuld {_format_optional_amount(market_data.debt, market_data.currency)}, "
            f"cash {_format_optional_amount(market_data.cash, market_data.currency)}."
        )
    if market_data.pe_ratio is not None or market_data.ev_ebitda is not None or market_data.dividend_yield is not None:
        facts.append(
            "Waardering: "
            f"K/W {_format_optional_number(market_data.pe_ratio)}, "
            f"EV/EBITDA {_format_optional_number(market_data.ev_ebitda)}, "
            f"dividendrendement {_format_optional_percent(market_data.dividend_yield)}."
        )
    facts.append(
        "Deze tekst is automatisch voorgevuld. Concurrentiepositie, cycliciteit, managementsignalen en risico moeten nog door jou worden aangevuld."
    )
    document = {
        "title": title,
        "source_type": "public_data_snapshot",
        "author": "Beleggingsraadgever datacollector",
        "publication_date": market_data.as_of,
        "source_path": market_data.statistics_url or market_data.source_url,
        "tags": [symbol, "datacollector", "fundamentals", "waardering"],
        "raw_text": " ".join(facts),
    }
    return [
        doc
        for doc in documents
        if not isinstance(doc, dict) or doc.get("title") != title
    ] + [document]


def _format_optional_percent(value: Optional[float]) -> str:
    if value is None:
        return "niet beschikbaar"
    return f"{value:.2%}"


def _format_percent(value: float, _currency: str) -> str:
    return f"{value:.2%}"


def _format_amount(value: float, currency: str) -> str:
    absolute = abs(value)
    sign = "-" if value < 0 else ""
    if absolute >= 1_000_000_000_000:
        return f"{sign}{currency} {absolute / 1_000_000_000_000:.2f} bln"
    if absolute >= 1_000_000_000:
        return f"{sign}{currency} {absolute / 1_000_000_000:.2f} mld"
    if absolute >= 1_000_000:
        return f"{sign}{currency} {absolute / 1_000_000:.2f} mln"
    return f"{currency} {value:,.2f}"


def _format_optional_amount(value: Optional[float], currency: str) -> str:
    if value is None:
        return "niet beschikbaar"
    return _format_amount(value, currency)


def _format_count(value: float, _currency: str) -> str:
    absolute = abs(value)
    sign = "-" if value < 0 else ""
    if absolute >= 1_000_000_000:
        return f"{sign}{absolute / 1_000_000_000:.2f} mld"
    if absolute >= 1_000_000:
        return f"{sign}{absolute / 1_000_000:.2f} mln"
    return f"{value:,.0f}"


def _format_optional_number(value: Optional[float]) -> str:
    if value is None:
        return "niet beschikbaar"
    return f"{value:.2f}"


def _is_stockanalysis_not_found(raw_html: str) -> bool:
    return "Page Not Found - 404" in raw_html or 'error: {message:"not found"}' in raw_html


def _parse_stockanalysis_chart_rows(raw_html: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    number_pattern = r"-?(?:\d+(?:\.\d*)?|\.\d+)"
    for match in re.finditer(rf"\{{c:({number_pattern})(?:,o:{number_pattern})?,t:(\d+)\}}", raw_html):
        try:
            timestamp = int(match.group(2))
            rows.append(
                {
                    "date": datetime.fromtimestamp(timestamp, timezone.utc).date(),
                    "close": float(match.group(1)),
                }
            )
        except (OverflowError, ValueError):
            continue
    return rows


def _daily_chart_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(rows) < 30:
        return []
    by_date: Dict[date, float] = {}
    for row in rows:
        by_date[row["date"]] = row["close"]
    daily_rows = [{"date": day, "close": close} for day, close in sorted(by_date.items())]
    if len(daily_rows) < 30:
        return []
    if (daily_rows[-1]["date"] - daily_rows[0]["date"]).days < 200:
        return []
    return daily_rows


def _extract_simple_object(raw_text: str, object_name: str) -> str:
    match = re.search(rf"{re.escape(object_name)}:\{{([^{{}}]*)\}}", raw_text)
    return match.group(1) if match else ""


def _extract_string_from_block(block: str, key: str) -> Optional[str]:
    match = re.search(rf"{re.escape(key)}:\"((?:\\.|[^\"])*)\"", block)
    if not match:
        return None
    return _decode_js_string(match.group(1))


def _extract_number_from_block(block: str, key: str) -> Optional[float]:
    match = re.search(rf"{re.escape(key)}:(-?(?:\d+(?:\.\d*)?|\.\d+))", block)
    if not match:
        return None
    return float(match.group(1))


def _extract_string_from_key(raw_text: str, key: str) -> Optional[str]:
    match = re.search(rf"{re.escape(key)}:\"((?:\\.|[^\"])*)\"", raw_text)
    if not match:
        return None
    return html_lib.unescape(_decode_js_string(match.group(1)))


def _extract_scaled_string_from_key(raw_text: str, key: str) -> Optional[float]:
    value = _extract_string_from_key(raw_text, key)
    return _parse_scaled_number(value)


def _extract_percent_from_key(raw_text: str, key: str) -> Optional[float]:
    value = _extract_string_from_key(raw_text, key)
    return _parse_percent(value)


def _extract_json_ld_name(raw_html: str) -> Optional[str]:
    match = re.search(r'"@type":"Corporation","name":"([^"]+)"', raw_html)
    if not match:
        return None
    return html_lib.unescape(_decode_js_string(match.group(1)))


def _extract_last_trailing_date(raw_html: str) -> Optional[str]:
    value = _extract_string_from_key(raw_html, "lastTrailingDate")
    if not value:
        return None
    try:
        return datetime.strptime(value, "%b %d, %Y").date().isoformat()
    except ValueError:
        return None


def _metric_number(raw_html: str, metric_id: str) -> Optional[float]:
    value = _metric_value(raw_html, metric_id)
    return _parse_scaled_number(value)


def _metric_percent(raw_html: str, metric_id: str) -> Optional[float]:
    value = _metric_value(raw_html, metric_id)
    return _parse_percent(value)


def _metric_value(raw_html: str, metric_id: str) -> Optional[str]:
    match = re.search(rf'\{{id:"{re.escape(metric_id)}"([^{{}}]*)\}}', raw_html)
    if not match:
        return None
    body = match.group(1)
    hover = _extract_string_from_block(body, "hover")
    value = _extract_string_from_block(body, "value")
    preferred = hover if hover and hover.lower() != "n/a" else value
    if not preferred or preferred.lower() == "n/a":
        return None
    return html_lib.unescape(preferred)


def _parse_scaled_number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"n/a", "na", "none", "void 0"}:
        return None
    cleaned = cleaned.replace("$", "").replace("€", "").replace("£", "")
    cleaned = cleaned.replace("EUR", "").replace("USD", "").replace("GBP", "")
    cleaned = cleaned.replace(",", "").strip()
    multiplier = 1.0
    if cleaned[-1:].upper() in {"K", "M", "B", "T"}:
        suffix = cleaned[-1:].upper()
        cleaned = cleaned[:-1]
        multiplier = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0, "T": 1_000_000_000_000.0}[suffix]
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1]
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def _parse_percent(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    number = _parse_scaled_number(value)
    if number is None:
        return None
    return number / 100.0 if "%" in value else number


def _fcf_yield_from_values(free_cash_flow: Optional[float], market_cap: Optional[float]) -> Optional[float]:
    if free_cash_flow is None or not market_cap:
        return None
    return free_cash_flow / market_cap


def _decode_js_string(value: str) -> str:
    return value.replace(r"\/", "/").replace(r"\"", '"').replace(r"\u0026", "&").replace(r"\u003C", "<")
