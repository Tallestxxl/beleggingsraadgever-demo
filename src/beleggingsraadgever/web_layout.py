"""Shared HTML layout for the local web UI."""

from __future__ import annotations

import html


CSS = """
:root {
  --bg: #f6f4ef;
  --surface: #ffffff;
  --surface-soft: #ebe7dd;
  --ink: #20231f;
  --muted: #667069;
  --line: #d8d2c4;
  --accent: #0f766e;
  --accent-dark: #0b5f59;
  --warn: #9a5b14;
  --danger: #9f2424;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
}

.shell {
  min-height: 100vh;
}

.topbar {
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}

.topbar-inner {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto;
  gap: 24px;
  align-items: center;
  max-width: 1180px;
  margin: 0 auto;
  padding: 18px 24px;
}

.brand {
  min-width: 0;
}

.brand-title {
  margin: 0;
  font-size: 20px;
  font-weight: 750;
  letter-spacing: 0;
}

.brand-meta {
  margin: 2px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.ticker-form {
  display: grid;
  grid-template-columns: 96px minmax(120px, 180px) auto auto auto auto auto;
  gap: 8px;
  align-items: end;
}

label {
  color: var(--muted);
  font-size: 13px;
  font-weight: 650;
}

input[type="text"] {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  font-size: 16px;
  padding: 8px 10px;
  text-transform: uppercase;
}

input[type="date"],
input[type="number"],
select,
textarea {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  font: inherit;
  padding: 8px 10px;
}

textarea {
  min-height: 120px;
  resize: vertical;
}

.note-form {
  display: grid;
  gap: 12px;
}

.note-form input[type="text"],
.knowledge-form input[type="text"] {
  text-transform: none;
}

.portfolio-form input[type="text"],
.portfolio-form input[type="number"] {
  text-transform: none;
}

.note-form .form-grid,
.knowledge-form .form-grid,
.portfolio-form .form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(160px, 220px);
  gap: 12px;
}

.portfolio-form,
.knowledge-form {
  display: grid;
  gap: 12px;
}

.asset-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.support-list {
  display: grid;
  gap: 8px;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

button,
.button {
  min-height: 40px;
  border: 1px solid var(--accent);
  border-radius: 6px;
  background: var(--accent);
  color: #ffffff;
  font-size: 14px;
  font-weight: 750;
  padding: 8px 14px;
  text-decoration: none;
  cursor: pointer;
  white-space: nowrap;
}

.button.secondary {
  background: var(--surface);
  color: var(--accent-dark);
}

main {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px;
}

.notice {
  border: 1px solid var(--line);
  border-left: 4px solid var(--warn);
  border-radius: 6px;
  background: var(--surface);
  padding: 14px 16px;
  color: var(--ink);
}

.workflow-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  margin-bottom: 18px;
}

.button-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

button:disabled {
  border-color: var(--line);
  background: var(--surface-soft);
  color: var(--muted);
  cursor: default;
}

.code-path {
  display: block;
  overflow-wrap: anywhere;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-soft);
  padding: 10px;
  color: var(--ink);
  font-size: 13px;
}

.report-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) repeat(3, minmax(110px, 150px));
  gap: 12px;
  align-items: stretch;
  margin-bottom: 18px;
}

.verdict {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  padding: 18px;
}

.verdict h2 {
  margin: 0;
  font-size: 28px;
  letter-spacing: 0;
}

.verdict p {
  margin: 6px 0 0;
  color: var(--muted);
}

.metric {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  padding: 14px;
}

.metric-label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

.metric-value {
  display: block;
  margin-top: 5px;
  font-size: 22px;
  font-weight: 800;
}

.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(300px, 0.8fr);
  gap: 18px;
}

.portfolio-wide-section {
  margin-top: 18px;
  overflow-x: auto;
}

.collapsible-content {
  margin-top: 12px;
}

section {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  padding: 18px;
}

section + section {
  margin-top: 18px;
}

h3 {
  margin: 0 0 12px;
  font-size: 17px;
  letter-spacing: 0;
}

.summary {
  margin: 0;
  max-width: 78ch;
}

.score-list {
  display: grid;
  gap: 12px;
}

.score-block {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}

.score-block:first-child {
  border-top: 0;
  padding-top: 0;
}

.score-row {
  display: grid;
  grid-template-columns: 150px minmax(120px, 1fr) 56px;
  gap: 10px;
  align-items: center;
}

.bar {
  height: 10px;
  border-radius: 999px;
  background: var(--surface-soft);
  overflow: hidden;
}

.bar span {
  display: block;
  height: 100%;
  background: var(--accent);
}

.score-detail {
  margin-top: 8px;
  color: var(--muted);
  font-size: 13px;
}

.score-detail summary,
.supporting-detail summary {
  cursor: pointer;
  font-weight: 700;
}

.score-detail ul,
.supporting-detail .source-list {
  margin-top: 8px;
}

.supporting-detail summary {
  color: var(--ink);
  font-size: 17px;
  letter-spacing: 0;
}

.status-pill {
  display: inline-block;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.status-ok {
  border-color: #7eb795;
  background: #e7f3eb;
  color: #22643b;
}

.status-warn {
  border-color: #d7a74c;
  background: #fff4d8;
  color: #7a4d0c;
}

.status-danger {
  border-color: #db8b8b;
  background: #fde7e7;
  color: #8a1e1e;
}

.status-info {
  border-color: #9eb3c7;
  background: #eaf0f6;
  color: #31506b;
}

.status-detail {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.status-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.status-actions form {
  margin: 0;
}

.status-actions .button,
.status-actions button {
  min-height: 32px;
  padding: 5px 8px;
  font-size: 12px;
}

.evidence-list {
  display: grid;
  gap: 12px;
}

.evidence-item {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}

.evidence-item:first-child {
  border-top: 0;
  padding-top: 0;
}

.evidence-title {
  margin: 0;
  font-weight: 750;
}

.evidence-meta,
.data-list,
.source-list,
.assumption-list,
.risk-list,
.workflow-list {
  color: var(--muted);
  font-size: 14px;
}

.evidence-text {
  margin: 6px 0 0;
}

.hidden-field {
  display: none;
}

.paragraph-list {
  display: grid;
  gap: 8px;
  max-height: 420px;
  overflow: auto;
  margin: 10px 0 0;
  padding-left: 0;
  list-style: none;
}

.paragraph-list li {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 10px;
  border-top: 1px solid var(--line);
  padding-top: 8px;
}

.paragraph-number {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.paragraph-text {
  color: var(--ink);
  font-size: 14px;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.data-table th,
.data-table td {
  border-top: 1px solid var(--line);
  padding: 8px 6px;
  text-align: left;
  vertical-align: top;
}

.data-table th {
  color: var(--muted);
  font-size: 12px;
  text-transform: uppercase;
}

ul {
  margin: 0;
  padding-left: 18px;
}

li + li {
  margin-top: 6px;
}

.risk-list {
  color: var(--danger);
}

@media (max-width: 860px) {
  .topbar-inner,
  .ticker-form,
  .workflow-header,
  .report-header,
  .grid {
    grid-template-columns: 1fr;
  }

  .ticker-form {
    align-items: stretch;
  }

  .score-row {
    grid-template-columns: 1fr;
  }

  .note-form .form-grid,
  .knowledge-form .form-grid,
  .portfolio-form .form-grid,
  .asset-grid {
    grid-template-columns: 1fr;
  }
}
"""


def build_shell(symbol: str, content: str) -> str:
    escaped_symbol = html.escape(symbol)
    return f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Beleggingsraadgever</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="topbar-inner">
        <div class="brand">
          <h1 class="brand-title">Beleggingsraadgever</h1>
          <p class="brand-meta">Local-first analyse met bewijsvoering</p>
        </div>
        <form class="ticker-form" action="/analyze" method="get">
          <label for="symbol">Ticker</label>
          <input id="symbol" name="symbol" type="text" value="{escaped_symbol}" autocomplete="off">
          <button type="submit">Analyseer</button>
          <a class="button secondary" href="/analyze?symbol=DEMO">Demo</a>
          <a class="button secondary" href="/portfolio">Portefeuille</a>
          <a class="button secondary" href="/knowledge">Kennis</a>
          <a class="button secondary" href="/status">V1-status</a>
        </form>
      </div>
    </header>
    <main>{content}</main>
  </div>
</body>
</html>"""
