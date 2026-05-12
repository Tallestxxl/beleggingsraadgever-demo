"""V1-status and peer-review rendering for the local web UI."""

from __future__ import annotations

import html
import sqlite3
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional
from urllib.parse import quote_plus

from .backups import create_database_backup
from .peers import MIN_PEERS
from .peer_discovery import refresh_peer_candidates, refresh_peer_candidates_for_portfolio
from .storage import SQLiteRepository
from .symbol_resolution import resolve_analysis_symbol
from .web_components import render_status_pill
from .web_layout import build_shell
from .web_params import first_param as _first_param


@dataclass(frozen=True)
class V1StatusRow:
    symbol: str
    status_label: str
    status_class: str
    identity_label: str
    identity_detail: str
    market_label: str
    market_detail: str
    fundamentals_label: str
    fundamentals_detail: str
    classification_label: str
    classification_detail: str
    peer_label: str
    peer_detail: str
    knowledge_label: str
    knowledge_detail: str
    issues: list[str]


def build_status_page(
    repository: SQLiteRepository,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    return build_shell("DEMO", render_v1_status_dashboard(repository, message=message, error=error))


def refresh_peer_candidates_workflow(repository: SQLiteRepository, params: dict) -> str:
    symbol = _first_param(params, "symbol").upper()
    if symbol == "__ALL__":
        refreshed = refresh_peer_candidates_for_portfolio(repository)
        count = sum(len(candidates) for candidates in refreshed.values())
        return f"Peer-kandidaten herberekend: {count}"
    if not symbol:
        return "Geen aandeel ontvangen"
    candidates = refresh_peer_candidates(repository, symbol)
    return f"Peer-kandidaten voor {symbol} herberekend: {len(candidates)}"


def update_peer_candidate_status_workflow(repository: SQLiteRepository, params: dict) -> str:
    symbol = _first_param(params, "symbol").upper()
    peer_symbol = _first_param(params, "peer_symbol").upper()
    status = _first_param(params, "status")
    if not symbol or not peer_symbol:
        raise ValueError("Aandeel en peer-kandidaat zijn verplicht.")
    if status not in {"vertrouwd", "voorgesteld", "verworpen"}:
        raise ValueError("Onbekende peerstatus.")
    updated = repository.update_peer_candidate_status(symbol, peer_symbol, status)
    if not updated:
        raise ValueError(f"Peer-kandidaat {peer_symbol} voor {symbol} is niet gevonden.")
    labels = {
        "vertrouwd": "vertrouwd",
        "voorgesteld": "teruggezet als voorstel",
        "verworpen": "verworpen",
    }
    return (
        f"Peer-kandidaat {peer_symbol} voor {symbol} is {labels[status]}. "
        f"{_backup_message(repository, f'peerstatus-{symbol}-{peer_symbol}-{status}')}"
    )


def _backup_message(repository: SQLiteRepository, reason: str) -> str:
    try:
        backup = create_database_backup(repository.db_path, reason)
    except (OSError, sqlite3.Error) as error:
        return f"Backup mislukt: {error}"
    return f"Backup bewaard: {backup.filename}"


def render_v1_status_dashboard(
    repository: SQLiteRepository,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    symbols = [position.symbol for position in repository.latest_portfolio_positions()]
    rows = [build_v1_status_row(repository, symbol) for symbol in symbols]
    ready_count = sum(1 for row in rows if row.status_label == "V1-klaar")
    warning_count = sum(1 for row in rows if row.status_label == "Bruikbaar met waarschuwing")
    control_count = sum(1 for row in rows if row.status_label == "Controle nodig")
    notice = ""
    if error:
        notice = f'<div class="notice">{html.escape(error)}</div>'
    elif message:
        notice = f'<div class="notice">{html.escape(message)}</div>'

    return f"""
    {notice}
    <div class="report-header">
      <div class="verdict">
        <h2>V1-status</h2>
        <p>Controlepaneel voor datakwaliteit, dekking en betrouwbaarheid per portefeuillepositie.</p>
      </div>
      <div class="metric">
        <span class="metric-label">V1-klaar</span>
        <span class="metric-value">{ready_count}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Waarschuwing</span>
        <span class="metric-value">{warning_count}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Controle nodig</span>
        <span class="metric-value">{control_count}</span>
      </div>
    </div>
    <section>
      <div class="workflow-header">
        <div>
          <h3>Dekking portefeuille</h3>
          <p class="summary">V1-klaar betekent: analyseerbare cijfers, recente koersdata, sector/thema, voldoende peerbasis en minimaal één kennisfragment of casusnotitie.</p>
        </div>
        <form method="post" action="/status/refresh-peers">
          <input type="hidden" name="symbol" value="__ALL__">
          <button type="submit">Herbereken alle peer-kandidaten</button>
        </form>
      </div>
      {render_v1_status_table(rows)}
    </section>
    <section>
      <h3>Peer-kandidaten beoordelen</h3>
      <p class="summary">Promoveer voorgestelde peers pas naar vertrouwd wanneer ze inhoudelijk vergelijkbaar genoeg zijn. Vertrouwde peers tellen mee voor V1-status en peeranalyse; voorgestelde peers blijven alleen op de kandidatenlijst staan.</p>
      {render_peer_candidate_review_table(repository, symbols)}
    </section>"""


def render_v1_status_table(rows: list[V1StatusRow]) -> str:
    if not rows:
        return '<p class="evidence-meta">Nog geen portefeuilleposities om V1-status voor te bepalen.</p>'
    body = "".join(render_v1_status_table_row(row) for row in rows)
    return f"""
          <table class="data-table">
            <thead>
              <tr><th>Aandeel</th><th>Status</th><th>Identiteit</th><th>Koersdata</th><th>Fundamentals</th><th>Sector/thema</th><th>Peers</th><th>Kennis</th><th>Acties</th></tr>
            </thead>
            <tbody>{body}</tbody>
          </table>"""


def render_v1_status_table_row(row: V1StatusRow) -> str:
    symbol = html.escape(row.symbol)
    issue_detail = " ".join(row.issues[:3])
    status_detail = f'<span class="status-detail">{html.escape(issue_detail)}</span>' if issue_detail else ""
    return f"""
        <tr>
          <td><strong>{symbol}</strong></td>
          <td>{render_status_pill(row.status_label, row.status_class)}{status_detail}</td>
          <td>{render_status_pill(row.identity_label, _label_class(row.identity_label))}<span class="status-detail">{html.escape(row.identity_detail)}</span></td>
          <td>{render_status_pill(row.market_label, _label_class(row.market_label))}<span class="status-detail">{html.escape(row.market_detail)}</span></td>
          <td>{render_status_pill(row.fundamentals_label, _label_class(row.fundamentals_label))}<span class="status-detail">{html.escape(row.fundamentals_detail)}</span></td>
          <td>{render_status_pill(row.classification_label, _label_class(row.classification_label))}<span class="status-detail">{html.escape(row.classification_detail)}</span></td>
          <td>{render_status_pill(row.peer_label, _label_class(row.peer_label))}<span class="status-detail">{html.escape(row.peer_detail)}</span></td>
          <td>{render_status_pill(row.knowledge_label, _label_class(row.knowledge_label))}<span class="status-detail">{html.escape(row.knowledge_detail)}</span></td>
          <td>{render_v1_status_actions(row.symbol)}</td>
        </tr>"""


def render_v1_status_actions(symbol: str) -> str:
    escaped_symbol = html.escape(symbol)
    quoted_symbol = quote_plus(symbol)
    return f"""
            <div class="status-actions">
              <a class="button secondary" href="/analyze?symbol={quoted_symbol}">Analyseer</a>
              <a class="button secondary" href="/workflow?symbol={quoted_symbol}">Workflow</a>
              <form method="post" action="/workflow/collect">
                <input type="hidden" name="symbol" value="{escaped_symbol}">
                <button type="submit">Verrijk data</button>
              </form>
              <form method="post" action="/status/refresh-peers">
                <input type="hidden" name="symbol" value="{escaped_symbol}">
                <button type="submit">Zoek peer-kandidaten</button>
              </form>
            </div>"""


def render_peer_candidate_review_table(repository: SQLiteRepository, symbols: list[str]) -> str:
    grouped = repository.peer_candidates_for_symbols(symbols)
    candidates = [
        candidate
        for symbol in symbols
        for candidate in grouped.get(symbol.upper(), [])
    ]
    if not candidates:
        return '<p class="evidence-meta">Nog geen peer-kandidaten gevonden. Gebruik eerst Zoek peer-kandidaten of Herbereken alle peer-kandidaten.</p>'
    body = "".join(render_peer_candidate_review_row(candidate) for candidate in candidates)
    return f"""
          <table class="data-table">
            <thead>
              <tr><th>Aandeel</th><th>Kandidaat</th><th>Peer-groep</th><th>Status</th><th>Bron</th><th>Confidence</th><th>Reden</th><th>Acties</th></tr>
            </thead>
            <tbody>{body}</tbody>
          </table>"""


def render_peer_candidate_review_row(candidate) -> str:
    status_class = "ok" if candidate.status == "vertrouwd" else "danger" if candidate.status == "verworpen" else "warn"
    return f"""
        <tr>
          <td>{html.escape(candidate.symbol)}</td>
          <td><strong>{html.escape(candidate.peer_symbol)}</strong></td>
          <td>{html.escape(candidate.peer_group)}</td>
          <td>{render_status_pill(candidate.status, status_class)}</td>
          <td>{html.escape(candidate.source)}</td>
          <td>{candidate.confidence:.0%}</td>
          <td>{html.escape(candidate.reason)}</td>
          <td>{render_peer_candidate_status_actions(candidate)}</td>
        </tr>"""


def render_peer_candidate_status_actions(candidate) -> str:
    buttons = []
    if candidate.status != "vertrouwd":
        buttons.append(render_peer_status_form(candidate.symbol, candidate.peer_symbol, "vertrouwd", "Vertrouw"))
    if candidate.status != "verworpen":
        buttons.append(render_peer_status_form(candidate.symbol, candidate.peer_symbol, "verworpen", "Verwerp"))
    if candidate.status == "verworpen":
        buttons.append(render_peer_status_form(candidate.symbol, candidate.peer_symbol, "voorgesteld", "Zet terug als voorstel"))
    return f'<div class="status-actions">{"".join(buttons)}</div>'


def render_peer_status_form(symbol: str, peer_symbol: str, status: str, label: str) -> str:
    return f"""
              <form method="post" action="/status/peer-status">
                <input type="hidden" name="symbol" value="{html.escape(symbol)}">
                <input type="hidden" name="peer_symbol" value="{html.escape(peer_symbol)}">
                <input type="hidden" name="status" value="{html.escape(status)}">
                <button type="submit">{html.escape(label)}</button>
              </form>"""


def build_v1_status_row(repository: SQLiteRepository, symbol: str) -> V1StatusRow:
    canonical_symbol = resolve_analysis_symbol(repository, symbol) or symbol.strip().upper()
    issues: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []

    identity_label, identity_detail = _v1_identity_status(repository, canonical_symbol, warnings)
    market_label, market_detail = _v1_market_status(repository, canonical_symbol, blockers, warnings)
    fundamentals_label, fundamentals_detail = _v1_fundamentals_status(repository, canonical_symbol, blockers, warnings)
    classification_label, classification_detail = _v1_classification_status(
        repository, canonical_symbol, blockers, warnings
    )
    peer_label, peer_detail = _v1_peer_status(repository, canonical_symbol, warnings)
    knowledge_label, knowledge_detail = _v1_knowledge_status(repository, canonical_symbol, warnings)

    issues.extend(blockers)
    issues.extend(warnings)
    if blockers:
        status_label = "Controle nodig"
        status_class = "danger"
    elif warnings:
        status_label = "Bruikbaar met waarschuwing"
        status_class = "warn"
    else:
        status_label = "V1-klaar"
        status_class = "ok"

    return V1StatusRow(
        symbol=canonical_symbol,
        status_label=status_label,
        status_class=status_class,
        identity_label=identity_label,
        identity_detail=identity_detail,
        market_label=market_label,
        market_detail=market_detail,
        fundamentals_label=fundamentals_label,
        fundamentals_detail=fundamentals_detail,
        classification_label=classification_label,
        classification_detail=classification_detail,
        peer_label=peer_label,
        peer_detail=peer_detail,
        knowledge_label=knowledge_label,
        knowledge_detail=knowledge_detail,
        issues=issues,
    )


def _v1_identity_status(
    repository: SQLiteRepository,
    symbol: str,
    warnings: list[str],
) -> tuple[str, str]:
    aliases = repository.portfolio_aliases_for_symbol(symbol)
    visible_aliases = [
        alias
        for alias in aliases
        if alias.alias_key != symbol or alias.alias_type != "portfolio_symbol"
    ]
    profile = repository.company_profile(symbol)
    if profile and profile.provider_symbol:
        alias_text = f", {len(visible_aliases)} alias(s)" if visible_aliases else ""
        suspicious_alias = _provider_name_mismatch(profile.company_name, profile.description, visible_aliases)
        if suspicious_alias:
            warnings.append(
                f"Providerprofiel voor {symbol} noemt {profile.company_name or profile.provider_symbol}, "
                f"maar portefeuillealias {suspicious_alias} lijkt een ander bedrijf."
            )
            return (
                "Controle",
                (
                    f"Provider-symbol {profile.provider_symbol}{alias_text}; "
                    f"providernaam {profile.company_name or 'onbekend'} matcht niet met alias {suspicious_alias}."
                ),
            )
        return "OK", f"Provider-symbol {profile.provider_symbol}{alias_text}."
    if visible_aliases:
        return "OK", f"{len(visible_aliases)} alias(s) gekoppeld; providerprofiel ontbreekt nog."
    warnings.append("Identiteitskoppeling is alleen een directe ticker; controleer provider-symbolen bij naam/tickerverwarring.")
    return "Basis", "Alleen directe portefeuilleticker bekend."


def _provider_name_mismatch(company_name: str, description: str, aliases: list) -> str:
    provider_tokens = _identity_tokens(f"{company_name} {description}")
    if not provider_tokens:
        return ""
    for alias in aliases:
        if alias.alias_type not in {"broker_name", "broker_name_clean", "broker_normalized_symbol"}:
            continue
        raw_value = alias.raw_value or alias.alias_key
        alias_tokens = _identity_tokens(raw_value)
        if not alias_tokens:
            continue
        if provider_tokens.isdisjoint(alias_tokens):
            return raw_value
    return ""


def _identity_tokens(value: str) -> set[str]:
    ignored = {"holding", "holdings", "group", "groep", "nv", "n.v", "sa", "s.a", "plc", "inc", "corp", "ltd"}
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) >= 4 and token not in ignored
    }


