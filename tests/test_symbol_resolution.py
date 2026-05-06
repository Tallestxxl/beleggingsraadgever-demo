from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.models import PortfolioPosition
from beleggingsraadgever.storage import SQLiteRepository
from beleggingsraadgever.symbol_resolution import resolve_analysis_symbol


class SymbolResolutionTests(unittest.TestCase):
    def test_resolves_short_input_to_single_portfolio_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_position(
                PortfolioPosition(
                    symbol="BAMNB",
                    quantity=100,
                    average_cost=4.50,
                    currency="EUR",
                    account="Test",
                    as_of="2026-05-06",
                )
            )

            self.assertEqual(resolve_analysis_symbol(repo, "BAM"), "BAMNB")
            self.assertEqual(repo.resolve_portfolio_aliases(["BAM"]), {"BAM": "BAMNB"})

    def test_keeps_ambiguous_short_input_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            for symbol in ["BAMNB", "BAMX"]:
                repo.upsert_portfolio_position(
                    PortfolioPosition(
                        symbol=symbol,
                        quantity=100,
                        average_cost=4.50,
                        currency="EUR",
                        account="Test",
                        as_of="2026-05-06",
                    )
                )

            self.assertEqual(resolve_analysis_symbol(repo, "BAM"), "BAM")


if __name__ == "__main__":
    unittest.main()
