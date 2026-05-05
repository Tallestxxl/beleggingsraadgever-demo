"""Small local web UI for the beleggingsraadgever."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from dataclasses import dataclass
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote_plus, urlparse

from .advisor import Advisor
from .collector import collect_snapshot_data
from .importer import (
    SnapshotValidationError,
    import_company_snapshot,
    load_company_snapshot,
    validate_company_snapshot,
    write_snapshot_template,
)
from .models import AdviceReport, DataSource, FinancialSnapshot, KnowledgeChunk, KnowledgeHit, MarketSnapshot
from .classification import classify_company, classify_symbol
from .models import InvestorProfile, PortfolioAsset, PortfolioClassification, PortfolioPosition
from .models import PortfolioPerformanceSummary, PortfolioPositionPerformance
from .portfolio import exposure_buckets, portfolio_position_exposures
from .portfolio_importer import import_portfolio_csv
from .real_data import DRAFTS_DIR, PROCESSED_DIR, seed_curated_snapshots
from .sample_data import seed_demo
from .storage import DEFAULT_DB_PATH, SQLiteRepository


@dataclass(frozen=True)
class SnapshotWorkflow:
    symbol: str
    path: Path
    created: bool
    errors: list[str]
    messages: list[str]

    @property
    def can_import(self) -> bool:
        return not self.errors


CSS = """
:root {
  --bg: #f6f4ef;
  --surface: #ffffff;
  --surface-soft: #ebe7dd;
  --ink: #20231f;
  --muted: #667069;
  --line: #d8d2c4;
  --accent: #0f766e;
  --accent-dark: #0b5f59;
  --warn: #9a5b14;
  --danger: #9f2424;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
}

.shell {
  min-height: 100vh;
}

.topbar {
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}

.topbar-inner {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto;
  gap: 24px;
  align-items: center;
  max-width: 1180px;
  margin: 0 auto;
  padding: 18px 24px;
}

.brand {
  min-width: 0;
}

.brand-title {
  margin: 0;
  font-size: 20px;
  font-weight: 750;
  letter-spacing: 0;
}

.brand-meta {
  margin: 2px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.ticker-form {
  display: grid;
  grid-template-columns: 96px minmax(120px, 180px) auto auto auto;
  gap: 8px;
  align-items: end;
}

label {
  color: var(--muted);
  font-size: 13px;
  font-weight: 650;
}

input[type="text"] {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  font-size: 16px;
  padding: 8px 10px;
  text-transform: uppercase;
}

input[type="date"],
input[type="number"],
select,
textarea {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  font: inherit;
  padding: 8px 10px;
}

textarea {
  min-height: 120px;
  resize: vertical;
}

.note-form {
  display: grid;
  gap: 12px;
}

.note-form input[type="text"] {
  text-transform: none;
}

.portfolio-form input[type="text"],
.portfolio-form input[type="number"] {
  text-transform: none;
}

.note-form .form-grid,
.portfolio-form .form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(160px, 220px);
  gap: 12px;
}

.portfolio-form {
  display: grid;
  gap: 12px;
}

.asset-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

button,
.button {
  min-height: 40px;
  border: 1px solid var(--accent);
  border-radius: 6px;
  background: var(--accent);
  color: #ffffff;
  font-size: 14px;
  font-weight: 750;
  padding: 8px 14px;
  text-decoration: none;
  cursor: pointer;
  white-space: nowrap;
}

.button.secondary {
  background: var(--surface);
  color: var(--accent-dark);
}

main {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px;
}

.notice {
  border: 1px solid var(--line);
  border-left: 4px solid var(--warn);
  border-radius: 6px;
  background: var(--surface);
  padding: 14px 16px;
  color: var(--ink);
}

.workflow-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  margin-bottom: 18px;
}

.button-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

button:disabled {
  border-color: var(--line);
  background: var(--surface-soft);
  color: var(--muted);
  cursor: default;
}

.code-path {
  display: block;
  overflow-wrap: anywhere;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-soft);
  padding: 10px;
  color: var(--ink);
  font-size: 13px;
}

.report-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) repeat(3, minmax(110px, 150px));
  gap: 12px;
  align-items: stretch;
  margin-bottom: 18px;
}

.verdict {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  padding: 18px;
}

.verdict h2 {
  margin: 0;
  font-size: 28px;
  letter-spacing: 0;
}

.verdict p {
  margin: 6px 0 0;
  color: var(--muted);
}

.metric {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  padding: 14px;
}

.metric-label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

.metric-value {
  display: block;
  margin-top: 5px;
  font-size: 22px;
  font-weight: 800;
}

.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(300px, 0.8fr);
  gap: 18px;
}

section {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  padding: 18px;
}

section + section {
  margin-top: 18px;
}

h3 {
  margin: 0 0 12px;
  font-size: 17px;
  letter-spacing: 0;
}

