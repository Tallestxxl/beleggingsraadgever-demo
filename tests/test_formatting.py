from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.formatting import format_currency, format_dutch_number


class FormattingTests(unittest.TestCase):
    def test_dutch_number_uses_points_for_thousands(self) -> None:
        self.assertEqual(format_dutch_number(1_000), "1.000")
        self.assertEqual(format_dutch_number(1_200_000), "1.200.000")

    def test_currency_uses_dutch_decimal_and_thousands_separators(self) -> None:
        self.assertEqual(format_currency(1_234.56, "EUR", decimals=2), "EUR 1.234,56")
        self.assertEqual(format_currency(1_200_000, "EUR", decimals=0), "EUR 1.200.000")


if __name__ == "__main__":
    unittest.main()
