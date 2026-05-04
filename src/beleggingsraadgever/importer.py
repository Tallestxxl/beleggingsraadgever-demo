"""Create, validate and import curated company snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .models import DataSource, FinancialSnapshot, MarketSnapshot, Principle
from .storage import SQLiteRepository


REQUIRED_FINANCIAL_FIELDS = ["period_end", "period_type", "revenue"]
REQUIRED_MARKET_FIELDS = ["as_of", "close_price", "currency"]
REQUIRED_DATA_SOURCE_FIELDS = [
    "field_name",
    "value_label",
    "source_name",
    "source_url",
    "source_date",
    "source_quality",
]
FINANCIAL_NUMERIC_FIELDS = [
    "revenue",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "free_cash_flow",
    "debt",
    "cash",
    "shares_outstanding",
    "dividend_per_share",
    "buyback_value",
]
MARKET_NUMERIC_FIELDS = [
    "close_price",
    "pe_ratio",
    "ev_ebitda",
    "fcf_yield",
    "dividend_yield",
    "momentum_12m",
    "volatility_1y",
]
TEMPLATE_FINANCIAL_FIELDS = [
    "period_end",
    "period_type",
    *FINANCIAL_NUMERIC_FIELDS,
]
TEMPLATE_MARKET_FIELDS = [
    "as_of",
    "currency",
    *MARKET_NUMERIC_FIELDS,
]


class SnapshotValidationError(ValueError):
    """Raised when a curated company snapshot cannot be imported safely."""

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


def import_company_snapshot(repository: SQLiteRepository, path: Path) -> str:
    """Import one curated company snapshot and return its normalized symbol."""

    data = load_company_snapshot(path)
    errors = validate_company_snapshot(data)
    if errors:
        raise SnapshotValidationError(errors)

    symbol = str(data["symbol"]).upper()

    repository.init()
    _import_financial_snapshot(repository, symbol, data["financial_snapshot"])
    _import_market_snapshot(repository, symbol, data["market_snapshot"])
    _import_data_sources(repository, symbol, data.get("data_sources", []))
    document_ids = _import_documents(repository, data.get("documents", []))
    _import_principles(repository, document_ids, data.get("principles", []))

    return symbol


def load_company_snapshot(path: Path) -> Dict[str, Any]:
    """Load a snapshot JSON file."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SnapshotValidationError(["Snapshot root must be a JSON object."])
    return data


def validate_company_snapshot(data: Dict[str, Any]) -> List[str]:
    """Return validation errors for a curated company snapshot."""

    errors: List[str] = []
    symbol = data.get("symbol")
    if not _is_nonempty_string(symbol):
        errors.append("symbol is required and must be a non-empty string.")

    financial = data.get("financial_snapshot")
    market = data.get("market_snapshot")
    documents = data.get("documents", [])
    principles = data.get("principles", [])
    data_sources = data.get("data_sources", [])

    if not isinstance(financial, dict):
        errors.append("financial_snapshot must be an object.")
        financial = {}
    if not isinstance(market, dict):
        errors.append("market_snapshot must be an object.")
        market = {}
    if not isinstance(documents, list):
        errors.append("documents must be a list.")
        documents = []
    if not isinstance(principles, list):
        errors.append("principles must be a list.")
        principles = []
    if not isinstance(data_sources, list):
        errors.append("data_sources must be a list.")
        data_sources = []

    _validate_required_fields(errors, "financial_snapshot", financial, REQUIRED_FINANCIAL_FIELDS)
    _validate_required_fields(errors, "market_snapshot", market, REQUIRED_MARKET_FIELDS)
    _validate_iso_date(errors, "financial_snapshot.period_end", financial.get("period_end"))
    _validate_iso_date(errors, "market_snapshot.as_of", market.get("as_of"))
    _validate_numeric_fields(errors, "financial_snapshot", financial, FINANCIAL_NUMERIC_FIELDS)
    _validate_numeric_fields(errors, "market_snapshot", market, MARKET_NUMERIC_FIELDS)
    _validate_no_todos(errors, "financial_snapshot", financial)
    _validate_no_todos(errors, "market_snapshot", market)

    source_fields = _validate_data_sources(errors, data_sources)
    _validate_source_coverage(errors, financial, market, source_fields)
    _validate_documents(errors, documents)
    _validate_principles(errors, principles, documents)

    return errors


