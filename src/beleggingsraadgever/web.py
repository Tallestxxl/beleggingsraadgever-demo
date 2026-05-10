"""Small local web UI for the beleggingsraadgever."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote_plus, urlparse

from .advisor import Advisor
from .collector import collect_snapshot_data
from .document_text import extract_text_from_file
from .importer import (
    SnapshotValidationError,
    import_company_snapshot,
    load_company_snapshot,
    validate_company_snapshot,
    write_snapshot_template,
)
from .knowledge import chunk_text, tokenize
from .knowledge_scope import build_knowledge_tags, knowledge_scope_from_tags
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
from .web_knowledge import (
    KNOWLEDGE_STATUS_LABELS,
    KnowledgeImportPreview,
    _scope_type_for_filter,
    build_knowledge_page,
    normalize_knowledge_filter_value,
    render_knowledge_status_form,
)
from .web_layout import build_shell
from .web_status import V1StatusRow, build_status_page, build_v1_status_row, render_v1_analysis_warning
from .web_formatting import (
    format_compact_amount,
    format_eur,
    format_optional_number,
    format_optional_percent,
    format_percent,
)
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


def build_knowledge_import_preview(repository: SQLiteRepository, params: dict) -> KnowledgeImportPreview:
    values, tags = _prepare_knowledge_import(params, apply_passage_selection=True)
    chunks = chunk_text(values["raw_text"], document_id=0, tags=tags)
    warnings = _knowledge_import_warnings(repository, values, tags, chunks)
    selection_warnings = [warning for warning in values.get("selection_warnings", "").split("\n") if warning]
    return KnowledgeImportPreview(
        values=values,
        tags=tags,
        chunks=chunks,
        warnings=[*selection_warnings, *warnings],
        char_count=len(values["raw_text"]),
        word_count=len(re.findall(r"\S+", values["raw_text"])),
        source_paragraphs=split_knowledge_source_paragraphs(values.get("source_raw_text") or values["raw_text"]),
        selection_summary=values.get("selection_summary", ""),
    )


def save_knowledge_document_workflow(repository: SQLiteRepository, params: dict) -> str:
    values, tags = _prepare_knowledge_import(params)
    document_id = repository.add_document(
        title=values["title"],
        source_type=values["source_type"],
        raw_text=values["raw_text"],
        author="Handmatig ingevoerd",
        publication_date=values["publication_date"],
        source_path=values["source_path"] or None,
        tags=tags,
        status=values["status"],
    )
    return f"Kennisfragment opgeslagen: {values['title']} (document {document_id})."


def _prepare_knowledge_import(params: dict, *, apply_passage_selection: bool = False) -> tuple[dict[str, str], list[str]]:
    title = _first_param(params, "title")
    raw_source_type = _first_param(params, "source_type")
    source_type = raw_source_type.lower().replace(" ", "_") if raw_source_type else ""
    publication_date = _first_param(params, "publication_date")
    source_path = _first_param(params, "source_path")
    source_raw_text = _first_param(params, "source_raw_text")
    raw_text = _first_param(params, "raw_text")
    file_path = _first_param(params, "file_path")
    scope_type = _first_param(params, "scope_type")
    scope_value = _first_param(params, "scope_value")
    extra_tags = _first_param(params, "tags")
    status = _first_param(params, "status") or "voorgesteld"
    passage_ranges = _first_param(params, "passage_ranges")
    anchor_start = _first_param(params, "anchor_start")
    anchor_end = _first_param(params, "anchor_end")
    anchor_ranges = _first_param(params, "anchor_ranges")

    if apply_passage_selection and source_raw_text:
        raw_text = source_raw_text
    if file_path and not raw_text:
        raw_text = extract_text_from_file(Path(file_path))
    if not title and file_path:
        title = Path(file_path).expanduser().stem
    if file_path and not source_path:
        source_path = str(Path(file_path).expanduser())
    if not title:
        raise ValueError("Titel is verplicht, behalve bij bestandsimport waar de bestandsnaam gebruikt kan worden.")
    if not source_type:
        raise ValueError("Bron/type is verplicht.")
    if not publication_date:
        raise ValueError("Datum is verplicht voor kennisimport.")
    if not scope_type:
        raise ValueError("Scope is verplicht.")
    if not raw_text:
        raise ValueError("Tekstfragment of bestandspad is verplicht.")
    if status not in {"vertrouwd", "voorgesteld", "verworpen"}:
        raise ValueError("Onbekende kennisstatus.")
    _required_iso_date(publication_date)
    tags = build_knowledge_tags(scope_type, scope_value, extra_tags)
    selected_text = raw_text.strip()
    selection_summary = "Hele tekst geselecteerd."
    selection_warnings: list[str] = []
    if apply_passage_selection:
        selected_text, selection_warnings, selection_summary = select_knowledge_passages(
            raw_text,
            passage_ranges=passage_ranges,
            anchor_start=anchor_start,
            anchor_end=anchor_end,
            anchor_ranges=anchor_ranges,
        )
        if not selected_text:
            raise ValueError("Passageselectie leverde geen tekst op.")
    return (
        {
            "title": title.strip(),
            "source_type": source_type.strip(),
            "publication_date": publication_date.strip(),
            "source_path": source_path.strip(),
            "file_path": file_path.strip(),
            "scope_type": scope_type.strip().lower(),
            "scope_value": scope_value.strip(),
            "tags": extra_tags.strip(),
            "status": status.strip(),
            "raw_text": selected_text.strip(),
            "source_raw_text": raw_text.strip() if apply_passage_selection else "",
            "passage_ranges": passage_ranges.strip(),
            "anchor_start": anchor_start.strip(),
            "anchor_end": anchor_end.strip(),
            "anchor_ranges": anchor_ranges.strip(),
            "selection_summary": selection_summary,
            "selection_warnings": "\n".join(selection_warnings),
        },
        tags,
    )


def split_knowledge_source_paragraphs(raw_text: str) -> list[str]:
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    if len(paragraphs) <= 1:
        line_parts = [part.strip() for part in text.splitlines() if part.strip()]
        if len(line_parts) > 1:
            paragraphs = line_parts
    if len(paragraphs) <= 1 and len(text) > 1000:
        paragraphs = _split_text_into_sentence_blocks(text)
    return paragraphs or [text]


def select_knowledge_passages(
    raw_text: str,
    *,
    passage_ranges: str = "",
    anchor_start: str = "",
    anchor_end: str = "",
    anchor_ranges: str = "",
) -> tuple[str, list[str], str]:
    paragraphs = split_knowledge_source_paragraphs(raw_text)
    selected_parts: list[str] = []
    warnings: list[str] = []
    summary_parts: list[str] = []

    if passage_ranges.strip():
        range_parts, range_warnings = _select_paragraph_ranges(paragraphs, passage_ranges)
        selected_parts.extend(range_parts)
        warnings.extend(range_warnings)
        if range_parts:
            summary_parts.append(f"Paragraafselectie: {passage_ranges.strip()}.")

    anchor_specs: list[tuple[str, str]] = []
    if anchor_start.strip() or anchor_end.strip():
        anchor_specs.append((anchor_start.strip(), anchor_end.strip()))
    anchor_specs.extend(_parse_anchor_range_lines(anchor_ranges))
    for start_text, end_text in anchor_specs:
        part, warning = _select_anchor_range(raw_text, start_text, end_text)
        if warning:
            warnings.append(warning)
        if part:
            selected_parts.append(part)
            summary_parts.append("Ankerselectie toegepast.")

    if not passage_ranges.strip() and not anchor_specs:
        return raw_text.strip(), warnings, "Hele tekst geselecteerd."
    if not selected_parts:
        return "", warnings or ["Geen passage gevonden met deze selectie."], "Geen passage geselecteerd."
    return "\n\n".join(_dedupe_passage_parts(selected_parts)).strip(), warnings, " ".join(summary_parts)


def _split_text_into_sentence_blocks(text: str, target_chars: int = 900) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text)) if part.strip()]
    blocks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > target_chars:
            blocks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        blocks.append(current)
    return blocks or [text]


def _select_paragraph_ranges(paragraphs: list[str], range_text: str) -> tuple[list[str], list[str]]:
    selected: list[str] = []
    warnings: list[str] = []
    for raw_part in re.split(r"[,;\n]+", range_text):
        part = raw_part.strip().lower()
        if not part:
            continue
        if part in {"alles", "all", "begin-eind", "begin - eind", "begin:eind"}:
            selected.extend(paragraphs)
            continue
        match = re.fullmatch(r"(begin|\d+)\s*(?:-|:|t/m|tot)\s*(eind|\d+)", part)
        if match:
            start = 1 if match.group(1) == "begin" else int(match.group(1))
            end = len(paragraphs) if match.group(2) == "eind" else int(match.group(2))
        elif re.fullmatch(r"\d+", part):
            start = end = int(part)
        else:
            warnings.append(f"Paragraafbereik '{raw_part.strip()}' is niet herkend.")
            continue
        if start > end:
            start, end = end, start
        if start < 1 or end > len(paragraphs):
            warnings.append(f"Paragraafbereik '{raw_part.strip()}' valt buiten 1-{len(paragraphs)}.")
            continue
        selected.extend(paragraphs[start - 1 : end])
    return selected, warnings


def _parse_anchor_range_lines(anchor_ranges: str) -> list[tuple[str, str]]:
    ranges: list[tuple[str, str]] = []
    for line in anchor_ranges.splitlines():
        line = line.strip()
        if not line:
            continue
        if "=>" in line:
            start, end = line.split("=>", 1)
        elif "->" in line:
            start, end = line.split("->", 1)
        elif "|" in line:
            start, end = line.split("|", 1)
        else:
            continue
        ranges.append((start.strip(), end.strip()))
    return ranges


def _select_anchor_range(raw_text: str, start_anchor: str, end_anchor: str) -> tuple[str, str]:
    start_index = 0
    end_index = len(raw_text)
    if start_anchor and start_anchor.strip().lower() not in {"begin", "start"}:
        found_start = _find_anchor(raw_text, start_anchor, start=0, return_end=False)
        if found_start is None:
            return "", f"Beginanker '{start_anchor}' is niet gevonden."
        start_index = found_start
    if end_anchor and end_anchor.strip().lower() not in {"eind", "end"}:
        found_end = _find_anchor(raw_text, end_anchor, start=start_index, return_end=True)
        if found_end is None:
            return "", f"Eindanker '{end_anchor}' is niet gevonden."
        end_index = found_end
    if start_index >= end_index:
        return "", "Ankerselectie heeft een lege passage opgeleverd."
    return raw_text[start_index:end_index].strip(), ""


def _find_anchor(raw_text: str, anchor: str, *, start: int = 0, return_end: bool = False) -> Optional[int]:
    anchor = re.sub(r"\s+", " ", anchor.strip())
    if not anchor:
        return start if not return_end else len(raw_text)
    pattern = re.escape(anchor).replace(r"\ ", r"\s+")
    match = re.search(pattern, raw_text[start:], flags=re.IGNORECASE)
    if match:
        return start + (match.end() if return_end else match.start())
    return _find_anchor_fuzzy(raw_text, anchor, start=start, return_end=return_end)


def _find_anchor_fuzzy(raw_text: str, anchor: str, *, start: int = 0, return_end: bool = False) -> Optional[int]:
    anchor_words = re.findall(r"\S+", anchor)
    if not anchor_words:
        return None
    window_size = len(anchor_words)
    tokens = list(re.finditer(r"\S+", raw_text[start:]))
    best_score = 0.0
    best_range: Optional[tuple[int, int]] = None
    target = _normalize_anchor_text(anchor)
    for index in range(0, max(0, len(tokens) - window_size + 1)):
        window_tokens = tokens[index : index + window_size]
        candidate = _normalize_anchor_text(" ".join(token.group(0) for token in window_tokens))
        score = SequenceMatcher(None, target, candidate).ratio()
        if score > best_score:
            best_score = score
            best_range = (start + window_tokens[0].start(), start + window_tokens[-1].end())
    if best_range is None or best_score < 0.78:
        return None
    return best_range[1] if return_end else best_range[0]


def _normalize_anchor_text(value: str) -> str:
    return re.sub(r"\W+", "", value.casefold())


def _dedupe_passage_parts(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        cleaned = part.strip()
        key = re.sub(r"\s+", " ", cleaned).casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _knowledge_import_warnings(
    repository: SQLiteRepository,
    values: dict[str, str],
    tags: list[str],
    chunks: list[KnowledgeChunk],
) -> list[str]:
    warnings: list[str] = []
    raw_text = values["raw_text"]
    if len(raw_text) < 250:
        warnings.append("De tekst is kort; controleer of OCR/import het volledige artikel heeft gelezen.")
    if not chunks:
        warnings.append("Er zijn geen RAG-chunks voorbereid; controleer de tekstinhoud.")
    if "TODO" in raw_text.upper():
        warnings.append("De tekst bevat TODO-tekst en is waarschijnlijk nog niet schoon.")
    if "�" in raw_text:
        warnings.append("De tekst bevat vervangtekens; OCR of tekencodering verdient controle.")
    odd_character_count = len(re.findall(r"[^\w\s.,;:!?%€$'\"()\-/+&]", raw_text, flags=re.UNICODE))
    if raw_text and odd_character_count / max(len(raw_text), 1) > 0.03:
        warnings.append("Relatief veel vreemde tekens gevonden; controleer de OCR-kwaliteit.")
    if values["publication_date"] > date.today().isoformat():
        warnings.append("De publicatiedatum ligt in de toekomst.")

    scope = knowledge_scope_from_tags(values["source_type"], tags)
    if scope.kind == "general":
        warnings.append("Algemene scope kan bij meerdere aandelen terugkomen; kies aandeel, sector of thema wanneer dit fragment specifieker is.")
    elif scope.display_value:
        scope_key = normalize_knowledge_filter_value(scope.display_value)
        text_key = normalize_knowledge_filter_value(raw_text)
        if scope_key and scope_key not in text_key:
            warnings.append(f"Scopewaarde '{scope.display_value}' komt niet herkenbaar in de tekst voor.")

    existing_documents = repository.list_knowledge_documents()
    for document in existing_documents:
        if document.source_type == values["source_type"] and document.raw_text.strip() == raw_text.strip():
            warnings.append(f"Mogelijk duplicaat van bestaand kennisfragment: {document.title}.")
            break
    return warnings


def update_knowledge_document_status_workflow(repository: SQLiteRepository, params: dict) -> str:
    document_id = _parse_required_int(_first_param(params, "document_id"), "document")
    status = _first_param(params, "status")
    if status not in {"vertrouwd", "voorgesteld", "verworpen"}:
        raise ValueError("Onbekende kennisstatus.")
    updated = repository.update_knowledge_document_status(document_id, status)
    if not updated:
        raise ValueError("Kennisfragment is niet gevonden.")
    return f"Kennisfragment {document_id} is {KNOWLEDGE_STATUS_LABELS[status].lower()}."


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


if __name__ == "__main__":
    raise SystemExit(main())
