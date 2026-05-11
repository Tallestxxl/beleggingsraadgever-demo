"""Portfolio page rendering helpers for the local web UI."""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path
from typing import Optional

from .classification import classify_symbol
from .models import (
    InvestorProfile,
    PortfolioAsset,
    PortfolioClassification,
    PortfolioPerformanceSummary,
    PortfolioPosition,
    PortfolioPositionPerformance,
)
from .portfolio import exposure_buckets, portfolio_position_exposures
from .peer_discovery import refresh_peer_candidates
from .portfolio_importer import import_portfolio_csv
from .storage import SQLiteRepository
from .web_formatting import (
    format_eur,
    format_eur_cents,
    format_input_number,
    format_money_input_number,
    format_percent,
    format_quantity,
)


ASSET_LABELS = {
    "cash": "Cash / spaargeld",
    "house": "Huis",
    "gold": "Goud",
    "bitcoin": "Bitcoin",
    "other": "Overig",
}


def save_portfolio_profile(repository: SQLiteRepository, params: dict) -> None:
    risk_profile = _first_param(params, "risk_profile") or "gebalanceerd"
    if risk_profile not in {"defensief", "gebalanceerd", "offensief"}:
        raise ValueError("Onbekend risicoprofiel.")
    profile = InvestorProfile(
        age=_parse_optional_int(_first_param(params, "age"), "leeftijd"),
        annual_income=_parse_optional_float(_first_param(params, "annual_income"), "jaarinkomen"),
        horizon_years=_parse_optional_int(_first_param(params, "horizon_years"), "beleggingshorizon"),
        cash_buffer=_parse_optional_float(_first_param(params, "cash_buffer"), "cashbuffer"),
        risk_profile=risk_profile,
    )
    repository.save_investor_profile(profile)

    as_of = date.today().isoformat()
    for asset_type in ASSET_LABELS:
        value = _parse_optional_float(_first_param(params, f"asset_{asset_type}"), ASSET_LABELS[asset_type])
        if value is None:
            continue
        repository.upsert_portfolio_asset(
            PortfolioAsset(asset_type=asset_type, value=value, currency="EUR", as_of=as_of)
        )


def save_portfolio_position(repository: SQLiteRepository, params: dict) -> None:
    symbol = _first_param(params, "symbol").upper()
    if not symbol:
        raise ValueError("Ticker is verplicht.")
    as_of = _first_param(params, "as_of") or date.today().isoformat()
    _required_iso_date(as_of)
    repository.upsert_portfolio_position(
        PortfolioPosition(
            symbol=symbol,
            quantity=_parse_required_float(_first_param(params, "quantity"), "aantal"),
            average_cost=_parse_required_float(_first_param(params, "average_cost"), "gemiddelde aankoopprijs"),
            currency=(_first_param(params, "currency") or "EUR").upper(),
            account=_first_param(params, "account") or "Hoofdrekening",
            as_of=as_of,
        )
    )
    classification = classify_symbol(symbol)
    repository.upsert_portfolio_classification(
        PortfolioClassification(symbol=symbol, sector=classification.sector, theme=classification.theme)
    )
    refresh_peer_candidates(repository, symbol)


def import_portfolio_csv_workflow(repository: SQLiteRepository, params: dict) -> str:
    csv_path = _first_param(params, "csv_path")
    if not csv_path:
        raise ValueError("CSV-pad is verplicht.")
    result = import_portfolio_csv(repository, Path(csv_path))
    return result.summary


