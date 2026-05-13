"""Analysis report rendering for the local web UI."""

from __future__ import annotations

import html
from typing import Optional
from urllib.parse import quote_plus

from .history import format_historical_value
from .knowledge import tokenize
from .knowledge_scope import knowledge_scope_from_tags
from .models import AdviceReport
from .web_formatting import (
    format_compact_amount,
    format_eur,
    format_optional_number,
    format_optional_percent,
    format_percent,
)
from .web_knowledge import _scope_type_for_filter, render_knowledge_status_form
from .web_status import V1StatusRow, render_v1_analysis_warning


def render_report(report: AdviceReport, v1_status: Optional[V1StatusRow] = None) -> str:
    flags = ""
    if report.score.flags:
        flags = f"""
        <section>
          <h3>Risicosignalen</h3>
          <ul class="risk-list">{''.join(f'<li>{html.escape(flag)}</li>' for flag in report.score.flags)}</ul>
        </section>"""

    evidence = "".join(render_evidence_item(hit, report) for hit in report.evidence)
    if not evidence:
        evidence = '<p class="evidence-meta">Geen relevante fragmenten gevonden in de lokale kennisbank.</p>'
    evidence_diagnostics = render_evidence_diagnostics(report)
    peer_analysis = render_peer_analysis(report)
    historical_analysis = render_historical_analysis(report)

    freshness = "".join(
        f"<li>{html.escape(name)}: {html.escape(value)}</li>"
        for name, value in report.data_freshness.items()
    )
    sources = "".join(render_data_source_item(source) for source in report.data_sources)
    if not sources:
        sources = '<p class="evidence-meta">Geen veldbronnen opgeslagen voor dit aandeel.</p>'
    assumptions = "".join(f"<li>{html.escape(item)}</li>" for item in report.assumptions)
    data_quality = render_v1_analysis_warning(v1_status) if v1_status is not None else ""
    portfolio_fit = ""
    if report.portfolio_fit:
        fit = report.portfolio_fit
        notes = "".join(f"<li>{html.escape(note)}</li>" for note in fit.notes)
        buy_room_limits = "".join(f"<li>{html.escape(item)}</li>" for item in fit.buy_room_limits)
        buy_room_calculation = "".join(f"<li>{html.escape(item)}</li>" for item in fit.buy_room_calculation)
        transaction_rationale = "".join(
            f"<li>{html.escape(item)}</li>" for item in fit.transaction_rationale
        )
        classification_rows = ""
        if fit.sector != "Onbekend":
            classification_rows += (
                f"<li>Sector {html.escape(fit.sector)}: "
                f"{html.escape(format_percent(fit.sector_weight))} van effecten</li>"
            )
        if fit.theme != "Onbekend":
            classification_rows += (
                f"<li>Thema {html.escape(fit.theme)}: "
                f"{html.escape(format_percent(fit.theme_weight))} van effecten</li>"
            )
        if not classification_rows:
            classification_rows = "<li>Sector/thema: nog niet geclassificeerd.</li>"
        portfolio_fit = f"""
        <section>
          <h3>Portefeuillefit</h3>
          <p class="summary">{html.escape(fit.summary)}</p>
          {f'<p class="evidence-title">Waarom dit transactieadvies?</p><ul class="data-list">{transaction_rationale}</ul>' if transaction_rationale else ''}
          <ul class="data-list">
            <li>Transactieadvies: <strong>{html.escape(fit.transaction_label)}</strong></li>
            <li>Huidige waarde positie: {html.escape(format_eur(fit.position_value))}</li>
            <li>Gewicht positie: {html.escape(format_percent(fit.position_weight))} van effecten</li>
            <li>Richtmaximum: {html.escape(format_percent(fit.max_weight))}</li>
            <li>Effectenvermogen: {html.escape(format_eur(fit.securities_value))}</li>
            <li>Ruimte tot richtmaximum: {html.escape(format_eur(fit.room_to_max))}</li>
            <li>Maximale nieuwe koopruimte: <strong>{html.escape(format_eur(fit.max_new_buy_amount))}</strong></li>
            <li>Praktische koopruimte: <strong>{html.escape(format_eur(fit.practical_buy_amount))}</strong></li>
            {classification_rows}
          </ul>
          <details class="score-detail">
            <summary>Toon koopruimte-berekening</summary>
            <ul>{buy_room_calculation}</ul>
            {f'<p class="evidence-meta">Beperkingen</p><ul>{buy_room_limits}</ul>' if buy_room_limits else ''}
          </details>
          <ul class="assumption-list">{notes}</ul>
        </section>"""

    return f"""
    <div class="report-header">
      <div class="verdict">
        <h2>{html.escape(report.symbol)}: {html.escape(report.verdict)}</h2>
        <p>{html.escape(report.summary)}</p>
      </div>
      <div class="metric">
        <span class="metric-label">Totaalscore</span>
        <span class="metric-value">{report.score.total:.1f}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Overtuiging</span>
        <span class="metric-value">{html.escape(report.conviction)}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Risico</span>
        <span class="metric-value">{report.score.risk:.1f}</span>
      </div>
    </div>
    <div class="grid">
      <div>
        <section>
          <h3>Scorekaart</h3>
          <p class="evidence-meta">Alle deelscores lopen van 0 tot 100. De totaalscore gebruikt vaste v1-gewichten.</p>
          <div class="score-list">
            {render_score_block("Bedrijfskwaliteit", report.score.quality, report.score.details.get("quality", []))}
            {render_score_block("Waardering", report.score.valuation, report.score.details.get("valuation", []))}
            {render_score_block("Momentum", report.score.momentum, report.score.details.get("momentum", []))}
            {render_score_block("Risico", report.score.risk, report.score.details.get("risk", []))}
            {render_score_block("Totaalscore", report.score.total, report.score.details.get("total", []))}
          </div>
        </section>
        {peer_analysis}
        {historical_analysis}
        {flags}
        <section>
          <h3>Relevante kennisbank-fragmenten</h3>
          {evidence_diagnostics}
          <div class="evidence-list">{evidence}</div>
        </section>
      </div>
      <div>
        <section>
          <h3>Dataversheid</h3>
          <ul class="data-list">{freshness}</ul>
        </section>
        {data_quality}
        {portfolio_fit}
        <section>
          <details class="supporting-detail">
            <summary>Bronnen per cijfer</summary>
            <div class="source-list">{sources}</div>
          </details>
        </section>
        <section>
          <h3>Aannames</h3>
          <ul class="assumption-list">{assumptions}</ul>
        </section>
      </div>
    </div>"""


