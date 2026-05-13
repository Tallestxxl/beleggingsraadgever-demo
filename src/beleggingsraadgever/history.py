"""Historical trend analysis from stored snapshots."""

from __future__ import annotations

from datetime import date
from typing import Optional

from .formatting import format_compact_number
from .models import FinancialSnapshot, HistoricalAnalysis, HistoricalTrendRow, MarketSnapshot
from .storage import SQLiteRepository


def build_historical_analysis(
    repository: SQLiteRepository,
    symbol: str,
    current_financial: FinancialSnapshot,
    current_market: MarketSnapshot,
    *,
    limit: int = 5,
) -> HistoricalAnalysis:
    financial_history = _financial_history(repository, symbol, current_financial, limit=limit)
    market_history = _market_history(repository, symbol, current_market, limit=limit)

    rows: list[HistoricalTrendRow] = []
    rows.extend(_financial_rows(financial_history))
    rows.extend(_market_rows(market_history))

    notes: list[str] = []
    if len(financial_history) < 2:
        notes.append("Nog minder dan 2 fundamentele snapshots; omzet-, marge- en kasstroomtrend zijn beperkt.")
    if len(market_history) < 2:
        notes.append("Nog minder dan 2 marktsnapshots; waarderings- en koersontwikkeling zijn beperkt.")

    return HistoricalAnalysis(
        summary=_summary(symbol, rows, len(financial_history), len(market_history)),
        rows=rows,
        notes=notes,
        financial_period_count=len(financial_history),
        market_point_count=len(market_history),
    )


def _financial_history(
    repository: SQLiteRepository,
    symbol: str,
    current: FinancialSnapshot,
    *,
    limit: int,
) -> list[FinancialSnapshot]:
    rows = repository.financial_history(symbol, period_type=current.period_type, limit=limit)
    if len(rows) < 2:
        rows = repository.financial_history(symbol, limit=limit)
    return _merge_financial(rows, current, limit=limit)


def _market_history(
    repository: SQLiteRepository,
    symbol: str,
    current: MarketSnapshot,
    *,
    limit: int,
) -> list[MarketSnapshot]:
    return _merge_market(repository.market_history(symbol, limit=limit), current, limit=limit)


def _merge_financial(
    rows: list[FinancialSnapshot],
    current: FinancialSnapshot,
    *,
    limit: int,
) -> list[FinancialSnapshot]:
    by_key = {(row.period_end, row.period_type): row for row in rows}
    by_key[(current.period_end, current.period_type)] = current
    return sorted(by_key.values(), key=lambda row: (row.period_end, row.period_type))[-limit:]


def _merge_market(rows: list[MarketSnapshot], current: MarketSnapshot, *, limit: int) -> list[MarketSnapshot]:
    by_key = {row.as_of: row for row in rows}
    by_key[current.as_of] = current
    return sorted(by_key.values(), key=lambda row: row.as_of)[-limit:]


def _financial_rows(rows: list[FinancialSnapshot]) -> list[HistoricalTrendRow]:
    if len(rows) < 2:
        return []
    start = rows[0]
    end = rows[-1]
    start_label = _period_label(start.period_end, start.period_type)
    end_label = _period_label(end.period_end, end.period_type)
    years = max(_year_fraction(start.period_end, end.period_end), 0.0)
    trend_rows = [
        _amount_row(
            "Omzet",
            start_label,
            end_label,
            start.revenue,
            end.revenue,
            years=years,
            higher_is_better=True,
        ),
        _percent_row(
            "Operationele marge",
            start_label,
            end_label,
            start.operating_margin,
            end.operating_margin,
            higher_is_better=True,
        ),
        _percent_row(
            "FCF-marge",
            start_label,
            end_label,
            _margin(start.free_cash_flow, start.revenue),
            _margin(end.free_cash_flow, end.revenue),
            higher_is_better=True,
        ),
        _ratio_row(
            "Schuld/FCF",
            start_label,
            end_label,
            _debt_to_fcf(start),
            _debt_to_fcf(end),
            higher_is_better=False,
        ),
        _amount_row(
            "Dividend/aandeel",
            start_label,
            end_label,
            start.dividend_per_share,
            end.dividend_per_share,
            years=years,
            higher_is_better=True,
        ),
    ]
    return [row for row in trend_rows if row is not None]


def _market_rows(rows: list[MarketSnapshot]) -> list[HistoricalTrendRow]:
    if len(rows) < 2:
        return []
    start = rows[0]
    end = rows[-1]
    start_label = start.as_of
    end_label = end.as_of
    return [
        row
        for row in [
            _amount_row(
                "Slotkoers",
                start_label,
                end_label,
                start.close_price,
                end.close_price,
                years=max(_year_fraction(start.as_of, end.as_of), 0.0),
                higher_is_better=True,
            ),
            _ratio_row(
                "K/W",
                start_label,
                end_label,
                start.pe_ratio,
                end.pe_ratio,
                higher_is_better=False,
            ),
            _percent_row(
                "FCF-yield",
                start_label,
                end_label,
                start.fcf_yield,
                end.fcf_yield,
                higher_is_better=True,
            ),
        ]
        if row is not None
    ]


