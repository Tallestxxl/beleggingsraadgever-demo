"""Portfolio valuation and exposure helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .classification import classify_symbol
from .models import PortfolioClassification, PortfolioPosition
from .storage import SQLiteRepository


@dataclass(frozen=True)
class PositionExposure:
    position: PortfolioPosition
    market_price: float
    market_value: float
    return_pct: float | None
    sector: str
    theme: str


@dataclass(frozen=True)
class ExposureBucket:
    label: str
    value: float
    securities_weight: float
    total_weight: float


def portfolio_position_exposures(repository: SQLiteRepository) -> list[PositionExposure]:
    exposures = []
    for position in repository.latest_portfolio_positions():
        market_price = _latest_price(repository, position)
        market_value = position.quantity * market_price
        cost_value = position.quantity * position.average_cost
        return_pct = ((market_value - cost_value) / cost_value) if cost_value else None
        classification = effective_classification(repository, position.symbol)
        exposures.append(
            PositionExposure(
                position=position,
                market_price=market_price,
                market_value=market_value,
                return_pct=return_pct,
                sector=classification.sector,
                theme=classification.theme,
            )
        )
    return exposures


def exposure_buckets(
    exposures: list[PositionExposure],
    *,
    by: str,
    total_wealth: float,
) -> list[ExposureBucket]:
    values: dict[str, float] = {}
    for exposure in exposures:
        label = exposure.sector if by == "sector" else exposure.theme
        values[label] = values.get(label, 0.0) + exposure.market_value

    securities_value = sum(values.values())
    return [
        ExposureBucket(
            label=label,
            value=value,
            securities_weight=value / securities_value if securities_value else 0.0,
            total_weight=value / total_wealth if total_wealth else 0.0,
        )
        for label, value in sorted(values.items(), key=lambda item: item[1], reverse=True)
    ]


def effective_classification(repository: SQLiteRepository, symbol: str) -> PortfolioClassification:
    stored = repository.portfolio_classification(symbol)
    if stored is not None:
        return stored
    fallback = classify_symbol(symbol)
    return PortfolioClassification(symbol=fallback.symbol, sector=fallback.sector, theme=fallback.theme)


def _latest_price(repository: SQLiteRepository, position: PortfolioPosition) -> float:
    portfolio_price = repository.latest_portfolio_price(position.symbol)
    if portfolio_price is not None:
        return portfolio_price.close_price
    try:
        return repository.latest_market_snapshot(position.symbol).close_price
    except LookupError:
        return position.average_cost
