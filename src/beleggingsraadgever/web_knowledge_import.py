"""Knowledge import workflows for the local web UI."""

from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from .document_text import extract_text_from_file
from .knowledge import chunk_text
from .knowledge_scope import build_knowledge_tags, knowledge_scope_from_tags
from .models import KnowledgeChunk
from .storage import SQLiteRepository
from .web_knowledge import (
    KNOWLEDGE_STATUS_LABELS,
    KnowledgeImportPreview,
    normalize_knowledge_filter_value,
)
from .web_params import first_param as _first_param, required_iso_date as _required_iso_date


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


def update_knowledge_document_status_workflow(repository: SQLiteRepository, params: dict) -> str:
    document_id = _parse_required_int(_first_param(params, "document_id"), "document")
    status = _first_param(params, "status")
    if status not in {"vertrouwd", "voorgesteld", "verworpen"}:
        raise ValueError("Onbekende kennisstatus.")
    updated = repository.update_knowledge_document_status(document_id, status)
    if not updated:
        raise ValueError("Kennisfragment is niet gevonden.")
    return f"Kennisfragment {document_id} is {KNOWLEDGE_STATUS_LABELS[status].lower()}."


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


def _parse_required_int(value: str, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} moet een heel getal zijn") from error
