"""Advice report generation."""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from .formatting import format_currency
from .identity import aliases_for_data_sources, candidate_portfolio_symbols, normalize_symbol
from .indicators import build_score, conviction_from_score, verdict_from_score
from .knowledge_scope import knowledge_scope_from_tags, scope_matches_analysis
from .models import (
    AdviceReport,
    DataSource,
    EvidenceDiagnostics,
    FinancialSnapshot,
    KnowledgeHit,
    MarketSnapshot,
    PortfolioFit,
    SellCandidate,
)
from .peers import SnapshotPair, build_peer_analysis
from .portfolio import (
    PositionExposure,
    effective_classification,
    exposure_buckets,
    portfolio_assets_net_value,
    portfolio_position_exposures,
)
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

    def analyze(self, symbol: str, *, peer_snapshots: Optional[dict[str, SnapshotPair]] = None) -> AdviceReport:
        normalized_symbol = symbol.upper()
        financial = self.repository.latest_financial_snapshot(normalized_symbol)
        market = self.repository.latest_market_snapshot(normalized_symbol)
        return self.analyze_snapshots(normalized_symbol, financial, market, peer_snapshots=peer_snapshots)

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
        peer_snapshots: Optional[dict[str, SnapshotPair]] = None,
    ) -> AdviceReport:
        normalized_symbol = symbol.upper()
        score = build_score(financial, market)
        verdict = verdict_from_score(score)
        conviction = conviction_from_score(score)
        evidence_diagnostics = None
        if evidence is None:
            evidence, evidence_diagnostics = self._retrieve_evidence(normalized_symbol, financial, market)
        data_sources = (
            data_sources if data_sources is not None else self.repository.data_sources_for_symbol(normalized_symbol)
        )
        portfolio_fit = self._build_portfolio_fit(normalized_symbol, market, score, data_sources=data_sources)
        peer_analysis = build_peer_analysis(
            self.repository,
            normalized_symbol,
            financial,
            market,
            extra_snapshots=peer_snapshots,
        )

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
            peer_analysis=peer_analysis,
            evidence_diagnostics=evidence_diagnostics,
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

        if report.peer_analysis:
            lines.extend(["## Peeranalyse", "", report.peer_analysis.summary, ""])
            lines.append(
                f"- Peerbeschikbaarheid: {report.peer_analysis.available_peer_count} van "
                f"{report.peer_analysis.configured_peer_count} peers beschikbaar; maximaal "
                f"{report.peer_analysis.max_peer_count} peers getoond."
            )
            for row in report.peer_analysis.rows:
                target = " (doel)" if row.is_target else ""
                lines.append(
                    f"- {row.symbol}{target}: kwaliteit {row.quality_score:.1f}, "
                    f"waardering {row.valuation_score:.1f}, "
                    f"op. marge {_format_percent_plain(row.operating_margin)}, "
                    f"K/W {_format_number_plain(row.pe_ratio)}, "
                    f"FCF-yield {_format_percent_plain(row.fcf_yield)}"
                )
            lines.extend(f"- {note}" for note in report.peer_analysis.notes)
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
                    f"- Huidige waarde positie: {_format_eur_plain(fit.position_value)}",
                    f"- Gewicht positie: {fit.position_weight:.1%}",
                    f"- Richtmaximum: {fit.max_weight:.1%}",
                    f"- Ruimte tot richtmaximum: {_format_eur_plain(fit.room_to_max)}",
                    f"- Maximale nieuwe koopruimte: {_format_eur_plain(fit.max_new_buy_amount)}",
                    f"- Praktische koopruimte: {_format_eur_plain(fit.practical_buy_amount)}",
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
            if fit.sell_candidates:
                lines.append(f"- Cash vrijmaken nodig: {_format_eur_plain(fit.cash_shortfall)}")
                for candidate in fit.sell_candidates:
                    score_text = "n.b." if candidate.score_total is None else f"{candidate.score_total:.1f}/100"
                    lines.append(
                        f"- Verkoopkandidaat {candidate.symbol}: circa "
                        f"{_format_eur_plain(candidate.suggested_sale_value)}; "
                        f"positie {_format_eur_plain(candidate.position_value)}, score {score_text}; "
                        f"{candidate.reason}."
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
        asset_value = portfolio_assets_net_value(assets)
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

        securities_value = sum(position_values.values())
        total_wealth = asset_value + securities_value
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
        position_weight = target_value / securities_value if securities_value else 0.0
        position_room = max(0.0, (securities_value * max_weight) - target_value) if securities_value else 0.0
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
        elif securities_value:
            notes.append(f"Resterende ruimte tot het richtmaximum is circa {_format_eur_plain(room_to_max)}.")
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
            position_basis=securities_value,
        )
        buy_room = _buy_room(
            score_total=score.total,
            transaction_action=transaction_action,
            securities_value=securities_value,
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
        sell_candidates = _cash_raising_sell_candidates(
            repository=self.repository,
            exposures=exposures,
            excluded_symbols=set(matched_symbols) | {symbol.upper()},
            cash_shortfall=(
                buy_room["cash_shortfall"]
                if transaction_action in {"kleine_startpositie", "bijkopen_tot_max"}
                else 0.0
            ),
            securities_value=securities_value,
            max_weight=max_weight,
            target_sector=classification.sector,
            target_theme=classification.theme,
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
            securities_value=securities_value,
            sector_name=classification.sector,
            sector_weight=sector_weight,
            theme_name=classification.theme,
            theme_weight=theme_weight,
            cash_value=cash_value,
            cash_buffer=cash_buffer,
            available_cash=available_cash,
            max_new_buy_amount=buy_room["max_new_buy_amount"],
            practical_buy_amount=buy_room["practical_buy_amount"],
            cash_shortfall=buy_room["cash_shortfall"],
            buy_room_limits=buy_room["limits"],
            sell_candidates=sell_candidates,
        )

        return PortfolioFit(
            summary=summary,
            position_value=target_value,
            position_weight=position_weight,
            max_weight=max_weight,
            room_to_max=room_to_max,
            total_wealth=total_wealth,
            securities_value=securities_value,
            transaction_action=transaction_action,
            transaction_label=TRANSACTION_LABELS[transaction_action],
            position_room=position_room,
            cash_value=cash_value,
            cash_buffer=cash_buffer,
            available_cash=available_cash,
            max_new_buy_amount=buy_room["max_new_buy_amount"],
            practical_buy_amount=buy_room["practical_buy_amount"],
            cash_shortfall=buy_room["cash_shortfall"],
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
            sell_candidates=sell_candidates,
            notes=notes,
        )

    def _retrieve_evidence(
        self,
        symbol: str,
        financial: FinancialSnapshot,
        market: MarketSnapshot,
    ) -> tuple[List[KnowledgeHit], EvidenceDiagnostics]:
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

        accepted_symbols = self._accepted_evidence_symbols(symbol)
        classification = effective_classification(self.repository, symbol)
        query = " ".join(query_parts)
        hits = self.repository.search_knowledge(query, limit=50)
        evidence: list[KnowledgeHit] = []
        seen_sources: set[tuple[str, str]] = set()
        for hit in hits:
            if not _knowledge_hit_matches_analysis(
                hit,
                accepted_symbols=accepted_symbols,
                sector=classification.sector,
                theme=classification.theme,
            ):
                continue
            source_key = (hit.title, hit.source_type)
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            evidence.append(hit)
            if len(evidence) >= 5:
                break
        return evidence, _build_evidence_diagnostics(
            query=query,
            accepted_symbols=accepted_symbols,
            sector=classification.sector,
            theme=classification.theme,
            trusted_hits_considered=len(hits),
            evidence=evidence,
        )

    def _accepted_evidence_symbols(self, symbol: str) -> set[str]:
        accepted = {normalize_symbol(symbol)}
        for alias in self.repository.portfolio_aliases_for_symbol(symbol):
            accepted.add(normalize_symbol(alias.alias_key))
            accepted.add(normalize_symbol(alias.raw_value))
        alias_matches = self.repository.resolve_portfolio_aliases(candidate_portfolio_symbols(symbol))
        accepted.update(normalize_symbol(alias) for alias in alias_matches.keys())
        accepted.update(normalize_symbol(portfolio_symbol) for portfolio_symbol in alias_matches.values())
        return {item for item in accepted if item}

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
    position_basis: float,
) -> str:
    if position_basis <= 0:
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


