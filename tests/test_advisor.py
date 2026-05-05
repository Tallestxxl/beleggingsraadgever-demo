from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.advisor import Advisor
from beleggingsraadgever.models import InvestorProfile, PortfolioAsset, PortfolioPosition
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


if __name__ == "__main__":
    unittest.main()
