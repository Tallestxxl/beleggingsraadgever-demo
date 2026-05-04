from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.advisor import Advisor
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


if __name__ == "__main__":
    unittest.main()

