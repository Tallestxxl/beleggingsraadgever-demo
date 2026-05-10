"""Small reusable HTML components for the local web UI."""

from __future__ import annotations

import html


def render_status_pill(label: str, status_class: str) -> str:
    return f'<span class="status-pill status-{html.escape(status_class)}">{html.escape(label)}</span>'

