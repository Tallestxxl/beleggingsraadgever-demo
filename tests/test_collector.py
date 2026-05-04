from pathlib import Path
from datetime import date, datetime, timedelta, timezone
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.collector import collect_market_data, collect_snapshot_data
from beleggingsraadgever.importer import load_company_snapshot


class CollectorTests(unittest.TestCase):
    def test_collect_market_data_from_stockanalysis_html(self) -> None:
        market = collect_market_data("FUGRO", fetch_text=_fake_stockanalysis_fetch)

        self.assertEqual(market.provider, "StockAnalysis")
        self.assertEqual(market.provider_symbol, "AMS:FUR")
        self.assertEqual(market.as_of, "2026-04-30")
        self.assertEqual(market.close_price, 20.0)
        self.assertAlmostEqual(market.momentum_12m or 0, 1.0)
        self.assertIsNotNone(market.volatility_1y)
        self.assertEqual(market.revenue, 1_000_000_000)
        self.assertEqual(market.free_cash_flow, 120_000_000)
        self.assertEqual(market.period_end, "2025-12-31")
        self.assertAlmostEqual(market.operating_margin or 0, 0.1234)
        self.assertAlmostEqual(market.ev_ebitda or 0, 8.4)
        self.assertAlmostEqual(market.dividend_yield or 0, 0.021)

    def test_collect_market_data_falls_back_to_stooq_csv(self) -> None:
        market = collect_market_data("FUGRO", fetch_text=_fake_stooq_fetch)

        self.assertEqual(market.provider_symbol, "fur.nl")
        self.assertEqual(market.as_of, "2026-04-30")
        self.assertEqual(market.close_price, 20.0)
        self.assertAlmostEqual(market.momentum_12m or 0, 1.0)
        self.assertIsNotNone(market.volatility_1y)

    def test_collect_market_data_uses_stockanalysis_symbol_lookup(self) -> None:
        market = collect_market_data("APERAM", fetch_text=_fake_stockanalysis_lookup_fetch)

        self.assertEqual(market.provider, "StockAnalysis")
        self.assertEqual(market.provider_symbol, "AMS:APAM")
        self.assertEqual(market.as_of, "2026-04-30")
        self.assertEqual(market.close_price, 20.0)
        self.assertEqual(market.revenue, 1_000_000_000)

    def test_collect_snapshot_data_prefills_market_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fugro.json"
            result = collect_snapshot_data("FUGRO", path=path, fetch_text=_fake_stockanalysis_fetch)
            data = load_company_snapshot(path)

            self.assertTrue(path.exists())
            self.assertIn("close_price", result.updated_fields)
            self.assertIn("revenue", result.updated_fields)
            self.assertIn("ev_ebitda", result.updated_fields)
            self.assertEqual(data["market_snapshot"]["close_price"], 20.0)
            self.assertEqual(data["market_snapshot"]["as_of"], "2026-04-30")
            self.assertEqual(data["financial_snapshot"]["period_type"], "TTM")
            self.assertEqual(data["financial_snapshot"]["period_end"], "2025-12-31")
            self.assertEqual(data["financial_snapshot"]["revenue"], 1_000_000_000)
            self.assertTrue(any(source["field_name"] == "close_price" for source in data["data_sources"]))
            self.assertTrue(any(source["field_name"] == "revenue" for source in data["data_sources"]))
            self.assertTrue(any(doc["title"] == "FUGRO eerste snapshot" for doc in data["documents"]))
            self.assertTrue(any(doc["title"] == "FUGRO automatisch opgehaalde marktdata" for doc in data["documents"]))


def _fake_stockanalysis_fetch(url: str) -> str:
    if "financials" in url:
        return _fake_stockanalysis_financials_html()
    if "statistics" in url:
        return _fake_stockanalysis_statistics_html()
    if "stockanalysis.com/quote/ams/FUR/" in url:
        return _fake_stockanalysis_overview_html()
    return "Page Not Found - 404"


