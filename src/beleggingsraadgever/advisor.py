"""Advice report generation."""

from __future__ import annotations

from typing import List

from .indicators import build_score, conviction_from_score, verdict_from_score
from .models import AdviceReport, FinancialSnapshot, KnowledgeHit, MarketSnapshot
from .storage import SQLiteRepository


class Advisor:
    def __init__(self, repository: SQLiteRepository) -> None:
        self.repository = repository

    def analyze(self, symbol: str) -> AdviceReport:
        normalized_symbol = symbol.upper()
        financial = self.repository.latest_financial_snapshot(normalized_symbol)
        market = self.repository.latest_market_snapshot(normalized_symbol)
        score = build_score(financial, market)
        verdict = verdict_from_score(score)
        conviction = conviction_from_score(score)
        evidence = self._retrieve_evidence(normalized_symbol, financial, market)

        summary = self._build_summary(normalized_symbol, financial, market, verdict, score)
        data_freshness = {
            "koersdata": market.as_of,
            "fundamentals": f"{financial.period_type} t/m {financial.period_end}",
            "kennisbank": "lokale index",
        }

        assumptions = [
            "Analyse gebruikt end-of-day data, geen intraday prijzen.",
            "Scores zijn v1-regels en vervangen nog geen definitief oordeel.",
            "Portefeuillefit wordt in een volgende stap verdiept met jouw actuele vermogensverdeling.",
        ]

        return AdviceReport(
            symbol=normalized_symbol,
            verdict=verdict,
            conviction=conviction,
            score=score,
            summary=summary,
            evidence=evidence,
            data_freshness=data_freshness,
            assumptions=assumptions,
        )

    def render_markdown(self, report: AdviceReport) -> str:
        lines: List[str] = [
            f"# Adviesrapport: {report.symbol}",
            "",
            f"**Advies:** {report.verdict}",
            f"**Overtuiging:** {report.conviction}",
            f"**Totaalscore:** {report.score.total}/100",
            "",
            "## Samenvatting",
            "",
            report.summary,
            "",
            "## Scorekaart",
            "",
            f"- Bedrijfskwaliteit: {report.score.quality}/100",
            f"- Waardering: {report.score.valuation}/100",
            f"- Momentum: {report.score.momentum}/100",
            f"- Risico: {report.score.risk}/100",
            "",
        ]

        if report.score.flags:
            lines.extend(["## Risicosignalen", ""])
            lines.extend(f"- {flag}" for flag in report.score.flags)
            lines.append("")

        lines.extend(["## Relevante kennisbank-fragmenten", ""])
        if report.evidence:
            for hit in report.evidence:
                date = f", {hit.publication_date}" if hit.publication_date else ""
                excerpt = hit.chunk.text[:320].strip()
                if len(hit.chunk.text) > 320:
                    excerpt += "..."
                lines.extend(
                    [
                        f"- {hit.title} ({hit.source_type}{date}, score {hit.score:.2f})",
                        f"  {excerpt}",
                    ]
                )
        else:
            lines.append("- Geen relevante fragmenten gevonden in de lokale kennisbank.")

        lines.extend(["", "## Dataversheid", ""])
        lines.extend(f"- {name}: {value}" for name, value in report.data_freshness.items())

        if report.score.details:
            lines.extend(["", "## Score-uitleg", ""])
            labels = {
                "quality": "Bedrijfskwaliteit",
                "valuation": "Waardering",
                "momentum": "Momentum",
                "risk": "Risico",
                "total": "Totaalscore",
            }
            for key in ("quality", "valuation", "momentum", "risk", "total"):
                details = report.score.details.get(key, [])
                if not details:
                    continue
                lines.extend([f"### {labels[key]}", ""])
                lines.extend(f"- {detail}" for detail in details)
                lines.append("")

        lines.extend(["", "## Aannames", ""])
        lines.extend(f"- {assumption}" for assumption in report.assumptions)
        lines.append("")

        return "\n".join(lines)

    def _retrieve_evidence(
        self,
        symbol: str,
        financial: FinancialSnapshot,
        market: MarketSnapshot,
    ) -> List[KnowledgeHit]:
        query_parts = [
            symbol,
            "waardering marge vrije kasstroom schuld dividend buybacks risico kwaliteit",
        ]
        if market.dividend_yield and market.dividend_yield > 0.04:
            query_parts.append("dividendrendement dividendvalkuil houdbaarheid")
        if market.pe_ratio and market.pe_ratio > 25:
            query_parts.append("kwaliteit groeiaandelen hoge multiple waardering")
        if financial.free_cash_flow and financial.revenue and financial.free_cash_flow / financial.revenue > 0.10:
            query_parts.append("sterke vrije kasstroom kapitaalallocatie")

        return self.repository.search_knowledge(" ".join(query_parts), limit=5)

    @staticmethod
    def _build_summary(
        symbol: str,
        financial: FinancialSnapshot,
        market: MarketSnapshot,
        verdict: str,
        score,
    ) -> str:
        fcf_margin = None
        if financial.free_cash_flow is not None and financial.revenue:
            fcf_margin = financial.free_cash_flow / financial.revenue

        parts = [
            f"{symbol} krijgt in deze v1-analyse het oordeel '{verdict}'.",
            f"De score wordt vooral gedragen door kwaliteit {score.quality}/100 en waardering {score.valuation}/100.",
        ]
        if financial.operating_margin is not None:
            parts.append(f"De operationele marge staat op {financial.operating_margin:.1%}.")
        if fcf_margin is not None:
            parts.append(f"De vrije kasstroommarge staat op {fcf_margin:.1%}.")
        if market.pe_ratio is not None:
            parts.append(f"De koers-winstverhouding is {market.pe_ratio:.1f}.")
        if score.flags:
            parts.append("Belangrijkste aandachtspunt: " + "; ".join(score.flags) + ".")
        return " ".join(parts)