def _knowledge_hit_matches_analysis(
    hit: KnowledgeHit,
    *,
    accepted_symbols: set[str],
    sector: Optional[str],
    theme: Optional[str],
) -> bool:
    return scope_matches_analysis(
        knowledge_scope_from_tags(hit.source_type, hit.chunk.tags),
        accepted_symbols=accepted_symbols,
        sector=sector,
        theme=theme,
    )


def _build_evidence_diagnostics(
    *,
    query: str,
    accepted_symbols: set[str],
    sector: str,
    theme: str,
    trusted_hits_considered: int,
    evidence: list[KnowledgeHit],
) -> EvidenceDiagnostics:
    scope_counts: dict[str, int] = {"general": 0, "symbol": 0, "sector": 0, "theme": 0}
    old_count = 0
    today = date.today()
    for hit in evidence:
        scope = knowledge_scope_from_tags(hit.source_type, hit.chunk.tags)
        scope_counts[scope.kind] = scope_counts.get(scope.kind, 0) + 1
        if _knowledge_hit_is_older_than_months(hit, today=today, months=18):
            old_count += 1

    warnings: list[str] = []
    if not evidence:
        warnings.append("Geen vertrouwde kennisfragmenten gevonden die door de scope-regels kwamen.")
    elif scope_counts.get("general", 0) == len(evidence):
        warnings.append("Alle gebruikte kennis is algemeen; er is geen aandeel-, sector- of thema-specifiek bewijs gebruikt.")
    if old_count:
        warnings.append(f"{old_count} van {len(evidence)} gebruikte kennisfragmenten is ouder dan 18 maanden.")

    return EvidenceDiagnostics(
        query=query,
        accepted_symbols=sorted(accepted_symbols),
        sector=sector,
        theme=theme,
        trusted_hits_considered=trusted_hits_considered,
        selected_count=len(evidence),
        scope_counts=scope_counts,
        warnings=warnings,
        max_age_months=18,
    )


