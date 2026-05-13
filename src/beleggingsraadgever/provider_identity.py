"""Provider-symbol discovery and review helpers."""

from __future__ import annotations

import re
from typing import Optional

from .collector import (
    AMSTERDAM_ALIASES,
    FetchText,
    StockAnalysisCandidate,
    _decode_js_string,
    _fetch_url_text,
    _stockanalysis_candidate_from_lookup_symbol,
    _stockanalysis_candidates,
    _stockanalysis_lookup_url,
)
from .identity import normalize_symbol
from .models import PortfolioAlias, ProviderCandidate
from .storage import SQLiteRepository


def refresh_provider_candidates(repository: SQLiteRepository, symbol: str, fetch_text: Optional[FetchText] = None) -> list[ProviderCandidate]:
    candidates = discover_provider_candidates(repository, symbol, fetch_text=fetch_text)
    repository.replace_provider_candidates(symbol, candidates)
    return repository.provider_candidates_for_symbol(symbol)


def refresh_provider_candidates_for_portfolio(repository: SQLiteRepository, fetch_text: Optional[FetchText] = None) -> dict[str, list[ProviderCandidate]]:
    refreshed: dict[str, list[ProviderCandidate]] = {}
    for position in repository.latest_portfolio_positions():
        refreshed[position.symbol] = refresh_provider_candidates(repository, position.symbol, fetch_text=fetch_text)
    return refreshed


def trusted_provider_symbols(repository: SQLiteRepository, symbol: str) -> list[str]:
    return [
        candidate.provider_symbol
        for candidate in repository.trusted_provider_candidates(symbol)
        if candidate.provider == "StockAnalysis" and candidate.provider_symbol
    ]


def discover_provider_candidates(
    repository: SQLiteRepository,
    symbol: str,
    *,
    fetch_text: Optional[FetchText] = None,
) -> list[ProviderCandidate]:
    normalized_symbol = normalize_symbol(symbol)
    if not normalized_symbol:
        return []

    aliases = repository.portfolio_aliases_for_symbol(normalized_symbol)
    by_key: dict[tuple[str, str], ProviderCandidate] = {}

    for candidate in _known_stockanalysis_candidates(normalized_symbol, aliases):
        _add_candidate(by_key, candidate)

    profile = repository.company_profile(normalized_symbol)
    if profile and profile.provider_symbol:
        _add_candidate(
            by_key,
            ProviderCandidate(
                symbol=normalized_symbol,
                provider=profile.source_name or "Provider",
                provider_symbol=profile.provider_symbol,
                provider_name=profile.company_name,
                source_url=profile.source_url,
                exchange=_exchange_from_provider_symbol(profile.provider_symbol),
                source="current_profile",
                confidence=0.70,
                reason="Huidig geïmporteerd providerprofiel; controleer bij tickerverwarring.",
                status="voorgesteld",
            ),
        )

    fetcher = fetch_text or _fetch_url_text
    for query in _lookup_queries(normalized_symbol, aliases):
        try:
            raw_html = fetcher(_stockanalysis_lookup_url(query))
        except Exception:
            continue
        for lookup_symbol, name in _parse_lookup_results(raw_html):
            stock_candidate = _stockanalysis_candidate_from_lookup_symbol(lookup_symbol)
            if stock_candidate is None:
                continue
            _add_candidate(
                by_key,
                _provider_candidate_from_stockanalysis(
                    normalized_symbol,
                    stock_candidate,
                    provider_name=name,
                    source="stockanalysis_lookup",
                    confidence=_candidate_confidence(name, query, aliases),
                    reason=f"StockAnalysis lookup voor '{query}'.",
                ),
            )

    return sorted(
        by_key.values(),
        key=lambda candidate: (
            0 if candidate.status == "vertrouwd" else 1,
            -candidate.confidence,
            candidate.provider,
            candidate.provider_symbol,
        ),
    )


def _known_stockanalysis_candidates(symbol: str, aliases: list[PortfolioAlias]) -> list[ProviderCandidate]:
    candidates: list[ProviderCandidate] = []
    for stock_candidate in _stockanalysis_candidates(symbol):
        source = "known_exchange_hint" if symbol in AMSTERDAM_ALIASES else "direct_symbol"
        confidence = 0.90 if symbol in AMSTERDAM_ALIASES else 0.55
        reason = (
            "Bekende lokale beursnotering voor dit portefeuillesymbool."
            if source == "known_exchange_hint"
            else "Directe tickerroute; extra controle bij korte tickers."
        )
        candidates.append(
            _provider_candidate_from_stockanalysis(
                symbol,
                stock_candidate,
                provider_name=_best_alias_name(symbol, aliases),
                source=source,
                confidence=confidence,
                reason=reason,
            )
        )
    return candidates


def _provider_candidate_from_stockanalysis(
    symbol: str,
    candidate: StockAnalysisCandidate,
    *,
    provider_name: str = "",
    source: str,
    confidence: float,
    reason: str,
) -> ProviderCandidate:
    return ProviderCandidate(
        symbol=symbol,
        provider="StockAnalysis",
        provider_symbol=candidate.provider_symbol,
        provider_name=provider_name,
        source_url=candidate.source_url,
        exchange=_exchange_from_provider_symbol(candidate.provider_symbol),
        source=source,
        confidence=confidence,
        reason=reason,
        status="voorgesteld",
    )


def _add_candidate(by_key: dict[tuple[str, str], ProviderCandidate], candidate: ProviderCandidate) -> None:
    key = (candidate.provider, candidate.provider_symbol.upper())
    existing = by_key.get(key)
    if existing is None or candidate.confidence > existing.confidence:
        by_key[key] = candidate


def _lookup_queries(symbol: str, aliases: list[PortfolioAlias]) -> list[str]:
    queries: list[str] = []

    def add(value: str) -> None:
        text = " ".join(str(value or "").replace("_", " ").split())
        if text and text not in queries:
            queries.append(text)

    add(symbol)
    for alias in aliases:
        if alias.alias_type in {"broker_name", "broker_name_clean", "analysis_input"}:
            add(alias.raw_value or alias.alias_key)
    return queries[:4]


def _parse_lookup_results(raw_html: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for match in re.finditer(r'\{s:"([^"]+)",n:"((?:\\.|[^"])*)",t:"Stock"', raw_html):
        results.append((_decode_js_string(match.group(1)), _decode_js_string(match.group(2))))
    return results


def _candidate_confidence(name: str, query: str, aliases: list[PortfolioAlias]) -> float:
    candidate_tokens = _identity_tokens(name)
    query_tokens = _identity_tokens(query)
    alias_tokens = set()
    for alias in aliases:
        alias_tokens.update(_identity_tokens(alias.raw_value or alias.alias_key))
    target_tokens = query_tokens | alias_tokens
    if not candidate_tokens or not target_tokens:
        return 0.55
    overlap = len(candidate_tokens & target_tokens)
    if overlap >= 2:
        return 0.86
    if overlap == 1:
        return 0.72
    return 0.50


def _identity_tokens(value: str) -> set[str]:
    ignored = {"holding", "holdings", "group", "groep", "koninklijke", "corp", "inc", "ltd", "plc", "nv", "n.v"}
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) >= 4 and token not in ignored
    }


def _best_alias_name(symbol: str, aliases: list[PortfolioAlias]) -> str:
    for alias in aliases:
        if alias.alias_type == "broker_name" and alias.raw_value:
            return alias.raw_value
    return symbol


def _exchange_from_provider_symbol(provider_symbol: str) -> str:
    if ":" in provider_symbol:
        return provider_symbol.split(":", 1)[0].upper()
    return "US"
