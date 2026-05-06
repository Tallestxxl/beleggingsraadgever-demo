"""Discover and persist peer candidates independent from owned positions."""

from __future__ import annotations

from .classification import CLASSIFICATION_BY_SYMBOL
from .models import PeerCandidate
from .peers import PEERS_BY_SYMBOL, PEERS_BY_THEME, peer_group_for_symbol, same_company
from .storage import SQLiteRepository


def refresh_peer_candidates(repository: SQLiteRepository, symbol: str) -> list[PeerCandidate]:
    candidates = discover_peer_candidates(repository, symbol)
    repository.replace_peer_candidates(symbol, candidates)
    return candidates


def refresh_peer_candidates_for_portfolio(repository: SQLiteRepository) -> dict[str, list[PeerCandidate]]:
    refreshed: dict[str, list[PeerCandidate]] = {}
    for position in repository.latest_portfolio_positions():
        refreshed[position.symbol] = refresh_peer_candidates(repository, position.symbol)
    return refreshed


def discover_peer_candidates(repository: SQLiteRepository, symbol: str) -> list[PeerCandidate]:
    normalized_symbol = symbol.strip().upper()
    peer_group = peer_group_for_symbol(repository, normalized_symbol)
    if not peer_group:
        return []

    candidates: dict[str, PeerCandidate] = {}

    for peer_symbol in PEERS_BY_SYMBOL.get(normalized_symbol, []):
        _add_candidate(
            candidates,
            repository,
            normalized_symbol,
            peer_symbol,
            peer_group,
            source="curated_symbol",
            confidence=0.95,
            reason="Handmatig onderhouden peer-set voor dit aandeel.",
        )

    for peer_symbol in PEERS_BY_THEME.get(peer_group, []):
        _add_candidate(
            candidates,
            repository,
            normalized_symbol,
            peer_symbol,
            peer_group,
            source="curated_theme",
            confidence=0.88,
            reason=f"Zelfde peer-groep/thema: {peer_group}.",
            allow_theme_list=True,
        )

    for peer_symbol, (_, theme) in CLASSIFICATION_BY_SYMBOL.items():
        if theme != peer_group:
            continue
        _add_candidate(
            candidates,
            repository,
            normalized_symbol,
            peer_symbol,
            peer_group,
            source="known_classification",
            confidence=0.78,
            reason=f"Bekende lokale classificatie met hetzelfde thema: {peer_group}.",
        )

    local_snapshot_symbols = set(repository.symbols_with_snapshots())
    for local_classification in repository.portfolio_classifications():
        if local_classification.symbol not in local_snapshot_symbols:
            continue
        if peer_group_for_symbol(repository, local_classification.symbol) != peer_group:
            continue
        _add_candidate(
            candidates,
            repository,
            normalized_symbol,
            local_classification.symbol,
            peer_group,
            source="local_snapshot_classification",
            confidence=0.72,
            reason=f"Lokaal analyseerbaar aandeel met hetzelfde thema: {peer_group}.",
        )

    return sorted(candidates.values(), key=lambda candidate: (-candidate.confidence, candidate.peer_symbol))


def _add_candidate(
    candidates: dict[str, PeerCandidate],
    repository: SQLiteRepository,
    symbol: str,
    peer_symbol: str,
    peer_group: str,
    *,
    source: str,
    confidence: float,
    reason: str,
    allow_theme_list: bool = False,
) -> None:
    normalized_peer = peer_symbol.strip().upper()
    if not normalized_peer or normalized_peer == symbol:
        return
    if same_company(repository, symbol, normalized_peer):
        return
    if not _is_compatible_peer(repository, normalized_peer, peer_group, allow_theme_list=allow_theme_list):
        return
    candidate = PeerCandidate(
        symbol=symbol,
        peer_symbol=normalized_peer,
        peer_group=peer_group,
        source=source,
        confidence=confidence,
        reason=reason,
    )
    existing = candidates.get(normalized_peer)
    if existing is None or candidate.confidence > existing.confidence:
        candidates[normalized_peer] = candidate


def _is_compatible_peer(
    repository: SQLiteRepository,
    symbol: str,
    peer_group: str,
    *,
    allow_theme_list: bool,
) -> bool:
    if not peer_group:
        return False
    if allow_theme_list and symbol in PEERS_BY_THEME.get(peer_group, []):
        return True
    return peer_group_for_symbol(repository, symbol) == peer_group