def _knowledge_hit_is_older_than_months(hit: KnowledgeHit, *, today: date, months: int) -> bool:
    if not hit.publication_date:
        return False
    try:
        published = date.fromisoformat(hit.publication_date)
    except ValueError:
        return False
    return (today.year - published.year) * 12 + today.month - published.month > months


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
    securities_value: float,
    sector_name: str,
    sector_weight: float,
    theme_name: str,
    theme_weight: float,
    cash_value: Optional[float],
    cash_buffer: Optional[float],
    available_cash: Optional[float],
    max_new_buy_amount: float,
    practical_buy_amount: float,
    cash_shortfall: float,
    buy_room_limits: List[str],
    sell_candidates: List[SellCandidate],
) -> List[str]:
    lines = [
        f"{transaction_label}: totaalscore {score_total:.1f}/100 en risicoscore {risk_score:.1f}/100.",
    ]
    if target_value > 0:
        lines.append(
            f"Huidige positie {_format_eur_plain(target_value)} ({position_weight:.1%} van effectenvermogen); "
            f"richtmaximum bij {risk_profile} profiel is {max_weight:.1%}."
        )
    else:
        lines.append(
            f"Geen bestaande positie; richtmaximum bij {risk_profile} profiel is {max_weight:.1%} "
            f"van effectenvermogen {_format_eur_plain(securities_value)}."
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
    if cash_shortfall > 0 and sell_candidates:
        lines.append(
            "Cash vrijmaken: eerste kandidaat "
            f"{sell_candidates[0].symbol} voor circa {_format_eur_plain(sell_candidates[0].suggested_sale_value)}."
        )
    return lines


def _buy_room(
    *,
    score_total: float,
    transaction_action: str,
    securities_value: float,
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
    factor_before_cash = factor
    if available_cash is not None and available_cash <= 0:
        factor = 0.0
        limits.append("Geen beschikbare beleggingscash boven de gewenste cashbuffer.")

    practical_buy_amount = max_new_buy_amount * factor
    desired_buy_amount_before_cash = position_room * factor_before_cash
    cash_shortfall = max(0.0, desired_buy_amount_before_cash - practical_buy_amount)
    calculation = [
        (
            "Positieruimte = effectenvermogen "
            f"{_format_eur_plain(securities_value)} × richtmaximum {max_weight:.1%} "
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
    if cash_shortfall > 0:
        calculation.append(
            f"Cashtekort voor volledige praktische ruimte: {_format_eur_plain(cash_shortfall)}."
        )

    return {
        "max_new_buy_amount": round(max_new_buy_amount, 2),
        "practical_buy_amount": round(practical_buy_amount, 2),
        "cash_shortfall": round(cash_shortfall, 2),
        "buy_room_factor": round(factor, 4),
        "limits": limits,
        "calculation": calculation,
    }


def _cash_raising_sell_candidates(
    *,
    repository: SQLiteRepository,
    exposures: List[PositionExposure],
    excluded_symbols: set[str],
    cash_shortfall: float,
    securities_value: float,
    max_weight: float,
    target_sector: str,
    target_theme: str,
) -> List[SellCandidate]:
    if cash_shortfall <= 0 or securities_value <= 0:
        return []

    ranked = []
    for exposure in exposures:
        symbol = exposure.position.symbol.upper()
        if symbol in excluded_symbols or exposure.market_value <= 0:
            continue
        position_weight = exposure.market_value / securities_value
        score_total = _local_score_total(repository, symbol)
        reasons = []
        priority = score_total if score_total is not None else 65.0
        if score_total is None:
            reasons.append("geen actuele analysescore; eerst handmatig controleren")
        elif score_total < 45:
            reasons.append(f"zwakke score {score_total:.1f}/100")
        elif score_total < 60:
            reasons.append(f"matige score {score_total:.1f}/100")
        else:
            reasons.append(f"score {score_total:.1f}/100; alleen verkoopbaar als cash nodig is")

        overweight_amount = max(0.0, exposure.market_value - (securities_value * max_weight))
        if overweight_amount > 0:
            priority -= 12
            reasons.append(f"positiegewicht {position_weight:.1%} boven richtmaximum {max_weight:.1%}")
        if target_sector != "Onbekend" and exposure.sector == target_sector:
            priority -= 6
            reasons.append(f"zelfde sector als nieuwe koop ({target_sector})")
        if target_theme != "Onbekend" and exposure.theme == target_theme:
            priority -= 6
            reasons.append(f"zelfde thema als nieuwe koop ({target_theme})")

        base_sale_cap = exposure.market_value * (0.50 if (score_total is not None and score_total < 60) else 0.25)
        sale_cap = max(base_sale_cap, overweight_amount) if overweight_amount > 0 else base_sale_cap
        ranked.append((priority, symbol, exposure, score_total, sale_cap, "; ".join(reasons)))

    remaining = cash_shortfall
    candidates: List[SellCandidate] = []
    for _, symbol, exposure, score_total, sale_cap, reason in sorted(ranked, key=lambda item: (item[0], item[1])):
        if remaining <= 0 or len(candidates) >= 3:
            break
        suggested_sale_value = min(remaining, sale_cap, exposure.market_value)
        if suggested_sale_value <= 0:
            continue
        candidates.append(
            SellCandidate(
                symbol=symbol,
                position_value=round(exposure.market_value, 2),
                position_weight=round(exposure.market_value / securities_value, 4),
                suggested_sale_value=round(suggested_sale_value, 2),
                score_total=score_total,
                reason=reason,
            )
        )
        remaining -= suggested_sale_value
    return candidates


def _local_score_total(repository: SQLiteRepository, symbol: str) -> Optional[float]:
    try:
        financial = repository.latest_financial_snapshot(symbol)
        market = repository.latest_market_snapshot(symbol)
    except LookupError:
        return None
    return build_score(financial, market).total


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
    return format_currency(value, "EUR", decimals=0)


def _format_percent_plain(value: Optional[float]) -> str:
    return "n.b." if value is None else f"{value:.1%}"


def _format_number_plain(value: Optional[float]) -> str:
    return "n.b." if value is None else f"{value:.1f}"
