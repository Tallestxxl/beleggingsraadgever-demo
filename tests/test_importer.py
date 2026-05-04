from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.advisor import Advisor
from beleggingsraadgever.importer import import_company_snapshot
from beleggingsraadgever.storage import SQLiteRepository


class ImporterTests(unittest.TestCase):
    def test_import_besi_snapshot_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            symbol = import_company_snapshot(repo, ROOT / "data" / "imports" / "besi.json")
            report = Advisor(repo).analyze(symbol)
            self.assertEqual(symbol, "BESI")
            self.assertEqual(report.symbol, "BESI")
            self.assertGreaterEqual(len(report.data_sources), 10)
            self.assertTrue(any(hit.title == "BESI eerste echte snapshot" for hit in report.evidence))


if __name__ == "__main__":
    unittest.main()

