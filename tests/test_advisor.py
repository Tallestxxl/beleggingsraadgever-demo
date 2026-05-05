from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.advisor import Advisor
from beleggingsraadgever.models import (
    DataSource,
    FinancialSnapshot,
    InvestorProfile,
    MarketSnapshot,
    PortfolioClassification,
    PortfolioAlias,
    PortfolioPosition,
    PortfolioPrice,
    PortfolioAsset,
)
from beleggingsraadgever.sample_data import seed_demo
from beleggingsraadgever.storage import SQLiteRepository


class AdvisorTests(unittest.TestCase):
    def test_demo_report_contains_evidence_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            seed_demo(repo)
            advisor = Advisor(repo)
            report = advisor.analyze("DEMO")
            markdown = advisor.render_markdown(report)
            self.assertEqual(report.symbol, "DEMO")
            self.assertIn("Adviesrapport", markdown)
            self.assertIn("Dataversheid", markdown)
            self.assertGreaterEqual(len(report.evidence), 1)

    def test_report_includes_portfolio_fit_when_profile_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            seed_demo(repo)
            repo.save_investor_profile(
                InvestorProfile(age=52, annual_income=90000, horizon_years=12, cash_buffer=25000)
            )
            repo.upsert_portfolio_asset(PortfolioAsset(asset_type="cash", value=25000, currency="EUR", as_of="2026-05-05"))
            repo.upsert_portfolio_position(
                PortfolioPosition(
                    symbol="DEMO",
                    quantity=10,
                    average_cost=90,
                    currency="EUR",
                    account="Test",
                    as_of="2026-05-05",
                )
            )

            report = Advisor(repo).analyze("DEMO")
            markdown = Advisor(repo).render_markdown(report)

            self.assertIsNotNone(report.portfolio_fit)
            self.assertIn("Portefeuillefit", markdown)
            self.assertGreater(report.portfolio_fit.total_wealth, 0)

    def test_portfolio_fit_warns_for_semiconductor_concentration_on_asmi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.save_investor_profile(
                InvestorProfile(age=52, annual_income=90000, horizon_years=12, cash_buffer=25000)
            )
            for symbol, value in [("ASML", 60000), ("BESI", 50000), ("SHELL", 40000)]:
                repo.upsert_portfolio_position(
                    PortfolioPosition(
                        symbol=symbol,
                        quantity=1,
                        average_cost=value,
                        currency="EUR",
                        account="Test",
                        as_of="2026-05-05",
                    )
                )
                repo.upsert_portfolio_price(
                    PortfolioPrice(symbol=symbol, as_of="2026-05-05", close_price=value, currency="EUR")
                )
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="ASML", sector="Semiconductors", theme="Semiconductor equipment")
            )
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="BESI", sector="Semiconductors", theme="Semiconductor equipment")
            )

            report = Advisor(repo).analyze_snapshots(
                "ASMI",
                FinancialSnapshot(symbol="ASMI", period_end="2025-12-31", period_type="TTM", revenue=1_000_000_000),
                MarketSnapshot(symbol="ASMI", as_of="2026-05-05", close_price=500, currency="EUR"),
            )

            self.assertIsNotNone(report.portfolio_fit)
            self.assertEqual(report.portfolio_fit.sector, "Semiconductors")
            self.assertGreater(report.portfolio_fit.sector_weight, 0.20)
            self.assertIn("Sectorconcentratie", " ".join(report.portfolio_fit.notes))
            self.assertIn("Semiconductors", report.portfolio_fit.summary)

    def test_analyze_snapshots_uses_stored_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="BP", sector="Energy", theme="Oil and gas")
            )

            report = Advisor(repo).analyze_snapshots(
                "BP",
                FinancialSnapshot(symbol="BP", period_end="2025-12-31", period_type="TTM", revenue=1_000_000_000),
                MarketSnapshot(symbol="BP", as_of="2026-05-05", close_price=5, currency="GBP"),
            )

            self.assertEqual(report.portfolio_fit.sector, "Energy")
            self.assertEqual(report.portfolio_fit.theme, "Oil and gas")

    def test_portfolio_fit_matches_existing_position_by_broker_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_position(
                PortfolioPosition(
                    symbol="DSFIR",
                    quantity=200,
                    average_cost=107.89,
                    currency="EUR",
                    account="Test",
                    as_of="2026-05-05",
                )
            )
            repo.upsert_portfolio_price(
                PortfolioPrice(symbol="DSFIR", as_of="2026-05-05", close_price=64.04, currency="EUR")
            )
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="DSFIR", sector="Consumer Staples", theme="Health and nutrition")
            )

            report = Advisor(repo).analyze_snapshots(
                "DSM FIRMENICH",
                FinancialSnapshot(
                    symbol="DSM FIRMENICH",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=9_034_000_000,
                ),
                MarketSnapshot(symbol="DSM FIRMENICH", as_of="2026-05-05", close_price=64.04, currency="EUR"),
                data_sources=[
                    DataSource(
                        symbol="DSM FIRMENICH",
                        field_name="close_price",
                        value_label="Slotkoers EUR 64.04",
                        source_name="StockAnalysis quote en koersen",
                        source_url="https://stockanalysis.com/quote/ams/DSFIR/",
                        source_date="2026-05-05",
                        source_quality="marktdata",
                    )
                ],
            )

            self.assertAlmostEqual(report.portfolio_fit.position_value, 12808)
            self.assertEqual(report.portfolio_fit.sector, "Consumer Staples")
            self.assertEqual(report.portfolio_fit.theme, "Health and nutrition")
            self.assertNotIn("Geen bestaande positie", " ".join(report.portfolio_fit.notes))
            self.assertIn("DSFIR", " ".join(report.portfolio_fit.notes))

    def test_analysis_learns_provider_alias_for_imported_broker_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_position(
                PortfolioPosition(
                    symbol="LAM_RESEARCH",
                    quantity=10,
                    average_cost=90,
                    currency="USD",
                    account="Test",
                    as_of="2026-05-05",
                )
            )
            repo.upsert_portfolio_price(
                PortfolioPrice(symbol="LAM_RESEARCH", as_of="2026-05-05", close_price=100, currency="USD")
            )
            repo.upsert_portfolio_alias(
                PortfolioAlias(
                    portfolio_symbol="LAM_RESEARCH",
                    alias_key="LAM_RESEARCH",
                    alias_type="broker_name",
                    raw_value="LAM RESEARCH",
                    source="portfolio_csv",
                )
            )
            data_sources = [
                DataSource(
                    symbol="LAM RESEARCH",
                    field_name="close_price",
                    value_label="Slotkoers USD 100",
                    source_name="StockAnalysis quote en koersen",
                    source_url="https://stockanalysis.com/stocks/lrcx/",
                    source_date="2026-05-05",
                    source_quality="marktdata",
                )
            ]

            first_report = Advisor(repo).analyze_snapshots(
                "LAM RESEARCH",
                FinancialSnapshot(symbol="LAM RESEARCH", period_end="2025-12-31", period_type="TTM", revenue=1),
                MarketSnapshot(symbol="LAM RESEARCH", as_of="2026-05-05", close_price=100, currency="USD"),
                data_sources=data_sources,
            )
            self.assertAlmostEqual(first_report.portfolio_fit.position_value, 1000)
            self.assertEqual(repo.resolve_portfolio_aliases(["LRCX"]), {"LRCX": "LAM_RESEARCH"})

            second_report = Advisor(repo).analyze_snapshots(
                "LRCX",
                FinancialSnapshot(symbol="LRCX", period_end="2025-12-31", period_type="TTM", revenue=1),
                MarketSnapshot(symbol="LRCX", as_of="2026-05-05", close_price=100, currency="USD"),
            )
            self.assertAlmostEqual(second_report.portfolio_fit.position_value, 1000)
            self.assertNotIn("Geen bestaande positie", " ".join(second_report.portfolio_fit.notes))

    def test_transaction_advice_suggests_small_start_position_for_strong_new_idea(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.save_investor_profile(
                InvestorProfile(age=52, annual_income=90000, horizon_years=12, cash_buffer=25000)
            )
            repo.upsert_portfolio_asset(
                PortfolioAsset(asset_type="cash", value=100000, currency="EUR", as_of="2026-05-05")
            )

            report = Advisor(repo).analyze_snapshots(
                "NEW",
                FinancialSnapshot(
                    symbol="NEW",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=1_000_000_000,
                    operating_margin=0.25,
                    net_margin=0.18,
                    free_cash_flow=150_000_000,
                    debt=50_000_000,
                    cash=80_000_000,
                ),
                MarketSnapshot(
                    symbol="NEW",
                    as_of="2026-05-05",
                    close_price=50,
                    currency="EUR",
                    pe_ratio=15,
                    ev_ebitda=7,
                    fcf_yield=0.08,
                    momentum_12m=0.10,
                    volatility_1y=0.20,
                ),
            )

            self.assertEqual(report.portfolio_fit.transaction_action, "kleine_startpositie")
            self.assertEqual(report.portfolio_fit.transaction_label, "Kleine startpositie")
            self.assertEqual(report.portfolio_fit.max_new_buy_amount, 5000)
            self.assertEqual(report.portfolio_fit.practical_buy_amount, 5000)
            self.assertTrue(any("Beschikbare beleggingscash" in line for line in report.portfolio_fit.buy_room_calculation))
            self.assertTrue(any("Kleine startpositie" in line for line in report.portfolio_fit.transaction_rationale))
            self.assertTrue(any("cashbuffer" in line for line in report.portfolio_fit.transaction_rationale))
            self.assertTrue(any("totaal vermogen" in line for line in report.portfolio_fit.transaction_rationale))

    def test_buy_room_is_capped_by_cash_above_buffer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.save_investor_profile(
                InvestorProfile(age=52, annual_income=90000, horizon_years=12, cash_buffer=20000)
            )
            repo.upsert_portfolio_asset(
                PortfolioAsset(asset_type="cash", value=40000, currency="EUR", as_of="2026-05-05")
            )
            repo.upsert_portfolio_asset(
                PortfolioAsset(asset_type="house", value=1_000_000, currency="EUR", as_of="2026-05-05")
            )

            report = Advisor(repo).analyze_snapshots(
                "CASHCAP",
                FinancialSnapshot(
                    symbol="CASHCAP",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=1_000_000_000,
                    operating_margin=0.25,
                    net_margin=0.18,
                    free_cash_flow=150_000_000,
                    debt=50_000_000,
                    cash=80_000_000,
                ),
                MarketSnapshot(
                    symbol="CASHCAP",
                    as_of="2026-05-05",
                    close_price=50,
                    currency="EUR",
                    pe_ratio=15,
                    ev_ebitda=7,
                    fcf_yield=0.08,
                    momentum_12m=0.10,
                    volatility_1y=0.20,
                ),
            )

            self.assertEqual(report.portfolio_fit.position_room, 52000)
            self.assertEqual(report.portfolio_fit.available_cash, 20000)
            self.assertEqual(report.portfolio_fit.max_new_buy_amount, 20000)
            self.assertEqual(report.portfolio_fit.practical_buy_amount, 20000)

    def test_transaction_advice_suggests_selling_weak_existing_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.save_investor_profile(
                InvestorProfile(age=52, annual_income=90000, horizon_years=12, cash_buffer=25000)
            )
            repo.upsert_portfolio_asset(
                PortfolioAsset(asset_type="cash", value=100000, currency="EUR", as_of="2026-05-05")
            )
            repo.upsert_portfolio_position(
                PortfolioPosition(
                    symbol="WEAK",
                    quantity=100,
                    average_cost=20,
                    currency="EUR",
                    account="Test",
                    as_of="2026-05-05",
                )
            )

            report = Advisor(repo).analyze_snapshots(
                "WEAK",
                FinancialSnapshot(
                    symbol="WEAK",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=1_000_000_000,
                    operating_margin=-0.05,
                    net_margin=-0.10,
                    free_cash_flow=-50_000_000,
                    debt=500_000_000,
                ),
                MarketSnapshot(
                    symbol="WEAK",
                    as_of="2026-05-05",
                    close_price=15,
                    currency="EUR",
                    pe_ratio=40,
                    ev_ebitda=24,
                    fcf_yield=-0.02,
                    momentum_12m=-0.30,
                    volatility_1y=0.45,
                ),
            )

            self.assertEqual(report.portfolio_fit.transaction_action, "verkopen")
            self.assertEqual(report.portfolio_fit.transaction_label, "Verkopen")


if __name__ == "__main__":
    unittest.main()
