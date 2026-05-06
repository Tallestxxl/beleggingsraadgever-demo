"""Portfolio sector and theme classification helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolClassification:
    symbol: str
    sector: str
    theme: str
    industry: str = ""
    confidence: float = 0.0
    source: str = ""
    reason: str = ""


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
        (
            "medical technology",
            "medical devices",
            "health technology",
            "healthcare technology",
            "diagnostic imaging",
            "diagnostics",
            "image-guided therapy",
            "patient monitoring",
            "health care equipment",
            "healthcare equipment",
        ),
        ("Healthcare", "Medical technology"),
    ),
    (
        ("pharmaceutical", "biotechnology", "biopharma", "drug discovery", "therapeutics"),
        ("Healthcare", "Pharmaceuticals and biotech"),
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


PROVIDER_SECTOR_MAP = {
    "basic materials": "Materials",
    "communication services": "Communication Services",
    "consumer cyclical": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "consumer discretionary": "Consumer Discretionary",
    "consumer staples": "Consumer Staples",
    "energy": "Energy",
    "financial services": "Financials",
    "financials": "Financials",
    "healthcare": "Healthcare",
    "health care": "Healthcare",
    "industrials": "Industrials",
    "real estate": "Real Estate",
    "technology": "Technology",
    "utilities": "Utilities",
}


INDUSTRY_CLASSIFICATIONS = [
    (
        (
            "semiconductor",
            "semiconductor equipment",
            "semiconductor materials",
            "electronic components",
        ),
        ("Semiconductors", "Semiconductor equipment"),
    ),
    (
        (
            "medical devices",
            "medical instruments",
            "medical technology",
            "diagnostics",
            "diagnostic imaging",
            "health information services",
            "health care equipment",
            "healthcare equipment",
        ),
        ("Healthcare", "Medical technology"),
    ),
    (
        ("biotechnology", "drug manufacturers", "pharmaceuticals", "pharmaceutical"),
        ("Healthcare", "Pharmaceuticals and biotech"),
    ),
    (
        ("oil", "gas", "integrated oil", "energy"),
        ("Energy", "Oil and gas"),
    ),
    (
        ("steel", "metals", "aluminum", "copper"),
        ("Materials", "Steel and metals"),
    ),
    (
        ("engineering", "construction", "infrastructure"),
        ("Industrials", "Construction"),
    ),
    (
        ("software", "application software", "infrastructure software", "cloud"),
        ("Technology", "Software"),
    ),
    (
        ("telecom", "telecommunication"),
        ("Communication Services", "Telecom"),
    ),
    (
        ("staffing", "employment services"),
        ("Industrials", "Staffing"),
    ),
]


def classify_symbol(symbol: str) -> SymbolClassification:
    normalized = symbol.strip().upper()
    sector, theme = CLASSIFICATION_BY_SYMBOL.get(normalized, ("Onbekend", "Onbekend"))
    confidence = 0.98 if sector != "Onbekend" or theme != "Onbekend" else 0.0
    source = "known_symbol" if confidence else ""
    return SymbolClassification(symbol=normalized, sector=sector, theme=theme, confidence=confidence, source=source)


def classify_company(
    symbol: str,
    *,
    company_name: str | None = None,
    provider_sector: str | None = None,
    provider_industry: str | None = None,
    description: str | None = None,
) -> SymbolClassification:
    normalized = symbol.strip().upper()
    known = classify_symbol(normalized)
    if known.sector != "Onbekend" or known.theme != "Onbekend":
        return known

    provider_sector_value = _normalize_provider_sector(provider_sector)
    industry_match = _classify_by_industry(provider_industry)
    if provider_sector_value != "Onbekend" or industry_match is not None:
        sector = provider_sector_value
        theme = "Onbekend"
        if industry_match is not None:
            industry_sector, theme = industry_match
            if sector == "Onbekend":
                sector = industry_sector
        confidence = 0.88 if sector != "Onbekend" and theme != "Onbekend" else 0.72
        return SymbolClassification(
            symbol=normalized,
            sector=sector,
            theme=theme,
            industry=(provider_industry or "").strip(),
            confidence=confidence,
            source="provider_profile",
            reason="Sector/industrie uit providerprofiel gecombineerd met lokale thema-mapping.",
        )

    haystack = " ".join(part for part in [company_name, provider_industry, description] if part).lower()
    for keywords, (sector, theme) in KEYWORD_CLASSIFICATIONS:
        if any(keyword in haystack for keyword in keywords):
            return SymbolClassification(
                symbol=normalized,
                sector=sector,
                theme=theme,
                industry=(provider_industry or "").strip(),
                confidence=0.64,
                source="description_keywords",
                reason="Afgeleid uit bedrijfsnaam/omschrijving met lokale keyword-regels.",
            )
    return known


def _normalize_provider_sector(sector: str | None) -> str:
    normalized = " ".join(str(sector or "").strip().lower().split())
    if not normalized:
        return "Onbekend"
    return PROVIDER_SECTOR_MAP.get(normalized, str(sector).strip())


def _classify_by_industry(industry: str | None) -> tuple[str, str] | None:
    normalized = " ".join(str(industry or "").strip().lower().split())
    if not normalized:
        return None
    for keywords, classification in INDUSTRY_CLASSIFICATIONS:
        if any(keyword in normalized for keyword in keywords):
            return classification
    return None