def render_historical_analysis(report: AdviceReport) -> str:
    analysis = report.historical_analysis
    if analysis is None:
        return ""
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row.metric)}</td>
          <td>{html.escape(format_historical_value(row.start_value, row.value_kind))}</td>
          <td>{html.escape(row.start_label)}</td>
          <td>{html.escape(format_historical_value(row.end_value, row.value_kind))}</td>
          <td>{html.escape(row.end_label)}</td>
          <td>{html.escape(row.change_label)}</td>
          <td>{html.escape(row.interpretation)}</td>
        </tr>"""
        for row in analysis.rows
    )
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in analysis.notes)
    if not rows:
        rows = '<tr><td colspan="7">Nog onvoldoende historische snapshots.</td></tr>'
    return f"""
        <section>
          <h3>Historische trend</h3>
          <p class="summary">{html.escape(analysis.summary)}</p>
          <table class="data-table">
            <thead><tr><th>Metriek</th><th>Start</th><th>Periode</th><th>Laatste</th><th>Periode</th><th>Verandering</th><th>Duiding</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
          {f'<ul class="assumption-list">{notes}</ul>' if notes else ''}
        </section>"""


def render_peer_analysis(report: AdviceReport) -> str:
    analysis = report.peer_analysis
    if analysis is None:
        return ""
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row.symbol)}{' *' if row.is_target else ''}</td>
          <td>{html.escape(format_compact_amount(row.revenue))}</td>
          <td>{html.escape(format_optional_percent(row.operating_margin))}</td>
          <td>{html.escape(format_optional_percent(row.fcf_margin))}</td>
          <td>{html.escape(format_optional_number(row.debt_to_fcf, suffix='x'))}</td>
          <td>{html.escape(format_optional_number(row.pe_ratio))}</td>
          <td>{html.escape(format_optional_number(row.ev_ebitda))}</td>
          <td>{html.escape(format_optional_percent(row.fcf_yield))}</td>
          <td>{html.escape(format_optional_percent(row.dividend_yield))}</td>
          <td>{html.escape(format_optional_percent(row.momentum_12m))}</td>
        </tr>"""
        for row in analysis.rows
    )
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in analysis.notes)
    return f"""
        <section>
          <h3>Peeranalyse</h3>
          <p class="summary">{html.escape(analysis.summary)}</p>
          <p class="evidence-meta">Peer-set: {html.escape(analysis.group_label)}. {analysis.available_peer_count} van {analysis.configured_peer_count} peers beschikbaar; maximaal {analysis.max_peer_count} peers getoond. * = geanalyseerd aandeel.</p>
          <table class="data-table">
            <thead>
              <tr><th>Aandeel</th><th>Omzet</th><th>Op. marge</th><th>FCF-marge</th><th>Schuld/FCF</th><th>K/W</th><th>EV/EBITDA</th><th>FCF-yield</th><th>Dividend</th><th>Momentum</th></tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
          <ul class="assumption-list">{notes}</ul>
        </section>"""


