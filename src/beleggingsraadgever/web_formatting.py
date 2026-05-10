"""Formatting helpers for web rendering."""

from __future__ import annotations

from typing import Optional

from .formatting import format_currency, format_dutch_number


def format_eur(value: Optional[float]) -> str:
    return format_currency(value, "EUR", decimals=0)


def format_eur_cents(value: Optional[float]) -> str:
    return format_currency(value, "EUR", decimals=2)


def format_quantity(value: float) -> str:
    return format_dutch_number(value, decimals=4)


def format_percent(value: float) -> str:
    return f"{value:.1%}"


def format_optional_percent(value: Optional[float]) -> str:
    return "n.b." if value is None else f"{value:.1%}"


def format_optional_number(value: Optional[float], suffix: str = "") -> str:
    return "n.b." if value is None else f"{value:.1f}{suffix}"


def format_compact_amount(value: Optional[float]) -> str:
    if value is None:
        return "n.b."
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{format_dutch_number(value / 1_000_000_000, decimals=1)} mld"
    if abs_value >= 1_000_000:
        return f"{format_dutch_number(value / 1_000_000, decimals=1)} mln"
    return format_dutch_number(value, decimals=0)


def format_input_number(value: Optional[float]) -> str:
    if value is None:
        return ""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return str(value)


def format_money_input_number(value: Optional[float]) -> str:
    if value is None:
        return ""
    decimals = 0 if float(value).is_integer() else 2
    return format_dutch_number(value, decimals=decimals)

