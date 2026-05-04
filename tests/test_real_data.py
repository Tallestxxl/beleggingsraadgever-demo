from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.advisor import Advisor
from beleggingsraadgever.real_data import seed_besi
from beleggingsraadgever.storage import SQLiteRepository


class RealDataTests(unittest.TestCase):
    def test_seed_besi_allows_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            seed_besi(repo)
            report = Advisor(repo).analyze("BESI")
            self.assertEqual(report.symbol, "BESI")
            self.assertGreater(report.score.quality, 90)
            self.assertLess(report.score.valuation, 25)
            self.assertTrue(report.evidence)
            self.assertGreaterEqual(len(report.data_sources), 10)
            self.assertTrue(any(source.field_name == "revenue" for source in report.data_sources))


if __name__ == "__main__":
    unittest.main()
