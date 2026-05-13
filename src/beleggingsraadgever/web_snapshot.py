"""Snapshot workflow and draft rendering for the local web UI."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .advisor import Advisor
from .classification import classify_company
from .collector import collect_snapshot_data
from .importer import (
    SnapshotValidationError,
    load_company_snapshot,
    validate_company_snapshot,
    write_snapshot_template,
)
from .models import (
    AdviceReport,
    CompanyProfile,
    DataSource,
    FinancialSnapshot,
    KnowledgeChunk,
    KnowledgeHit,
    MarketSnapshot,
    PortfolioClassification,
)
from .peer_discovery import refresh_peer_candidates
from .placeholders import contains_todo, is_placeholder as _is_placeholder
from .provider_identity import refresh_provider_candidates, trusted_provider_symbols
from .real_data import DRAFTS_DIR, PROCESSED_DIR
from .storage import SQLiteRepository
from .web_params import first_param as _first_param, required_iso_date as _required_iso_date
from .web_snapshot_render import render_case_note_form, render_snapshot_workflow


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


@dataclass(frozen=True)
class ArchivedSnapshot:
    path: Path
    source_checksum: str


def ensure_snapshot_workflow(
    symbol: str,
    drafts_dir: Path = DRAFTS_DIR,
    auto_collect: bool = False,
    fetch_text=None,
    repository: Optional[SQLiteRepository] = None,
) -> SnapshotWorkflow:
    normalized_symbol = symbol.strip().upper()
    path = drafts_dir / f"{normalized_symbol.lower()}.json"
    created = False
    if not path.exists():
        write_snapshot_template(normalized_symbol, path)
        created = True
    messages: list[str] = []
    if auto_collect and (created or not _draft_has_core_figures(path)):
        provider_gate = _provider_review_gate(repository, normalized_symbol, fetch_text=fetch_text)
        if provider_gate:
            messages.append(provider_gate)
        else:
            collection = collect_snapshot_data(
                normalized_symbol,
                path,
                fetch_text=fetch_text,
                preferred_stockanalysis_symbols=_trusted_provider_symbols(repository, normalized_symbol),
            )
            messages.extend(collection.messages)
            messages.extend(collection.errors[:1] if not collection.messages else [])
    errors = validate_snapshot_file(path)
    return SnapshotWorkflow(symbol=normalized_symbol, path=path, created=created, errors=errors, messages=messages)


def collect_snapshot_workflow(
    symbol: str,
    drafts_dir: Path = DRAFTS_DIR,
    repository: Optional[SQLiteRepository] = None,
    fetch_text=None,
) -> SnapshotWorkflow:
    normalized_symbol = symbol.strip().upper()
    path = drafts_dir / f"{normalized_symbol.lower()}.json"
    provider_gate = _provider_review_gate(repository, normalized_symbol, fetch_text=fetch_text)
    if provider_gate:
        created = False
        if not path.exists():
            write_snapshot_template(normalized_symbol, path)
            created = True
        return SnapshotWorkflow(
            symbol=normalized_symbol,
            path=path,
            created=created,
            errors=validate_snapshot_file(path),
            messages=[provider_gate],
        )
    result = collect_snapshot_data(
        normalized_symbol,
        path,
        fetch_text=fetch_text,
        preferred_stockanalysis_symbols=_trusted_provider_symbols(repository, normalized_symbol),
    )
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


def _trusted_provider_symbols(repository: Optional[SQLiteRepository], symbol: str) -> list[str]:
    if repository is None:
        return []
    return trusted_provider_symbols(repository, symbol)


def _provider_review_gate(
    repository: Optional[SQLiteRepository],
    symbol: str,
    fetch_text=None,
) -> str:
    if repository is None or _explicit_provider_symbol(symbol):
        return ""
    if _trusted_provider_symbols(repository, symbol):
        return ""
    candidates = repository.provider_candidates_for_symbol(symbol)
    if not candidates:
        candidates = refresh_provider_candidates(repository, symbol, fetch_text=fetch_text)
    active_candidates = [candidate for candidate in candidates if candidate.status != "verworpen"]
    if not active_candidates or _has_known_exchange_hint(active_candidates):
        return ""
    return (
        f"Provider-kandidaten gevonden voor {symbol}. Vertrouw eerst de juiste providerkoppeling "
        "en haal daarna marktdata op."
    )


def _explicit_provider_symbol(symbol: str) -> bool:
    return ":" in symbol or symbol.upper().endswith(".AS")


def _has_known_exchange_hint(candidates) -> bool:
    return any(candidate.source == "known_exchange_hint" and candidate.confidence >= 0.85 for candidate in candidates)


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


def validate_snapshot_file(path: Path) -> list[str]:
    try:
        return validate_company_snapshot(load_company_snapshot(path))
    except SnapshotValidationError as error:
        return error.errors
    except json.JSONDecodeError as error:
        return [f"Snapshot JSON is ongeldig: {error.msg} op regel {error.lineno}."]
    except OSError as error:
        return [f"Snapshotbestand kan niet worden gelezen: {error}."]


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


def _principle_is_todo(principle: dict) -> bool:
    values = [principle.get("title"), principle.get("statement")]
    return any(contains_todo(value) for value in values)
