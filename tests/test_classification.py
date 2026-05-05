from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.classification import classify_company, classify_symbol


class ClassificationTests(unittest.TestCase):
    def test_classifies_energy_company_from_description(self) -> None:
        classification = classify_company(
            "BP",
            company_name="BP p.l.c.",
            description="BP is an integrated energy company engaged in the oil and gas business worldwide.",
        )

        self.assertEqual(classification.sector, "Energy")
        self.assertEqual(classification.theme, "Oil and gas")

    def test_known_symbol_mapping_still_wins(self) -> None:
        classification = classify_company("ASMI", description="Semiconductor equipment maker.")

        self.assertEqual(classification.sector, "Semiconductors")
        self.assertEqual(classification.theme, "Semiconductor equipment")

    def test_unknown_without_description_remains_unknown(self) -> None:
        classification = classify_symbol("TOTALLYNEW")

        self.assertEqual(classification.sector, "Onbekend")
        self.assertEqual(classification.theme, "Onbekend")


if __name__ == "__main__":
    unittest.main()