def _fake_stockanalysis_lookup_fetch(url: str) -> str:
    if "symbol-lookup" in url:
        return """
        <script>
          data:[{type:"data",data:{query:"APERAM",count:1,
          results:[{s:"@ams/APAM",n:"Aperam S.A.",t:"Stock",p:47.22,m:3282864667}]}}]
        </script>
        """
    if "financials" in url and "quote/ams/APAM" in url:
        return _fake_stockanalysis_financials_html()
    if "statistics" in url and "quote/ams/APAM" in url:
        return _fake_stockanalysis_statistics_html()
    if "stockanalysis.com/quote/ams/APAM/" in url:
        return _fake_stockanalysis_overview_html()
    return "Page Not Found - 404"


def _fake_stooq_fetch(url: str) -> str:
    if "stockanalysis.com" in url:
        return "Page Not Found - 404"
    if "fur.nl" not in url:
        return "Date,Open,High,Low,Close,Volume\n"
    return "\n".join(
        [
            "Date,Open,High,Low,Close,Volume",
            "2025-04-30,10,10,10,10,1000",
            "2025-05-01,10,11,9,11,1000",
            "2026-04-29,19,19,18,19,1000",
            "2026-04-30,20,21,19,20,1000",
        ]
    )


def _fake_stockanalysis_overview_html() -> str:
    return f"""
    <script>
      data: [
        {{type:"data",data:{{info:{{quote:{{p:20.1,cl:20.0,td:"2026-04-30"}},curr:{{price:"EUR",main:"EUR"}}}}}}}},
        {{type:"data",data:{{description:"Fugro levert geo-data diensten voor energie, infrastructuur en water.",
          chart:{{expiration:0,data:[{_fake_chart_points()}]}},
          changes:{{price1y:10.0}}}}}}
      ]
    </script>
    <script type="application/ld+json">{{"@type":"Corporation","name":"Fugro","legalName":"Fugro N.V.","tickerSymbol":"AMS:FUR"}}</script>
    """


def _fake_stockanalysis_statistics_html() -> str:
    return """
    <script>
      data: [{type:"data",data:{
        valuation:{data:[{id:"marketcap",title:"Market Cap",value:"1.80B",hover:"1,800,000,000"}]},
        ratios:{data:[{id:"pe",title:"PE Ratio",value:"18.50",hover:"18.50"}]},
        evRatios:{data:[{id:"evEbitda",title:"EV / EBITDA",value:"8.40",hover:"8.40"}]},
        incomeStatement:{data:[
          {id:"revenue",title:"Revenue",value:"1.00B",hover:"1,000,000,000"},
          {id:"gp",title:"Gross Profit",value:"350.00M",hover:"350,000,000"}
        ]},
        balanceSheet:{data:[
          {id:"totalcash",title:"Cash & Cash Equivalents",value:"200.00M",hover:"200,000,000"},
          {id:"debt",title:"Total Debt",value:"300.00M",hover:"300,000,000"}
        ]},
        cashFlow:{data:[{id:"fcf",title:"Free Cash Flow",value:"120.00M",hover:"120,000,000"}]},
        margins:{data:[
          {id:"grossMargin",title:"Gross Margin",value:"35.00%",hover:"35.000%"},
          {id:"operatingMargin",title:"Operating Margin",value:"12.34%",hover:"12.340%"},
          {id:"profitMargin",title:"Profit Margin",value:"9.87%",hover:"9.870%"}
        ]},
        dividends:{data:[
          {id:"dps",title:"Dividend Per Share",value:"0.42",hover:"0.420"},
          {id:"dividendYield",title:"Dividend Yield",value:"2.10%",hover:"2.100%"},
          {id:"fcfYield",title:"FCF Yield",value:"6.67%",hover:"6.667%"}
        ]},
        shares:{data:[{id:"sharesout",title:"Shares Outstanding",value:"100.00M",hover:"100,000,000"}]},
        stockPrice:{data:[{id:"ch1y",title:"52-Week Price Change",value:"+100.00%",hover:"100.000%"}]}
      }}]
    </script>
    """


def _fake_stockanalysis_financials_html() -> str:
    return 'details:{source:"spg",lastTrailingDate:"Dec 31, 2025"}'


def _fake_chart_points() -> str:
    start = date(2025, 4, 30)
    points = []
    for index in range(31):
        day = start + timedelta(days=round(index * 365 / 30))
        timestamp = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
        close = 10 + index / 3
        points.append(f"{{c:{close:.4f},t:{timestamp}}}")
    return ",".join(points)


if __name__ == "__main__":
    unittest.main()