.summary {
  margin: 0;
  max-width: 78ch;
}

.score-list {
  display: grid;
  gap: 12px;
}

.score-block {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}

.score-block:first-child {
  border-top: 0;
  padding-top: 0;
}

.score-row {
  display: grid;
  grid-template-columns: 150px minmax(120px, 1fr) 56px;
  gap: 10px;
  align-items: center;
}

.bar {
  height: 10px;
  border-radius: 999px;
  background: var(--surface-soft);
  overflow: hidden;
}

.bar span {
  display: block;
  height: 100%;
  background: var(--accent);
}

.score-detail {
  margin-top: 8px;
  color: var(--muted);
  font-size: 13px;
}

.score-detail summary,
.supporting-detail summary {
  cursor: pointer;
  font-weight: 700;
}

.score-detail ul,
.supporting-detail .source-list {
  margin-top: 8px;
}

.supporting-detail summary {
  color: var(--ink);
  font-size: 17px;
  letter-spacing: 0;
}

.evidence-list {
  display: grid;
  gap: 12px;
}

.evidence-item {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}

.evidence-item:first-child {
  border-top: 0;
  padding-top: 0;
}

.evidence-title {
  margin: 0;
  font-weight: 750;
}

.evidence-meta,
.data-list,
.source-list,
.assumption-list,
.risk-list,
.workflow-list {
  color: var(--muted);
  font-size: 14px;
}