def render_score_block(label: str, value: float, details: list[str]) -> str:
    width = max(0.0, min(100.0, value))
    detail_list = "".join(f"<li>{html.escape(detail)}</li>" for detail in details)
    detail_html = ""
    if detail_list:
        detail_html = f"""
      <details class="score-detail">
        <summary>Toon berekening</summary>
        <ul>{detail_list}</ul>
      </details>"""
    return f"""
    <div class="score-block">
      <div class="score-row">
        <span>{html.escape(label)}</span>
        <div class="bar" aria-hidden="true"><span style="width: {width:.1f}%"></span></div>
        <strong>{value:.1f}</strong>
      </div>
      {detail_html}
    </div>"""


def render_evidence_diagnostics(report: AdviceReport) -> str:
    diagnostics = report.evidence_diagnostics
    if diagnostics is None:
        return ""
    scope_labels = {
        "symbol": "Aandeel",
        "sector": "Sector",
        "theme": "Thema",
        "general": "Algemeen",
    }
    scope_items = "".join(
        f"<li>{html.escape(scope_labels.get(scope, scope))}: {diagnostics.scope_counts.get(scope, 0)}</li>"
        for scope in ("symbol", "sector", "theme", "general")
        if diagnostics.scope_counts.get(scope, 0)
    )
    if not scope_items:
        scope_items = "<li>Geen geselecteerde fragmenten.</li>"
    warning_items = "".join(f"<li>{html.escape(warning)}</li>" for warning in diagnostics.warnings)
    warning_block = f'<ul class="risk-list">{warning_items}</ul>' if warning_items else ""
    accepted = ", ".join(diagnostics.accepted_symbols[:8]) or report.symbol
    context_items = [
        f"Vertrouwde hits bekeken: {diagnostics.trusted_hits_considered}",
        f"Gebruikt in analyse: {diagnostics.selected_count}",
        f"Toegestane aandelen/aliassen: {accepted}",
    ]
    if diagnostics.sector and diagnostics.sector != "Onbekend":
        context_items.append(f"Sectorregel: {diagnostics.sector}")
    if diagnostics.theme and diagnostics.theme != "Onbekend":
        context_items.append(f"Themaregel: {diagnostics.theme}")
    context_list = "".join(f"<li>{html.escape(item)}</li>" for item in context_items)
    return f"""
          <details class="supporting-detail" open>
            <summary>Bewijsdiagnose</summary>
            <p class="evidence-meta">Zoekcontext: {html.escape(diagnostics.query)}</p>
            <ul class="data-list">{context_list}</ul>
            <p class="evidence-meta">Verdeling gebruikt bewijs</p>
            <ul class="data-list">{scope_items}</ul>
            {warning_block}
          </details>"""


