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
from beleggingsraadgever.web import SnapshotWorkflow, build_draft_report, build_page, ensure_snapshot_workflow


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
            self.assertIn("conceptbestand", html)
            self.assertIn("Slotkoers EUR 12.35", html)
            self.assertNotIn("pe_ratio: TODO", html)


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
