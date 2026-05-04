"""Import curated company snapshots from JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .models import DataSource, FinancialSnapshot, MarketSnapshot, Principle
from .storage import SQLiteRepository


def import_company_snapshot(repository: SQLiteRepository, path: Path) -> str:
    """Import one curated company snapshot and return its normalized symbol."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    symbol = str(data["symbol"]).upper()

    repository.init()
    _import_financial_snapshot(repository, symbol, data["financial_snapshot"])
    _import_market_snapshot(repository, symbol, data["market_snapshot"])
    _import_data_sources(repository, symbol, data.get("data_sources", []))
    document_ids = _import_documents(repository, data.get("documents", []))
    _import_principles(repository, document_ids, data.get("principles", []))

    return symbol


def _import_financial_snapshot(repository: SQLiteRepository, symbol: str, data: Dict[str, Any]) -> None:
    repository.upsert_financial_snapshot(FinancialSnapshot(symbol=symbol, **data))


def _import_market_snapshot(repository: SQLiteRepository, symbol: str, data: Dict[str, Any]) -> None:
    repository.upsert_market_snapshot(MarketSnapshot(symbol=symbol, **data))


def _import_data_sources(repository: SQLiteRepository, symbol: str, sources: list[Dict[str, Any]]) -> None:
    for source in sources:
        repository.upsert_data_source(DataSource(symbol=symbol, **source))


def _import_documents(repository: SQLiteRepository, documents: list[Dict[str, Any]]) -> Dict[str, int]:
    document_ids: Dict[str, int] = {}
    for document in documents:
        title = document["title"]
        document_ids[title] = repository.add_document(
            title=title,
            source_type=document["source_type"],
            raw_text=document["raw_text"],
            author=document.get("author"),
            publication_date=document.get("publication_date"),
            source_path=document.get("source_path"),
            tags=document.get("tags", []),
        )
    return document_ids


def _import_principles(
    repository: SQLiteRepository,
    document_ids: Dict[str, int],
    principles: list[Dict[str, Any]],
) -> None:
    for principle in principles:
        source_title = principle.get("source_document_title")
        repository.add_principle(
            Principle(
                title=principle["title"],
                statement=principle["statement"],
                category=principle["category"],
                approved=principle.get("approved", True),
                confidence=principle.get("confidence", 1.0),
                source_document_id=document_ids.get(source_title) if source_title else None,
            )
        )

