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


KEYWORD_CLASSIFICATIONS = [
    (
        ("semiconductor", "halfgeleider", "wafer", "chip", "deposition", "lithography", "lithografie"),
        ("Semiconductors", "Semiconductor equipment"),
    ),
    (
        (
            "oil and gas",
            "olie en gas",
            "natural gas",
            "aardgas",
            "crude oil",
            "petroleum",
            "integrated energy",
            "aviation fuel",
            "refinery",
            "raffinaderij",
            "upstream",
            "downstream",
            "lubricants",
            "brandstof",
        ),
        ("Energy", "Oil and gas"),
    ),
    (
        ("renewable energy", "wind", "solar", "hydrogen", "low carbon", "hernieuwbare energie", "waterstof"),
        ("Energy", "Energy transition"),
    ),
    (
        ("steel", "staal", "stainless", "roestvast", "alloy", "legering", "metals"),
        ("Materials", "Steel and metals"),
    ),
    (
        ("chemical", "chemicals", "coatings"),
        ("Materials", "Chemicals"),
    ),
    (
        ("biobased", "bio-based", "polymer", "plastics"),
        ("Materials", "Biobased materials"),
    ),
    (
        ("telecom", "telecommunications", "broadband", "mobile network"),
        ("Communication Services", "Telecom"),
    ),
    (
        ("staffing", "recruitment", "human resources"),
        ("Industrials", "Staffing"),
    ),
    (
        ("construction", "building", "infrastructure"),
        ("Industrials", "Construction"),
    ),
    (
        ("space", "launch", "satellite", "lunar"),
        ("Aerospace", "Space"),
    ),
    (
        ("consumer goods", "food", "nutrition", "personal care"),
        ("Consumer Staples", "Global consumer staples"),
    ),
    (
        ("bank", "banking", "insurance", "asset management", "financial services"),
        ("Financials", "Financial services"),
    ),
    (
        ("software", "cloud", "saas", "cybersecurity", "data platform"),
        ("Technology", "Software"),
    ),
    (
        ("pharmaceutical", "biotechnology", "medical devices", "healthcare", "diagnostics"),
        ("Healthcare", "Healthcare"),
    ),
    (
        ("retail", "e-commerce", "apparel", "luxury goods", "restaurants"),
        ("Consumer Discretionary", "Consumer discretionary"),
    ),
    (
        ("utility", "electricity", "grid", "water utility", "gas distribution"),
        ("Utilities", "Utilities"),
    ),
    (
        ("real estate", "reit", "property portfolio", "commercial property"),
        ("Real Estate", "Real estate"),
    ),
    (
        ("mining", "gold", "copper", "lithium", "iron ore"),
        ("Materials", "Mining"),
    ),
    (
        ("automotive", "vehicles", "electric vehicles", "car manufacturer"),
        ("Consumer Discretionary", "Automotive"),
    ),
]


def classify_symbol(symbol: str) -> SymbolClassification:
    normalized = symbol.strip().upper()
    sector, theme = CLASSIFICATION_BY_SYMBOL.get(normalized, ("Onbekend", "Onbekend"))
    return SymbolClassification(symbol=normalized, sector=sector, theme=theme)


def classify_company(
    symbol: str,
    *,
    company_name: str | None = None,
    description: str | None = None,
) -> SymbolClassification:
    normalized = symbol.strip().upper()
    known = classify_symbol(normalized)
    if known.sector != "Onbekend" or known.theme != "Onbekend":
        return known

    haystack = " ".join(part for part in [company_name, description] if part).lower()
    for keywords, (sector, theme) in KEYWORD_CLASSIFICATIONS:
        if any(keyword in haystack for keyword in keywords):
            return SymbolClassification(symbol=normalized, sector=sector, theme=theme)
    return known
