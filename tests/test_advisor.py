from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.advisor import Advisor
from beleggingsraadgever.models import (
    DataSource,
    FinancialSnapshot,
    InvestorProfile,
    MarketSnapshot,
    PeerCandidate,
    PortfolioClassification,
    PortfolioAlias,
    PortfolioPosition,
    PortfolioPrice,
    PortfolioAsset,
)
from beleggingsraadgever.sample_data import seed_demo
from beleggingsraadgever.storage import SQLiteRepository
from beleggingsraadgever.peer_discovery import refresh_peer_candidates


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

    def test_report_includes_portfolio_fit_when_profile_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            seed_demo(repo)
            repo.save_investor_profile(
                InvestorProfile(age=52, annual_income=90000, horizon_years=12, cash_buffer=25000)
            )
            repo.upsert_portfolio_asset(PortfolioAsset(asset_type="cash", value=25000, currency="EUR", as_of="2026-05-05"))
            repo.upsert_portfolio_position(
                PortfolioPosition(
                    symbol="DEMO",
                    quantity=10,
                    average_cost=90,
                    currency="EUR",
                    account="Test",
                    as_of="2026-05-05",
                )
            )

            report = Advisor(repo).analyze("DEMO")
            markdown = Advisor(repo).render_markdown(report)

            self.assertIsNotNone(report.portfolio_fit)
            self.assertIn("Portefeuillefit", markdown)
            self.assertGreater(report.portfolio_fit.total_wealth, 0)

    def test_portfolio_fit_warns_for_semiconductor_concentration_on_asmi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.save_investor_profile(
                InvestorProfile(age=52, annual_income=90000, horizon_years=12, cash_buffer=25000)
            )
            for symbol, value in [("ASML", 60000), ("BESI", 50000), ("SHELL", 40000)]:
                repo.upsert_portfolio_position(
                    PortfolioPosition(
                        symbol=symbol,
                        quantity=1,
                        average_cost=value,
                        currency="EUR",
                        account="Test",
                        as_of="2026-05-05",
                    )
                )
                repo.upsert_portfolio_price(
                    PortfolioPrice(symbol=symbol, as_of="2026-05-05", close_price=value, currency="EUR")
                )
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="ASML", sector="Semiconductors", theme="Semiconductor equipment")
            )
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="BESI", sector="Semiconductors", theme="Semiconductor equipment")
            )

            report = Advisor(repo).analyze_snapshots(
                "ASMI",
                FinancialSnapshot(symbol="ASMI", period_end="2025-12-31", period_type="TTM", revenue=1_000_000_000),
                MarketSnapshot(symbol="ASMI", as_of="2026-05-05", close_price=500, currency="EUR"),
            )

            self.assertIsNotNone(report.portfolio_fit)
            self.assertEqual(report.portfolio_fit.sector, "Semiconductors")
            self.assertGreater(report.portfolio_fit.sector_weight, 0.20)
            self.assertIn("Sectorconcentratie", " ".join(report.portfolio_fit.notes))
            self.assertIn("Semiconductors", report.portfolio_fit.summary)

    def test_analyze_snapshots_uses_stored_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="BP", sector="Energy", theme="Oil and gas")
            )

            report = Advisor(repo).analyze_snapshots(
                "BP",
                FinancialSnapshot(symbol="BP", period_end="2025-12-31", period_type="TTM", revenue=1_000_000_000),
                MarketSnapshot(symbol="BP", as_of="2026-05-05", close_price=5, currency="GBP"),
            )

            self.assertEqual(report.portfolio_fit.sector, "Energy")
            self.assertEqual(report.portfolio_fit.theme, "Oil and gas")

    def test_symbol_scoped_snapshot_evidence_must_match_analyzed_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.add_document(
                title="BAM Brookfield snapshot",
                source_type="public_data_snapshot",
                raw_text="BAM Brookfield Asset Management waardering marge vrije kasstroom.",
                tags=["BAM", "datacollector"],
            )
            repo.add_document(
                title="Algemeen bouwprincipe",
                source_type="beleggers_belangen",
                raw_text="Bij bouwbedrijven zijn marges, kasstroom en schuld belangrijk.",
                tags=["bouw", "marge"],
            )

            report = Advisor(repo).analyze_snapshots(
                "BAMNB",
                FinancialSnapshot(
                    symbol="BAMNB",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=1_000_000_000,
                    operating_margin=0.04,
                ),
                MarketSnapshot(symbol="BAMNB", as_of="2026-05-06", close_price=4.50, currency="EUR"),
            )

            self.assertNotIn("BAM Brookfield snapshot", [hit.title for hit in report.evidence])
            self.assertIn("Algemeen bouwprincipe", [hit.title for hit in report.evidence])

    def test_symbol_tagged_case_note_must_match_analyzed_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.add_document(
                title="APERAM dividendcasus",
                source_type="beleggers_belangen",
                raw_text=(
                    "Zorg dat er voldoende free cashflow is om het dividend elke drie maanden te kunnen betalen. "
                    "Waardering, marge, vrije kasstroom, schuld, dividend, buybacks, risico en kwaliteit."
                ),
                tags=["APERAM", "casusnotitie"],
            )
            repo.add_document(
                title="Algemeen dividendprincipe",
                source_type="beleggers_belangen",
                raw_text=(
                    "Dividend moet worden ondersteund door vrije kasstroom, balansruimte en lage schuld. "
                    "Waardering, marge, vrije kasstroom, schuld, dividend, buybacks, risico en kwaliteit."
                ),
                tags=["dividend", "vrije kasstroom"],
            )

            report = Advisor(repo).analyze_snapshots(
                "BESI",
                FinancialSnapshot(
                    symbol="BESI",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=1_000_000_000,
                    free_cash_flow=180_000_000,
                    operating_margin=0.25,
                ),
                MarketSnapshot(
                    symbol="BESI",
                    as_of="2026-05-06",
                    close_price=130,
                    currency="EUR",
                    dividend_yield=0.045,
                ),
            )

            evidence_titles = [hit.title for hit in report.evidence]
            self.assertNotIn("APERAM dividendcasus", evidence_titles)
            self.assertIn("Algemeen dividendprincipe", evidence_titles)

    def test_sector_scoped_evidence_must_match_analysis_sector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="BESI", sector="Semiconductors", theme="Semiconductor equipment")
            )
            repo.add_document(
                title="Semiconductor margin principle",
                source_type="educatie",
                raw_text="Semiconductorbedrijven vragen discipline rond waardering, marge, vrije kasstroom en risico.",
                tags=["Semiconductors", "scope:sector", "marge"],
            )
            repo.add_document(
                title="Construction margin principle",
                source_type="educatie",
                raw_text="Bouwbedrijven vragen discipline rond waardering, marge, vrije kasstroom en risico.",
                tags=["Construction", "scope:sector", "marge"],
            )

            report = Advisor(repo).analyze_snapshots(
                "BESI",
                FinancialSnapshot(symbol="BESI", period_end="2025-12-31", period_type="TTM", revenue=1_000_000_000),
                MarketSnapshot(symbol="BESI", as_of="2026-05-06", close_price=130, currency="EUR"),
            )

            evidence_titles = [hit.title for hit in report.evidence]
            self.assertIn("Semiconductor margin principle", evidence_titles)
            self.assertNotIn("Construction margin principle", evidence_titles)

    def test_peer_analysis_compares_against_available_peer_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="ASMI", sector="Semiconductors", theme="Semiconductor equipment")
            )
            for symbol, operating_margin, pe_ratio in [
                ("ASML", 0.33, 42),
                ("BESI", 0.28, 36),
            ]:
                repo.upsert_financial_snapshot(
                    FinancialSnapshot(
                        symbol=symbol,
                        period_end="2025-12-31",
                        period_type="TTM",
                        revenue=1_000_000_000,
                        operating_margin=operating_margin,
                        free_cash_flow=200_000_000,
                        debt=100_000_000,
                    )
                )
                repo.upsert_market_snapshot(
                    MarketSnapshot(
                        symbol=symbol,
                        as_of="2026-05-05",
                        close_price=100,
                        currency="EUR",
                        pe_ratio=pe_ratio,
                        ev_ebitda=18,
                        fcf_yield=0.04,
                        momentum_12m=0.20,
                    )
                )

            report = Advisor(repo).analyze_snapshots(
                "ASMI",
                FinancialSnapshot(
                    symbol="ASMI",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=1_000_000_000,
                    operating_margin=0.35,
                    free_cash_flow=220_000_000,
                    debt=90_000_000,
                ),
                MarketSnapshot(
                    symbol="ASMI",
                    as_of="2026-05-05",
                    close_price=500,
                    currency="EUR",
                    pe_ratio=30,
                    ev_ebitda=16,
                    fcf_yield=0.05,
                    momentum_12m=0.30,
                ),
            )

            self.assertIsNotNone(report.peer_analysis)
            self.assertEqual([row.symbol for row in report.peer_analysis.rows], ["ASMI", "ASML", "BESI"])
            self.assertEqual(report.peer_analysis.available_peer_count, 2)
            self.assertEqual(report.peer_analysis.configured_peer_count, 5)
            self.assertEqual(report.peer_analysis.max_peer_count, 6)
            self.assertEqual(report.peer_analysis.min_peer_count, 2)
            self.assertIn("Relatief beeld", report.peer_analysis.summary)
            markdown = Advisor(repo).render_markdown(report)
            self.assertIn("Peeranalyse", markdown)
            self.assertIn("2 van 5 peers beschikbaar", markdown)

    def test_peer_analysis_is_hidden_until_minimum_peer_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="ASMI", sector="Semiconductors", theme="Semiconductor equipment")
            )
            repo.upsert_financial_snapshot(
                FinancialSnapshot(
                    symbol="ASML",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=1_000_000_000,
                    operating_margin=0.33,
                )
            )
            repo.upsert_market_snapshot(
                MarketSnapshot(symbol="ASML", as_of="2026-05-05", close_price=100, currency="EUR")
            )

            report = Advisor(repo).analyze_snapshots(
                "ASMI",
                FinancialSnapshot(symbol="ASMI", period_end="2025-12-31", period_type="TTM", revenue=1_000_000_000),
                MarketSnapshot(symbol="ASMI", as_of="2026-05-05", close_price=500, currency="EUR"),
            )

            self.assertIsNone(report.peer_analysis)

    def test_nedap_is_not_compared_with_fugro_or_vopak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="NEDAP", sector="Industrials", theme="Technology hardware")
            )
            for symbol in ["FUGRO", "VOPAK"]:
                repo.upsert_financial_snapshot(
                    FinancialSnapshot(
                        symbol=symbol,
                        period_end="2025-12-31",
                        period_type="TTM",
                        revenue=1_000_000_000,
                        operating_margin=0.20,
                    )
                )
                repo.upsert_market_snapshot(
                    MarketSnapshot(
                        symbol=symbol,
                        as_of="2026-05-05",
                        close_price=100,
                        currency="EUR",
                        pe_ratio=20,
                    )
                )

            report = Advisor(repo).analyze_snapshots(
                "NEDAP",
                FinancialSnapshot(
                    symbol="NEDAP",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=279_800_000,
                    operating_margin=0.117,
                ),
                MarketSnapshot(
                    symbol="NEDAP",
                    as_of="2026-05-05",
                    close_price=55,
                    currency="EUR",
                    pe_ratio=22.9,
                ),
            )

            self.assertIsNone(report.peer_analysis)

    def test_peer_analysis_discovers_local_peers_by_same_theme_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            for symbol, theme in [
                ("CUSTOM_A", "Precision hardware"),
                ("CUSTOM_B", "Precision hardware"),
                ("CUSTOM_C", "Precision hardware"),
                ("CUSTOM_D", "Offshore services"),
            ]:
                repo.upsert_portfolio_classification(
                    PortfolioClassification(symbol=symbol, sector="Industrials", theme=theme)
                )

            for symbol, operating_margin, pe_ratio in [
                ("CUSTOM_B", 0.18, 18),
                ("CUSTOM_C", 0.16, 22),
                ("CUSTOM_D", 0.35, 12),
            ]:
                repo.upsert_financial_snapshot(
                    FinancialSnapshot(
                        symbol=symbol,
                        period_end="2025-12-31",
                        period_type="TTM",
                        revenue=500_000_000,
                        operating_margin=operating_margin,
                        free_cash_flow=50_000_000,
                    )
                )
                repo.upsert_market_snapshot(
                    MarketSnapshot(
                        symbol=symbol,
                        as_of="2026-05-05",
                        close_price=100,
                        currency="EUR",
                        pe_ratio=pe_ratio,
                    )
                )

            refresh_peer_candidates(repo, "CUSTOM_A")

            report = Advisor(repo).analyze_snapshots(
                "CUSTOM_A",
                FinancialSnapshot(
                    symbol="CUSTOM_A",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=600_000_000,
                    operating_margin=0.20,
                    free_cash_flow=60_000_000,
                ),
                MarketSnapshot(
                    symbol="CUSTOM_A",
                    as_of="2026-05-05",
                    close_price=100,
                    currency="EUR",
                    pe_ratio=20,
                ),
            )

            self.assertIsNotNone(report.peer_analysis)
            self.assertEqual(
                [row.symbol for row in report.peer_analysis.rows],
                ["CUSTOM_A", "CUSTOM_B", "CUSTOM_C"],
            )
            self.assertEqual(report.peer_analysis.group_label, "Precision hardware")
            self.assertEqual(report.peer_analysis.available_peer_count, 2)
            self.assertEqual(report.peer_analysis.configured_peer_count, 2)
            self.assertNotIn("CUSTOM_D", [row.symbol for row in report.peer_analysis.rows])

    def test_peer_discovery_uses_generic_theme_seed_list_for_construction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()

            candidates = refresh_peer_candidates(repo, "BAMNB")
            peer_symbols = {candidate.peer_symbol for candidate in candidates}
            sources = {candidate.source for candidate in candidates}
            statuses = {candidate.peer_symbol: candidate.status for candidate in candidates}

            self.assertIn("HEIJMANS", peer_symbols)
            self.assertIn("VINCI", peer_symbols)
            self.assertIn("curated_theme", sources)
            self.assertEqual(statuses["HEIJMANS"], "voorgesteld")
            self.assertNotIn("BAMNB", peer_symbols)

            self.assertTrue(repo.update_peer_candidate_status("BAMNB", "HEIJMANS", "vertrouwd"))
            refresh_peer_candidates(repo, "BAMNB")
            trusted = {
                candidate.peer_symbol: candidate
                for candidate in repo.peer_candidates_for_symbol("BAMNB")
            }
            self.assertEqual(trusted["HEIJMANS"].status, "vertrouwd")
            self.assertEqual(trusted["HEIJMANS"].source, "user_approved")

            self.assertTrue(repo.update_peer_candidate_status("BAMNB", "HEIJMANS", "verworpen"))
            refresh_peer_candidates(repo, "BAMNB")
            rejected = {
                candidate.peer_symbol: candidate
                for candidate in repo.peer_candidates_for_symbol("BAMNB")
            }
            self.assertEqual(rejected["HEIJMANS"].status, "verworpen")
            self.assertEqual(rejected["HEIJMANS"].source, "user_rejected")

    def test_peer_analysis_rejects_alias_and_wrong_curated_group_even_with_stale_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_alias(
                PortfolioAlias(
                    portfolio_symbol="BAMNB",
                    alias_key="BAM",
                    alias_type="analysis_input",
                    raw_value="BAM",
                    source="test",
                )
            )
            for symbol in ["BAMNB", "BAM", "NVIDIA"]:
                repo.upsert_portfolio_classification(
                    PortfolioClassification(symbol=symbol, sector="Industrials", theme="Construction")
                )
            repo.replace_peer_candidates(
                "BAMNB",
                [
                    PeerCandidate(
                        symbol="BAMNB",
                        peer_symbol="BAM",
                        peer_group="Construction",
                        source="stale",
                        confidence=0.9,
                    ),
                    PeerCandidate(
                        symbol="BAMNB",
                        peer_symbol="NVIDIA",
                        peer_group="Construction",
                        source="stale",
                        confidence=0.9,
                    ),
                ],
            )
            peer_snapshots = {}
            for symbol in ["BAM", "NVIDIA"]:
                peer_snapshots[symbol] = (
                    FinancialSnapshot(
                        symbol=symbol,
                        period_end="2025-12-31",
                        period_type="TTM",
                        revenue=1_000_000_000,
                        operating_margin=0.40,
                    ),
                    MarketSnapshot(
                        symbol=symbol,
                        as_of="2026-05-06",
                        close_price=100,
                        currency="EUR",
                        pe_ratio=40,
                    ),
                )

            report = Advisor(repo).analyze_snapshots(
                "BAMNB",
                FinancialSnapshot(
                    symbol="BAMNB",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=7_000_000_000,
                    operating_margin=0.032,
                ),
                MarketSnapshot(
                    symbol="BAMNB",
                    as_of="2026-05-06",
                    close_price=9.45,
                    currency="EUR",
                    pe_ratio=11.8,
                ),
                peer_snapshots=peer_snapshots,
            )

            self.assertIsNone(report.peer_analysis)

    def test_portfolio_fit_matches_existing_position_by_broker_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_position(
                PortfolioPosition(
                    symbol="DSFIR",
                    quantity=200,
                    average_cost=107.89,
                    currency="EUR",
                    account="Test",
                    as_of="2026-05-05",
                )
            )
            repo.upsert_portfolio_price(
                PortfolioPrice(symbol="DSFIR", as_of="2026-05-05", close_price=64.04, currency="EUR")
            )
            repo.upsert_portfolio_classification(
                PortfolioClassification(symbol="DSFIR", sector="Consumer Staples", theme="Health and nutrition")
            )

            report = Advisor(repo).analyze_snapshots(
                "DSM FIRMENICH",
                FinancialSnapshot(
                    symbol="DSM FIRMENICH",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=9_034_000_000,
                ),
                MarketSnapshot(symbol="DSM FIRMENICH", as_of="2026-05-05", close_price=64.04, currency="EUR"),
                data_sources=[
                    DataSource(
                        symbol="DSM FIRMENICH",
                        field_name="close_price",
                        value_label="Slotkoers EUR 64.04",
                        source_name="StockAnalysis quote en koersen",
                        source_url="https://stockanalysis.com/quote/ams/DSFIR/",
                        source_date="2026-05-05",
                        source_quality="marktdata",
                    )
                ],
            )

            self.assertAlmostEqual(report.portfolio_fit.position_value, 12808)
            self.assertEqual(report.portfolio_fit.sector, "Consumer Staples")
            self.assertEqual(report.portfolio_fit.theme, "Health and nutrition")
            self.assertNotIn("Geen bestaande positie", " ".join(report.portfolio_fit.notes))
            self.assertIn("DSFIR", " ".join(report.portfolio_fit.notes))

    def test_analysis_learns_provider_alias_for_imported_broker_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.upsert_portfolio_position(
                PortfolioPosition(
                    symbol="LAM_RESEARCH",
                    quantity=10,
                    average_cost=90,
                    currency="USD",
                    account="Test",
                    as_of="2026-05-05",
                )
            )
            repo.upsert_portfolio_price(
                PortfolioPrice(symbol="LAM_RESEARCH", as_of="2026-05-05", close_price=100, currency="USD")
            )
            repo.upsert_portfolio_alias(
                PortfolioAlias(
                    portfolio_symbol="LAM_RESEARCH",
                    alias_key="LAM_RESEARCH",
                    alias_type="broker_name",
                    raw_value="LAM RESEARCH",
                    source="portfolio_csv",
                )
            )
            data_sources = [
                DataSource(
                    symbol="LAM RESEARCH",
                    field_name="close_price",
                    value_label="Slotkoers USD 100",
                    source_name="StockAnalysis quote en koersen",
                    source_url="https://stockanalysis.com/stocks/lrcx/",
                    source_date="2026-05-05",
                    source_quality="marktdata",
                )
            ]

            first_report = Advisor(repo).analyze_snapshots(
                "LAM RESEARCH",
                FinancialSnapshot(symbol="LAM RESEARCH", period_end="2025-12-31", period_type="TTM", revenue=1),
                MarketSnapshot(symbol="LAM RESEARCH", as_of="2026-05-05", close_price=100, currency="USD"),
                data_sources=data_sources,
            )
            self.assertAlmostEqual(first_report.portfolio_fit.position_value, 1000)
            self.assertEqual(repo.resolve_portfolio_aliases(["LRCX"]), {"LRCX": "LAM_RESEARCH"})

            second_report = Advisor(repo).analyze_snapshots(
                "LRCX",
                FinancialSnapshot(symbol="LRCX", period_end="2025-12-31", period_type="TTM", revenue=1),
                MarketSnapshot(symbol="LRCX", as_of="2026-05-05", close_price=100, currency="USD"),
            )
            self.assertAlmostEqual(second_report.portfolio_fit.position_value, 1000)
            self.assertNotIn("Geen bestaande positie", " ".join(second_report.portfolio_fit.notes))

    def test_transaction_advice_suggests_small_start_position_for_strong_new_idea(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.save_investor_profile(
                InvestorProfile(age=52, annual_income=90000, horizon_years=12, cash_buffer=25000)
            )
            repo.upsert_portfolio_asset(
                PortfolioAsset(asset_type="cash", value=100000, currency="EUR", as_of="2026-05-05")
            )

            report = Advisor(repo).analyze_snapshots(
                "NEW",
                FinancialSnapshot(
                    symbol="NEW",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=1_000_000_000,
                    operating_margin=0.25,
                    net_margin=0.18,
                    free_cash_flow=150_000_000,
                    debt=50_000_000,
                    cash=80_000_000,
                ),
                MarketSnapshot(
                    symbol="NEW",
                    as_of="2026-05-05",
                    close_price=50,
                    currency="EUR",
                    pe_ratio=15,
                    ev_ebitda=7,
                    fcf_yield=0.08,
                    momentum_12m=0.10,
                    volatility_1y=0.20,
                ),
            )

            self.assertEqual(report.portfolio_fit.transaction_action, "kleine_startpositie")
            self.assertEqual(report.portfolio_fit.transaction_label, "Kleine startpositie")
            self.assertEqual(report.portfolio_fit.max_new_buy_amount, 5000)
            self.assertEqual(report.portfolio_fit.practical_buy_amount, 5000)
            self.assertTrue(any("Beschikbare beleggingscash" in line for line in report.portfolio_fit.buy_room_calculation))
            self.assertTrue(any("Kleine startpositie" in line for line in report.portfolio_fit.transaction_rationale))
            self.assertTrue(any("cashbuffer" in line for line in report.portfolio_fit.transaction_rationale))
            self.assertTrue(any("totaal vermogen" in line for line in report.portfolio_fit.transaction_rationale))

    def test_buy_room_is_capped_by_cash_above_buffer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.save_investor_profile(
                InvestorProfile(age=52, annual_income=90000, horizon_years=12, cash_buffer=20000)
            )
            repo.upsert_portfolio_asset(
                PortfolioAsset(asset_type="cash", value=40000, currency="EUR", as_of="2026-05-05")
            )
            repo.upsert_portfolio_asset(
                PortfolioAsset(asset_type="house", value=1_000_000, currency="EUR", as_of="2026-05-05")
            )

            report = Advisor(repo).analyze_snapshots(
                "CASHCAP",
                FinancialSnapshot(
                    symbol="CASHCAP",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=1_000_000_000,
                    operating_margin=0.25,
                    net_margin=0.18,
                    free_cash_flow=150_000_000,
                    debt=50_000_000,
                    cash=80_000_000,
                ),
                MarketSnapshot(
                    symbol="CASHCAP",
                    as_of="2026-05-05",
                    close_price=50,
                    currency="EUR",
                    pe_ratio=15,
                    ev_ebitda=7,
                    fcf_yield=0.08,
                    momentum_12m=0.10,
                    volatility_1y=0.20,
                ),
            )

            self.assertEqual(report.portfolio_fit.position_room, 52000)
            self.assertEqual(report.portfolio_fit.available_cash, 20000)
            self.assertEqual(report.portfolio_fit.max_new_buy_amount, 20000)
            self.assertEqual(report.portfolio_fit.practical_buy_amount, 20000)

    def test_transaction_advice_suggests_selling_weak_existing_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite")
            repo.init()
            repo.save_investor_profile(
                InvestorProfile(age=52, annual_income=90000, horizon_years=12, cash_buffer=25000)
            )
            repo.upsert_portfolio_asset(
                PortfolioAsset(asset_type="cash", value=100000, currency="EUR", as_of="2026-05-05")
            )
            repo.upsert_portfolio_position(
                PortfolioPosition(
                    symbol="WEAK",
                    quantity=100,
                    average_cost=20,
                    currency="EUR",
                    account="Test",
                    as_of="2026-05-05",
                )
            )

            report = Advisor(repo).analyze_snapshots(
                "WEAK",
                FinancialSnapshot(
                    symbol="WEAK",
                    period_end="2025-12-31",
                    period_type="TTM",
                    revenue=1_000_000_000,
                    operating_margin=-0.05,
                    net_margin=-0.10,
                    free_cash_flow=-50_000_000,
                    debt=500_000_000,
                ),
                MarketSnapshot(
                    symbol="WEAK",
                    as_of="2026-05-05",
                    close_price=15,
                    currency="EUR",
                    pe_ratio=40,
                    ev_ebitda=24,
                    fcf_yield=-0.02,
                    momentum_12m=-0.30,
                    volatility_1y=0.45,
                ),
            )

            self.assertEqual(report.portfolio_fit.transaction_action, "verkopen")
            self.assertEqual(report.portfolio_fit.transaction_label, "Verkopen")


if __name__ == "__main__":
    unittest.main()