.evidence-text {
  margin: 6px 0 0;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.data-table th,
.data-table td {
  border-top: 1px solid var(--line);
  padding: 8px 6px;
  text-align: left;
  vertical-align: top;
}

.data-table th {
  color: var(--muted);
  font-size: 12px;
  text-transform: uppercase;
}

ul {
  margin: 0;
  padding-left: 18px;
}

li + li {
  margin-top: 6px;
}

.risk-list {
  color: var(--danger);
}

@media (max-width: 860px) {
  .topbar-inner,
  .ticker-form,
  .workflow-header,
  .report-header,
  .grid {
    grid-template-columns: 1fr;
  }

  .ticker-form {
    align-items: stretch;
  }

  .score-row {
    grid-template-columns: 1fr;
  }

  .note-form .form-grid,
  .portfolio-form .form-grid,
  .asset-grid {
    grid-template-columns: 1fr;
  }
}
"""


def serve(
    db_path: Path = DEFAULT_DB_PATH,
    host: str = "127.0.0.1",
    port: int = 8765,
    seed: bool = True,
) -> None:
    repository = SQLiteRepository(db_path)
    repository.init()
    if seed:
        seed_demo(repository)
        seed_curated_snapshots(repository)

    handler = _make_handler(repository)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Beleggingsraadgever web UI: http://{host}:{port}")
    print(f"Database: {db_path}")
    server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beleggingsraadgever-web")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-seed", action="store_true", help="Do not load demo data on startup")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    serve(Path(args.db), args.host, args.port, seed=not args.no_seed)
    return 0


def _make_handler(repository: SQLiteRepository):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json({"ok": True})
                return
            if parsed.path not in {"/", "/analyze", "/workflow", "/portfolio"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            params = parse_qs(parsed.query)
            symbol = params.get("symbol", ["DEMO"])[0].strip().upper() or "DEMO"
            if parsed.path == "/portfolio":
                message = params.get("message", [""])[0].strip()
                self._send_html(build_portfolio_page(repository, message=message or None))
                return

            report = None
            error = None
            workflow = None

            if parsed.path == "/workflow":
                workflow = ensure_snapshot_workflow(symbol)
                report = build_draft_report(repository, workflow)
            elif parsed.path == "/analyze" or parsed.query:
                try:
                    report = Advisor(repository).analyze(symbol, peer_snapshots=local_peer_snapshots())
                except LookupError:
                    workflow = ensure_snapshot_workflow(symbol, auto_collect=True)
                    report = build_draft_report(repository, workflow)

            self._send_html(build_page(symbol=symbol, report=report, error=error, workflow=workflow))

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path not in {
                "/workflow/import",
                "/workflow/collect",
                "/workflow/note",
                "/portfolio/import-csv",
                "/portfolio/profile",
                "/portfolio/position",
            }:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            body_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(body_length).decode("utf-8")
            params = parse_qs(body)

            if parsed.path == "/portfolio/profile":
                try:
                    save_portfolio_profile(repository, params)
                except ValueError as error:
                    self._send_html(build_portfolio_page(repository, error=str(error)))
                    return
                self._redirect("/portfolio?message=Profiel%20opgeslagen")
                return

            if parsed.path == "/portfolio/import-csv":
                try:
                    message = import_portfolio_csv_workflow(repository, params)
                except (OSError, ValueError) as error:
                    self._send_html(build_portfolio_page(repository, error=str(error)))
                    return
                self._redirect(f"/portfolio?message={quote_plus(message)}")
                return

            if parsed.path == "/portfolio/position":
                try:
                    save_portfolio_position(repository, params)
                except ValueError as error:
                    self._send_html(build_portfolio_page(repository, error=str(error)))
                    return
                self._redirect("/portfolio?message=Positie%20opgeslagen")
                return

            symbol = params.get("symbol", [""])[0].strip().upper()
            if not symbol:
                self._send_html(build_page(error="Geen ticker ontvangen."))
                return

            if parsed.path == "/workflow/collect":
                workflow = collect_snapshot_workflow(symbol)
                report = build_draft_report(repository, workflow)
                self._send_html(build_page(symbol=symbol, report=report, workflow=workflow))
                return

            if parsed.path == "/workflow/note":
                workflow, note_error = save_case_note_workflow(symbol, params)
                report = build_draft_report(repository, workflow)
                self._send_html(build_page(symbol=symbol, report=report, workflow=workflow, error=note_error))
                return

            workflow = ensure_snapshot_workflow(symbol)
            if workflow.errors:
                self._send_html(
                    build_page(
                        symbol=symbol,
                        workflow=workflow,
                        error="Snapshot is nog niet importeerbaar.",
                    )
                )
                return

            try:
                imported_symbol = import_company_snapshot(repository, workflow.path)
                archive_path = archive_imported_snapshot(workflow.path, symbol, processed_dir=PROCESSED_DIR)
                repository.record_snapshot_import(
                    symbol=imported_symbol,
                    imported_from=str(workflow.path),
                    source_checksum=archive_path.source_checksum,
                    processed_path=str(archive_path.path),
                )
            except SnapshotValidationError as validation_error:
                workflow = SnapshotWorkflow(
                    symbol=symbol,
                    path=workflow.path,
                    created=False,
                    errors=validation_error.errors,
                    messages=[],
                )
                self._send_html(build_page(symbol=symbol, workflow=workflow, error="Snapshot is nog niet importeerbaar."))
                return

            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", f"/analyze?symbol={quote_plus(symbol)}")
            self.end_headers()

        def _redirect(self, location: str) -> None:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            self.end_headers()

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(self, payload: dict) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def build_page(
    symbol: str = "DEMO",
    report: Optional[AdviceReport] = None,
    error: Optional[str] = None,
    workflow: Optional[SnapshotWorkflow] = None,
) -> str:
    escaped_symbol = html.escape(symbol)
    content = ""
    if workflow and report:
        notice_text = error or (
            "Conceptanalyse: de cijfers zijn al bruikbaar voor een eerste score. "
            "De snapshot is nog niet definitief geïmporteerd zolang er validatiepunten open staan."
        )
        content = (
            f'<div class="notice">{html.escape(notice_text)}</div>'
            + render_report(report)
            + render_snapshot_workflow(workflow)
        )
    elif workflow:
        notice = f'<div class="notice">{html.escape(error)}</div>' if error else ""
        content = notice + render_snapshot_workflow(workflow)
    elif error:
        content = f'<div class="notice">{html.escape(error)}</div>'
    elif report:
        content = render_report(report)
    else:
        content = '<div class="notice">DEMO staat klaar als eerste analyse.</div>'

    return build_shell(symbol, content)


def build_shell(symbol: str, content: str) -> str:
    escaped_symbol = html.escape(symbol)
    return f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Beleggingsraadgever</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="topbar-inner">
        <div class="brand">
          <h1 class="brand-title">Beleggingsraadgever</h1>
          <p class="brand-meta">Local-first analyse met bewijsvoering</p>
        </div>
        <form class="ticker-form" action="/analyze" method="get">
          <label for="symbol">Ticker</label>
          <input id="symbol" name="symbol" type="text" value="{escaped_symbol}" autocomplete="off">
          <button type="submit">Analyseer</button>
          <a class="button secondary" href="/analyze?symbol=DEMO">Demo</a>
          <a class="button secondary" href="/portfolio">Portefeuille</a>
        </form>
      </div>
    </header>
    <main>{content}</main>
  </div>
</body>
</html>"""


ASSET_LABELS = {
    "cash": "Cash / spaargeld",
    "house": "Huis",
    "gold": "Goud",
    "bitcoin": "Bitcoin",
    "other": "Overig",
}


def build_portfolio_page(
    repository: SQLiteRepository,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    return build_shell("DEMO", render_portfolio_dashboard(repository, message=message, error=error))


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
          <h3>Effectenportefeuille</h3>
          {render_positions_table(positions)}
        </section>
        <section>
          <h3>Identiteitskoppelingen</h3>
          {render_aliases_table(aliases)}
        </section>
      </div>
    </div>"""


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
                <input id="asset-{html.escape(asset_type)}" name="asset_{html.escape(asset_type)}" type="number" step="0.01" min="0" value="{format_input_number(asset_values.get(asset_type))}">
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
                <input id="annual-income" name="annual_income" type="number" min="0" step="100" value="{format_input_number(profile.annual_income if profile else None)}">
              </div>
            </div>
            <div class="form-grid">
              <div>
                <label for="horizon-years">Beleggingshorizon in jaren</label>
                <input id="horizon-years" name="horizon_years" type="number" min="0" step="1" value="{format_input_number(profile.horizon_years if profile else None)}">
              </div>
              <div>
                <label for="cash-buffer">Gewenste cashbuffer</label>
                <input id="cash-buffer" name="cash_buffer" type="number" min="0" step="100" value="{format_input_number(profile.cash_buffer if profile else None)}">
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
          <td>{row["quantity"]:,.4f}</td>
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


def import_portfolio_csv_workflow(repository: SQLiteRepository, params: dict) -> str:
    csv_path = _first_param(params, "csv_path")
    if not csv_path:
        raise ValueError("CSV-pad is verplicht.")
    result = import_portfolio_csv(repository, Path(csv_path))
    return result.summary


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


def format_eur(value: Optional[float]) -> str:
    if value is None:
        return "EUR 0"
    return f"EUR {value:,.0f}".replace(",", ".")


def format_eur_cents(value: Optional[float]) -> str:
    if value is None:
        return "EUR 0,00"
    formatted = f"EUR {value:,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def format_percent(value: float) -> str:
    return f"{value:.1%}"


def format_optional_percent(value: Optional[float]) -> str:
    return "n.b." if value is None else f"{value:.1%}"


def format_optional_number(value: Optional[float], suffix: str = "") -> str:
    return "n.b." if value is None else f"{value:.1f}{suffix}"


def format_compact_amount(value: Optional[float]) -> str:
    if value is None:
        return "n.b."
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f} mld"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f} mln"
    return f"{value:,.0f}".replace(",", ".")


def format_input_number(value: Optional[float]) -> str:
    if value is None:
        return ""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return str(value)


def ensure_snapshot_workflow(
    symbol: str,
    drafts_dir: Path = DRAFTS_DIR,
    auto_collect: bool = False,
    fetch_text=None,
) -> SnapshotWorkflow:
    normalized_symbol = symbol.strip().upper()
    path = drafts_dir / f"{normalized_symbol.lower()}.json"
    created = False
    if not path.exists():
        write_snapshot_template(normalized_symbol, path)
        created = True
    messages: list[str] = []
    if auto_collect and (created or not _draft_has_core_figures(path)):
        collection = collect_snapshot_data(normalized_symbol, path, fetch_text=fetch_text)
        messages.extend(collection.messages)
        messages.extend(collection.errors[:1] if not collection.messages else [])
    errors = validate_snapshot_file(path)
    return SnapshotWorkflow(symbol=normalized_symbol, path=path, created=created, errors=errors, messages=messages)


def collect_snapshot_workflow(symbol: str, drafts_dir: Path = DRAFTS_DIR) -> SnapshotWorkflow:
    normalized_symbol = symbol.strip().upper()
    path = drafts_dir / f"{normalized_symbol.lower()}.json"
    result = collect_snapshot_data(normalized_symbol, path)
    messages = list(result.messages)
    if result.updated_fields:
        messages.append("Bijgewerkte velden: " + ", ".join(result.updated_fields))
    if result.errors and not result.messages:
        messages.append(result.errors[0])
    return SnapshotWorkflow(
        symbol=normalized_symbol,
        path=result.path,
        created=False,
        errors=validate_snapshot_file(result.path),
        messages=messages,
    )


def save_case_note_workflow(symbol: str, params: dict, drafts_dir: Path = DRAFTS_DIR) -> tuple[SnapshotWorkflow, Optional[str]]:
    normalized_symbol = symbol.strip().upper()
    path = drafts_dir / f"{normalized_symbol.lower()}.json"
    if not path.exists():
        write_snapshot_template(normalized_symbol, path)

    title = _first_param(params, "note_title")
    source_type = _first_param(params, "source_type") or "eigen_notitie"
    publication_date = _first_param(params, "publication_date") or date.today().isoformat()
    raw_text = _first_param(params, "raw_text")
    conclusion = _first_param(params, "principle_statement")

    if not title or not raw_text or not conclusion:
        workflow = ensure_snapshot_workflow(normalized_symbol, drafts_dir=drafts_dir)
        return workflow, "Vul minimaal titel, tekstfragment en conclusie in."

    try:
        _save_case_note(path, normalized_symbol, title, source_type, publication_date, raw_text, conclusion)
        message = "Casusnotitie opgeslagen en gekoppeld aan dit aandeel."
    except (OSError, json.JSONDecodeError, SnapshotValidationError, ValueError) as error:
        workflow = ensure_snapshot_workflow(normalized_symbol, drafts_dir=drafts_dir)
        return workflow, f"Casusnotitie kon niet worden opgeslagen: {error}"

    workflow = SnapshotWorkflow(
        symbol=normalized_symbol,
        path=path,
        created=False,
        errors=validate_snapshot_file(path),
        messages=[message],
    )
    return workflow, None


def _save_case_note(
    path: Path,
    symbol: str,
    title: str,
    source_type: str,
    publication_date: str,
    raw_text: str,
    conclusion: str,
) -> None:
    data = load_company_snapshot(path)
    if publication_date:
        _required_iso_date(publication_date)

    note_title = title.strip()
    document = {
        "title": note_title,
        "source_type": source_type.strip() or "eigen_notitie",
        "author": "Handmatig ingevoerd",
        "publication_date": publication_date,
        "tags": [symbol, "casusnotitie"],
        "raw_text": raw_text.strip(),
    }

    documents = data.setdefault("documents", [])
    data["documents"] = [
        document_item
        for document_item in documents
        if not isinstance(document_item, dict) or document_item.get("title") != note_title
    ] + [document]

    principle = {
        "title": f"{symbol}: {note_title}",
        "statement": conclusion.strip(),
        "category": "casus",
        "approved": True,
        "confidence": 1.0,
        "source_document_title": note_title,
    }

    principles = data.setdefault("principles", [])
    if principles and isinstance(principles[0], dict) and _principle_is_todo(principles[0]):
        principles[0] = principle
    else:
        data["principles"] = [
            item
            for item in principles
            if not isinstance(item, dict) or item.get("source_document_title") != note_title
        ] + [principle]

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _first_param(params: dict, name: str) -> str:
    values = params.get(name, [""])
    return values[0].strip() if values else ""


def _parse_optional_float(value: str, label: str) -> Optional[float]:
    if not value:
        return None
    try:
        parsed = float(value.replace(",", "."))
    except ValueError as error:
        raise ValueError(f"{label} moet een getal zijn.") from error
    if parsed < 0:
        raise ValueError(f"{label} mag niet negatief zijn.")
    return parsed


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


def _principle_is_todo(principle: dict) -> bool:
    values = [principle.get("title"), principle.get("statement")]
    return any(isinstance(value, str) and "TODO" in value.upper() for value in values)


def _required_iso_date(value: str) -> None:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError("datum moet YYYY-MM-DD gebruiken")
    date.fromisoformat(value)


def build_draft_report(repository: SQLiteRepository, workflow: SnapshotWorkflow) -> Optional[AdviceReport]:
    """Build a provisional report from a draft snapshot when core figures are present."""

    try:
        snapshot = load_company_snapshot(workflow.path)
        financial = _financial_from_snapshot(workflow.symbol, snapshot)
        market = _market_from_snapshot(workflow.symbol, snapshot)
    except (KeyError, TypeError, ValueError, SnapshotValidationError, json.JSONDecodeError, OSError):
        return None

    _store_snapshot_classification(repository, workflow.symbol, snapshot)
    return Advisor(repository).analyze_snapshots(
        workflow.symbol,
        financial,
        market,
        data_sources=_data_sources_from_snapshot(workflow.symbol, snapshot),
        evidence=_evidence_from_snapshot(snapshot),
        peer_snapshots=local_peer_snapshots(),
        extra_assumptions=[
            "Dit is een conceptanalyse uit het lokale conceptbestand; nog niet alle handmatige controlepunten zijn afgerond.",
            "Concurrentiepositie, cycliciteit, managementsignalen en jouw beleggingsprincipe kunnen het oordeel nog wijzigen.",
        ],
        knowledge_label="conceptbestand",
    )


def local_peer_snapshots() -> dict[str, tuple[FinancialSnapshot, MarketSnapshot]]:
    snapshots: dict[str, tuple[FinancialSnapshot, MarketSnapshot]] = {}
    for directory in (DRAFTS_DIR, Path("data/imports"), PROCESSED_DIR):
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            try:
                data = load_company_snapshot(path)
                symbol = str(data.get("symbol", "")).strip().upper()
                if not symbol:
                    continue
                snapshots[symbol] = (_financial_from_snapshot(symbol, data), _market_from_snapshot(symbol, data))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, SnapshotValidationError):
                continue
    return snapshots


def _store_snapshot_classification(repository: SQLiteRepository, symbol: str, snapshot: dict) -> None:
    classification_data = snapshot.get("classification") if isinstance(snapshot.get("classification"), dict) else {}
    sector = classification_data.get("sector")
    theme = classification_data.get("theme")
    if _classification_value_missing(sector) or _classification_value_missing(theme):
        description = " ".join(
            str(document.get("raw_text") or "")
            for document in snapshot.get("documents", [])
            if isinstance(document, dict)
        )
        classification = classify_company(symbol, description=description)
        sector = classification.sector if _classification_value_missing(sector) else sector
        theme = classification.theme if _classification_value_missing(theme) else theme
    if _classification_value_missing(sector) and _classification_value_missing(theme):
        return
    repository.upsert_portfolio_classification(
        PortfolioClassification(symbol=symbol, sector=str(sector), theme=str(theme))
    )


def _classification_value_missing(value: object) -> bool:
    return not str(value or "").strip() or str(value).strip() == "Onbekend"


def validate_snapshot_file(path: Path) -> list[str]:
    try:
        return validate_company_snapshot(load_company_snapshot(path))
    except SnapshotValidationError as error:
        return error.errors
    except json.JSONDecodeError as error:
        return [f"Snapshot JSON is ongeldig: {error.msg} op regel {error.lineno}."]
    except OSError as error:
        return [f"Snapshotbestand kan niet worden gelezen: {error}."]


@dataclass(frozen=True)
class ArchivedSnapshot:
    path: Path
    source_checksum: str


def archive_imported_snapshot(path: Path, symbol: str, processed_dir: Path = PROCESSED_DIR) -> ArchivedSnapshot:
    """Move an imported draft snapshot to processed storage and preserve audit metadata."""

    source_path = Path(path)
    source_bytes = source_path.read_bytes()
    source_checksum = hashlib.sha256(source_bytes).hexdigest()
    imported_at = datetime.now().astimezone().isoformat(timespec="seconds")
    data = json.loads(source_bytes.decode("utf-8"))
    data["import_metadata"] = {
        "imported_at": imported_at,
        "imported_from": str(source_path),
        "source_checksum": source_checksum,
    }

    processed_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_processed_path(processed_dir, symbol, imported_at, source_checksum)
    destination.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    source_path.unlink()
    return ArchivedSnapshot(path=destination, source_checksum=source_checksum)


def _unique_processed_path(processed_dir: Path, symbol: str, imported_at: str, checksum: str) -> Path:
    stamp = (
        imported_at.replace("-", "")
        .replace(":", "")
        .replace("+", "-")
        .replace(".", "")
    )
    stamp = "".join(character for character in stamp if character.isalnum() or character == "-")[:15]
    base = f"{symbol.strip().lower()}-{stamp}-{checksum[:8]}"
    destination = processed_dir / f"{base}.json"
    index = 2
    while destination.exists():
        destination = processed_dir / f"{base}-{index}.json"
        index += 1
    return destination


def _draft_has_core_figures(path: Path) -> bool:
    try:
        snapshot = load_company_snapshot(path)
        _financial_from_snapshot(str(snapshot.get("symbol", "")), snapshot)
        _market_from_snapshot(str(snapshot.get("symbol", "")), snapshot)
        return True
    except (KeyError, TypeError, ValueError, SnapshotValidationError, json.JSONDecodeError, OSError):
        return False


def _financial_from_snapshot(symbol: str, snapshot: dict) -> FinancialSnapshot:
    data = snapshot["financial_snapshot"]
    return FinancialSnapshot(
        symbol=symbol,
        period_end=_required_text(data.get("period_end")),
        period_type=_required_text(data.get("period_type")),
        revenue=_required_float(data.get("revenue")),
        gross_margin=_optional_float(data.get("gross_margin")),
        operating_margin=_optional_float(data.get("operating_margin")),
        net_margin=_optional_float(data.get("net_margin")),
        free_cash_flow=_optional_float(data.get("free_cash_flow")),
        debt=_optional_float(data.get("debt")),
        cash=_optional_float(data.get("cash")),
        shares_outstanding=_optional_float(data.get("shares_outstanding")),
        dividend_per_share=_optional_float(data.get("dividend_per_share")),
        buyback_value=_optional_float(data.get("buyback_value")),
    )


def _market_from_snapshot(symbol: str, snapshot: dict) -> MarketSnapshot:
    data = snapshot["market_snapshot"]
    return MarketSnapshot(
        symbol=symbol,
        as_of=_required_text(data.get("as_of")),
        close_price=_required_float(data.get("close_price")),
        currency=_required_text(data.get("currency")),
        pe_ratio=_optional_float(data.get("pe_ratio")),
        ev_ebitda=_optional_float(data.get("ev_ebitda")),
        fcf_yield=_optional_float(data.get("fcf_yield")),
        dividend_yield=_optional_float(data.get("dividend_yield")),
        momentum_12m=_optional_float(data.get("momentum_12m")),
        volatility_1y=_optional_float(data.get("volatility_1y")),
    )


def _data_sources_from_snapshot(symbol: str, snapshot: dict) -> list[DataSource]:
    sources = []
    for source in snapshot.get("data_sources", []):
        if not isinstance(source, dict):
            continue
        required = [
            source.get("field_name"),
            source.get("value_label"),
            source.get("source_name"),
            source.get("source_url"),
            source.get("source_date"),
            source.get("source_quality"),
        ]
        if any(_is_placeholder(value) for value in required):
            continue
        sources.append(
            DataSource(
                symbol=symbol,
                field_name=str(source["field_name"]),
                value_label=str(source["value_label"]),
                source_name=str(source["source_name"]),
                source_url=str(source["source_url"]),
                source_date=str(source["source_date"]),
                source_quality=str(source["source_quality"]),
                note=str(source.get("note") or ""),
            )
        )
    return sources


def _evidence_from_snapshot(snapshot: dict) -> list[KnowledgeHit]:
    hits = []
    for index, document in enumerate(snapshot.get("documents", [])):
        if not isinstance(document, dict):
            continue
        raw_text = str(document.get("raw_text") or "").strip()
        if not raw_text or "TODO:" in raw_text:
            continue
        tags = document.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        hits.append(
            KnowledgeHit(
                chunk=KnowledgeChunk(
                    document_id=0,
                    chunk_index=index,
                    text=raw_text,
                    tags=[str(tag) for tag in tags],
                ),
                score=1.0,
                title=str(document.get("title") or "Conceptdocument"),
                source_type=str(document.get("source_type") or "concept_snapshot"),
                publication_date=document.get("publication_date"),
            )
        )
    return hits[:5]


def _required_text(value) -> str:
    if _is_placeholder(value):
        raise ValueError("required text is missing")
    return str(value).strip()


def _required_float(value) -> float:
    if _is_placeholder(value):
        raise ValueError("required number is missing")
    return float(value)


def _optional_float(value) -> Optional[float]:
    if _is_placeholder(value):
        return None
    return float(value)


def _is_placeholder(value) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text == "YYYY-MM-DD" or text.upper().startswith("TODO")


def render_snapshot_workflow(workflow: SnapshotWorkflow) -> str:
    status = "Concept aangemaakt" if workflow.created else "Concept gevonden"
    status_detail = "Klaar voor import" if workflow.can_import else f"{len(workflow.errors)} punten open"
    messages = "".join(f"<li>{html.escape(message)}</li>" for message in workflow.messages)
    visible_errors = workflow.errors[:24]
    hidden_count = max(0, len(workflow.errors) - len(visible_errors))
    errors = "".join(f"<li>{html.escape(error)}</li>" for error in visible_errors)
    if hidden_count:
        errors += f"<li>Nog {hidden_count} extra punten. Gebruik de validator voor de volledige lijst.</li>"
    if not errors:
        errors = "<li>Geen validatiefouten gevonden.</li>"
    import_disabled = "" if workflow.can_import else " disabled"
    action_hint = (
        "Alle validatiepunten zijn opgelost. Importeer de snapshot om dit aandeel voortaan als reguliere analyse te gebruiken."
        if workflow.can_import
        else "Vul de resterende validatiepunten aan voordat de snapshot definitief kan worden geïmporteerd."
    )

    return f"""
    <div class="workflow-header">
      <div class="verdict">
        <h2>{html.escape(workflow.symbol)}: Workflow gestart</h2>
        <p>Het conceptbestand bewaart opgehaalde cijfers, brondata en de resterende handmatige controlepunten.</p>
      </div>
      <div class="metric">
        <span class="metric-label">Status</span>
        <span class="metric-value">{html.escape(status_detail)}</span>
      </div>
    </div>
    <div class="grid">
      <div>
        <section>
          <h3>Conceptbestand</h3>
          <p class="evidence-meta">{html.escape(status)}</p>
          <code class="code-path">{html.escape(str(workflow.path))}</code>
        </section>
        {f'<section><h3>Workflowmeldingen</h3><ul class="workflow-list">{messages}</ul></section>' if messages else ''}
        <section>
          <h3>Validatie</h3>
          <ul class="workflow-list">{errors}</ul>
        </section>
      </div>
      <div>
        {render_case_note_form(workflow)}
        <section>
          <h3>Acties</h3>
          <p class="evidence-meta">{html.escape(action_hint)}</p>
          <div class="button-row">
            <a class="button secondary" href="/workflow?symbol={html.escape(workflow.symbol)}">Controleer opnieuw</a>
            <form method="post" action="/workflow/collect">
              <input type="hidden" name="symbol" value="{html.escape(workflow.symbol)}">
              <button type="submit">Haal marktdata op</button>
            </form>
            <form method="post" action="/workflow/import">
              <input type="hidden" name="symbol" value="{html.escape(workflow.symbol)}">
              <button type="submit"{import_disabled}>Importeer snapshot</button>
            </form>
          </div>
        </section>
        <section>
          <h3>Bronnen</h3>
          <ul class="workflow-list">
            <li>Jaarverslag of kwartaalbericht voor omzet, marges, kasstroom, schuld en kapitaalallocatie.</li>
            <li>Koers- en waarderingsbron voor slotkoers, multiple, FCF-yield, dividendrendement en momentum.</li>
            <li>Een korte casustekst met concurrentiepositie, cycliciteit, managementsignalen en risico.</li>
          </ul>
        </section>
      </div>
    </div>"""


def render_case_note_form(workflow: SnapshotWorkflow) -> str:
    source_options = {
        "eigen_notitie": "Eigen notitie",
        "artikel": "Artikel",
        "podcast": "Podcast",
        "jaarverslag": "Jaarverslag",
        "beleggers_belangen": "Beleggers Belangen",
        "interview": "Interview",
    }
    options = "".join(
        f'<option value="{html.escape(value)}">{html.escape(label)}</option>'
        for value, label in source_options.items()
    )
    return f"""
        <section>
          <h3>Casusnotitie voor {html.escape(workflow.symbol)}</h3>
          <form class="note-form" method="post" action="/workflow/note">
            <input type="hidden" name="symbol" value="{html.escape(workflow.symbol)}">
            <div>
              <label for="note-title-{html.escape(workflow.symbol)}">Titel</label>
              <input id="note-title-{html.escape(workflow.symbol)}" name="note_title" type="text" autocomplete="off">
            </div>
            <div class="form-grid">
              <div>
                <label for="source-type-{html.escape(workflow.symbol)}">Bron/type</label>
                <select id="source-type-{html.escape(workflow.symbol)}" name="source_type">{options}</select>
              </div>
              <div>
                <label for="publication-date-{html.escape(workflow.symbol)}">Datum</label>
                <input id="publication-date-{html.escape(workflow.symbol)}" name="publication_date" type="date" value="{date.today().isoformat()}">
              </div>
            </div>
            <div>
              <label for="raw-text-{html.escape(workflow.symbol)}">Tekstfragment</label>
              <textarea id="raw-text-{html.escape(workflow.symbol)}" name="raw_text"></textarea>
            </div>
            <div>
              <label for="principle-statement-{html.escape(workflow.symbol)}">Belangrijk principe / conclusie</label>
              <textarea id="principle-statement-{html.escape(workflow.symbol)}" name="principle_statement"></textarea>
            </div>
            <button type="submit">Sla casusnotitie op</button>
          </form>
        </section>"""


def render_report(report: AdviceReport) -> str:
    flags = ""
    if report.score.flags:
        flags = f"""
        <section>
          <h3>Risicosignalen</h3>
          <ul class="risk-list">{''.join(f'<li>{html.escape(flag)}</li>' for flag in report.score.flags)}</ul>
        </section>"""

    evidence = "".join(render_evidence_item(hit) for hit in report.evidence)
    if not evidence:
        evidence = '<p class="evidence-meta">Geen relevante fragmenten gevonden in de lokale kennisbank.</p>'
    peer_analysis = render_peer_analysis(report)

    freshness = "".join(
        f"<li>{html.escape(name)}: {html.escape(value)}</li>"
        for name, value in report.data_freshness.items()
    )
    sources = "".join(render_data_source_item(source) for source in report.data_sources)
    if not sources:
        sources = '<p class="evidence-meta">Geen veldbronnen opgeslagen voor dit aandeel.</p>'
    assumptions = "".join(f"<li>{html.escape(item)}</li>" for item in report.assumptions)
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
            <li>Gewicht positie: {html.escape(format_percent(fit.position_weight))}</li>
            <li>Richtmaximum: {html.escape(format_percent(fit.max_weight))}</li>
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
        {flags}
        <section>
          <h3>Relevante kennisbank-fragmenten</h3>
          <div class="evidence-list">{evidence}</div>
        </section>
      </div>
      <div>
        <section>
          <h3>Dataversheid</h3>
          <ul class="data-list">{freshness}</ul>
        </section>
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
          <p class="evidence-meta">Peer-set: {html.escape(analysis.group_label)}. * = geanalyseerd aandeel.</p>
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


def render_evidence_item(hit) -> str:
    date = f", {hit.publication_date}" if hit.publication_date else ""
    excerpt = hit.chunk.text[:520].strip()
    if len(hit.chunk.text) > 520:
        excerpt += "..."
    return f"""
    <article class="evidence-item">
      <p class="evidence-title">{html.escape(hit.title)}</p>
      <p class="evidence-meta">{html.escape(hit.source_type)}{html.escape(date)} - score {hit.score:.2f}</p>
      <p class="evidence-text">{html.escape(excerpt)}</p>
    </article>"""


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


if __name__ == "__main__":
    raise SystemExit(main())
