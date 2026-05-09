"""Shared helpers for draft/template placeholder detection."""

from __future__ import annotations

from typing import Any


def is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text == "YYYY-MM-DD" or text.upper().startswith("TODO")


def is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def contains_todo(value: Any) -> bool:
    return isinstance(value, str) and "TODO" in value.upper()
