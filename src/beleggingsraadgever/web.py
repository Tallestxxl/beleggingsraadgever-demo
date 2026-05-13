"""Small local web UI for the beleggingsraadgever."""

from __future__ import annotations

import argparse
import html
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote_plus, urlparse

from .advisor import Advisor
from .importer import (
    SnapshotValidationError,
    import_company_snapshot,
)
from .models import AdviceReport
from .peer_discovery import refresh_peer_candidates_for_portfolio
from .real_data import PROCESSED_DIR, seed_curated_snapshots
from .sample_data import seed_demo
from .storage import DEFAULT_DB_PATH, SQLiteRepository
from .symbol_resolution import resolve_analysis_symbol
from .web_knowledge import build_knowledge_page
from .web_knowledge_import import (
    build_knowledge_import_preview,
    save_knowledge_document_workflow,
    update_knowledge_document_status_workflow,
)
from .web_layout import build_shell
from .web_params import first_param as _first_param, redirect_with_message, safe_return_path
from .web_report import render_report
from .web_snapshot import (
    SnapshotWorkflow,
    archive_imported_snapshot,
    build_draft_report,
    collect_snapshot_workflow,
    ensure_snapshot_workflow,
    local_peer_snapshots,
    render_snapshot_workflow,
    save_case_note_workflow,
)
from .web_status import (
    build_status_page,
    build_v1_status_row,
    refresh_provider_candidates_workflow,
    refresh_peer_candidates_workflow,
    update_provider_candidate_status_workflow,
    update_peer_candidate_status_workflow,
)
from .web_portfolio import (
    build_portfolio_page,
    create_manual_backup_workflow,
    import_portfolio_csv_workflow,
    refresh_portfolio_snapshots_workflow,
    save_portfolio_position,
    save_portfolio_profile,
)


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
    refresh_peer_candidates_for_portfolio(repository)

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
            if parsed.path not in {"/", "/analyze", "/workflow", "/portfolio", "/status", "/knowledge"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            params = parse_qs(parsed.query)
            raw_symbol = params.get("symbol", ["DEMO"])[0].strip().upper() or "DEMO"
            symbol = resolve_analysis_symbol(repository, raw_symbol) or raw_symbol
            if parsed.path == "/knowledge":
                message = params.get("message", [""])[0].strip()
                try:
                    self._send_html(build_knowledge_page(repository, message=message or None, filters=params))
                except ValueError as error:
                    self._send_html(build_knowledge_page(repository, error=str(error)))
                return
            if parsed.path == "/status":
                message = params.get("message", [""])[0].strip()
                self._send_html(build_status_page(repository, message=message or None))
                return
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
                    workflow = ensure_snapshot_workflow(symbol, auto_collect=True, repository=repository)
                    report = build_draft_report(repository, workflow)

            self._send_html(build_page(symbol=symbol, report=report, error=error, workflow=workflow, repository=repository))

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path not in {
                "/workflow/import",
                "/workflow/collect",
                "/workflow/note",
                "/portfolio/import-csv",
                "/portfolio/backup",
                "/portfolio/profile",
                "/portfolio/position",
                "/portfolio/refresh-snapshots",
                "/knowledge/preview",
                "/knowledge/import",
                "/knowledge/status",
                "/status/refresh-peers",
                "/status/refresh-providers",
                "/status/provider-status",
                "/status/peer-status",
            }:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            body_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(body_length).decode("utf-8")
            params = parse_qs(body)

            if parsed.path == "/status/refresh-peers":
                message = refresh_peer_candidates_workflow(repository, params)
                self._redirect(f"/status?message={quote_plus(message)}")
                return

            if parsed.path == "/status/refresh-providers":
                return_to = safe_return_path(_first_param(params, "return_to"))
                message = refresh_provider_candidates_workflow(repository, params)
                self._redirect(redirect_with_message(return_to or "/status", message))
                return

            if parsed.path == "/status/provider-status":
                return_to = safe_return_path(_first_param(params, "return_to"))
                try:
                    message = update_provider_candidate_status_workflow(repository, params)
                except ValueError as error:
                    self._redirect(redirect_with_message(return_to or "/status", str(error)))
                    return
                self._redirect(redirect_with_message(return_to or "/status", message))
                return

            if parsed.path == "/status/peer-status":
                try:
                    message = update_peer_candidate_status_workflow(repository, params)
                except ValueError as error:
                    self._redirect(f"/status?message={quote_plus(str(error))}")
                    return
                self._redirect(f"/status?message={quote_plus(message)}")
                return

            if parsed.path == "/knowledge/preview":
                try:
                    preview = build_knowledge_import_preview(repository, params)
                except ValueError as error:
                    self._send_html(build_knowledge_page(repository, error=str(error)))
                    return
                self._send_html(
                    build_knowledge_page(
                        repository,
                        message="Import voorbereid; controleer de metadata en OCR-tekst voordat je definitief opslaat.",
                        preview=preview,
                    )
                )
                return

            if parsed.path == "/knowledge/import":
                try:
                    message = save_knowledge_document_workflow(repository, params)
                except ValueError as error:
                    self._send_html(build_knowledge_page(repository, error=str(error)))
                    return
                self._redirect(f"/knowledge?message={quote_plus(message)}")
                return

            if parsed.path == "/knowledge/status":
                return_to = safe_return_path(_first_param(params, "return_to"))
                try:
                    message = update_knowledge_document_status_workflow(repository, params)
                except ValueError as error:
                    self._redirect(redirect_with_message(return_to or "/knowledge", str(error)))
                    return
                self._redirect(redirect_with_message(return_to or "/knowledge", message))
                return

            if parsed.path == "/portfolio/backup":
                try:
                    message = create_manual_backup_workflow(repository)
                except OSError as error:
                    self._send_html(build_portfolio_page(repository, error=str(error)))
                    return
                self._redirect(f"/portfolio?message={quote_plus(message)}")
                return

            if parsed.path == "/portfolio/profile":
                try:
                    message = save_portfolio_profile(repository, params)
                except ValueError as error:
                    self._send_html(build_portfolio_page(repository, error=str(error)))
                    return
                self._redirect(f"/portfolio?message={quote_plus(message)}")
                return

            if parsed.path == "/portfolio/import-csv":
                try:
                    message = import_portfolio_csv_workflow(repository, params)
                except (OSError, ValueError) as error:
                    self._send_html(build_portfolio_page(repository, error=str(error)))
                    return
                self._redirect(f"/portfolio?message={quote_plus(message)}")
                return

            if parsed.path == "/portfolio/refresh-snapshots":
                message = refresh_portfolio_snapshots_workflow(repository, params)
                self._redirect(f"/portfolio?message={quote_plus(message)}")
                return

            if parsed.path == "/portfolio/position":
                try:
                    message = save_portfolio_position(repository, params)
                except ValueError as error:
                    self._send_html(build_portfolio_page(repository, error=str(error)))
                    return
                self._redirect(f"/portfolio?message={quote_plus(message)}")
                return

            symbol = params.get("symbol", [""])[0].strip().upper()
            if not symbol:
                self._send_html(build_page(error="Geen ticker ontvangen."))
                return

            if parsed.path == "/workflow/collect":
                workflow = collect_snapshot_workflow(symbol, repository=repository)
                report = build_draft_report(repository, workflow)
                self._send_html(build_page(symbol=symbol, report=report, workflow=workflow, repository=repository))
                return

            if parsed.path == "/workflow/note":
                workflow, note_error = save_case_note_workflow(symbol, params)
                report = build_draft_report(repository, workflow)
                self._send_html(
                    build_page(symbol=symbol, report=report, workflow=workflow, error=note_error, repository=repository)
                )
                return

            workflow = ensure_snapshot_workflow(symbol)
            if workflow.errors:
                self._send_html(
                    build_page(
                        symbol=symbol,
                        workflow=workflow,
                        error="Snapshot is nog niet importeerbaar.",
                        repository=repository,
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
                self._send_html(
                    build_page(
                        symbol=symbol,
                        workflow=workflow,
                        error="Snapshot is nog niet importeerbaar.",
                        repository=repository,
                    )
                )
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
    repository: Optional[SQLiteRepository] = None,
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
            + render_snapshot_workflow(workflow, repository=repository)
        )
    elif workflow:
        notice = f'<div class="notice">{html.escape(error)}</div>' if error else ""
        content = notice + render_snapshot_workflow(workflow, repository=repository)
    elif error:
        content = f'<div class="notice">{html.escape(error)}</div>'
    elif report:
        v1_status = build_v1_status_row(repository, report.symbol) if repository is not None else None
        content = render_report(report, v1_status=v1_status)
    else:
        content = '<div class="notice">DEMO staat klaar als eerste analyse.</div>'

    return build_shell(symbol, content)


if __name__ == "__main__":
    raise SystemExit(main())