def _v1_market_status(
    repository: SQLiteRepository,
    symbol: str,
    blockers: list[str],
    warnings: list[str],
) -> tuple[str, str]:
    try:
        market = repository.latest_market_snapshot(symbol)
    except LookupError:
        market = None
    if market is not None:
        age = _days_old(market.as_of)
        if age is not None and age > 45:
            warnings.append(f"Koersdata voor {symbol} is ouder dan 45 dagen.")
            return "Oud", f"Analysesnapshot {market.as_of}."
        return "OK", f"Analysesnapshot {market.as_of}."

    portfolio_price = repository.latest_portfolio_price(symbol)
    if portfolio_price is not None:
        warnings.append(f"{symbol} heeft alleen een portefeuillekoers; waarderingsdata uit analysesnapshot ontbreekt.")
        return "CSV", f"Portefeuillekoers {portfolio_price.as_of}."

    blockers.append(f"Koersdata voor {symbol} ontbreekt.")
    return "Ontbreekt", "Geen koerssnapshot gevonden."


def _v1_fundamentals_status(
    repository: SQLiteRepository,
    symbol: str,
    blockers: list[str],
    warnings: list[str],
) -> tuple[str, str]:
    try:
        financial = repository.latest_financial_snapshot(symbol)
    except LookupError:
        blockers.append(f"Fundamentals voor {symbol} ontbreken.")
        return "Ontbreekt", "Geen fundamentalsnapshot gevonden."
    age = _days_old(financial.period_end)
    if age is not None and age > 550:
        warnings.append(f"Fundamentals voor {symbol} zijn ouder dan circa 18 maanden.")
        return "Oud", f"{financial.period_type} t/m {financial.period_end}."
    return "OK", f"{financial.period_type} t/m {financial.period_end}."


