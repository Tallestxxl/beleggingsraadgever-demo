"""Portfolio sector and theme classification helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolClassification:
    symbol: str
    sector: str
    theme: str


CLASSIFICATION_BY_SYMBOL = {
    "AALB": ("Industrials", "Dutch quality industrials"),
    "AKZA": ("Materials", "Chemicals"),
    "ALFEN": ("Industrials", "Energy transition"),
    "APERAM": ("Materials", "Steel and metals"),
    "ASMI": ("Semiconductors", "Semiconductor equipment"),
    "ASML": ("Semiconductors", "Semiconductor equipment"),
    "AVTX": ("Materials", "Biobased materials"),
    "BAMNB": ("Industrials", "Construction"),
    "BESI": ("Semiconductors", "Semiconductor equipment"),
    "BP": ("Energy", "Oil and gas"),
    "CRBN": ("Consumer Staples", "Ingredients"),
    "DSFIR": ("Consumer Staples", "Health and nutrition"),
    "EBUS": ("Industrials", "Energy transition"),
    "FUGRO": ("Industrials", "Offshore services"),
    "INVESCO_RAFI_US": ("ETF", "Broad US equities"),
    "KPN": ("Communication Services", "Telecom"),
    "LUNR": ("Aerospace", "Space"),
    "NEDAP": ("Industrials", "Technology hardware"),
    "RAND": ("Industrials", "Staffing"),
    "RDW": ("Aerospace", "Space"),
    "RKLB": ("Aerospace", "Space"),
    "SHELL": ("Energy", "Oil and gas"),
    "TWEKA": ("Industrials", "Technology hardware"),
    "UNA": ("Consumer Staples", "Global consumer staples"),
    "VWRL": ("ETF", "Global equities"),
    "XDWH": ("ETF", "Healthcare equities"),
}


def classify_symbol(symbol: str) -> SymbolClassification:
    normalized = symbol.strip().upper()
    sector, theme = CLASSIFICATION_BY_SYMBOL.get(normalized, ("Onbekend", "Onbekend"))
    return SymbolClassification(symbol=normalized, sector=sector, theme=theme)
