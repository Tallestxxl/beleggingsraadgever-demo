"""Shared request parameter helpers for the local web UI."""

from __future__ import annotations

from datetime import date
from urllib.parse import quote_plus, urlparse


def first_param(params: dict, name: str) -> str:
    value = params.get(name, [""])
    if isinstance(value, list):
        return value[0].strip() if value else ""
    return str(value).strip()


def required_iso_date(value: str) -> None:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError("datum moet YYYY-MM-DD gebruiken")
    date.fromisoformat(value)


def safe_return_path(value: str) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return ""
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return ""
    return value


def redirect_with_message(path: str, message: str) -> str:
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}message={quote_plus(message)}"
