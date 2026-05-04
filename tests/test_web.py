from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.advisor import Advisor
from beleggingsraadgever.sample_data import seed_demo
from beleggingsraadgever.storage import SQLiteRepository
from beleggingsraadgever.web import build_page, ensure_snapshot_workflow


class WebTests(unittest.TestCase):
    def test_build_page_renders_report(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            seed_demo(repo)
            report = Advisor(repo).analyze("DEMO")
            html = build_page(symbol="DEMO", report=report)
            self.assertIn("Beleggingsraadgever", html)
            self.assertIn("DEMO", html)
            self.assertIn("Scorekaart", html)
            self.assertIn("Toon berekening", html)
            self.assertIn("Dataversheid", html)
            self.assertIn("<summary>Bronnen per cijfer</summary>", html)

    def test_unknown_symbol_workflow_creates_draft(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            workflow = ensure_snapshot_workflow("shell", drafts_dir=Path(tmp))
            html = build_page(symbol="SHELL", workflow=workflow)

            self.assertEqual(workflow.symbol, "SHELL")
            self.assertTrue(workflow.path.exists())
            self.assertIn("SHELL: Workflow gestart", html)
            self.assertIn("Conceptbestand", html)
            self.assertIn("Importeer snapshot", html)
            self.assertIn("financial_snapshot.revenue is required", html)


if __name__ == "__main__":
    unittest.main()
