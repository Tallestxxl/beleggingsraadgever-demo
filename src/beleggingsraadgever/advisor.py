"""Advice report generation."""

from __future__ import annotations

from typing import List, Optional

from .indicators import build_score, conviction_from_score, verdict_from_score
from .models import AdviceReport, DataSource, FinancialSnapshot, KnowledgeHit, MarketSnapshot, PortfolioFit
from .storage import SQLiteRepository


class Advisor:
    def __init__(self, repository: SQLiteRepository) -> None:
        self.repository = repository

    def analyze(self, symbol: str) -> AdviceReport:
        normalized_symbol = symbol.upper()
        financial = self.repository.latest_financial_snapshot(normalized_symbol)
        market = self.repository.latest_market_snapshot(normalized_symbol)
        return self.analyze_snapshots(normalized_symbol, financial, market)

    def analyze_snapshots(
        self,
        symbol: str,
        financial: FinancialSnapshot,
        market: MarketSnapshot,
        *,
        data_sources: Optional[List[DataSource]] = None,
        evidence: Optional[List[KnowledgeHit]] = None,
        extra_assumptions: Optional[List[str]] = None,
        knowledge_label: str = "lokale index",
    ) -> AdviceReport:
        normalized_symbol = symbol.upper()
        score = build_score(financial, market)
        verdict = verdict_from_score(score)
        conviction = conviction_from_score(score)
        evidence = evidence if evidence is not None else self._retrieve_evidence(normalized_symbol, financial, market)
        data_sources = (
            data_sources if data_sources is not None else self.repository.data_sources_for_symbol(normalized_symbol)
        )
        portfolio_fit = self._build_portfolio_fit(normalized_symbol, market, score)

        summary = self._build_summary(normalized_symbol, financial, market, verdict, score)
        data_freshness = {
            "koersdata": market.as_of,
            "fundamentals": f"{financial.period_type} t/m {financial.period_end}",
            "kennisbank": knowledge_label,
        }

        assumptions = [
            "Analyse gebruikt end-of-day data, geen intraday prijzen.",
            "Scores zijn v1-regels en vervangen nog geen definitief oordeel.",
            "Portefeuillefit gebruikt handmatig ingevoerde posities en vermogenscategorieën.",
        ]
        if extra_assumptions:
            assumptions = extra_assumptions + assumptions

        return AdviceReport(
            symbol=normalized_symbol,
            verdict=verdict,
            conviction=conviction,
            score=score,
            summary=summary,
            evidence=evidence,
            data_freshness=data_freshness,
            assumptions=assumptions,
            data_sources=data_sources,
            portfolio_fit=portfolio_fit,
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

        if report.data_sources:
            lines.extend(["", "## Bronvermelding per cijfer", ""])
            for source in report.data_sources:
                note = f" - {source.note}" if source.note else ""
                lines.append(
                    f"- {source.field_name}: {source.value_label} | "
                    f"{source.source_name} ({source.source_date}, {source.source_quality}){note}"
                )

        if report.portfolio_fit:
            fit = report.portfolio_fit
            lines.extend(["", "## Portefeuillefit", ""])
            lines.append(fit.summary)
            lines.extend(
                [
                    f"- Huidige waarde positie: EUR {fit.position_value:,.0f}",
                    f"- Gewicht positie: {fit.position_weight:.1%}",
                    f"- Richtmaximum: {fit.max_weight:.1%}",
                    f"- Ruimte tot richtmaximum: EUR {fit.room_to_max:,.0f}",
                ]
            )
            lines.extend(f"- {note}" for note in fit.notes)

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

    def _build_portfolio_fit(self, symbol: str, market: MarketSnapshot, score) -> PortfolioFit:
        profile = self.repository.investor_profile()
        positions = self.repository.latest_portfolio_positions()
        assets = self.repository.portfolio_assets()
        asset_value = sum(asset.value for asset in assets)

        position_values: dict[str, float] = {}
        for position in positions:
            value = position.quantity * position.average_cost
            portfolio_price = self.repository.latest_portfolio_price(position.symbol)
            if portfolio_price is not None:
                value = position.quantity * portfolio_price.close_price
            else:
                try:
                    value = position.quantity * self.repository.latest_market_snapshot(position.symbol).close_price
                except LookupError:
                    pass
            position_values[position.symbol.upper()] = position_values.get(position.symbol.upper(), 0.0) + value

        target_value = position_values.get(symbol.upper(), 0.0)
        if target_value == 0 and any(position.symbol.upper() == symbol.upper() for position in positions):
            target_value = market.close_price * sum(
                position.quantity for position in positions if position.symbol.upper() == symbol.upper()
            )

        total_wealth = asset_value + sum(position_values.values())
        risk_profile = profile.risk_profile if profile else "gebalanceerd"
        max_weight = {"defensief": 0.03, "gebalanceerd": 0.05, "offensief": 0.07}.get(risk_profile, 0.05)
        position_weight = target_value / total_wealth if total_wealth else 0.0
        room_to_max = max(0.0, (total_wealth * max_weight) - target_value) if total_wealth else 0.0

        notes: List[str] = []
        if profile is None:
            notes.append("Profiel ontbreekt nog; vul leeftijd, inkomen, horizon en risicoprofiel aan voor scherpere limieten.")
        elif profile.horizon_years is not None and profile.horizon_years < 5:
            notes.append("Beleggingshorizon is korter dan 5 jaar; wees voorzichtig met cyclische of volatiele posities.")
        if not positions and not assets:
            notes.append("Portefeuille ontbreekt nog; voer posities en overige vermogenscategorieën in.")
        if target_value == 0:
            notes.append(f"Geen bestaande positie in {symbol}; dit aandeel zou een nieuwe positie zijn.")
        if position_weight > max_weight:
            notes.append("Huidig gewicht ligt boven het richtmaximum; bijkopen ligt niet voor de hand.")
        elif total_wealth:
            notes.append(f"Resterende ruimte tot het richtmaximum is circa EUR {room_to_max:,.0f}.")
        if score.total < 60:
            notes.append("De aandelenscore is lager dan 60; behandel eventuele koopruimte als onderzoeksruimte, niet als koopsignaal.")
        if score.flags:
            notes.append("Risicosignalen in de analyse verlagen de praktische overtuiging.")

        if not total_wealth:
            summary = "Portefeuillefit is nog niet bepaalbaar omdat profiel en portefeuille ontbreken."
        elif position_weight > max_weight:
            summary = f"{symbol} is al groter dan het richtmaximum voor een {risk_profile} profiel."
        elif target_value == 0:
            summary = f"{symbol} past alleen als kleine startpositie binnen het huidige {risk_profile} profiel."
        else:
            summary = f"{symbol} blijft binnen het richtmaximum voor een {risk_profile} profiel."

        return PortfolioFit(
            summary=summary,
            position_value=target_value,
            position_weight=position_weight,
            max_weight=max_weight,
            room_to_max=room_to_max,
            total_wealth=total_wealth,
            notes=notes,
        )

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
