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
from .models import CompanyProfile, InvestorProfile, PortfolioAsset, PortfolioClassification, PortfolioPosition
from .peer_discovery import refresh_peer_candidates, refresh_peer_candidates_for_portfolio
from .placeholders import contains_todo, is_placeholder as _is_placeholder
from .portfolio_importer import import_portfolio_csv
from .real_data import DRAFTS_DIR, PROCESSED_DIR, seed_curated_snapshots
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
from .web_report import render_report
from .web_status import build_status_page, build_v1_status_row
from .web_portfolio import ASSET_LABELS, render_portfolio_dashboard


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
                    workflow = ensure_snapshot_workflow(symbol, auto_collect=True)
                    report = build_draft_report(repository, workflow)

            self._send_html(build_page(symbol=symbol, report=report, error=error, workflow=workflow, repository=repository))

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path not in {
                "/workflow/import",
                "/workflow/collect",
                "/workflow/note",
                "/portfolio/import-csv",
                "/portfolio/profile",
                "/portfolio/position",
                "/knowledge/preview",
                "/knowledge/import",
                "/knowledge/status",
                "/status/refresh-peers",
                "/status/peer-status",
            }:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            body_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(body_length).decode("utf-8")
            params = parse_qs(body)

            if parsed.path == "/status/refresh-peers":
                symbol = _first_param(params, "symbol").upper()
                if symbol == "__ALL__":
                    refreshed = refresh_peer_candidates_for_portfolio(repository)
                    count = sum(len(candidates) for candidates in refreshed.values())
                    self._redirect(f"/status?message={quote_plus(f'Peer-kandidaten herberekend: {count}')}")
                    return
                if not symbol:
                    self._redirect("/status?message=Geen%20aandeel%20ontvangen")
                    return
                candidates = refresh_peer_candidates(repository, symbol)
                self._redirect(
                    f"/status?message={quote_plus(f'Peer-kandidaten voor {symbol} herberekend: {len(candidates)}')}"
                )
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
            + render_snapshot_workflow(workflow)
        )
    elif workflow:
        notice = f'<div class="notice">{html.escape(error)}</div>' if error else ""
        content = notice + render_snapshot_workflow(workflow)
    elif error:
        content = f'<div class="notice">{html.escape(error)}</div>'
    elif report:
        v1_status = build_v1_status_row(repository, report.symbol) if repository is not None else None
        content = render_report(report, v1_status=v1_status)
    else:
        content = '<div class="notice">DEMO staat klaar als eerste analyse.</div>'

    return build_shell(symbol, content)


def build_portfolio_page(
    repository: SQLiteRepository,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    return build_shell("DEMO", render_portfolio_dashboard(repository, message=message, error=error))


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
    return f"Peer-kandidaat {peer_symbol} voor {symbol} is {labels[status]}."


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


def safe_return_path(value: str) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return ""
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return ""
    return value


def redirect_with_message(path: str, message: str) -> str:
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}message={quote_plus(message)}"


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


def _parse_required_int(value: str, label: str) -> int:
    parsed = _parse_optional_int(value, label)
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
    return any(contains_todo(value) for value in values)


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
    profile_data = snapshot.get("company_profile") if isinstance(snapshot.get("company_profile"), dict) else {}
    sector = classification_data.get("sector")
    theme = classification_data.get("theme")
    description = ""
    industry = str(classification_data.get("industry") or profile_data.get("industry") or "")
    if _classification_value_missing(sector) or _classification_value_missing(theme):
        description = " ".join(
            str(document.get("raw_text") or "")
            for document in snapshot.get("documents", [])
            if isinstance(document, dict)
        )
        classification = classify_company(
            symbol,
            company_name=profile_data.get("company_name"),
            provider_sector=profile_data.get("sector"),
            provider_industry=profile_data.get("industry"),
            description=description or profile_data.get("description"),
        )
        sector = classification.sector if _classification_value_missing(sector) else sector
        theme = classification.theme if _classification_value_missing(theme) else theme
        confidence = classification.confidence
        source = classification.source
        industry = classification.industry or industry
    else:
        confidence = float(classification_data.get("confidence") or profile_data.get("classification_confidence") or 0.0)
        source = str(classification_data.get("source") or profile_data.get("classification_source") or "")
    if _classification_value_missing(sector) and _classification_value_missing(theme):
        return
    repository.upsert_portfolio_classification(
        PortfolioClassification(symbol=symbol, sector=str(sector), theme=str(theme))
    )
    if profile_data or classification_data or description:
        repository.upsert_company_profile(
            CompanyProfile(
                symbol=symbol,
                company_name=str(profile_data.get("company_name") or ""),
                provider_symbol=str(profile_data.get("provider_symbol") or ""),
                source_name=str(profile_data.get("provider") or source),
                source_url=str(profile_data.get("source_url") or classification_data.get("source_url") or ""),
                as_of=str(profile_data.get("as_of") or ""),
                sector=str(profile_data.get("sector") or sector),
                industry=industry,
                description=str(profile_data.get("description") or description),
                classification_confidence=confidence,
                classification_source=source,
            )
        )
    refresh_peer_candidates(repository, symbol)


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


if __name__ == "__main__":
    raise SystemExit(main())
