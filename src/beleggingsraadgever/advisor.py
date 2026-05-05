"""Advice report generation."""

from __future__ import annotations

from typing import List, Optional

from .identity import aliases_for_data_sources, candidate_portfolio_symbols
from .indicators import build_score, conviction_from_score, verdict_from_score
from .models import AdviceReport, DataSource, FinancialSnapshot, KnowledgeHit, MarketSnapshot, PortfolioFit
from .portfolio import effective_classification, exposure_buckets, portfolio_position_exposures
from .storage import SQLiteRepository


SECTOR_WARNING_THRESHOLD = 0.20
THEME_WARNING_THRESHOLD = 0.25

TRANSACTION_LABELS = {
    "niet_kopen": "Niet kopen",
    "watchlist": "Watchlist",
    "kleine_startpositie": "Kleine startpositie",
    "bijkopen_tot_max": "Bijkopen tot max",
    "afbouwen": "Afbouwen",
    "verkopen": "Verkopen",
}


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
        portfolio_fit = self._build_portfolio_fit(normalized_symbol, market, score, data_sources=data_sources)

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
                    f"- Maximale nieuwe koopruimte: EUR {fit.max_new_buy_amount:,.0f}",
                    f"- Praktische koopruimte: EUR {fit.practical_buy_amount:,.0f}",
                ]
            )
            if fit.sector != "Onbekend":
                lines.append(f"- Sector {fit.sector}: {fit.sector_weight:.1%} van effecten")
            if fit.theme != "Onbekend":
                lines.append(f"- Thema {fit.theme}: {fit.theme_weight:.1%} van effecten")
            if fit.sector == "Onbekend" and fit.theme == "Onbekend":
                lines.append("- Sector/thema: nog niet geclassificeerd.")
            lines.append(f"- Transactieadvies: {fit.transaction_label}")
            if fit.transaction_rationale:
                lines.extend(f"- Waarom dit transactieadvies: {line}" for line in fit.transaction_rationale)
            if fit.buy_room_calculation:
                lines.extend(f"- Berekening koopruimte: {line}" for line in fit.buy_room_calculation)
            if fit.buy_room_limits:
                lines.extend(f"- Beperking koopruimte: {line}" for line in fit.buy_room_limits)
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

    def _build_portfolio_fit(
        self,
        symbol: str,
        market: MarketSnapshot,
        score,
        *,
        data_sources: Optional[List[DataSource]] = None,
    ) -> PortfolioFit:
        profile = self.repository.investor_profile()
        exposures = portfolio_position_exposures(self.repository)
        assets = self.repository.portfolio_assets()
        asset_value = sum(asset.value for asset in assets)
        cash_value = next((asset.value for asset in assets if asset.asset_type == "cash"), None)
        cash_buffer = profile.cash_buffer if profile and profile.cash_buffer is not None else None
        symbol_candidates = candidate_portfolio_symbols(symbol, data_sources or [])
        resolved_aliases = self.repository.resolve_portfolio_aliases(symbol_candidates)
        for resolved_symbol in resolved_aliases.values():
            if resolved_symbol not in symbol_candidates:
                symbol_candidates.append(resolved_symbol)

        position_values: dict[str, float] = {}
        for exposure in exposures:
            symbol_key = exposure.position.symbol.upper()
            position_values[symbol_key] = position_values.get(symbol_key, 0.0) + exposure.market_value

        matched_symbols = [candidate for candidate in symbol_candidates if candidate in position_values]
        target_value = sum(position_values[candidate] for candidate in matched_symbols)
        target_positions = [
            exposure for exposure in exposures if exposure.position.symbol.upper() in matched_symbols
        ]
        if len(matched_symbols) == 1:
            matched_symbol = matched_symbols[0]
            self.repository.upsert_portfolio_aliases(
                aliases_for_data_sources(matched_symbol, data_sources or [], source="analysis")
            )
        if target_value == 0 and target_positions:
            target_value = market.close_price * sum(
                exposure.position.quantity for exposure in target_positions
            )

        total_wealth = asset_value + sum(position_values.values())
        classification_symbol = _classification_symbol(self.repository, symbol_candidates, matched_symbols, symbol)
        classification = effective_classification(self.repository, classification_symbol)
        sector_buckets = exposure_buckets(exposures, by="sector", total_wealth=total_wealth)
        theme_buckets = exposure_buckets(exposures, by="theme", total_wealth=total_wealth)
        sector_bucket = next((bucket for bucket in sector_buckets if bucket.label == classification.sector), None)
        theme_bucket = next((bucket for bucket in theme_buckets if bucket.label == classification.theme), None)
        sector_value = sector_bucket.value if sector_bucket else 0.0
        sector_weight = sector_bucket.securities_weight if sector_bucket else 0.0
        theme_value = theme_bucket.value if theme_bucket else 0.0
        theme_weight = theme_bucket.securities_weight if theme_bucket else 0.0
        risk_profile = profile.risk_profile if profile else "gebalanceerd"
        max_weight = {"defensief": 0.03, "gebalanceerd": 0.05, "offensief": 0.07}.get(risk_profile, 0.05)
        position_weight = target_value / total_wealth if total_wealth else 0.0
        position_room = max(0.0, (total_wealth * max_weight) - target_value) if total_wealth else 0.0
        room_to_max = position_room
        available_cash = (
            max(0.0, cash_value - cash_buffer)
            if cash_value is not None and cash_buffer is not None
            else None
        )

        notes: List[str] = []
        if profile is None:
            notes.append("Profiel ontbreekt nog; vul leeftijd, inkomen, horizon en risicoprofiel aan voor scherpere limieten.")
        elif profile.horizon_years is not None and profile.horizon_years < 5:
            notes.append("Beleggingshorizon is korter dan 5 jaar; wees voorzichtig met cyclische of volatiele posities.")
        if not exposures and not assets:
            notes.append("Portefeuille ontbreekt nog; voer posities en overige vermogenscategorieën in.")
        if target_value == 0:
            notes.append(f"Geen bestaande positie in {symbol}; dit aandeel zou een nieuwe positie zijn.")
        elif matched_symbols and symbol.upper() not in matched_symbols:
            notes.append(f"Bestaande positie gevonden via portefeuillesymbool {', '.join(matched_symbols)}.")
        if position_weight > max_weight:
            notes.append("Huidig gewicht ligt boven het richtmaximum; bijkopen ligt niet voor de hand.")
        elif total_wealth:
            notes.append(f"Resterende ruimte tot het richtmaximum is circa EUR {room_to_max:,.0f}.")
        if score.total < 60:
            notes.append("De aandelenscore is lager dan 60; behandel eventuele koopruimte als onderzoeksruimte, niet als koopsignaal.")
        if score.flags:
            notes.append("Risicosignalen in de analyse verlagen de praktische overtuiging.")
        if classification.sector != "Onbekend" and sector_weight >= SECTOR_WARNING_THRESHOLD:
            notes.append(
                f"Sectorconcentratie: {classification.sector} is al {sector_weight:.1%} van de effectenportefeuille."
            )
        if classification.theme != "Onbekend" and theme_weight >= THEME_WARNING_THRESHOLD:
            notes.append(f"Themaconcentratie: {classification.theme} is al {theme_weight:.1%} van de effectenportefeuille.")

        if not total_wealth:
            summary = "Portefeuillefit is nog niet bepaalbaar omdat profiel en portefeuille ontbreken."
        elif classification.sector != "Onbekend" and sector_weight >= SECTOR_WARNING_THRESHOLD:
            summary = f"{symbol} vraagt voorzichtigheid door bestaande {classification.sector}-concentratie."
        elif position_weight > max_weight:
            summary = f"{symbol} is al groter dan het richtmaximum voor een {risk_profile} profiel."
        elif target_value == 0:
            summary = f"{symbol} past alleen als kleine startpositie binnen het huidige {risk_profile} profiel."
        else:
            summary = f"{symbol} blijft binnen het richtmaximum voor een {risk_profile} profiel."

        transaction_action = _transaction_action(
            score_total=score.total,
            has_position=target_value > 0,
            position_weight=position_weight,
            max_weight=max_weight,
            sector_concentrated=classification.sector != "Onbekend" and sector_weight >= SECTOR_WARNING_THRESHOLD,
            theme_concentrated=classification.theme != "Onbekend" and theme_weight >= THEME_WARNING_THRESHOLD,
            total_wealth=total_wealth,
        )
        buy_room = _buy_room(
            score_total=score.total,
            transaction_action=transaction_action,
            total_wealth=total_wealth,
            target_value=target_value,
            max_weight=max_weight,
            position_room=position_room,
            cash_value=cash_value,
            cash_buffer=cash_buffer,
            available_cash=available_cash,
            sector_name=classification.sector,
            sector_concentrated=classification.sector != "Onbekend" and sector_weight >= SECTOR_WARNING_THRESHOLD,
            theme_name=classification.theme,
            theme_concentrated=classification.theme != "Onbekend" and theme_weight >= THEME_WARNING_THRESHOLD,
        )
        transaction_rationale = _transaction_rationale(
            transaction_label=TRANSACTION_LABELS[transaction_action],
            score_total=score.total,
            risk_score=score.risk,
            target_value=target_value,
            position_weight=position_weight,
            risk_profile=risk_profile,
            max_weight=max_weight,
            total_wealth=total_wealth,
            sector_name=classification.sector,
            sector_weight=sector_weight,
            theme_name=classification.theme,
            theme_weight=theme_weight,
            cash_value=cash_value,
            cash_buffer=cash_buffer,
            available_cash=available_cash,
            max_new_buy_amount=buy_room["max_new_buy_amount"],
            practical_buy_amount=buy_room["practical_buy_amount"],
            buy_room_limits=buy_room["limits"],
        )

        return PortfolioFit(
            summary=summary,
            position_value=target_value,
            position_weight=position_weight,
            max_weight=max_weight,
            room_to_max=room_to_max,
            total_wealth=total_wealth,
            transaction_action=transaction_action,
            transaction_label=TRANSACTION_LABELS[transaction_action],
            position_room=position_room,
            cash_value=cash_value,
            cash_buffer=cash_buffer,
            available_cash=available_cash,
            max_new_buy_amount=buy_room["max_new_buy_amount"],
            practical_buy_amount=buy_room["practical_buy_amount"],
            buy_room_factor=buy_room["buy_room_factor"],
            sector=classification.sector,
            sector_value=sector_value,
            sector_weight=sector_weight,
            theme=classification.theme,
            theme_value=theme_value,
            theme_weight=theme_weight,
            buy_room_limits=buy_room["limits"],
            buy_room_calculation=buy_room["calculation"],
            transaction_rationale=transaction_rationale,
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


def _transaction_action(
    *,
    score_total: float,
    has_position: bool,
    position_weight: float,
    max_weight: float,
    sector_concentrated: bool,
    theme_concentrated: bool,
    total_wealth: float,
) -> str:
    if total_wealth <= 0:
        return "watchlist"
    if score_total < 45:
        return "verkopen" if has_position else "niet_kopen"
    if score_total < 60:
        return "afbouwen" if has_position else "niet_kopen"
    if score_total < 70:
        return "watchlist"
    if has_position and position_weight > max_weight:
        return "afbouwen"
    if sector_concentrated or theme_concentrated:
        return "watchlist"
    if has_position:
        return "bijkopen_tot_max"
    return "kleine_startpositie"


def _classification_symbol(
    repository: SQLiteRepository,
    symbol_candidates: list[str],
    matched_symbols: list[str],
    fallback_symbol: str,
) -> str:
    for candidate in matched_symbols + symbol_candidates:
        stored = repository.portfolio_classification(candidate)
        if stored is not None and (stored.sector != "Onbekend" or stored.theme != "Onbekend"):
            return candidate
    return fallback_symbol


def _transaction_rationale(
    *,
    transaction_label: str,
    score_total: float,
    risk_score: float,
    target_value: float,
    position_weight: float,
    risk_profile: str,
    max_weight: float,
    total_wealth: float,
    sector_name: str,
    sector_weight: float,
    theme_name: str,
    theme_weight: float,
    cash_value: Optional[float],
    cash_buffer: Optional[float],
    available_cash: Optional[float],
    max_new_buy_amount: float,
    practical_buy_amount: float,
    buy_room_limits: List[str],
) -> List[str]:
    lines = [
        f"{transaction_label}: totaalscore {score_total:.1f}/100 en risicoscore {risk_score:.1f}/100.",
    ]
    if target_value > 0:
        lines.append(
            f"Huidige positie {_format_eur_plain(target_value)} ({position_weight:.1%} van totaal vermogen); "
            f"richtmaximum bij {risk_profile} profiel is {max_weight:.1%}."
        )
    else:
        lines.append(
            f"Geen bestaande positie; richtmaximum bij {risk_profile} profiel is {max_weight:.1%} "
            f"van totaal vermogen {_format_eur_plain(total_wealth)}."
        )

    exposure_parts = []
    if sector_name != "Onbekend":
        exposure_parts.append(f"sector {sector_name} {sector_weight:.1%}")
    if theme_name != "Onbekend":
        exposure_parts.append(f"thema {theme_name} {theme_weight:.1%}")
    if exposure_parts:
        lines.append("Exposure binnen effecten: " + ", ".join(exposure_parts) + ".")
    else:
        lines.append("Sector/thema-exposure is nog onbekend.")

    if available_cash is not None and cash_value is not None and cash_buffer is not None:
        lines.append(
            f"Beschikbare beleggingscash {_format_eur_plain(available_cash)} "
            f"na cashbuffer {_format_eur_plain(cash_buffer)}; totaal vermogen {_format_eur_plain(total_wealth)}."
        )
    else:
        lines.append(
            f"Totaal vermogen {_format_eur_plain(total_wealth)}; cashbuffer of cashpositie ontbreekt nog."
        )

    if practical_buy_amount < max_new_buy_amount:
        limiting_text = " ".join(buy_room_limits[:3])
        lines.append(
            f"Maximale koopruimte {_format_eur_plain(max_new_buy_amount)}, praktisch "
            f"{_format_eur_plain(practical_buy_amount)} door: {limiting_text}"
        )
    else:
        lines.append(
            f"Praktische koopruimte {_format_eur_plain(practical_buy_amount)} "
            f"binnen maximale koopruimte {_format_eur_plain(max_new_buy_amount)}."
        )
    return lines


def _buy_room(
    *,
    score_total: float,
    transaction_action: str,
    total_wealth: float,
    target_value: float,
    max_weight: float,
    position_room: float,
    cash_value: Optional[float],
    cash_buffer: Optional[float],
    available_cash: Optional[float],
    sector_name: str,
    sector_concentrated: bool,
    theme_name: str,
    theme_concentrated: bool,
) -> dict:
    max_new_buy_amount = min(position_room, available_cash) if available_cash is not None else position_room
    factor = _score_buy_factor(score_total)
    limits: List[str] = [_score_buy_factor_label(score_total)]

    if transaction_action in {"niet_kopen", "verkopen", "afbouwen"}:
        factor = 0.0
        limits.append(f"Transactieadvies {TRANSACTION_LABELS[transaction_action]}: praktische koopruimte op EUR 0.")
    if sector_concentrated:
        factor *= 0.5
        limits.append(f"Sectorconcentratie {sector_name} boven {SECTOR_WARNING_THRESHOLD:.0%}: 50% rem.")
    if theme_concentrated:
        factor *= 0.5
        limits.append(f"Themaconcentratie {theme_name} boven {THEME_WARNING_THRESHOLD:.0%}: 50% rem.")
    if available_cash is not None and available_cash <= 0:
        factor = 0.0
        limits.append("Geen beschikbare beleggingscash boven de gewenste cashbuffer.")

    practical_buy_amount = max_new_buy_amount * factor
    calculation = [
        (
            "Positieruimte = totaal vermogen "
            f"{_format_eur_plain(total_wealth)} × richtmaximum {max_weight:.1%} "
            f"- huidige positie {_format_eur_plain(target_value)} = {_format_eur_plain(position_room)}."
        )
    ]
    if available_cash is not None and cash_value is not None and cash_buffer is not None:
        calculation.append(
            "Beschikbare beleggingscash = cash/spaargeld "
            f"{_format_eur_plain(cash_value)} - gewenste cashbuffer {_format_eur_plain(cash_buffer)} "
            f"= {_format_eur_plain(available_cash)}."
        )
        calculation.append(
            "Maximale nieuwe koopruimte = min(positieruimte "
            f"{_format_eur_plain(position_room)}, beschikbare cash {_format_eur_plain(available_cash)}) "
            f"= {_format_eur_plain(max_new_buy_amount)}."
        )
    else:
        calculation.append(
            "Cash en/of gewenste cashbuffer ontbreken; maximale nieuwe koopruimte volgt voorlopig alleen uit positieruimte."
        )
        calculation.append(f"Maximale nieuwe koopruimte = {_format_eur_plain(max_new_buy_amount)}.")
    calculation.append(
        f"Praktische koopruimte = {_format_eur_plain(max_new_buy_amount)} × {factor:.0%} "
        f"= {_format_eur_plain(practical_buy_amount)}."
    )

    return {
        "max_new_buy_amount": round(max_new_buy_amount, 2),
        "practical_buy_amount": round(practical_buy_amount, 2),
        "buy_room_factor": round(factor, 4),
        "limits": limits,
        "calculation": calculation,
    }


def _score_buy_factor(score_total: float) -> float:
    if score_total < 60:
        return 0.0
    if score_total < 70:
        return 0.25
    if score_total < 78:
        return 0.5
    return 1.0


def _score_buy_factor_label(score_total: float) -> str:
    if score_total < 60:
        return f"Score {score_total:.1f} lager dan 60: 0% koopruimte."
    if score_total < 70:
        return f"Score {score_total:.1f} tussen 60 en 70: 25% van de maximale koopruimte."
    if score_total < 78:
        return f"Score {score_total:.1f} tussen 70 en 78: 50% van de maximale koopruimte."
    return f"Score {score_total:.1f} vanaf 78: 100% van de maximale koopruimte."


def _format_eur_plain(value: Optional[float]) -> str:
    if value is None:
        return "EUR 0"
    return f"EUR {value:,.0f}".replace(",", ".")
