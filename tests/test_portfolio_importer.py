from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.portfolio_importer import import_portfolio_csv, normalize_broker_name
from beleggingsraadgever.storage import SQLiteRepository


class PortfolioImporterTests(unittest.TestCase):
    def test_import_portfolio_csv_maps_broker_names_and_skips_dividend_lines(self) -> None:
        csv_text = """A VAN EGMOND | Depotnummer 41.70.77.300 | 05 may.26 | 11:25
"Resultaten | 2026"," 83.198,00" EUR
Soort,Beleggen,Naam,Status,Aantal,Kostpr. per eenheid,Valuta kostpr. per eenheid,Opgebouwd vanaf,Koers,Valuta koers,Koers per,Marktwaarde, Valuta marktwaarde,Dividend / Coupons,Valuta Dividend / Coupons,Resultaat %,Resultaat EUR,
Aandelen,"","","","","","","","",""
,"417077300","APERAM","Ongerealiseerd","ST  334"," 35,24","EUR","17-11-2023"," 46,88","EUR","17-11-2023"," 15.658","EUR"," 165","EUR"," 33,0 %"," 3.889",
,"417077300","BE SEMICONDUCTOR IND","Ongerealiseerd","ST  200"," 133,75","EUR","02-11-2022"," 247,10","EUR","02-11-2022"," 49.420","EUR"," 316","EUR"," 84,7 %"," 22.670",
,"417077300","DIV FUGRO MEI26","Ongerealiseerd","ST  850"," 0,00","EUR","28-04-2026"," 0,15","EUR","28-04-2026"," 128","EUR"," 0","EUR","0 %"," 128",
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.csv"
            path.write_text(csv_text, encoding="utf-8")
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()

            result = import_portfolio_csv(repo, path)

            positions = repo.latest_portfolio_positions()
            self.assertEqual(result.imported_positions, 2)
            self.assertEqual(result.imported_market_prices, 2)
            self.assertEqual(result.imported_position_performance, 2)
            self.assertTrue(result.imported_performance_summary)
            self.assertGreaterEqual(result.discovered_peer_candidates, 2)
            self.assertEqual(result.skipped_rows, ["DIV FUGRO MEI26"])
            self.assertEqual(result.as_of, "2026-05-05")
            self.assertEqual([position.symbol for position in positions], ["APERAM", "BESI"])
            self.assertEqual(positions[0].quantity, 334)
            self.assertEqual(positions[0].average_cost, 35.24)
            self.assertEqual(repo.latest_portfolio_price("APERAM").close_price, 46.88)
            self.assertEqual(repo.portfolio_classification("BESI").sector, "Semiconductors")
            self.assertEqual(
                repo.resolve_portfolio_aliases(["BE_SEMICONDUCTOR_IND"]),
                {"BE_SEMICONDUCTOR_IND": "BESI"},
            )
            besi_aliases = {alias.alias_key for alias in repo.portfolio_aliases_for_symbol("BESI")}
            self.assertIn("BESI", besi_aliases)
            self.assertIn("BE_SEMICONDUCTOR_IND", besi_aliases)
            besi_peers = {candidate.peer_symbol for candidate in repo.peer_candidates_for_symbol("BESI")}
            self.assertIn("ASML", besi_peers)
            self.assertIn("ASMI", besi_peers)
            self.assertIn("LAM RESEARCH", besi_peers)
            summary = repo.latest_portfolio_performance_summary()
            self.assertIsNotNone(summary)
            self.assertEqual(summary.period_label, "2026")
            self.assertEqual(summary.total_result, 83198)
            performances = repo.latest_portfolio_position_performances()
            self.assertEqual(len(performances), 2)
            self.assertEqual(performances[0].symbol, "APERAM")
            self.assertEqual(performances[0].dividend_coupons, 165)
            self.assertAlmostEqual(performances[0].result_pct or 0, 0.33)
            self.assertEqual(performances[0].result_value, 3889)
            with self.assertRaises(LookupError):
                repo.latest_market_snapshot("APERAM")

    def test_normalize_broker_name_uses_known_aliases_and_fallback(self) -> None:
        self.assertEqual(normalize_broker_name("ASML  HOLDING"), "ASML")
        self.assertEqual(normalize_broker_name("ASMI"), "ASMI")
        self.assertEqual(normalize_broker_name("BP"), "BP")
        self.assertEqual(normalize_broker_name("BAM GROEP /KON/"), "BAMNB")
        self.assertEqual(normalize_broker_name("Onbekend Fonds Naam"), "ONBEKEND_FONDS_NAAM")


if __name__ == "__main__":
    unittest.main()
