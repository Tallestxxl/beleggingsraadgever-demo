"""Peer comparison helpers for local stock analysis."""

from __future__ import annotations

from statistics import median
from typing import Dict, Iterable, Optional, Tuple

from .identity import normalize_symbol
from .indicators import build_score
from .models import FinancialSnapshot, MarketSnapshot, PeerAnalysis, PeerComparisonRow, PortfolioClassification
from .portfolio import effective_classification
from .storage import SQLiteRepository

SnapshotPair = Tuple[FinancialSnapshot, MarketSnapshot]

MIN_PEERS = 2
MAX_PEERS = 6


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
    "FUGRO": ["SBMO", "SUBC", "CGG"],
    "VOPAK": ["KMI", "OKE", "GIB_A"],
    "NEDAP": ["TWEKA"],
}

PEERS_BY_THEME = {
    "Dutch quality industrials": ["AALB", "TKH GROUP", "NEDAP"],
    "Semiconductor equipment": ["ASML", "ASMI", "BESI", "LAM RESEARCH", "TSMI", "NVIDIA"],
    "Oil and gas": ["SHELL", "BP", "CHEVRON"],
    "Steel and metals": ["APERAM", "OUTOKUMPU", "ARCELORMITTAL", "NUCOR", "STEEL DYNAMICS"],
    "Chemicals": ["AKZA", "BASF", "COVESTRO", "LANXESS", "ARKEMA"],
    "Energy transition": ["ALFEN", "EBUS", "VESTAS", "ORSTED", "ENPHASE", "SOLAREDGE"],
    "Biobased materials": ["AVTX", "CORBION", "DSM FIRMENICH"],
    "Construction": ["BAMNB", "HEIJMANS", "VINCI", "BOUYGUES", "EIFFAGE", "ACS", "FERROVIAL", "SKANSKA"],
    "Ingredients": ["CRBN", "DSM FIRMENICH", "KERRY GROUP", "INGREDION"],
    "Health and nutrition": ["DSM FIRMENICH", "CORBION", "UNILEVER"],
    "Global consumer staples": ["UNILEVER", "DSM FIRMENICH", "CORBION"],
    "Offshore services": ["FUGRO", "SBMO", "SUBC", "CGG"],
    "Technology hardware": ["NEDAP", "TKH GROUP"],
    "Staffing": ["RAND", "ADECCO", "MANPOWERGROUP", "ROBERT HALF"],
    "Telecom": ["KPN", "DEUTSCHE TELEKOM", "ORANGE", "VODAFONE"],
    "Space": ["LUNR", "RKLB", "RDW", "IRDM"],
    "Broad US equities": ["INVESCO_RAFI_US", "SPY", "IVV", "VOO", "VTI"],
    "Global equities": ["VWRL", "VWCE", "ACWI", "URTH"],
    "Healthcare equities": ["XDWH", "IXJ", "XLV"],
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
    peer_group = peer_group_for_symbol(repository, normalized_symbol)
    if not peer_group:
        return None

    snapshots = extra_snapshots or {}
    peer_symbols = _peer_symbols(repository, normalized_symbol, peer_group)
    configured_peer_count = len(peer_symbols)
    target_row = _peer_row(normalized_symbol, financial, market, True)
    peer_rows = []
    available_peer_count = 0
    for peer_symbol in peer_symbols:
        pair = _snapshot_pair(repository, peer_symbol, snapshots)
        if pair is None:
            continue
        available_peer_count += 1
        if len(peer_rows) >= MAX_PEERS:
            continue
        peer_financial, peer_market = pair
        peer_rows.append(_peer_row(peer_symbol, peer_financial, peer_market, False))

    if len(peer_rows) < MIN_PEERS:
        return None

    rows = [target_row] + peer_rows
    return PeerAnalysis(
        group_label=peer_group,
        summary=_peer_summary(target_row, peer_rows),
        rows=rows,
        notes=[
            (
                f"{available_peer_count} van {configured_peer_count} peers in dezelfde peer-groep zijn lokaal beschikbaar; "
                f"de tabel toont maximaal {MAX_PEERS} peers."
            ),
            "Kandidaten worden generiek gefilterd op dezelfde peer-groep/thema; een brede sector alleen telt niet als peer-match.",
            f"Peeranalyse verschijnt vanaf minimaal {MIN_PEERS} beschikbare peers.",
            "Omzetgroei wordt toegevoegd zodra historische reeksen beschikbaar zijn; deze tabel gebruikt de laatste snapshot.",
        ],
        available_peer_count=available_peer_count,
        configured_peer_count=configured_peer_count,
        max_peer_count=MAX_PEERS,
        min_peer_count=MIN_PEERS,
    )


def _peer_symbols(
    repository: SQLiteRepository,
    symbol: str,
    peer_group: str,
) -> list[str]:
    peers = []
    seen = {symbol}

    for candidate in repository.peer_candidates_for_symbol(symbol):
        if candidate.status != "vertrouwd":
            continue
        if candidate.peer_group == peer_group and _same_peer_group(repository, candidate.peer_symbol, peer_group):
            _add_peer_candidate(repository, symbol, peers, seen, candidate.peer_symbol)

    for candidate in PEERS_BY_SYMBOL.get(symbol, []):
        normalized_candidate = candidate.strip().upper()
        if _same_peer_group(repository, normalized_candidate, peer_group):
            _add_peer_candidate(repository, symbol, peers, seen, normalized_candidate)

    return peers


def _add_peer_candidate(
    repository: SQLiteRepository,
    symbol: str,
    peers: list[str],
    seen: set[str],
    candidate: str,
) -> None:
    if candidate not in seen and not same_company(repository, symbol, candidate):
        seen.add(candidate)
        peers.append(candidate)


def _same_peer_group(repository: SQLiteRepository, symbol: str, peer_group: str) -> bool:
    if not peer_group:
        return False
    if symbol in PEERS_BY_THEME.get(peer_group, []):
        return True
    return peer_group_for_symbol(repository, symbol) == peer_group


def peer_group_for_symbol(repository: SQLiteRepository, symbol: str) -> str:
    normalized_symbol = symbol.strip().upper()
    curated_groups = [
        group
        for group, symbols in PEERS_BY_THEME.items()
        if normalized_symbol in {candidate.strip().upper() for candidate in symbols}
    ]
    if len(set(curated_groups)) == 1:
        return curated_groups[0]
    return _peer_group(effective_classification(repository, normalized_symbol))


def same_company(repository: SQLiteRepository, left: str, right: str) -> bool:
    return _canonical_symbol(repository, left) == _canonical_symbol(repository, right)


def _canonical_symbol(repository: SQLiteRepository, symbol: str) -> str:
    normalized_symbol = normalize_symbol(symbol)
    return repository.resolve_portfolio_aliases([normalized_symbol]).get(normalized_symbol, normalized_symbol)


def _peer_group(classification: PortfolioClassification) -> str:
    theme = classification.theme.strip()
    if theme and theme != "Onbekend":
        return theme
    return ""


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