def _v1_classification_status(
    repository: SQLiteRepository,
    symbol: str,
    blockers: list[str],
    warnings: list[str],
) -> tuple[str, str]:
    classification = repository.portfolio_classification(symbol)
    if (
        classification is None
        or classification.sector == "Onbekend"
        or classification.theme == "Onbekend"
    ):
        blockers.append(f"Sector/thema voor {symbol} ontbreekt of is onbekend.")
        return "Ontbreekt", "Sector/thema nog niet betrouwbaar geclassificeerd."

    profile = repository.company_profile(symbol)
    source = profile.classification_source if profile else ""
    confidence = profile.classification_confidence if profile else 0.0
    detail = f"{classification.sector} / {classification.theme}"
    if source:
        detail += f" via {source}"
    if confidence:
        detail += f" ({confidence:.0%})"
        if confidence < 0.60:
            warnings.append(f"Sector/thema-confidence voor {symbol} is lager dan 60%.")
            return "Laag", detail + "."
    return "OK", detail + "."


def _v1_peer_status(
    repository: SQLiteRepository,
    symbol: str,
    warnings: list[str],
) -> tuple[str, str]:
    candidates = repository.peer_candidates_for_symbol(symbol)
    trusted = [candidate for candidate in candidates if candidate.status == "vertrouwd"]
    proposed = [candidate for candidate in candidates if candidate.status != "vertrouwd"]
    available = sum(1 for candidate in trusted if _has_analysis_snapshots(repository, candidate.peer_symbol))
    if available >= MIN_PEERS:
        detail = f"{available} van {len(trusted)} vertrouwde peer(s) met lokale data"
        if proposed:
            detail += f"; {len(proposed)} voorgesteld."
        return "OK", detail + "."
    if candidates:
        warnings.append(f"Peeranalyse voor {symbol} heeft minder dan {MIN_PEERS} beschikbare vertrouwde peers.")
        return "Beperkt", f"{available} van {len(trusted)} vertrouwde peer(s) met lokale data; {len(proposed)} voorgesteld."
    warnings.append(f"Nog geen peer-kandidaten voor {symbol}.")
    return "Ontbreekt", "Geen peer-kandidaten opgeslagen."


