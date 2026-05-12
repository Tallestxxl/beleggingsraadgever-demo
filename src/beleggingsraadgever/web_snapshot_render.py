"""Snapshot workflow rendering helpers for the local web UI."""

from __future__ import annotations

import html
from datetime import date


def render_snapshot_workflow(workflow) -> str:
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


def render_case_note_form(workflow) -> str:
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