def render_evidence_item(hit, report: AdviceReport) -> str:
    date = f", {hit.publication_date}" if hit.publication_date else ""
    scope = knowledge_scope_from_tags(hit.source_type, hit.chunk.tags)
    excerpt = hit.chunk.text[:520].strip()
    if len(hit.chunk.text) > 520:
        excerpt += "..."
    diagnostics = report.evidence_diagnostics
    query = diagnostics.query if diagnostics is not None else ""
    scope_rule = evidence_scope_rule(scope, diagnostics)
    matching_terms = evidence_matching_terms(hit, query)
    match_label = ", ".join(matching_terms) if matching_terms else "Geen directe termhighlight; score komt uit vectoroverlap."
    tags_label = ", ".join(hit.chunk.tags) if hit.chunk.tags else "n.b."
    knowledge_filter = knowledge_filter_url_for_scope(scope)
    actions = render_evidence_actions(hit, report.symbol)
    return f"""
    <article class="evidence-item">
      <p class="evidence-title">{html.escape(hit.title)}</p>
      <p class="evidence-meta">{html.escape(hit.source_type)}{html.escape(date)} - {html.escape(scope.label)} - score {hit.score:.2f}</p>
      <p class="evidence-text">{html.escape(excerpt)}</p>
      <details class="score-detail">
        <summary>Waarom gekozen?</summary>
        <ul class="data-list">
          <li>Zoekcontext: {html.escape(query or "n.b.")}</li>
          <li>Scope-regel: {html.escape(scope_rule)}</li>
          <li>Chunk: {hit.chunk.chunk_index + 1}; tags: {html.escape(tags_label)}</li>
          <li>Matchende termen: {html.escape(match_label)}</li>
        </ul>
      </details>
      <div class="button-row">
        <a class="button secondary" href="{html.escape(knowledge_filter)}">Open in kennisbibliotheek</a>
        {actions}
      </div>
    </article>"""


def evidence_scope_rule(scope, diagnostics) -> str:
    if scope.kind == "general":
        return "Algemene kennis mag altijd meewegen, maar krijgt een waarschuwing wanneer dit de enige bewijssoort is."
    if scope.kind == "symbol":
        accepted = ", ".join(diagnostics.accepted_symbols) if diagnostics is not None else ""
        return f"Aandeel-specifiek; toegestaan wanneer {scope.value} in aliassen/tickers zit ({accepted})."
    if scope.kind == "sector":
        sector = diagnostics.sector if diagnostics is not None else ""
        return f"Sector-specifiek; toegestaan wanneer scope {scope.value} overeenkomt met analyse-sector {sector}."
    if scope.kind == "theme":
        theme = diagnostics.theme if diagnostics is not None else ""
        return f"Thema-specifiek; toegestaan wanneer scope {scope.value} overeenkomt met analyse-thema {theme}."
    return "Onbekende scope; fragment is alleen getoond nadat de centrale scopefilter het toeliet."


def evidence_matching_terms(hit, query: str) -> list[str]:
    if not query:
        return []
    chunk_terms = set(tokenize(hit.chunk.text))
    matches: list[str] = []
    seen: set[str] = set()
    for term in tokenize(query):
        if len(term) < 4 or term in seen:
            continue
        seen.add(term)
        if term in chunk_terms:
            matches.append(term)
        if len(matches) >= 10:
            break
    return matches


def knowledge_filter_url_for_scope(scope) -> str:
    scope_type = _scope_type_for_filter(scope.kind)
    params = ["status=vertrouwd"]
    if scope_type:
        params.append(f"scope_type={quote_plus(scope_type)}")
    if scope.value:
        params.append(f"scope_value={quote_plus(scope.display_value or scope.value)}")
    return "/knowledge?" + "&".join(params)


def render_evidence_actions(hit, symbol: str) -> str:
    document_id = hit.chunk.document_id
    if not document_id:
        return ""
    return (
        render_knowledge_status_form(
            document_id,
            "voorgesteld",
            "Zet terug naar voorgesteld",
            return_to=f"/analyze?symbol={quote_plus(symbol)}",
        )
        + render_knowledge_status_form(
            document_id,
            "verworpen",
            "Verwerp document",
            return_to=f"/analyze?symbol={quote_plus(symbol)}",
        )
    )


def render_data_source_item(source) -> str:
    note = f"<br>{html.escape(source.note)}" if source.note else ""
    return f"""
    <article class="evidence-item">
      <p class="evidence-title">{html.escape(source.field_name)}: {html.escape(source.value_label)}</p>
      <p class="evidence-meta">
        <a href="{html.escape(source.source_url)}" target="_blank" rel="noreferrer">{html.escape(source.source_name)}</a>
        - {html.escape(source.source_date)}
        - {html.escape(source.source_quality)}
        {note}
      </p>
    </article>"""
