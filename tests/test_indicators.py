import unittest

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.indicators import build_score, verdict_from_score
from beleggingsraadgever.models import FinancialSnapshot, MarketSnapshot


class IndicatorTests(unittest.TestCase):
    def test_profitable_cash_generative_business_scores_well(self) -> None:
        financial = FinancialSnapshot(
            symbol="TST",
            period_end="2025-12-31",
            period_type="FY",
            revenue=100,
            operating_margin=0.25,
            net_margin=0.18,
            free_cash_flow=18,
            debt=20,
            cash=10,
        )
        market = MarketSnapshot(
            symbol="TST",
            as_of="2026-05-03",
            close_price=50,
            pe_ratio=18,
            ev_ebitda=12,
            fcf_yield=0.06,
            momentum_12m=0.10,
            volatility_1y=0.22,
        )
        score = build_score(financial, market)
        self.assertGreater(score.total, 65)
        self.assertIn(verdict_from_score(score), {"Kopen op zwakte", "Koopwaardig"})
        self.assertIn("quality", score.details)
        self.assertTrue(any("Operationele marge" in item for item in score.details["quality"]))

    def test_negative_fcf_creates_risk_flag(self) -> None:
        financial = FinancialSnapshot(
            symbol="BAD",
            period_end="2025-12-31",
            period_type="FY",
            revenue=100,
            operating_margin=0.05,
            net_margin=0.02,
            free_cash_flow=-5,
            debt=80,
            cash=5,
        )
        market = MarketSnapshot(
            symbol="BAD",
            as_of="2026-05-03",
            close_price=50,
            pe_ratio=42,
            volatility_1y=0.48,
        )
        score = build_score(financial, market)
        self.assertIn("Negatieve vrije kasstroom", score.flags)
        self.assertLess(score.total, 55)
        self.assertTrue(any("Hoge multiple" in item for item in score.details["risk"]))


if __name__ == "__main__":
    unittest.main()