def render_portfolio_dashboard(
    repository: SQLiteRepository,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    profile = repository.investor_profile()
    assets = repository.portfolio_assets()
    exposures = portfolio_position_exposures(repository)
    performance_summary = repository.latest_portfolio_performance_summary()
    position_performance = repository.latest_portfolio_position_performances()
    positions = portfolio_position_rows(exposures, position_performance)
    aliases = repository.portfolio_aliases()
    peer_coverage = portfolio_peer_coverage_rows(repository, [row["symbol"] for row in positions])
    securities_value = sum(row["market_value"] for row in positions)
    asset_value = sum(asset.value for asset in assets)
    total_value = securities_value + asset_value
    notice = ""
    if error:
        notice = f'<div class="notice">{html.escape(error)}</div>'
    elif message:
        notice = f'<div class="notice">{html.escape(message)}</div>'

    return f"""
    {notice}
    <div class="report-header">
      <div class="verdict">
        <h2>Profiel & portefeuille</h2>
        <p>Handmatige v1-laag voor persoonlijke limieten, vermogensverdeling en portefeuillefit per aandeel.</p>
      </div>
      <div class="metric">
        <span class="metric-label">Totaal vermogen</span>
        <span class="metric-value">{format_eur(total_value)}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Effecten</span>
        <span class="metric-value">{format_eur(securities_value)}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Overig</span>
        <span class="metric-value">{format_eur(asset_value)}</span>
      </div>
    </div>
    <div class="grid">
      <div>
        <section>
          <h3>Persoonlijke situatie</h3>
          {render_profile_form(profile, assets)}
        </section>
        <section>
          <h3>Vermogensverdeling</h3>
          {render_allocation_table(assets, securities_value, total_value)}
        </section>
        <section>
          <h3>Historisch resultaat</h3>
          {render_performance_summary(performance_summary)}
        </section>
        <section>
          <h3>Sectorverdeling effecten</h3>
          {render_exposure_table(exposure_buckets(exposures, by="sector", total_wealth=total_value))}
        </section>
        <section>
          <h3>Themaverdeling effecten</h3>
          {render_exposure_table(exposure_buckets(exposures, by="theme", total_wealth=total_value))}
        </section>
        <section>
          <details class="supporting-detail">
            <summary>Peerdekking</summary>
            <div class="collapsible-content">{render_peer_coverage_table(peer_coverage)}</div>
          </details>
        </section>
      </div>
      <div>
        <section>
          <h3>CSV-import</h3>
          {render_csv_import_form()}
        </section>
        <section>
          <h3>Nieuwe of bijgewerkte positie</h3>
          {render_position_form()}
        </section>
        <section>
          <details class="supporting-detail">
            <summary>Identiteitskoppelingen</summary>
            <div class="collapsible-content">{render_aliases_table(aliases)}</div>
          </details>
        </section>
      </div>
    </div>
    <section class="portfolio-wide-section">
      <h3>Effectenportefeuille</h3>
      {render_positions_table(positions)}
    </section>"""


def render_csv_import_form() -> str:
    return """
          <form class="portfolio-form" method="post" action="/portfolio/import-csv">
            <div>
              <label for="csv-path">CSV-pad</label>
              <input id="csv-path" name="csv_path" type="text" value="/Users/albertvanegmond/Downloads/Beleggen_report (1).csv">
            </div>
            <button type="submit">Importeer CSV</button>
          </form>"""


def render_profile_form(profile: Optional[InvestorProfile], assets: list[PortfolioAsset]) -> str:
    asset_values = {asset.asset_type: asset.value for asset in assets}
    risk_profile = profile.risk_profile if profile else "gebalanceerd"
    risk_options = "".join(
        f'<option value="{value}"{" selected" if risk_profile == value else ""}>{label}</option>'
        for value, label in {
            "defensief": "Defensief",
            "gebalanceerd": "Gebalanceerd",
            "offensief": "Offensief",
        }.items()
    )
    asset_inputs = "".join(
        f"""
              <div>
                <label for="asset-{html.escape(asset_type)}">{html.escape(label)}</label>
                <input id="asset-{html.escape(asset_type)}" name="asset_{html.escape(asset_type)}" type="text" inputmode="decimal" value="{format_money_input_number(asset_values.get(asset_type))}">
              </div>"""
        for asset_type, label in ASSET_LABELS.items()
    )
    return f"""
          <form class="portfolio-form" method="post" action="/portfolio/profile">
            <div class="form-grid">
              <div>
                <label for="age">Leeftijd</label>
                <input id="age" name="age" type="number" min="0" step="1" value="{format_input_number(profile.age if profile else None)}">
              </div>
              <div>
                <label for="annual-income">Bruto jaarinkomen</label>
                <input id="annual-income" name="annual_income" type="text" inputmode="decimal" value="{format_money_input_number(profile.annual_income if profile else None)}">
              </div>
            </div>
            <div class="form-grid">
              <div>
                <label for="horizon-years">Beleggingshorizon in jaren</label>
                <input id="horizon-years" name="horizon_years" type="number" min="0" step="1" value="{format_input_number(profile.horizon_years if profile else None)}">
              </div>
              <div>
                <label for="cash-buffer">Gewenste cashbuffer</label>
                <input id="cash-buffer" name="cash_buffer" type="text" inputmode="decimal" value="{format_money_input_number(profile.cash_buffer if profile else None)}">
              </div>
            </div>
            <div>
              <label for="risk-profile">Risicoprofiel</label>
              <select id="risk-profile" name="risk_profile">{risk_options}</select>
            </div>
            <div class="asset-grid">{asset_inputs}
            </div>
            <button type="submit">Sla profiel op</button>
          </form>"""


def render_position_form() -> str:
    today = date.today().isoformat()
    return f"""
          <form class="portfolio-form" method="post" action="/portfolio/position">
            <div class="form-grid">
              <div>
                <label for="position-symbol">Ticker</label>
                <input id="position-symbol" name="symbol" type="text" autocomplete="off">
              </div>
              <div>
                <label for="position-account">Account</label>
                <input id="position-account" name="account" type="text" value="Hoofdrekening">
              </div>
            </div>
            <div class="form-grid">
              <div>
                <label for="position-quantity">Aantal</label>
                <input id="position-quantity" name="quantity" type="number" step="0.0001">
              </div>
              <div>
                <label for="position-cost">Gemiddelde aankoopprijs</label>
                <input id="position-cost" name="average_cost" type="number" step="0.01" min="0">
              </div>
            </div>
            <div class="form-grid">
              <div>
                <label for="position-currency">Valuta</label>
                <input id="position-currency" name="currency" type="text" value="EUR">
              </div>
              <div>
                <label for="position-date">Peildatum</label>
                <input id="position-date" name="as_of" type="date" value="{today}">
              </div>
            </div>
            <button type="submit">Sla positie op</button>
          </form>"""


def render_allocation_table(assets: list[PortfolioAsset], securities_value: float, total_value: float) -> str:
    rows = [
        ("Effectenportefeuille", securities_value),
        *[(ASSET_LABELS.get(asset.asset_type, asset.asset_type), asset.value) for asset in assets],
    ]
    if not rows or total_value <= 0:
        return '<p class="evidence-meta">Nog geen vermogensgegevens opgeslagen.</p>'
    body = "".join(
        f"""
        <tr>
          <td>{html.escape(label)}</td>
          <td>{format_eur(value)}</td>
          <td>{format_percent(value / total_value if total_value else 0)}</td>
        </tr>"""
        for label, value in rows
        if value > 0
    )
    return f"""
          <table class="data-table">
            <thead><tr><th>Categorie</th><th>Waarde</th><th>Gewicht</th></tr></thead>
            <tbody>{body}</tbody>
          </table>"""


def render_performance_summary(summary: Optional[PortfolioPerformanceSummary]) -> str:
    if summary is None:
        return '<p class="evidence-meta">Nog geen historische resultaatgegevens geïmporteerd.</p>'
    rows = [
        ("Periode", summary.period_label),
        ("Totaal resultaat", format_eur(summary.total_result)),
        ("Ongerealiseerd resultaat", format_eur(summary.unrealized_result)),
        ("Gerealiseerd resultaat", format_eur(summary.realized_result)),
        ("Dividend en coupons", format_eur(summary.dividend_coupons)),
        ("Peildatum", summary.as_of),
    ]
    body = "".join(
        f"""
        <tr>
          <td>{html.escape(label)}</td>
          <td>{html.escape(value)}</td>
        </tr>"""
        for label, value in rows
    )
    return f"""
          <table class="data-table">
            <tbody>{body}</tbody>
          </table>"""


def render_positions_table(positions: list[dict]) -> str:
    if not positions:
        return '<p class="evidence-meta">Nog geen posities opgeslagen.</p>'
    body = "".join(
        f"""
        <tr>
          <td>{html.escape(row["symbol"])}</td>
          <td>{html.escape(row["sector"])}</td>
          <td>{html.escape(row["theme"])}</td>
          <td>{format_quantity(row["quantity"])}</td>
          <td>{format_eur_cents(row["average_cost"])}</td>
          <td>{format_eur_cents(row["market_price"])}</td>
          <td>{format_eur(row["market_value"])}</td>
          <td>{format_percent(row["return_pct"]) if row["return_pct"] is not None else ""}</td>
          <td>{format_eur(row["result_value"]) if row["result_value"] is not None else ""}</td>
          <td>{format_eur(row["dividend_coupons"]) if row["dividend_coupons"] is not None else ""}</td>
        </tr>"""
        for row in positions
    )
    return f"""
          <table class="data-table">
            <thead>
              <tr><th>Ticker</th><th>Sector</th><th>Thema</th><th>Aantal</th><th>Kostprijs</th><th>Laatste koers</th><th>Waarde</th><th>Resultaat %</th><th>Resultaat EUR</th><th>Dividend/coupons</th></tr>
            </thead>
            <tbody>{body}</tbody>
          </table>"""


def render_aliases_table(aliases) -> str:
    if not aliases:
        return '<p class="evidence-meta">Nog geen alias-koppelingen opgeslagen.</p>'
    visible_aliases = [
        alias
        for alias in aliases
        if alias.alias_key != alias.portfolio_symbol or alias.alias_type != "portfolio_symbol"
    ]
    if not visible_aliases:
        return '<p class="evidence-meta">Alleen directe tickers zijn bekend; nog geen alternatieve namen of provider-symbolen.</p>'
    body = "".join(
        f"""
        <tr>
          <td>{html.escape(alias.alias_key)}</td>
          <td>{html.escape(alias.portfolio_symbol)}</td>
          <td>{html.escape(alias.alias_type)}</td>
          <td>{html.escape(alias.raw_value)}</td>
          <td>{html.escape(alias.source)}</td>
        </tr>"""
        for alias in visible_aliases
    )
    return f"""
          <table class="data-table">
            <thead><tr><th>Alias</th><th>Portefeuillesymbool</th><th>Type</th><th>Origineel</th><th>Bron</th></tr></thead>
            <tbody>{body}</tbody>
          </table>"""


def render_exposure_table(buckets) -> str:
    if not buckets:
        return '<p class="evidence-meta">Nog geen effectenposities opgeslagen.</p>'
    body = "".join(
        f"""
        <tr>
          <td>{html.escape(bucket.label)}</td>
          <td>{format_eur(bucket.value)}</td>
          <td>{format_percent(bucket.securities_weight)}</td>
        </tr>"""
        for bucket in buckets
    )
    return f"""
          <table class="data-table">
            <thead><tr><th>Label</th><th>Waarde</th><th>% effecten</th></tr></thead>
            <tbody>{body}</tbody>
          </table>"""


def portfolio_peer_coverage_rows(repository: SQLiteRepository, symbols: list[str]) -> list[dict]:
    grouped_candidates = repository.peer_candidates_for_symbols(symbols)
    rows = []
    for symbol in symbols:
        candidates = grouped_candidates.get(symbol.upper(), [])
        classification = repository.portfolio_classification(symbol)
        peer_group = candidates[0].peer_group if candidates else ""
        if not peer_group and classification is not None and classification.theme != "Onbekend":
            peer_group = classification.theme
        trusted = [candidate for candidate in candidates if candidate.status == "vertrouwd"]
        proposed = [candidate for candidate in candidates if candidate.status != "vertrouwd"]
        available = sum(1 for candidate in trusted if _has_analysis_snapshots(repository, candidate.peer_symbol))
        rows.append(
            {
                "symbol": symbol,
                "peer_group": peer_group or "Nog onbekend",
                "candidate_count": len(candidates),
                "trusted_count": len(trusted),
                "proposed_count": len(proposed),
                "available_count": available,
                "missing_count": max(0, len(trusted) - available),
                "examples": ", ".join(
                    candidate.peer_symbol + (" (?)" if candidate.status != "vertrouwd" else "")
                    for candidate in candidates[:5]
                ),
            }
        )
    return rows


def render_peer_coverage_table(rows: list[dict]) -> str:
    if not rows:
        return '<p class="evidence-meta">Nog geen portefeuilleposities om peers voor te bepalen.</p>'
    body = "".join(
        f"""
        <tr>
          <td>{html.escape(row["symbol"])}</td>
          <td>{html.escape(row["peer_group"])}</td>
          <td>{row["candidate_count"]}</td>
          <td>{row["trusted_count"]}</td>
          <td>{row["proposed_count"]}</td>
          <td>{row["available_count"]}</td>
          <td>{row["missing_count"]}</td>
          <td>{html.escape(row["examples"]) if row["examples"] else "Nog te verrijken"}</td>
        </tr>"""
        for row in rows
    )
    return f"""
          <table class="data-table">
            <thead><tr><th>Aandeel</th><th>Peer-groep</th><th>Totaal</th><th>Vertrouwd</th><th>Voorgesteld</th><th>Met data</th><th>Wacht op data</th><th>Voorbeelden</th></tr></thead>
            <tbody>{body}</tbody>
          </table>"""


def _has_analysis_snapshots(repository: SQLiteRepository, symbol: str) -> bool:
    try:
        repository.latest_financial_snapshot(symbol)
        repository.latest_market_snapshot(symbol)
    except LookupError:
        return False
    return True


def portfolio_position_rows(
    exposures,
    position_performance: list[PortfolioPositionPerformance] | None = None,
) -> list[dict]:
    performance_by_key = {
        (performance.symbol.upper(), performance.account): performance
        for performance in (position_performance or [])
    }
    rows = []
    for exposure in exposures:
        position = exposure.position
        performance = performance_by_key.get((position.symbol.upper(), position.account))
        rows.append(
            {
                "symbol": position.symbol,
                "account": position.account,
                "sector": exposure.sector,
                "theme": exposure.theme,
                "quantity": position.quantity,
                "average_cost": position.average_cost,
                "market_price": exposure.market_price,
                "market_value": exposure.market_value,
                "return_pct": performance.result_pct if performance and performance.result_pct is not None else exposure.return_pct,
                "result_value": performance.result_value if performance else None,
                "dividend_coupons": performance.dividend_coupons if performance else None,
            }
        )
    return rows


def _first_param(params: dict, name: str) -> str:
    values = params.get(name, [""])
    return values[0].strip() if values else ""


def _parse_optional_float(value: str, label: str) -> Optional[float]:
    if not value:
        return None
    normalized = _normalize_localized_number(value)
    try:
        parsed = float(normalized)
    except ValueError as error:
        raise ValueError(f"{label} moet een getal zijn.") from error
    if parsed < 0:
        raise ValueError(f"{label} mag niet negatief zijn.")
    return parsed


def _normalize_localized_number(value: str) -> str:
    text = value.strip().replace(" ", "")
    if "," in text:
        return text.replace(".", "").replace(",", ".")
    if "." in text and _looks_like_dutch_thousands(text):
        return text.replace(".", "")
    return text


def _looks_like_dutch_thousands(value: str) -> bool:
    parts = value.split(".")
    return (
        len(parts) > 1
        and 1 <= len(parts[0]) <= 3
        and all(part.isdigit() and len(part) == 3 for part in parts[1:])
    )


def _parse_required_float(value: str, label: str) -> float:
    parsed = _parse_optional_float(value, label)
    if parsed is None:
        raise ValueError(f"{label} is verplicht.")
    return parsed


def _parse_optional_int(value: str, label: str) -> Optional[int]:
    parsed = _parse_optional_float(value, label)
    if parsed is None:
        return None
    if int(parsed) != parsed:
        raise ValueError(f"{label} moet een heel getal zijn.")
    return int(parsed)


def _required_iso_date(value: str) -> None:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError("datum moet YYYY-MM-DD gebruiken")
    date.fromisoformat(value)
