"""Resolve user-entered symbols to the local portfolio identity when possible."""

from __future__ import annotations

from .identity import normalize_broker_name, normalize_symbol
from .models import PortfolioAlias
from .storage import SQLiteRepository


def resolve_analysis_symbol(repository: SQLiteRepository, raw_symbol: str, *, learn: bool = True) -> str:
    normalized = normalize_symbol(raw_symbol)
    if not normalized:
        return ""

    candidates = _input_candidates(raw_symbol)
    alias_matches = repository.resolve_portfolio_aliases(candidates)
    for candidate in candidates:
        match = alias_matches.get(candidate)
        if match:
            _learn_alias(repository, normalized, match, raw_symbol, learn=learn)
            return match

    portfolio_symbols = sorted({position.symbol.upper() for position in repository.latest_portfolio_positions()})
    if normalized in portfolio_symbols:
        return normalized

    prefix_matches = [
        portfolio_symbol
        for portfolio_symbol in portfolio_symbols
        if len(normalized) >= 3 and portfolio_symbol.startswith(normalized)
    ]
    if len(prefix_matches) == 1:
        resolved = prefix_matches[0]
        _learn_alias(repository, normalized, resolved, raw_symbol, learn=learn)
        return resolved

    return normalized


def _input_candidates(raw_symbol: str) -> list[str]:
    candidates = []
    for candidate in [raw_symbol, normalize_broker_name(raw_symbol), normalize_symbol(raw_symbol)]:
        normalized = normalize_symbol(candidate)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _learn_alias(
    repository: SQLiteRepository,
    alias_key: str,
    portfolio_symbol: str,
    raw_symbol: str,
    *,
    learn: bool,
) -> None:
    if not learn or alias_key == portfolio_symbol:
        return
    repository.upsert_portfolio_alias(
        PortfolioAlias(
            portfolio_symbol=portfolio_symbol,
            alias_key=alias_key,
            alias_type="analysis_input",
            raw_value=raw_symbol,
            source="analysis_symbol_resolution",
        )
    )
