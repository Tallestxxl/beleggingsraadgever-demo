from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.models import DataSource
from beleggingsraadgever.storage import SQLiteRepository


class SourceTests(unittest.TestCase):
    def test_upsert_and_fetch_data_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_data_source(
                DataSource(
                    symbol="TST",
                    field_name="revenue",
                    value_label="EUR 100 mln",
                    source_name="Test source",
                    source_url="https://example.com",
                    source_date="2026-05-04",
                    source_quality="primair",
                    note="Test note",
                )
            )
            sources = repo.data_sources_for_symbol("TST")
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].field_name, "revenue")
            self.assertEqual(sources[0].source_quality, "primair")


if __name__ == "__main__":
    unittest.main()

