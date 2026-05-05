from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.advisor import Advisor
from beleggingsraadgever.models import (
    FinancialSnapshot,
    InvestorProfile,
    MarketSnapshot,
    PortfolioClassification,
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

    def test_bp_is_classified_as_energy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()

            report = Advisor(repo).analyze_snapshots(
                "BP",
                FinancialSnapshot(symbol="BP", period_end="2025-12-31", period_type="TTM", revenue=1_000_000_000),
                MarketSnapshot(symbol="BP", as_of="2026-05-05", close_price=5, currency="GBP"),
            )

            self.assertEqual(report.portfolio_fit.sector, "Energy")
            self.assertEqual(report.portfolio_fit.theme, "Oil and gas")


if __name__ == "__main__":
    unittest.main()
