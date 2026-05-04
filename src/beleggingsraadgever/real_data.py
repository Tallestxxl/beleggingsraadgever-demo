"""Curated first real-company snapshots for local v1 experiments."""

from __future__ import annotations

from .models import FinancialSnapshot, MarketSnapshot, Principle
from .storage import SQLiteRepository


BESI_NOTES = """
BESI snapshot samengesteld voor v1-testgebruik op basis van openbare informatie.
De financiele snapshot gebruikt FY 2025 plus Q1 2026 als TTM-benadering.

Belangrijkste punten:
- FY 2025 omzet was EUR 591.3 miljoen en nettowinst EUR 131.6 miljoen.
- Q1 2026 omzet was EUR 184.9 miljoen en nettowinst EUR 51.6 miljoen.
- Q1 2026 orders waren EUR 269.7 miljoen, duidelijk hoger dan Q1 2025.
- Q1 2026 net cash was EUR 103.3 miljoen, met cash plus deposits boven long-term debt.
- De waardering is zeer hoog ten opzichte van actuele winst en vrije kasstroom.
- De casus hangt sterk aan advanced packaging, hybrid bonding, AI-gerelateerde 2.5D vraag en herstel in eindmarkten.
- Recente koersinformatie rond 30 april 2026 wijst op een sterke koersbeweging en hoog momentum.

Bronnen:
- Besi Q4/FY 2025 press release, 19 februari 2026.
- Besi Q1 2026 press release via Euronext, 23 april 2026.
- Trivano/MarketScreener koersinformatie, 30 april 2026.
"""


def seed_besi(repository: SQLiteRepository) -> None:
    """Load an explicit BESI v1 snapshot into the local database."""

    repository.init()
    repository.upsert_financial_snapshot(
        FinancialSnapshot(
            symbol="BESI",
            period_end="2026-03-31",
            period_type="TTM",
            revenue=632_000_000,
            gross_margin=0.633,
            operating_margin=0.313,
            net_margin=0.240,
            free_cash_flow=213_000_000,
            debt=508_100_000,
            cash=611_400_000,
            shares_outstanding=79_242_404,
            dividend_per_share=1.58,
            buyback_value=14_200_000,
        )
    )
    repository.upsert_market_snapshot(
        MarketSnapshot(
            symbol="BESI",
            as_of="2026-04-30",
            close_price=247.20,
            currency="EUR",
            pe_ratio=129.3,
            ev_ebitda=106.0,
            fcf_yield=0.011,
            dividend_yield=0.0064,
            momentum_12m=1.42,
            volatility_1y=0.45,
        )
    )
    document_id = repository.add_document(
        title="BESI eerste echte snapshot",
        source_type="curated_public_sources",
        raw_text=BESI_NOTES,
        author="Beleggingsraadgever",
        publication_date="2026-05-04",
        tags=["BESI", "semiconductors", "advanced packaging", "waardering", "momentum"],
    )
    repository.add_principle(
        Principle(
            title="BESI: waardering vraagt bewijs",
            statement=(
                "Bij BESI is de kwaliteit hoog, maar de waardering impliceert stevige groei. "
                "Herbeoordeel wanneer orders, hybrid bonding adoptie of marges tegenvallen."
            ),
            category="waardering",
            source_document_id=document_id,
        )
    )

