"""Small local web UI for the beleggingsraadgever."""

from __future__ import annotations

import argparse
import html
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .advisor import Advisor
from .models import AdviceReport
from .real_data import seed_besi
from .sample_data import seed_demo
from .storage import DEFAULT_DB_PATH, SQLiteRepository


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
  grid-template-columns: 96px minmax(120px, 180px) auto auto;
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

.score-detail summary {
  cursor: pointer;
  font-weight: 700;
}

.score-detail ul {
  margin-top: 8px;
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
.assumption-list,
.risk-list {
  color: var(--muted);
  font-size: 14px;
}

.evidence-text {
  margin: 6px 0 0;
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
        seed_besi(repository)

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
            if parsed.path not in {"/", "/analyze"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            params = parse_qs(parsed.query)
            symbol = params.get("symbol", ["DEMO"])[0].strip().upper() or "DEMO"
            report = None
            error = None

            if parsed.path == "/analyze" or parsed.query:
                try:
                    report = Advisor(repository).analyze(symbol)
                except LookupError:
                    error = f"Geen lokale data gevonden voor {symbol}. Probeer DEMO of importeer eerst data."

            self._send_html(build_page(symbol=symbol, report=report, error=error))

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


def build_page(symbol: str = "DEMO", report: Optional[AdviceReport] = None, error: Optional[str] = None) -> str:
    escaped_symbol = html.escape(symbol)
    content = ""
    if error:
        content = f'<div class="notice">{html.escape(error)}</div>'
    elif report:
        content = render_report(report)
    else:
        content = '<div class="notice">DEMO staat klaar als eerste analyse.</div>'

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
        </form>
      </div>
    </header>
    <main>{content}</main>
  </div>
</body>
</html>"""


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

    freshness = "".join(
        f"<li>{html.escape(name)}: {html.escape(value)}</li>"
        for name, value in report.data_freshness.items()
    )
    assumptions = "".join(f"<li>{html.escape(item)}</li>" for item in report.assumptions)

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
        <section>
          <h3>Aannames</h3>
          <ul class="assumption-list">{assumptions}</ul>
        </section>
      </div>
    </div>"""


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


if __name__ == "__main__":
    raise SystemExit(main())
