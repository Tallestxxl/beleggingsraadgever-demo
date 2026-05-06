"""Scope helpers for knowledge documents and retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .identity import normalize_symbol


SYMBOL_SCOPED_SOURCE_TYPES = {
    "curated_public_sources",
    "public_data_snapshot",
    "public_market_data",
}

SCOPE_TAG_GENERAL = "SCOPE_ALGEMEEN"
SCOPE_TAG_SYMBOL = "SCOPE_AANDEEL"
SCOPE_TAG_SECTOR = "SCOPE_SECTOR"
SCOPE_TAG_THEME = "SCOPE_THEMA"

LEGACY_SYMBOL_SCOPE_TAGS = {
    "AANDEEL_KENNIS",
    "CASUSNOTITIE",
}


@dataclass(frozen=True)
class KnowledgeScope:
    kind: str
    value: str = ""
    display_value: str = ""

    @property
    def label(self) -> str:
        if self.kind == "symbol":
            return f"Aandeel: {self.display_value or self.value}"
        if self.kind == "sector":
            return f"Sector: {self.display_value or self.value}"
        if self.kind == "theme":
            return f"Thema: {self.display_value or self.value}"
        return "Algemeen"


def knowledge_scope_from_tags(source_type: str, tags: Iterable[str]) -> KnowledgeScope:
    tag_list = [str(tag).strip() for tag in tags if str(tag).strip()]
    normalized_tags = {_normalize_tag(tag) for tag in tag_list}
    primary_raw = tag_list[0] if tag_list else ""
    primary = normalize_symbol(primary_raw)
    if source_type in SYMBOL_SCOPED_SOURCE_TYPES and primary:
        return KnowledgeScope("symbol", primary, primary_raw)
    if normalized_tags & ({SCOPE_TAG_SYMBOL} | LEGACY_SYMBOL_SCOPE_TAGS) and primary:
        return KnowledgeScope("symbol", primary, primary_raw)
    if SCOPE_TAG_SECTOR in normalized_tags and primary:
        return KnowledgeScope("sector", primary, primary_raw)
    if SCOPE_TAG_THEME in normalized_tags and primary:
        return KnowledgeScope("theme", primary, primary_raw)
    return KnowledgeScope("general")


def build_knowledge_tags(scope_type: str, scope_value: str, extra_tags: str) -> list[str]:
    manual_tags = _split_tags(extra_tags)
    normalized_scope = scope_type.strip().lower() or "algemeen"
    value = scope_value.strip()
    if normalized_scope == "algemeen":
        return _dedupe_tags(["scope:algemeen", *manual_tags])
    if normalized_scope == "aandeel":
        symbol = normalize_symbol(value)
        if not symbol:
            raise ValueError("Vul een aandeel of ticker in voor aandeel-specifieke kennis.")
        return _dedupe_tags([symbol, "scope:aandeel", *manual_tags])
    if normalized_scope == "sector":
        if not value:
            raise ValueError("Vul een sector in voor sector-specifieke kennis.")
        return _dedupe_tags([value, "scope:sector", *manual_tags])
    if normalized_scope == "thema":
        if not value:
            raise ValueError("Vul een thema in voor thema-specifieke kennis.")
        return _dedupe_tags([value, "scope:thema", *manual_tags])
    raise ValueError("Onbekende kennisscope.")


def scope_matches_analysis(
    scope: KnowledgeScope,
    *,
    accepted_symbols: set[str],
    sector: Optional[str],
    theme: Optional[str],
) -> bool:
    if scope.kind == "general":
        return True
    if scope.kind == "symbol":
        return scope.value in accepted_symbols
    if scope.kind == "sector":
        return scope.value == normalize_symbol(sector or "")
    if scope.kind == "theme":
        return scope.value == normalize_symbol(theme or "")
    return True


def _split_tags(value: str) -> list[str]:
    tags: list[str] = []
    for raw_part in value.replace("\n", ",").replace(";", ",").split(","):
        tag = raw_part.strip()
        if tag:
            tags.append(tag)
    return tags


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        key = _normalize_tag(tag)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(tag)
    return result


def _normalize_tag(tag: str) -> str:
    return normalize_symbol(tag.replace(":", "_"))
