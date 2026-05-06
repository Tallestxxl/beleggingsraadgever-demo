"""Dutch display formatting helpers."""

from __future__ import annotations

from typing import Optional


def format_dutch_number(value: float, decimals: int = 0) -> str:
    """Format numbers with Dutch thousands and decimal separators."""

    formatted = f"{value:,.{decimals}f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def format_currency(value: Optional[float], currency: str = "EUR", decimals: int = 0) -> str:
    if value is None:
        return f"{currency} 0" if decimals == 0 else f"{currency} {format_dutch_number(0, decimals)}"
    return f"{currency} {format_dutch_number(value, decimals)}"


def format_compact_number(value: float, decimals: int = 1) -> str:
    return format_dutch_number(value, decimals)