def build_snapshot_template(symbol: str) -> Dict[str, Any]:
    """Build a JSON-serializable template for a new company snapshot."""

    normalized_symbol = symbol.strip().upper()
    financial = {field: None for field in TEMPLATE_FINANCIAL_FIELDS}
    market = {field: None for field in TEMPLATE_MARKET_FIELDS}
    financial["period_end"] = "YYYY-MM-DD"
    financial["period_type"] = "TTM"
    market["as_of"] = "YYYY-MM-DD"
    market["currency"] = "EUR"

    return {
        "symbol": normalized_symbol,
        "financial_snapshot": financial,
        "market_snapshot": market,
        "documents": [
            {
                "title": f"{normalized_symbol} eerste snapshot",
                "source_type": "curated_public_sources",
                "author": "Beleggingsraadgever",
                "publication_date": "YYYY-MM-DD",
                "tags": [normalized_symbol],
                "raw_text": (
                    f"TODO: vat de beleggingscasus voor {normalized_symbol} samen met omzetgroei, "
                    "marges, schuld, kasstroom, waardering, dividend, buybacks, cycliciteit, "
                    "concurrentiepositie, managementsignalen, momentum en risico."
                ),
            }
        ],
        "principles": [
            {
                "title": f"{normalized_symbol}: TODO principe",
                "statement": "TODO: formuleer het belangrijkste beleggingsprincipe voor deze casus.",
                "category": "waardering",
                "approved": True,
                "confidence": 1.0,
                "source_document_title": f"{normalized_symbol} eerste snapshot",
            }
        ],
        "data_sources": [
            _data_source_template(field)
            for field in [
                "revenue",
                "operating_margin",
                "net_margin",
                "free_cash_flow",
                "debt",
                "cash",
                "shares_outstanding",
                "dividend_per_share",
                "buyback_value",
                "close_price",
                "pe_ratio",
                "ev_ebitda",
                "fcf_yield",
                "dividend_yield",
                "momentum_12m",
                "volatility_1y",
            ]
        ],
    }


def write_snapshot_template(symbol: str, path: Path, force: bool = False) -> Path:
    """Write a new snapshot template."""

    destination = Path(path)
    if destination.exists() and not force:
        raise FileExistsError(f"Snapshot already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    template = build_snapshot_template(symbol)
    destination.write_text(json.dumps(template, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


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


def _data_source_template(field_name: str) -> Dict[str, str]:
    return {
        "field_name": field_name,
        "value_label": "TODO",
        "source_name": "TODO",
        "source_url": "TODO",
        "source_date": "YYYY-MM-DD",
        "source_quality": "primair",
        "note": "TODO",
    }


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_required_fields(
    errors: List[str],
    section_name: str,
    section: Dict[str, Any],
    fields: List[str],
) -> None:
    for field in fields:
        if field not in section or section[field] is None or section[field] == "":
            errors.append(f"{section_name}.{field} is required.")


def _validate_numeric_fields(
    errors: List[str],
    section_name: str,
    section: Dict[str, Any],
    fields: List[str],
) -> None:
    for field in fields:
        value = section.get(field)
        if value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"{section_name}.{field} must be numeric or null.")


def _validate_no_todos(errors: List[str], section_name: str, section: Dict[str, Any]) -> None:
    for field, value in section.items():
        if isinstance(value, str) and "TODO" in value.upper():
            errors.append(f"{section_name}.{field} still contains TODO.")


def _validate_data_sources(errors: List[str], data_sources: List[Any]) -> set[str]:
    source_fields: set[str] = set()
    for index, source in enumerate(data_sources):
        if not isinstance(source, dict):
            errors.append(f"data_sources[{index}] must be an object.")
            continue
        _validate_required_fields(errors, f"data_sources[{index}]", source, REQUIRED_DATA_SOURCE_FIELDS)
        _validate_no_todos(errors, f"data_sources[{index}]", source)
        field_name = source.get("field_name")
        if _is_nonempty_string(field_name):
            source_fields.add(str(field_name))
        _validate_iso_date(errors, f"data_sources[{index}].source_date", source.get("source_date"))
    if not data_sources:
        errors.append("data_sources must contain at least one source.")
    return source_fields


def _validate_source_coverage(
    errors: List[str],
    financial: Dict[str, Any],
    market: Dict[str, Any],
    source_fields: set[str],
) -> None:
    covered_fields = {
        field
        for field, value in {**financial, **market}.items()
        if field not in {"period_end", "period_type", "as_of", "currency"} and value is not None
    }
    for field in sorted(covered_fields - source_fields):
        errors.append(f"data_sources is missing a source for {field}.")


def _validate_documents(errors: List[str], documents: List[Any]) -> None:
    if not documents:
        errors.append("documents must contain at least one knowledge document.")
    for index, document in enumerate(documents):
        if not isinstance(document, dict):
            errors.append(f"documents[{index}] must be an object.")
            continue
        _validate_required_fields(errors, f"documents[{index}]", document, ["title", "source_type", "raw_text"])
        _validate_no_todos(errors, f"documents[{index}]", document)
        if document.get("publication_date"):
            _validate_iso_date(errors, f"documents[{index}].publication_date", document.get("publication_date"))


def _validate_principles(errors: List[str], principles: List[Any], documents: List[Any]) -> None:
    document_titles = {document.get("title") for document in documents if isinstance(document, dict)}
    for index, principle in enumerate(principles):
        if not isinstance(principle, dict):
            errors.append(f"principles[{index}] must be an object.")
            continue
        _validate_required_fields(errors, f"principles[{index}]", principle, ["title", "statement", "category"])
        _validate_no_todos(errors, f"principles[{index}]", principle)
        source_title = principle.get("source_document_title")
        if source_title and source_title not in document_titles:
            errors.append(f"principles[{index}].source_document_title does not match a document title.")


def _validate_iso_date(errors: List[str], field_name: str, value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str) or len(value) != 10:
        errors.append(f"{field_name} must use YYYY-MM-DD.")
        return
    if value[4] != "-" or value[7] != "-":
        errors.append(f"{field_name} must use YYYY-MM-DD.")
        return
    digits = value[:4] + value[5:7] + value[8:10]
    if not digits.isdigit():
        errors.append(f"{field_name} must use YYYY-MM-DD.")