def _amount_row(
    metric: str,
    start_label: str,
    end_label: str,
    start_value: Optional[float],
    end_value: Optional[float],
    *,
    years: float,
    higher_is_better: bool,
) -> Optional[HistoricalTrendRow]:
    if start_value is None or end_value is None:
        return None
    change_label = _compound_growth_label(start_value, end_value, years)
    return HistoricalTrendRow(
        metric=metric,
        start_label=start_label,
        end_label=end_label,
        start_value=start_value,
        end_value=end_value,
        value_kind="amount",
        change_label=change_label,
        interpretation=_direction_text(end_value - start_value, higher_is_better=higher_is_better),
    )


def _percent_row(
    metric: str,
    start_label: str,
    end_label: str,
    start_value: Optional[float],
    end_value: Optional[float],
    *,
    higher_is_better: bool,
) -> Optional[HistoricalTrendRow]:
    if start_value is None or end_value is None:
        return None
    delta = end_value - start_value
    return HistoricalTrendRow(
        metric=metric,
        start_label=start_label,
        end_label=end_label,
        start_value=start_value,
        end_value=end_value,
        value_kind="percent",
        change_label=f"{delta:+.1%}p",
        interpretation=_direction_text(delta, higher_is_better=higher_is_better),
    )


def _ratio_row(
    metric: str,
    start_label: str,
    end_label: str,
    start_value: Optional[float],
    end_value: Optional[float],
    *,
    higher_is_better: bool,
) -> Optional[HistoricalTrendRow]:
    if start_value is None or end_value is None:
        return None
    delta = end_value - start_value
    return HistoricalTrendRow(
        metric=metric,
        start_label=start_label,
        end_label=end_label,
        start_value=start_value,
        end_value=end_value,
        value_kind="ratio",
        change_label=f"{delta:+.1f}x",
        interpretation=_direction_text(delta, higher_is_better=higher_is_better),
    )


def _summary(
    symbol: str,
    rows: list[HistoricalTrendRow],
    financial_period_count: int,
    market_point_count: int,
) -> str:
    if not rows:
        return (
            f"{symbol} heeft nog onvoldoende historische snapshots voor trendanalyse "
            f"({financial_period_count} fundamenteel, {market_point_count} markt)."
        )
    highlights = []
    for metric in ("Omzet", "Operationele marge", "FCF-marge", "Schuld/FCF"):
        row = next((item for item in rows if item.metric == metric), None)
        if row is not None:
            highlights.append(f"{metric.lower()} {row.change_label}")
    if not highlights:
        for metric in ("Slotkoers", "K/W", "FCF-yield"):
            row = next((item for item in rows if item.metric == metric), None)
            if row is not None:
                highlights.append(f"{metric.lower()} {row.change_label}")
    return f"Historische trend op basis van {financial_period_count} fundamentele periode(n): " + "; ".join(
        highlights[:4]
    ) + "."


def _margin(value: Optional[float], revenue: Optional[float]) -> Optional[float]:
    if value is None or not revenue:
        return None
    return value / revenue


def _debt_to_fcf(snapshot: FinancialSnapshot) -> Optional[float]:
    if snapshot.debt is None or not snapshot.free_cash_flow or snapshot.free_cash_flow <= 0:
        return None
    return snapshot.debt / snapshot.free_cash_flow


def _compound_growth_label(start_value: float, end_value: float, years: float) -> str:
    if not start_value:
        return "n.b."
    if years >= 1 and start_value > 0 and end_value >= 0:
        cagr = (end_value / start_value) ** (1 / years) - 1
        return f"CAGR {cagr:+.1%}"
    return f"{(end_value / start_value) - 1:+.1%}"


def _direction_text(delta: float, *, higher_is_better: bool) -> str:
    if abs(delta) < 0.0001:
        return "stabiel"
    improved = delta > 0 if higher_is_better else delta < 0
    return "verbeterd" if improved else "verslechterd"


def _period_label(period_end: str, period_type: str) -> str:
    return f"{period_type} {period_end}"


def _year_fraction(start_date: str, end_date: str) -> float:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        return 0.0
    return (end - start).days / 365.25


def format_historical_value(value: Optional[float], value_kind: str) -> str:
    if value is None:
        return "n.b."
    if value_kind == "amount":
        return _format_amount(value)
    if value_kind == "percent":
        return f"{value:.1%}"
    if value_kind == "ratio":
        return f"{value:.1f}x"
    return f"{value:.1f}"


def _format_amount(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{format_compact_number(value / 1_000_000_000, decimals=1)} mld"
    if abs_value >= 1_000_000:
        return f"{format_compact_number(value / 1_000_000, decimals=1)} mln"
    return format_compact_number(value, decimals=1)
