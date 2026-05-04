from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.advisor import Advisor
from beleggingsraadgever.importer import (
    SnapshotValidationError,
    import_company_snapshot,
    load_company_snapshot,
    validate_company_snapshot,
    write_snapshot_template,
)
from beleggingsraadgever.storage import SQLiteRepository


class ImporterTests(unittest.TestCase):
    def test_import_besi_snapshot_file(self) -> None:
        self._assert_snapshot_import("BESI", "BESI eerste echte snapshot")

    def test_import_asml_snapshot_file(self) -> None:
        self._assert_snapshot_import("ASML", "ASML eerste echte snapshot")

    def test_write_snapshot_template_creates_unfilled_shell_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_snapshot_template("shell", Path(tmp) / "shell.json")
            data = load_company_snapshot(path)
            errors = validate_company_snapshot(data)

            self.assertEqual(data["symbol"], "SHELL")
            self.assertTrue(any("market_snapshot.close_price is required" in error for error in errors))
            self.assertTrue(any("TODO" in error for error in errors))

    def test_import_rejects_snapshot_without_metric_source(self) -> None:
        data = load_company_snapshot(ROOT / "data" / "imports" / "asml.json")
        data["data_sources"] = [
            source for source in data["data_sources"] if source["field_name"] != "revenue"
        ]

        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "asml.json"
            snapshot.write_text(json.dumps(data), encoding="utf-8")
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")

            with self.assertRaises(SnapshotValidationError) as context:
                import_company_snapshot(repo, snapshot)

            self.assertIn("data_sources is missing a source for revenue.", context.exception.errors)

    def test_import_skips_inactive_placeholder_sources(self) -> None:
        data = load_company_snapshot(ROOT / "data" / "imports" / "asml.json")
        data["data_sources"].append(
            {
                "field_name": "manual_extra",
                "value_label": "TODO",
                "source_name": "TODO",
                "source_url": "TODO",
                "source_date": "YYYY-MM-DD",
                "source_quality": "primair",
                "note": "TODO",
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "asml.json"
            snapshot.write_text(json.dumps(data), encoding="utf-8")
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")

            import_company_snapshot(repo, snapshot)

            with repo.connect() as conn:
                placeholder_count = conn.execute(
                    "SELECT COUNT(*) FROM data_sources WHERE source_name = 'TODO'"
                ).fetchone()[0]
            self.assertEqual(placeholder_count, 0)

    def _assert_snapshot_import(self, symbol: str, evidence_title: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            imported_symbol = import_company_snapshot(repo, ROOT / "data" / "imports" / f"{symbol.lower()}.json")
            report = Advisor(repo).analyze(imported_symbol)
            self.assertEqual(imported_symbol, symbol)
            self.assertEqual(report.symbol, symbol)
            self.assertGreaterEqual(len(report.data_sources), 10)
            self.assertTrue(any(hit.title == evidence_title for hit in report.evidence))

            with repo.connect() as conn:
                import_row = conn.execute(
                    """
                    SELECT imported_from, source_checksum, processed_path
                    FROM snapshot_imports
                    WHERE symbol = ?
                    """,
                    (symbol,),
                ).fetchone()
            self.assertIsNotNone(import_row)
            self.assertTrue(import_row["imported_from"].endswith(f"{symbol.lower()}.json"))
            self.assertEqual(len(import_row["source_checksum"]), 64)
            self.assertIsNone(import_row["processed_path"])


if __name__ == "__main__":
    unittest.main()
