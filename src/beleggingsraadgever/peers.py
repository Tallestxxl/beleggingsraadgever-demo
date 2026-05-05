"""Peer comparison helpers for local stock analysis."""

from __future__ import annotations

from statistics import median
from typing import Dict, Iterable, Optional, Tuple

from .indicators import build_score
from .models import FinancialSnapshot, MarketSnapshot, PeerAnalysis, PeerComparisonRow
from .portfolio import effective_classification
from .storage import SQLiteRepository

SnapshotPair = Tuple[FinancialSnapshot, MarketSnapshot]


PEERS_BY_SYMBOL = {
    "ASMI": ["ASML", "BESI", "LAM RESEARCH", "TSMI", "NVIDIA"],
    "ASML": ["ASMI", "BESI", "LAM RESEARCH", "TSMI", "NVIDIA"],
    "BESI": ["ASML", "ASMI", "LAM RESEARCH", "TSMI", "NVIDIA"],
    "LAM RESEARCH": ["ASML", "ASMI", "BESI", "TSMI", "NVIDIA"],
    "LRCX": ["ASML", "ASMI", "BESI", "TSMI", "NVIDIA"],
    "SHELL": ["BP", "CHEVRON"],
    "BP": ["SHELL", "CHEVRON"],
    "CHEVRON": ["SHELL", "BP"],
    "APERAM": ["CORBION", "DSM FIRMENICH"],
    "DSM FIRMENICH": ["CORBION", "UNILEVER"],
    "DSFIR": ["CORBION", "UNILEVER"],
    "CORBION": ["DSM FIRMENICH", "UNILEVER"],
    "FUGRO": ["VOPAK", "NEDAP"],
    "VOPAK": ["FUGRO", "NEDAP"],
    "NEDAP": ["FUGRO", "VOPAK"],
}

PEERS_BY_THEME = {
    "Semiconductor equipment": ["ASML", "ASMI", "BESI", "LAM RESEARCH", "TSMI", "NVIDIA"],
    "Oil and gas": ["SHELL", "BP", "CHEVRON"],
    "Steel and metals": ["APERAM"],
    "Health and nutrition": ["DSM FIRMENICH", "CORBION", "UNILEVER"],
    "Global consumer staples": ["UNILEVER", "DSM FIRMENICH", "CORBION"],
    "Offshore services": ["FUGRO", "VOPAK"],
    "Technology hardware": ["NEDAP", "TKH GROUP"],
}


def build_peer_analysis(
    repository: SQLiteRepository,
    symbol: str,
    financial: FinancialSnapshot,
    market: MarketSnapshot,
    *,
    extra_snapshots: Optional[Dict[str, SnapshotPair]] = None,
) -> Optional[PeerAnalysis]:
    normalized_symbol = symbol.strip().upper()
    classification = effective_classification(repository, normalized_symbol)
    peer_symbols = _peer_symbols(normalized_symbol, classification.theme)
    snapshots = extra_snapshots or {}
    rows = []
    for peer_symbol in peer_symbols:
        pair = (financial, market) if peer_symbol == normalized_symbol else _snapshot_pair(repository, peer_symbol, snapshots)
        if pair is None:
            continue
        peer_financial, peer_market = pair
        row = _peer_row(peer_symbol, peer_financial, peer_market, peer_symbol == normalized_symbol)
        rows.append(row)

    if len(rows) < 2:
        return None

    target = next((row for row in rows if row.is_target), None)
    if target is None:
        target = _peer_row(normalized_symbol, financial, market, True)
        rows = [target] + rows

    peer_rows = [row for row in rows if not row.is_target]
    group_label = classification.theme if classification.theme != "Onbekend" else classification.sector
    if group_label == "Onbekend":
        group_label = "curated peers"
    return PeerAnalysis(
        group_label=group_label,
        summary=_peer_summary(target, peer_rows),
        rows=rows,
        notes=[
            "V1 vergelijkt alleen peers waarvoor lokaal een recente snapshot beschikbaar is.",
            "Omzetgroei wordt toegevoegd zodra historische reeksen beschikbaar zijn; deze tabel gebruikt de laatste snapshot.",
        ],
    )


