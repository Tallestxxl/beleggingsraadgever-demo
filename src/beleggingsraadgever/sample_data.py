"""Demo data for the first local run."""

from __future__ import annotations

from .models import FinancialSnapshot, MacroObservation, MarketSnapshot, Principle
from .storage import SQLiteRepository


DEMO_COLUMN = """
Kwaliteitsaandelen verdienen soms een hogere waardering, maar alleen wanneer
de omzetgroei, marges en vrije kasstroom de multiple blijven ondersteunen. Bij
cyclische groeiers is het belangrijk om niet alleen naar de piekwinst te kijken.
Een hoge multiple vraagt om discipline: heroverweeg wanneer groei vertraagt,
marges structureel dalen of de balans meer risico gaat tonen.

Dividendrendement is geen gratis lunch. Een uitzonderlijk hoog dividend kan een
signaal zijn dat de markt twijfelt aan de houdbaarheid. Controleer altijd vrije
kasstroom, schuldpositie en investeringsbehoefte voordat een aandeel als
inkomensbron wordt beoordeeld.
"""


def seed_demo(repository: SQLiteRepository) -> None:
    repository.init()
    repository.upsert_financial_snapshot(
        FinancialSnapshot(
            symbol="DEMO",
            period_end="2025-12-31",
            period_type="FY",
            revenue=100_000_000,
            gross_margin=0.52,
            operating_margin=0.24,
            net_margin=0.18,
            free_cash_flow=16_500_000,
            debt=24_000_000,
            cash=18_000_000,
            shares_outstanding=10_000_000,
            dividend_per_share=1.20,
            buyback_value=2_000_000,
        )
    )
    repository.upsert_market_snapshot(
        MarketSnapshot(
            symbol="DEMO",
            as_of="2026-05-03",
            close_price=48.0,
            currency="EUR",
            pe_ratio=24.0,
            ev_ebitda=15.0,
            fcf_yield=0.045,
            dividend_yield=0.025,
            momentum_12m=0.18,
            volatility_1y=0.28,
        )
    )
    repository.upsert_macro_observation(
        MacroObservation(
            indicator="policy_rate",
            region="eurozone",
            as_of="2026-04-30",
            value=2.5,
            unit="percent",
        )
    )
    repository.add_document(
        title="Demo principes uit educatieve columns",
        source_type="demo_column",
        raw_text=DEMO_COLUMN,
        author="Beleggingsraadgever demo",
        publication_date="2026-05-04",
        tags=["kwaliteit", "waardering", "dividend", "risico"],
    )
    repository.add_principle(
        Principle(
            title="Hoge multiple vraagt bewijs",
            statement=(
                "Een hoge waardering is alleen verdedigbaar wanneer groei, marges "
                "en vrije kasstroom de verwachting blijven ondersteunen."
            ),
            category="waardering",
        )
    )
    repository.add_principle(
        Principle(
            title="Dividend checken op houdbaarheid",
            statement=(
                "Een hoog dividendrendement moet worden getoetst aan vrije "
                "kasstroom, schuldpositie en investeringsbehoefte."
            ),
            category="dividend",
        )
    )

