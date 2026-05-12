"""Knowledge-library page rendering for the local web UI."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .document_text import ocr_engine_status
from .knowledge_scope import knowledge_scope_from_tags
from .models import KnowledgeChunk, KnowledgeDocument
from .storage import SQLiteRepository
from .web_components import render_status_pill
from .web_layout import build_shell
from .web_params import first_param as _first_param, required_iso_date as _required_iso_date


@dataclass(frozen=True)
class KnowledgeImportPreview:
    values: dict[str, str]
    tags: list[str]
    chunks: list[KnowledgeChunk]
    warnings: list[str]
    char_count: int
    word_count: int
    source_paragraphs: list[str] = field(default_factory=list)
    selection_summary: str = ""


def build_knowledge_page(
    repository: SQLiteRepository,
    message: Optional[str] = None,
    error: Optional[str] = None,
    filters: Optional[dict] = None,
    preview: Optional[KnowledgeImportPreview] = None,
) -> str:
    return build_shell(
        "DEMO",
        render_knowledge_dashboard(repository, message=message, error=error, filters=filters, preview=preview),
    )


SOURCE_TYPE_LABELS = {
    "beleggers_belangen": "Beleggers Belangen",
    "educatie": "Educatie",
    "podcast": "Podcast",
    "eigen_notitie": "Eigen notitie",
    "jaarverslag": "Jaarverslag",
    "overig": "Overig",
}

KNOWLEDGE_STATUS_LABELS = {
    "vertrouwd": "Vertrouwd",
    "voorgesteld": "Voorgesteld",
    "verworpen": "Verworpen",
}


def render_knowledge_dashboard(
    repository: SQLiteRepository,
    message: Optional[str] = None,
    error: Optional[str] = None,
    filters: Optional[dict] = None,
    preview: Optional[KnowledgeImportPreview] = None,
) -> str:
    active_filters = _knowledge_filter_values(filters or {})
    all_documents = repository.list_knowledge_documents()
    documents = filter_knowledge_documents(all_documents, active_filters)
    counts = _knowledge_scope_counts(all_documents)
    notice = ""
    if error:
        notice = f'<div class="notice">{html.escape(error)}</div>'
    elif message:
        notice = f'<div class="notice">{html.escape(message)}</div>'

    return f"""
    {notice}
    <div class="report-header">
      <div class="verdict">
        <h2>Kennisbibliotheek</h2>
        <p>Lokale kennisfragmenten met expliciete scope voor veilige bewijsvoering.</p>
      </div>
      <div class="metric">
        <span class="metric-label">Fragmenten</span>
        <span class="metric-value">{len(documents)}/{len(all_documents)}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Aandeel</span>
        <span class="metric-value">{counts["symbol"]}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Sector/thema</span>
        <span class="metric-value">{counts["sector"] + counts["theme"]}</span>
      </div>
    </div>
    <section>
      <h3>Nieuw kennisfragment</h3>
      {render_knowledge_import_form() if not preview else '<a class="button secondary" href="/knowledge">Nieuwe import starten</a>'}
    </section>
    {render_knowledge_import_review(preview) if preview else ""}
    <section>
      <h3>Bibliotheek</h3>
      {render_knowledge_filter_form(active_filters)}
      {render_knowledge_document_table(documents)}
    </section>"""


def render_knowledge_import_form(
    values: Optional[dict[str, str]] = None,
    *,
    action: str = "/knowledge/preview",
    button_label: str = "Controleer import",
) -> str:
    values = values or {}
    source_options = "".join(
        f'<option value="{html.escape(value)}"{" selected" if value == values.get("source_type") else ""}>{html.escape(label)}</option>'
        for value, label in SOURCE_TYPE_LABELS.items()
    )
    status_options = "".join(
        f'<option value="{html.escape(value)}"{" selected" if value == (values.get("status") or "voorgesteld") else ""}>{html.escape(label)}</option>'
        for value, label in KNOWLEDGE_STATUS_LABELS.items()
    )
    scope_options = _select_options(
        {
            "algemeen": "Algemeen",
            "aandeel": "Aandeel",
            "sector": "Sector",
            "thema": "Thema",
        },
        values.get("scope_type") or "algemeen",
    )
    date_value = values.get("publication_date") or date.today().isoformat()
    return f"""
      <form class="knowledge-form" method="post" action="{html.escape(action)}">
        <div class="form-grid">
          <div>
            <label for="knowledge-title">Titel</label>
            <input id="knowledge-title" name="title" type="text" value="{html.escape(values.get("title", ""))}" autocomplete="off">
          </div>
          <div>
            <label for="knowledge-date">Datum</label>
            <input id="knowledge-date" name="publication_date" type="date" value="{html.escape(date_value)}">
          </div>
        </div>
        <div class="form-grid">
          <div>
            <label for="knowledge-source-type">Bron/type</label>
            <select id="knowledge-source-type" name="source_type">{source_options}</select>
          </div>
          <div>
            <label for="knowledge-source-path">Bronpad of URL</label>
            <input id="knowledge-source-path" name="source_path" type="text" value="{html.escape(values.get("source_path", ""))}" autocomplete="off">
          </div>
        </div>
        <div>
          <label for="knowledge-file-path">Bestandspad (.txt, .md, .pdf, afbeelding)</label>
          <input id="knowledge-file-path" name="file_path" type="text" value="{html.escape(values.get("file_path", ""))}" autocomplete="off">
          <p class="evidence-meta">{html.escape(ocr_engine_status())}</p>
        </div>
        <div class="form-grid">
          <div>
            <label for="knowledge-status">Status</label>
            <select id="knowledge-status" name="status">{status_options}</select>
          </div>
          <div>
            <label for="knowledge-tags">Tags</label>
            <input id="knowledge-tags" name="tags" type="text" value="{html.escape(values.get("tags", ""))}" autocomplete="off">
          </div>
        </div>
        <div class="form-grid">
          <div>
            <label for="knowledge-scope-type">Scope</label>
            <select id="knowledge-scope-type" name="scope_type">{scope_options}</select>
          </div>
          <div>
            <label for="knowledge-scope-value">Scopewaarde</label>
            <input id="knowledge-scope-value" name="scope_value" type="text" value="{html.escape(values.get("scope_value", ""))}" autocomplete="off">
          </div>
        </div>
        <div>
          <label for="knowledge-text">Tekstfragment</label>
          <textarea id="knowledge-text" name="raw_text">{html.escape(values.get("raw_text", ""))}</textarea>
        </div>
        <button type="submit">{html.escape(button_label)}</button>
      </form>"""


def render_knowledge_import_review(preview: KnowledgeImportPreview) -> str:
    metadata = preview.values
    scope = knowledge_scope_from_tags(metadata["source_type"], preview.tags)
    warning_items = (
        "".join(f"<li>{html.escape(warning)}</li>" for warning in preview.warnings)
        if preview.warnings
        else "<li>Geen kwaliteitswaarschuwingen gevonden.</li>"
    )
    warning_class = "warn" if preview.warnings else "ok"
    chunks = "".join(render_knowledge_chunk_preview(chunk) for chunk in preview.chunks[:4])
    more_chunks = ""
    if len(preview.chunks) > 4:
        more_chunks = f'<p class="evidence-meta">Nog {len(preview.chunks) - 4} extra chunks voorbereid.</p>'
    pill_label = "Waarschuwingen" if preview.warnings else "Geen waarschuwingen"
    return f"""
    <section>
      <h3>Importcontrole</h3>
      <p class="summary">{render_status_pill(pill_label, warning_class)} <span class="status-detail">Controleer metadata, scope en OCR-tekst voordat dit fragment in de kennisbibliotheek komt. Na opslag krijgt het standaard de status voorgesteld.</span></p>
      <div class="report-header">
        <div class="metric">
          <span class="metric-label">Scope</span>
          <span class="metric-value">{html.escape(scope.label)}</span>
        </div>
        <div class="metric">
          <span class="metric-label">Tekst</span>
          <span class="metric-value">{preview.word_count} woorden</span>
        </div>
        <div class="metric">
          <span class="metric-label">Chunks</span>
          <span class="metric-value">{len(preview.chunks)}</span>
        </div>
        <div class="metric">
          <span class="metric-label">Status</span>
          <span class="metric-value">{html.escape(KNOWLEDGE_STATUS_LABELS.get(metadata["status"], metadata["status"]))}</span>
        </div>
      </div>
      <details class="supporting-detail" open>
        <summary>Kwaliteitscontrole</summary>
        <ul class="workflow-list">{warning_items}</ul>
      </details>
      {render_knowledge_passage_selector(preview)}
      <details class="supporting-detail" open>
        <summary>Voorbereide chunks</summary>
        <div class="evidence-list">{chunks}</div>
        {more_chunks}
      </details>
      <h3>Definitief opslaan</h3>
      {render_knowledge_import_form(metadata, action="/knowledge/import", button_label="Sla definitief op")}
    </section>"""


def render_knowledge_passage_selector(preview: KnowledgeImportPreview) -> str:
    metadata = preview.values
    source_text = metadata.get("source_raw_text") or metadata.get("raw_text", "")
    paragraph_items = "".join(render_knowledge_source_paragraph(index, paragraph) for index, paragraph in enumerate(preview.source_paragraphs, 1))
    paragraph_help = "Gebruik bijvoorbeeld 3-8, 12 of begin-eind. Meerdere passages mogen met komma's of nieuwe regels."
    return f"""
      <details class="supporting-detail" open>
        <summary>Passageselectie vóór chunking</summary>
        <p class="evidence-meta">{html.escape(preview.selection_summary or "Hele tekst geselecteerd.")}</p>
        <form class="knowledge-form" method="post" action="/knowledge/preview">
          {render_knowledge_preview_hidden_fields(metadata, source_text)}
          <div class="form-grid">
            <div>
              <label for="knowledge-passage-ranges">Paragraafbereik</label>
              <input id="knowledge-passage-ranges" name="passage_ranges" type="text" value="{html.escape(metadata.get("passage_ranges", ""))}" autocomplete="off">
              <p class="evidence-meta">{html.escape(paragraph_help)}</p>
            </div>
            <div>
              <label for="knowledge-anchor-start">Eerste woorden</label>
              <input id="knowledge-anchor-start" name="anchor_start" type="text" value="{html.escape(metadata.get("anchor_start", ""))}" autocomplete="off">
            </div>
          </div>
          <div class="form-grid">
            <div>
              <label for="knowledge-anchor-end">Laatste woorden</label>
              <input id="knowledge-anchor-end" name="anchor_end" type="text" value="{html.escape(metadata.get("anchor_end", ""))}" autocomplete="off">
              <p class="evidence-meta">Laat beide ankers leeg wanneer je alleen paragraafbereiken gebruikt.</p>
            </div>
            <div>
              <label for="knowledge-anchor-ranges">Extra ankerparen</label>
              <textarea id="knowledge-anchor-ranges" name="anchor_ranges">{html.escape(metadata.get("anchor_ranges", ""))}</textarea>
              <p class="evidence-meta">Een passage per regel: beginwoorden =&gt; eindwoorden.</p>
            </div>
          </div>
          <button type="submit">Selectie toepassen</button>
        </form>
        <details class="supporting-detail">
          <summary>Brontekst in paragrafen</summary>
          <ol class="paragraph-list">{paragraph_items}</ol>
        </details>
      </details>"""


def render_knowledge_preview_hidden_fields(metadata: dict[str, str], source_text: str) -> str:
    names = [
        "title",
        "source_type",
        "publication_date",
        "source_path",
        "file_path",
        "scope_type",
        "scope_value",
        "tags",
        "status",
    ]
    fields = "".join(
        f'<input type="hidden" name="{name}" value="{html.escape(metadata.get(name, ""))}">' for name in names
    )
    fields += f'<textarea class="hidden-field" name="source_raw_text">{html.escape(source_text)}</textarea>'
    return fields


def render_knowledge_source_paragraph(index: int, paragraph: str) -> str:
    excerpt = paragraph[:700].strip()
    if len(paragraph) > 700:
        excerpt += "..."
    return f"""
        <li>
          <span class="paragraph-number">{index}</span>
          <span class="paragraph-text">{html.escape(excerpt)}</span>
        </li>"""


def render_knowledge_chunk_preview(chunk: KnowledgeChunk) -> str:
    excerpt = chunk.text[:520].strip()
    if len(chunk.text) > 520:
        excerpt += "..."
    return f"""
      <article class="evidence-item">
        <p class="evidence-title">Chunk {chunk.chunk_index + 1}</p>
        <p class="evidence-meta">{len(chunk.text)} tekens - tags: {html.escape(", ".join(chunk.tags) if chunk.tags else "n.b.")}</p>
        <p class="evidence-text">{html.escape(excerpt)}</p>
      </article>"""


def render_knowledge_filter_form(filters: dict[str, str]) -> str:
    source_options = _select_options(
        {"": "Alle bronnen", **SOURCE_TYPE_LABELS},
        filters.get("source_type", ""),
    )
    status_options = _select_options(
        {"": "Alle statussen", **KNOWLEDGE_STATUS_LABELS},
        filters.get("status", ""),
    )
    scope_options = _select_options(
        {
            "": "Alle scopes",
            "algemeen": "Algemeen",
            "aandeel": "Aandeel",
            "sector": "Sector",
            "thema": "Thema",
        },
        filters.get("scope_type", ""),
    )
    return f"""
      <form class="knowledge-form" action="/knowledge" method="get">
        <div class="form-grid">
          <div>
            <label for="knowledge-filter-query">Zoektekst</label>
            <input id="knowledge-filter-query" name="q" type="text" value="{html.escape(filters.get("q", ""))}" autocomplete="off">
          </div>
          <div>
            <label for="knowledge-filter-status">Status</label>
            <select id="knowledge-filter-status" name="status">{status_options}</select>
          </div>
        </div>
        <div class="form-grid">
          <div>
            <label for="knowledge-filter-source">Bron/type</label>
            <select id="knowledge-filter-source" name="source_type">{source_options}</select>
          </div>
          <div>
            <label for="knowledge-filter-scope">Scope</label>
            <select id="knowledge-filter-scope" name="scope_type">{scope_options}</select>
          </div>
        </div>
        <div class="form-grid">
          <div>
            <label for="knowledge-filter-scope-value">Aandeel, sector of thema</label>
            <input id="knowledge-filter-scope-value" name="scope_value" type="text" value="{html.escape(filters.get("scope_value", ""))}" autocomplete="off">
          </div>
          <div>
            <label for="knowledge-filter-date-from">Vanaf datum</label>
            <input id="knowledge-filter-date-from" name="date_from" type="date" value="{html.escape(filters.get("date_from", ""))}">
          </div>
        </div>
        <div class="form-grid">
          <div>
            <label for="knowledge-filter-date-to">Tot datum</label>
            <input id="knowledge-filter-date-to" name="date_to" type="date" value="{html.escape(filters.get("date_to", ""))}">
          </div>
          <div class="button-row">
            <button type="submit">Filter</button>
            <a class="button secondary" href="/knowledge">Wis filters</a>
          </div>
        </div>
      </form>"""


def render_knowledge_document_table(documents: list[KnowledgeDocument]) -> str:
    if not documents:
        return '<p class="evidence-meta">Nog geen kennisfragmenten opgeslagen.</p>'
    rows = "".join(render_knowledge_document_row(document) for document in documents)
    return f"""
          <table class="data-table">
            <thead>
              <tr><th>Titel</th><th>Bron</th><th>Scope</th><th>Status</th><th>Tags</th><th>Chunks</th><th>Fragment</th><th>Acties</th></tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>"""


def render_knowledge_document_row(document: KnowledgeDocument) -> str:
    source_label = SOURCE_TYPE_LABELS.get(document.source_type, document.source_type)
    date_label = f"<br>{html.escape(document.publication_date)}" if document.publication_date else ""
    path_label = ""
    if document.source_path:
        path = html.escape(document.source_path)
        path_label = f'<br><a href="{path}" target="_blank" rel="noreferrer">bron</a>' if document.source_path.startswith(("http://", "https://")) else f"<br>{path}"
    scope = knowledge_scope_from_tags(document.source_type, document.tags)
    tag_label = ", ".join(document.tags) if document.tags else "n.b."
    excerpt = document.raw_text[:220].strip()
    if len(document.raw_text) > 220:
        excerpt += "..."
    status_class = "ok" if document.status == "vertrouwd" else "danger" if document.status == "verworpen" else "warn"
    return f"""
        <tr>
          <td><strong>{html.escape(document.title)}</strong></td>
          <td>{html.escape(source_label)}{date_label}{path_label}</td>
          <td>{html.escape(scope.label)}</td>
          <td>{render_status_pill(KNOWLEDGE_STATUS_LABELS.get(document.status, document.status), status_class)}</td>
          <td>{html.escape(tag_label)}</td>
          <td>{document.chunk_count}</td>
          <td>{html.escape(excerpt)}</td>
          <td>{render_knowledge_status_actions(document)}</td>
        </tr>"""


def render_knowledge_status_actions(document: KnowledgeDocument) -> str:
    buttons = []
    if document.status != "vertrouwd":
        buttons.append(render_knowledge_status_form(document.document_id, "vertrouwd", "Vertrouw"))
    if document.status != "voorgesteld":
        buttons.append(render_knowledge_status_form(document.document_id, "voorgesteld", "Zet op voorstel"))
    if document.status != "verworpen":
        buttons.append(render_knowledge_status_form(document.document_id, "verworpen", "Verwerp"))
    return f'<div class="status-actions">{"".join(buttons)}</div>'


def render_knowledge_status_form(document_id: int, status: str, label: str, return_to: str = "") -> str:
    return_field = f'<input type="hidden" name="return_to" value="{html.escape(return_to)}">' if return_to else ""
    return f"""
              <form method="post" action="/knowledge/status">
                <input type="hidden" name="document_id" value="{document_id}">
                <input type="hidden" name="status" value="{html.escape(status)}">
                {return_field}
                <button type="submit">{html.escape(label)}</button>
              </form>"""


def _knowledge_scope_counts(documents: list[KnowledgeDocument]) -> dict[str, int]:
    counts = {"general": 0, "symbol": 0, "sector": 0, "theme": 0}
    for document in documents:
        scope = knowledge_scope_from_tags(document.source_type, document.tags)
        counts[scope.kind] = counts.get(scope.kind, 0) + 1
    return counts


def _knowledge_filter_values(params: dict) -> dict[str, str]:
    filters = {
        "q": _first_param(params, "q"),
        "source_type": _first_param(params, "source_type"),
        "status": _first_param(params, "status"),
        "scope_type": _first_param(params, "scope_type"),
        "scope_value": _first_param(params, "scope_value"),
        "date_from": _first_param(params, "date_from"),
        "date_to": _first_param(params, "date_to"),
    }
    if filters["date_from"]:
        _required_iso_date(filters["date_from"])
    if filters["date_to"]:
        _required_iso_date(filters["date_to"])
    return filters


def filter_knowledge_documents(documents: list[KnowledgeDocument], filters: dict[str, str]) -> list[KnowledgeDocument]:
    result = []
    query = filters.get("q", "").casefold()
    scope_type = filters.get("scope_type", "")
    scope_value = filters.get("scope_value", "")
    normalized_scope_value = normalize_knowledge_filter_value(scope_value)
    for document in documents:
        scope = knowledge_scope_from_tags(document.source_type, document.tags)
        if filters.get("source_type") and document.source_type != filters["source_type"]:
            continue
        if filters.get("status") and document.status != filters["status"]:
            continue
        if scope_type and _scope_type_for_filter(scope.kind) != scope_type:
            continue
        if normalized_scope_value and normalized_scope_value not in {
            normalize_knowledge_filter_value(scope.value),
            normalize_knowledge_filter_value(scope.display_value),
        }:
            continue
        if filters.get("date_from") and (not document.publication_date or document.publication_date < filters["date_from"]):
            continue
        if filters.get("date_to") and (not document.publication_date or document.publication_date > filters["date_to"]):
            continue
        if query and query not in _knowledge_document_search_text(document, scope).casefold():
            continue
        result.append(document)
    return result


def normalize_knowledge_filter_value(value: str) -> str:
    return "_".join(value.strip().upper().replace(":", " ").split())


def _scope_type_for_filter(scope_kind: str) -> str:
    return {
        "general": "algemeen",
        "symbol": "aandeel",
        "sector": "sector",
        "theme": "thema",
    }.get(scope_kind, "")


def _knowledge_document_search_text(document: KnowledgeDocument, scope) -> str:
    return " ".join(
        [
            document.title,
            document.source_type,
            document.publication_date or "",
            scope.label,
            " ".join(document.tags),
            document.raw_text,
        ]
    )


def _select_options(options: dict[str, str], selected: str) -> str:
    return "".join(
        f'<option value="{html.escape(value)}"{" selected" if value == selected else ""}>{html.escape(label)}</option>'
        for value, label in options.items()
    )