def _peer_symbols(symbol: str, theme: str) -> list[str]:
    peers = [symbol]
    for candidate in PEERS_BY_SYMBOL.get(symbol, []):
        if candidate not in peers:
            peers.append(candidate)
    for candidate in PEERS_BY_THEME.get(theme, []):
        if candidate not in peers:
            peers.append(candidate)
    return peers


def _snapshot_pair(
    repository: SQLiteRepository,
    symbol: str,
    extra_snapshots: Dict[str, SnapshotPair],
) -> Optional[SnapshotPair]:
    normalized_symbol = symbol.strip().upper()
    if normalized_symbol in extra_snapshots:
        return extra_snapshots[normalized_symbol]
    try:
        return (
            repository.latest_financial_snapshot(normalized_symbol),
            repository.latest_market_snapshot(normalized_symbol),
        )
    except LookupError:
        return None


def _peer_row(
    symbol: str,
    financial: FinancialSnapshot,
    market: MarketSnapshot,
    is_target: bool,
) -> PeerComparisonRow:
    fcf_margin = None
    if financial.free_cash_flow is not None and financial.revenue:
        fcf_margin = financial.free_cash_flow / financial.revenue
    debt_to_fcf = None
    if financial.debt is not None and financial.free_cash_flow:
        debt_to_fcf = financial.debt / max(abs(financial.free_cash_flow), 1.0)
    score = build_score(financial, market)
    return PeerComparisonRow(
        symbol=symbol,
        is_target=is_target,
        revenue=financial.revenue,
        operating_margin=financial.operating_margin,
        fcf_margin=fcf_margin,
        debt_to_fcf=debt_to_fcf,
        pe_ratio=market.pe_ratio,
        ev_ebitda=market.ev_ebitda,
        fcf_yield=market.fcf_yield,
        dividend_yield=market.dividend_yield,
        momentum_12m=market.momentum_12m,
        quality_score=score.quality,
        valuation_score=score.valuation,
    )


def _peer_summary(target: PeerComparisonRow, peers: Iterable[PeerComparisonRow]) -> str:
    peer_rows = list(peers)
    parts = []
    quality_median = _median(row.quality_score for row in peer_rows)
    valuation_median = _median(row.valuation_score for row in peer_rows)
    pe_median = _median(row.pe_ratio for row in peer_rows)
    margin_median = _median(row.operating_margin for row in peer_rows)
    fcf_yield_median = _median(row.fcf_yield for row in peer_rows)

    if quality_median is not None:
        direction = _relation(target.quality_score, quality_median, higher_label="boven", lower_label="onder")
        parts.append(f"kwaliteit {direction} peer-mediaan ({target.quality_score:.1f} vs {quality_median:.1f})")
    if valuation_median is not None:
        direction = _relation(target.valuation_score, valuation_median, higher_label="boven", lower_label="onder")
        parts.append(f"waardering-score {direction} peer-mediaan ({target.valuation_score:.1f} vs {valuation_median:.1f})")
    if pe_median is not None and target.pe_ratio is not None:
        direction = _relation(target.pe_ratio, pe_median, higher_label="duurder", lower_label="goedkoper")
        parts.append(f"K/W {direction} dan peers ({target.pe_ratio:.1f} vs {pe_median:.1f})")
    if margin_median is not None and target.operating_margin is not None:
        direction = _relation(target.operating_margin, margin_median, higher_label="sterker", lower_label="zwakker")
        parts.append(f"operationele marge {direction} ({target.operating_margin:.1%} vs {margin_median:.1%})")
    if fcf_yield_median is not None and target.fcf_yield is not None:
        direction = _relation(target.fcf_yield, fcf_yield_median, higher_label="hoger", lower_label="lager")
        parts.append(f"FCF-yield {direction} ({target.fcf_yield:.1%} vs {fcf_yield_median:.1%})")

    if not parts:
        return "Er zijn peers gevonden, maar er zijn nog te weinig vergelijkbare metrics voor een relatieve conclusie."
    return "Relatief beeld: " + "; ".join(parts[:4]) + "."


def _median(values: Iterable[Optional[float]]) -> Optional[float]:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return median(cleaned)


def _relation(value: float, benchmark: float, *, higher_label: str, lower_label: str) -> str:
    if abs(value - benchmark) < 0.0001:
        return "in lijn met"
    return higher_label if value > benchmark else lower_label
