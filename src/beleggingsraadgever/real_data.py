"""Curated first real-company snapshots for local v1 experiments."""

from __future__ import annotations

from .models import DataSource, FinancialSnapshot, MarketSnapshot, Principle
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
    for source in _besi_sources():
        repository.upsert_data_source(source)
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


def _besi_sources() -> list[DataSource]:
    fy_url = "https://www.besi.com/events/events-shows/details/be-semiconductor-industries-nv-announces-q4-25-and-full-year-2025-results/"
    q1_url = "https://live.euronext.com/en/products/equities/company-news/2026-04-23-be-semiconductor-industries-nv-announces-q1-26-results"
    trivano_url = "https://www.trivano.com/aandeel/besi.352.index"
    marketscreener_url = "https://www.marketscreener.com/quote/stock/BE-SEMICONDUCTOR-INDUSTRI-6318/"

    primary = "primair"
    market = "marktdata"
    derived = "afgeleid"

    return [
        DataSource(
            symbol="BESI",
            field_name="revenue",
            value_label="TTM omzet EUR 632.0 mln",
            source_name="Besi FY 2025 results + Q1 2026 results",
            source_url=q1_url,
            source_date="2026-04-23",
            source_quality=derived,
            note="TTM-benadering samengesteld uit FY 2025 en Q1 2026 cijfers.",
        ),
        DataSource(
            symbol="BESI",
            field_name="gross_margin",
            value_label="Brutomarge 63.3%",
            source_name="Besi Q1 2026 results",
            source_url=q1_url,
            source_date="2026-04-23",
            source_quality=primary,
            note="Gebruikt als recente marge-indicatie voor de v1 snapshot.",
        ),
        DataSource(
            symbol="BESI",
            field_name="operating_margin",
            value_label="Operationele marge 31.3%",
            source_name="Besi FY 2025 and Q1 2026 results",
            source_url=q1_url,
            source_date="2026-04-23",
            source_quality=derived,
            note="TTM-benadering op basis van openbare resultaten.",
        ),
        DataSource(
            symbol="BESI",
            field_name="net_margin",
            value_label="Nettomarge 24.0%",
            source_name="Besi FY 2025 and Q1 2026 results",
            source_url=fy_url,
            source_date="2026-02-19",
            source_quality=derived,
            note="TTM-benadering op basis van omzet en nettowinst.",
        ),
        DataSource(
            symbol="BESI",
            field_name="free_cash_flow",
            value_label="Vrije kasstroom EUR 213.0 mln",
            source_name="Besi FY 2025 results",
            source_url=fy_url,
            source_date="2026-02-19",
            source_quality=primary,
            note="Gebruikt als v1 cashflowbasis; later vervangen door genormaliseerde TTM cashflow.",
        ),
        DataSource(
            symbol="BESI",
            field_name="debt",
            value_label="Long-term debt EUR 508.1 mln",
            source_name="Besi Q1 2026 results",
            source_url=q1_url,
            source_date="2026-04-23",
            source_quality=primary,
            note="Schuldpositie uit Q1 2026 balansinformatie.",
        ),
        DataSource(
            symbol="BESI",
            field_name="cash",
            value_label="Cash plus deposits EUR 611.4 mln",
            source_name="Besi Q1 2026 results",
            source_url=q1_url,
            source_date="2026-04-23",
            source_quality=primary,
            note="Gebruikt om netto kaspositie te beoordelen.",
        ),
        DataSource(
            symbol="BESI",
            field_name="shares_outstanding",
            value_label="79,242,404 aandelen",
            source_name="Besi Q1 2026 results",
            source_url=q1_url,
            source_date="2026-04-23",
            source_quality=primary,
            note="Aantal uitstaande aandelen na treasury shares.",
        ),
        DataSource(
            symbol="BESI",
            field_name="dividend_per_share",
            value_label="Dividend EUR 1.58 per aandeel",
            source_name="Besi FY 2025 results",
            source_url=fy_url,
            source_date="2026-02-19",
            source_quality=primary,
            note="Voorgesteld dividend over 2025.",
        ),
        DataSource(
            symbol="BESI",
            field_name="buyback_value",
            value_label="Buybacks EUR 14.2 mln",
            source_name="Besi Q1 2026 results",
            source_url=q1_url,
            source_date="2026-04-23",
            source_quality=primary,
            note="Aandeleninkoop in Q1 2026.",
        ),
        DataSource(
            symbol="BESI",
            field_name="close_price",
            value_label="Slotkoers EUR 247.20",
            source_name="Trivano BESI koersinformatie",
            source_url=trivano_url,
            source_date="2026-04-30",
            source_quality=market,
            note="Gebruikt als end-of-day koerspunt voor de v1-analyse.",
        ),
        DataSource(
            symbol="BESI",
            field_name="pe_ratio",
            value_label="Koers-winstverhouding 129.3",
            source_name="MarketScreener BESI valuation",
            source_url=marketscreener_url,
            source_date="2026-04-30",
            source_quality=market,
            note="Indicatieve marktwaardering; later vervangen door eigen berekening.",
        ),
        DataSource(
            symbol="BESI",
            field_name="ev_ebitda",
            value_label="EV/EBITDA 106.0",
            source_name="MarketScreener BESI valuation",
            source_url=marketscreener_url,
            source_date="2026-04-30",
            source_quality=market,
            note="Indicatieve marktwaardering; later vervangen door eigen berekening.",
        ),
        DataSource(
            symbol="BESI",
            field_name="fcf_yield",
            value_label="FCF-yield 1.1%",
            source_name="Beleggingsraadgever berekening",
            source_url=fy_url,
            source_date="2026-05-04",
            source_quality=derived,
            note="Afgeleid uit koers, aandelen en vrije kasstroom.",
        ),
        DataSource(
            symbol="BESI",
            field_name="momentum_12m",
            value_label="12-maands momentum 142.0%",
            source_name="Trivano/MarketScreener koersinformatie",
            source_url=trivano_url,
            source_date="2026-04-30",
            source_quality=derived,
            note="Handmatige v1-inschatting uit recente koersinformatie.",
        ),
        DataSource(
            symbol="BESI",
            field_name="volatility_1y",
            value_label="1-jaars volatiliteit 45.0%",
            source_name="Beleggingsraadgever v1 risico-inschatting",
            source_url=marketscreener_url,
            source_date="2026-05-04",
            source_quality=derived,
            note="Voorlopige risicoparameter; later vervangen door berekening uit koershistorie.",
        ),
    ]