def _v1_knowledge_status(
    repository: SQLiteRepository,
    symbol: str,
    warnings: list[str],
) -> tuple[str, str]:
    count = repository.knowledge_document_count_for_symbol(symbol)
    if count > 0:
        return "OK", f"{count} document(en) of casusnotitie(s)."
    warnings.append(f"Geen aandeel-specifieke kennisfragmenten of casusnotities voor {symbol}.")
    return "Ontbreekt", "Geen aandeel-specifieke kennis gevonden."


def _has_analysis_snapshots(repository: SQLiteRepository, symbol: str) -> bool:
    try:
        repository.latest_financial_snapshot(symbol)
        repository.latest_market_snapshot(symbol)
    except LookupError:
        return False
    return True


def _days_old(value: str) -> Optional[int]:
    try:
        return (date.today() - date.fromisoformat(value)).days
    except (TypeError, ValueError):
        return None


def _label_class(label: str) -> str:
    if label in {"OK", "V1-klaar"}:
        return "ok"
    if label in {"Ontbreekt", "Controle nodig"}:
        return "danger"
    if label in {"Basis", "CSV", "Oud", "Laag", "Beperkt", "Bruikbaar met waarschuwing"}:
        return "warn"
    return "info"


def render_v1_analysis_warning(row: Optional[V1StatusRow]) -> str:
    if row is None or row.status_label == "V1-klaar":
        return ""
    issues = "".join(f"<li>{html.escape(issue)}</li>" for issue in row.issues[:5])
    return f"""
        <section>
          <h3>V1-datakwaliteit</h3>
          <p class="summary">{render_status_pill(row.status_label, row.status_class)} <span class="status-detail">Deze analyse is bruikbaar in verhouding tot de onderstaande datadekking.</span></p>
          <ul class="assumption-list">{issues}</ul>
          <div class="button-row">
            <a class="button secondary" href="/status">Open V1-status</a>
            <a class="button secondary" href="/workflow?symbol={quote_plus(row.symbol)}">Open workflow</a>
          </div>
        </section>"""
