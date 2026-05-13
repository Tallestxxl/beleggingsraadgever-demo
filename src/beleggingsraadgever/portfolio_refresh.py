"""Portfolio-wide snapshot freshness and refresh workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .classification import classify_company
from .collector import FetchText, MarketData, collect_market_data, market_data_sources
from .models import (
    CompanyProfile,
    DataSource,
    FinancialSnapshot,
    MarketSnapshot,
    PortfolioClassification,
    PortfolioPrice,
)
from .peer_discovery import refresh_peer_candidates
from .provider_identity import trusted_provider_symbols
from .storage import SQLiteRepository


MARKET_STALE_DAYS = 7
FUNDAMENTAL_STALE_DAYS = 180


@dataclass(frozen=True)
class PortfolioSnapshotStatus:
    symbol: str
    needs_refresh: bool
    reasons: list[str] = field(default_factory=list)
    market_as_of: str = ""
    financial_period_end: str = ""
    financial_period_type: str = ""
    market_age_days: Optional[int] = None
    financial_age_days: Optional[int] = None


@dataclass(frozen=True)
class PortfolioSnapshotRefreshItem:
    symbol: str
    refreshed: bool = False
    skipped: bool = False
    updated_fields: list[str] = field(default_factory=list)
    message: str = ""
    error: str = ""


@dataclass(frozen=True)
class PortfolioSnapshotRefreshResult:
    items: list[PortfolioSnapshotRefreshItem]

    @property
    def refreshed_count(self) -> int:
        return sum(1 for item in self.items if item.refreshed)

    @property
    def skipped_count(self) -> int:
        return sum(1 for item in self.items if item.skipped)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if item.error)

    @property
    def summary(self) -> str:
        details = (
            f"{self.refreshed_count} bijgewerkt, "
            f"{self.skipped_count} actueel overgeslagen, "
            f"{self.failed_count} fout(en)"
        )
        failures = [f"{item.symbol}: {item.error}" for item in self.items if item.error]
        if failures:
            details += ". Eerste fout: " + failures[0]
        return f"Portefeuille-snapshots ververst: {details}."


def portfolio_snapshot_statuses(
    repository: SQLiteRepository,
    *,
    today: Optional[date] = None,
) -> list[PortfolioSnapshotStatus]:
    symbols = sorted({position.symbol.upper() for position in repository.latest_portfolio_positions()})
    return [portfolio_snapshot_status(repository, symbol, today=today) for symbol in symbols]


def portfolio_snapshot_status(
    repository: SQLiteRepository,
    symbol: str,
    *,
    today: Optional[date] = None,
) -> PortfolioSnapshotStatus:
    normalized_symbol = symbol.strip().upper()
    reference_date = today or date.today()
    reasons: list[str] = []
    market_as_of = ""
    financial_period_end = ""
    financial_period_type = ""
    market_age = None
    financial_age = None

    try:
        market = repository.latest_market_snapshot(normalized_symbol)
        market_as_of = market.as_of
        market_age = _days_old(market.as_of, today=reference_date)
        if market_age is None:
            reasons.append("Koersdatum is niet leesbaar.")
        elif market_age > MARKET_STALE_DAYS:
            reasons.append(f"Koerssnapshot ouder dan {MARKET_STALE_DAYS} dagen.")
    except LookupError:
        reasons.append("Koerssnapshot ontbreekt.")

    try:
        financial = repository.latest_financial_snapshot(normalized_symbol)
        financial_period_end = financial.period_end
        financial_period_type = financial.period_type
        financial_age = _days_old(financial.period_end, today=reference_date)
        if financial_age is None:
            reasons.append("Fundamentaldatum is niet leesbaar.")
        elif financial_age > FUNDAMENTAL_STALE_DAYS:
            reasons.append(f"Fundamentalsnapshot ouder dan {FUNDAMENTAL_STALE_DAYS} dagen.")
    except LookupError:
        reasons.append("Fundamentalsnapshot ontbreekt.")

    return PortfolioSnapshotStatus(
        symbol=normalized_symbol,
        needs_refresh=bool(reasons),
        reasons=reasons,
        market_as_of=market_as_of,
        financial_period_end=financial_period_end,
        financial_period_type=financial_period_type,
        market_age_days=market_age,
        financial_age_days=financial_age,
    )


def refresh_portfolio_snapshots(
    repository: SQLiteRepository,
    *,
    fetch_text: Optional[FetchText] = None,
    only_stale: bool = True,
    today: Optional[date] = None,
) -> PortfolioSnapshotRefreshResult:
    items: list[PortfolioSnapshotRefreshItem] = []
    statuses = portfolio_snapshot_statuses(repository, today=today)
    for status in statuses:
        if only_stale and not status.needs_refresh:
            items.append(
                PortfolioSnapshotRefreshItem(
                    symbol=status.symbol,
                    skipped=True,
                    message="Snapshot is nog actueel.",
                )
            )
            continue

        try:
            preferred_symbols = trusted_provider_symbols(repository, status.symbol)
            market_data = collect_market_data(
                status.symbol,
                fetch_text=fetch_text,
                preferred_stockanalysis_symbols=preferred_symbols,
            )
            updated_fields = store_collected_market_data(repository, status.symbol, market_data)
            items.append(
                PortfolioSnapshotRefreshItem(
                    symbol=status.symbol,
                    refreshed=True,
                    updated_fields=updated_fields,
                    message=(
                        f"{market_data.provider} {market_data.provider_symbol} "
                        f"t/m {market_data.as_of}."
                    ),
                )
            )
        except Exception as error:  # pragma: no cover - exact provider errors vary.
            items.append(PortfolioSnapshotRefreshItem(symbol=status.symbol, error=str(error)))
    return PortfolioSnapshotRefreshResult(items)


def store_collected_market_data(
    repository: SQLiteRepository,
    symbol: str,
    market_data: MarketData,
) -> list[str]:
    normalized_symbol = symbol.strip().upper()
    updated_fields = ["market_snapshot", "portfolio_price"]
    repository.upsert_market_snapshot(
        MarketSnapshot(
            symbol=normalized_symbol,
            as_of=market_data.as_of,
            close_price=market_data.close_price,
            currency=market_data.currency,
            pe_ratio=market_data.pe_ratio,
            ev_ebitda=market_data.ev_ebitda,
            fcf_yield=market_data.fcf_yield,
            dividend_yield=market_data.dividend_yield,
            momentum_12m=market_data.momentum_12m,
            volatility_1y=market_data.volatility_1y,
        )
    )
    repository.upsert_portfolio_price(
        PortfolioPrice(
            symbol=normalized_symbol,
            as_of=market_data.as_of,
            close_price=market_data.close_price,
            currency=market_data.currency,
            source="snapshot_refresh",
        )
    )

    if market_data.revenue is not None and market_data.period_end and market_data.period_type:
        repository.upsert_financial_snapshot(
            FinancialSnapshot(
                symbol=normalized_symbol,
                period_end=market_data.period_end,
                period_type=market_data.period_type,
                revenue=market_data.revenue,
                gross_margin=market_data.gross_margin,
                operating_margin=market_data.operating_margin,
                net_margin=market_data.net_margin,
                free_cash_flow=market_data.free_cash_flow,
                debt=market_data.debt,
                cash=market_data.cash,
                shares_outstanding=market_data.shares_outstanding,
                dividend_per_share=market_data.dividend_per_share,
            )
        )
        updated_fields.append("financial_snapshot")

    for source in market_data_sources(market_data):
        repository.upsert_data_source(DataSource(symbol=normalized_symbol, **source))
    updated_fields.append("data_sources")

    if market_data.company_name or market_data.sector or market_data.industry or market_data.description:
        classification = classify_company(
            normalized_symbol,
            company_name=market_data.company_name,
            provider_sector=market_data.sector,
            provider_industry=market_data.industry,
            description=market_data.description,
        )
        repository.upsert_company_profile(
            CompanyProfile(
                symbol=normalized_symbol,
                company_name=market_data.company_name or "",
                provider_symbol=market_data.provider_symbol,
                source_name=market_data.provider,
                source_url=market_data.source_url,
                as_of=market_data.as_of,
                sector=market_data.sector or "",
                industry=market_data.industry or "",
                description=market_data.description or "",
                classification_confidence=classification.confidence,
                classification_source=classification.source,
            )
        )
        updated_fields.append("company_profile")
        if classification.sector != "Onbekend" or classification.theme != "Onbekend":
            repository.upsert_portfolio_classification(
                PortfolioClassification(
                    symbol=normalized_symbol,
                    sector=classification.sector,
                    theme=classification.theme,
                )
            )
            refresh_peer_candidates(repository, normalized_symbol)
            updated_fields.append("classification")

    return updated_fields


def _days_old(value: str, *, today: date) -> Optional[int]:
    try:
        return (today - date.fromisoformat(value)).days
    except (TypeError, ValueError):
        return None
