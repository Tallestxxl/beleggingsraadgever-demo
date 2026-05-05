from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.advisor import Advisor
from beleggingsraadgever.importer import write_snapshot_template
from beleggingsraadgever.sample_data import seed_demo
from beleggingsraadgever.storage import SQLiteRepository
from beleggingsraadgever.web import (
    SnapshotWorkflow,
    archive_imported_snapshot,
    build_draft_report,
    build_page,
    build_portfolio_page,
    ensure_snapshot_workflow,
    import_portfolio_csv_workflow,
    save_portfolio_position,
    save_portfolio_profile,
    save_case_note_workflow,
)


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
            self.assertIn("Casusnotitie voor SHELL", html)
            self.assertIn("financial_snapshot.revenue is required", html)

    def test_existing_incomplete_draft_auto_collects_on_analysis_flow(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aperam.json"
            write_snapshot_template("APERAM", path)

            workflow = ensure_snapshot_workflow(
                "APERAM",
                drafts_dir=Path(tmp),
                auto_collect=True,
                fetch_text=_fake_web_stockanalysis_lookup_fetch,
            )

            self.assertTrue(path.exists())
            self.assertNotIn("financial_snapshot.revenue is required.", workflow.errors)
            self.assertNotIn("market_snapshot.close_price is required.", workflow.errors)
            self.assertTrue(any("AMS:APAM" in message for message in workflow.messages))

    def test_draft_with_core_figures_renders_concept_analysis(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fugro.json"
            path.write_text(
                json.dumps(
                    {
                        "symbol": "FUGRO",
                        "financial_snapshot": {
                            "period_end": "2025-12-31",
                            "period_type": "TTM",
                            "revenue": 1848071000.0,
                            "gross_margin": 0.29447,
                            "operating_margin": 0.04421,
                            "net_margin": -0.01107,
                            "free_cash_flow": -155490000.0,
                            "debt": 475737000.0,
                            "cash": 93166000.0,
                            "shares_outstanding": 111334361.0,
                            "dividend_per_share": 0.15,
                            "buyback_value": None,
                        },
                        "market_snapshot": {
                            "as_of": "2026-04-30",
                            "close_price": 12.35,
                            "currency": "EUR",
                            "pe_ratio": None,
                            "ev_ebitda": 6.5,
                            "fcf_yield": -0.11309,
                            "dividend_yield": 0.01215,
                            "momentum_12m": 0.1852,
                            "volatility_1y": 0.3637,
                        },
                        "documents": [
                            {
                                "title": "FUGRO automatisch opgehaalde marktdata",
                                "source_type": "public_market_data",
                                "publication_date": "2026-04-30",
                                "tags": ["FUGRO", "marktdata"],
                                "raw_text": "Automatisch opgehaalde marktdata voor FUGRO.",
                            }
                        ],
                        "principles": [
                            {
                                "title": "FUGRO: TODO principe",
                                "statement": "TODO: formuleer het belangrijkste beleggingsprincipe.",
                                "category": "waardering",
                            }
                        ],
                        "data_sources": [
                            {
                                "field_name": "close_price",
                                "value_label": "Slotkoers EUR 12.35",
                                "source_name": "StockAnalysis quote en koersen",
                                "source_url": "https://stockanalysis.com/quote/ams/FUR/",
                                "source_date": "2026-04-30",
                                "source_quality": "marktdata",
                                "note": "Automatisch opgehaald als end-of-day koerspunt.",
                            },
                            {
                                "field_name": "pe_ratio",
                                "value_label": "TODO",
                                "source_name": "TODO",
                                "source_url": "TODO",
                                "source_date": "YYYY-MM-DD",
                                "source_quality": "primair",
                                "note": "TODO",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            workflow = SnapshotWorkflow(
                symbol="FUGRO",
                path=path,
                created=False,
                errors=["principles[0].title still contains TODO."],
                messages=[],
            )
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()

            report = build_draft_report(repo, workflow)
            html = build_page(symbol="FUGRO", report=report, workflow=workflow)

            self.assertIsNotNone(report)
            self.assertIn("Conceptanalyse", html)
            self.assertIn("FUGRO:", html)
            self.assertIn("Scorekaart", html)
            self.assertIn("Transactieadvies", html)
            self.assertIn("conceptbestand", html)
            self.assertIn("Slotkoers EUR 12.35", html)
            self.assertNotIn("pe_ratio: TODO", html)

    def test_draft_report_stores_classification_from_company_description(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bp.json"
            path.write_text(
                json.dumps(
                    {
                        "symbol": "BP",
                        "financial_snapshot": {
                            "period_end": "2025-12-31",
                            "period_type": "TTM",
                            "revenue": 1_000_000_000,
                        },
                        "market_snapshot": {
                            "as_of": "2026-05-05",
                            "close_price": 5,
                            "currency": "GBP",
                        },
                        "documents": [
                            {
                                "title": "BP automatisch opgehaalde marktdata",
                                "source_type": "public_market_data",
                                "publication_date": "2026-05-05",
                                "raw_text": (
                                    "BP is an integrated energy company engaged in the oil and gas business worldwide."
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            workflow = SnapshotWorkflow(symbol="BP", path=path, created=False, errors=[], messages=[])
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()

            report = build_draft_report(repo, workflow)
            stored = repo.portfolio_classification("BP")

            self.assertIsNotNone(report)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.sector, "Energy")
            self.assertEqual(stored.theme, "Oil and gas")
            self.assertEqual(report.portfolio_fit.sector, "Energy")
            self.assertEqual(report.portfolio_fit.theme, "Oil and gas")

    def test_case_note_replaces_todo_principle_and_makes_collected_draft_importable(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aperam.json"
            workflow = ensure_snapshot_workflow(
                "APERAM",
                drafts_dir=Path(tmp),
                auto_collect=True,
                fetch_text=_fake_web_stockanalysis_lookup_fetch,
            )
            self.assertEqual(workflow.path, path)
            self.assertTrue(any("principles[0]" in error for error in workflow.errors))

            workflow, error = save_case_note_workflow(
                "APERAM",
                {
                    "note_title": ["Aperam cyclische staalcasus"],
                    "source_type": ["eigen_notitie"],
                    "publication_date": ["2026-05-04"],
                    "raw_text": [
                        "Aperam is gevoelig voor de staalcyclus, maar vrije kasstroom en dividenddiscipline zijn de kern."
                    ],
                    "principle_statement": [
                        "Bij Aperam alleen opschalen wanneer vrije kasstroom en balans de dividenduitkering ondersteunen."
                    ],
                },
                drafts_dir=Path(tmp),
            )

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsNone(error)
            self.assertEqual(workflow.errors, [])
            self.assertTrue(any(doc["title"] == "Aperam cyclische staalcasus" for doc in data["documents"]))
            self.assertEqual(data["principles"][0]["title"], "APERAM: Aperam cyclische staalcasus")
            self.assertNotIn("TODO", data["principles"][0]["statement"])

            html = build_page(symbol="APERAM", workflow=workflow)
            self.assertIn("Klaar voor import", html)
            self.assertIn("Workflowmeldingen", html)
            self.assertIn("Alle validatiepunten zijn opgelost", html)
            self.assertIn("button type=\"submit\">Importeer snapshot</button>", html)

    def test_archive_imported_snapshot_moves_draft_to_processed_with_metadata(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aperam.json"
            processed_dir = Path(tmp) / "processed"
            workflow = ensure_snapshot_workflow(
                "APERAM",
                drafts_dir=Path(tmp),
                auto_collect=True,
                fetch_text=_fake_web_stockanalysis_lookup_fetch,
            )
            workflow, error = save_case_note_workflow(
                "APERAM",
                {
                    "note_title": ["Dividend"],
                    "source_type": ["beleggers_belangen"],
                    "publication_date": ["2026-05-05"],
                    "raw_text": ["Free cashflow moet het kwartaaldividend dragen."],
                    "principle_statement": ["Dividend is alleen aantrekkelijk wanneer kasstroom het ondersteunt."],
                },
                drafts_dir=Path(tmp),
            )

            self.assertIsNone(error)
            self.assertEqual(workflow.errors, [])
            archived = archive_imported_snapshot(path, "APERAM", processed_dir=processed_dir)
            data = json.loads(archived.path.read_text(encoding="utf-8"))

            self.assertFalse(path.exists())
            self.assertTrue(archived.path.exists())
            self.assertEqual(len(archived.source_checksum), 64)
            self.assertEqual(data["import_metadata"]["source_checksum"], archived.source_checksum)
            self.assertEqual(data["import_metadata"]["imported_from"], str(path))
            self.assertEqual(data["principles"][0]["title"], "APERAM: Dividend")

    def test_portfolio_page_saves_profile_assets_and_position(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()

            save_portfolio_profile(
                repo,
                {
                    "age": ["52"],
                    "annual_income": ["90000"],
                    "horizon_years": ["12"],
                    "cash_buffer": ["25000"],
                    "risk_profile": ["gebalanceerd"],
                    "asset_cash": ["25000"],
                    "asset_house": ["500000"],
                    "asset_gold": ["10000"],
                    "asset_bitcoin": ["15000"],
                    "asset_other": [""],
                },
            )
            save_portfolio_position(
                repo,
                {
                    "symbol": ["DEMO"],
                    "account": ["Hoofdrekening"],
                    "quantity": ["10"],
                    "average_cost": ["90"],
                    "currency": ["EUR"],
                    "as_of": ["2026-05-05"],
                },
            )

            html = build_portfolio_page(repo)

            self.assertIn("Profiel & portefeuille", html)
            self.assertIn("CSV-import", html)
            self.assertIn("Effectenportefeuille", html)
            self.assertIn("Sectorverdeling effecten", html)
            self.assertIn("% effecten", html)
            self.assertNotIn("% totaal", html)
            self.assertIn("DEMO", html)
            self.assertIn("EUR 550.000", html)

    def test_portfolio_csv_workflow_imports_file_path(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "portfolio.csv"
            csv_path.write_text(
                """A VAN EGMOND | Depotnummer 41.70.77.300 | 05 may.26 | 11:25
"Resultaten | Historisch"," 204.042,00" EUR
"Ongerealiseerd resultaat"," 53.104" EUR
"Gerealiseerd resultaat"," 116.714" EUR
"Dividend en coupons"," 34.224" EUR
Soort,Beleggen,Naam,Status,Aantal,Kostpr. per eenheid,Valuta kostpr. per eenheid,Opgebouwd vanaf,Koers,Valuta koers,Koers per,Marktwaarde, Valuta marktwaarde,Dividend / Coupons,Valuta Dividend / Coupons,Resultaat %,Resultaat EUR,
,"417077300","SHELL","Ongerealiseerd","ST  1.077"," 31,56","EUR","28-01-2022"," 38,32","EUR","28-01-2022"," 41.265","EUR"," 345","EUR"," 21,4 %"," 7.273",
""",
                encoding="utf-8",
            )
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()

            message = import_portfolio_csv_workflow(repo, {"csv_path": [str(csv_path)]})
            html = build_portfolio_page(repo)

            self.assertIn("1 posities", message)
            self.assertIn("historische samenvatting", message)
            self.assertEqual(repo.latest_portfolio_positions()[0].symbol, "SHELL")
            self.assertIn("Historisch resultaat", html)
            self.assertIn("EUR 204.042", html)
            self.assertIn("EUR 7.273", html)
            self.assertIn("EUR 345", html)


def _fake_web_stockanalysis_lookup_fetch(url: str) -> str:
    if "symbol-lookup" in url:
        return 'data:{query:"APERAM",count:1,results:[{s:"@ams/APAM",n:"Aperam S.A.",t:"Stock",p:47.22,m:3282864667}]}'
    if "financials" in url and "quote/ams/APAM" in url:
        return 'details:{source:"spg",lastTrailingDate:"Dec 31, 2025"}'
    if "statistics" in url and "quote/ams/APAM" in url:
        return """
        <script>
          data:[{type:"data",data:{
            incomeStatement:{data:[{id:"revenue",title:"Revenue",value:"6.00B",hover:"6,000,000,000"}]},
            margins:{data:[{id:"operatingMargin",title:"Operating Margin",value:"6.00%",hover:"6.000%"}]},
            cashFlow:{data:[{id:"fcf",title:"Free Cash Flow",value:"80.00M",hover:"80,000,000"}]},
            evRatios:{data:[{id:"evEbitda",title:"EV / EBITDA",value:"8.40",hover:"8.40"}]}
          }}]
        </script>
        """
    if "stockanalysis.com/quote/ams/APAM/" in url:
        return """
        <script>
          data:[{type:"data",data:{info:{quote:{p:47.88,cl:47.88,td:"2026-05-04"},curr:{price:"EUR",main:"EUR"}}}}],
          description:"Aperam produceert roestvast staal en speciale legeringen."
        </script>
        <script type="application/ld+json">{"@type":"Corporation","name":"Aperam","legalName":"Aperam S.A.","tickerSymbol":"AMS:APAM"}</script>
        """
    return "Page Not Found - 404"


if __name__ == "__main__":
    unittest.main()
