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
        self._assert_snapshot_import("BESI", "BESI eerste echte snapshot")

    def test_import_asml_snapshot_file(self) -> None:
        self._assert_snapshot_import("ASML", "ASML eerste echte snapshot")

    def _assert_snapshot_import(self, symbol: str, evidence_title: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            imported_symbol = import_company_snapshot(repo, ROOT / "data" / "imports" / f"{symbol.lower()}.json")
            report = Advisor(repo).analyze(imported_symbol)
            self.assertEqual(imported_symbol, symbol)
            self.assertEqual(report.symbol, symbol)
            self.assertGreaterEqual(len(report.data_sources), 10)
            self.assertTrue(any(hit.title == evidence_title for hit in report.evidence))


if __name__ == "__main__":
    unittest.main()
