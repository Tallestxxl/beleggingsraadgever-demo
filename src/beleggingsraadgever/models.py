"""Core dataclasses for the beleggingsraadgever domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FinancialSnapshot:
    symbol: str
    period_end: str
    period_type: str
    revenue: float
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    free_cash_flow: Optional[float] = None
    debt: Optional[float] = None
    cash: Optional[float] = None
    shares_outstanding: Optional[float] = None
    dividend_per_share: Optional[float] = None
    buyback_value: Optional[float] = None


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    as_of: str
    close_price: float
    currency: str = "EUR"
    pe_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None
    fcf_yield: Optional[float] = None
    dividend_yield: Optional[float] = None
    momentum_12m: Optional[float] = None
    volatility_1y: Optional[float] = None


@dataclass(frozen=True)
class MacroObservation:
    indicator: str
    region: str
    as_of: str
    value: float
    unit: str = ""


@dataclass(frozen=True)
class PortfolioPosition:
    symbol: str
    quantity: float
    average_cost: float
    currency: str
    account: str
    as_of: str


@dataclass(frozen=True)
class PortfolioPrice:
    symbol: str
    as_of: str
    close_price: float
    currency: str = "EUR"
    source: str = "portfolio_csv"


@dataclass(frozen=True)
class PortfolioPerformanceSummary:
    as_of: str
    period_label: str
    total_result: Optional[float] = None
    unrealized_result: Optional[float] = None
    realized_result: Optional[float] = None
    dividend_coupons: Optional[float] = None
    currency: str = "EUR"
    source: str = "portfolio_csv"


@dataclass(frozen=True)
class PortfolioPositionPerformance:
    symbol: str
    account: str
    as_of: str
    status: str = ""
    dividend_coupons: Optional[float] = None
    dividend_currency: str = "EUR"
    result_pct: Optional[float] = None
    result_value: Optional[float] = None
    result_currency: str = "EUR"
    source: str = "portfolio_csv"


@dataclass(frozen=True)
class PortfolioClassification:
    symbol: str
    sector: str
    theme: str


@dataclass(frozen=True)
class CompanyProfile:
    symbol: str
    company_name: str = ""
    provider_symbol: str = ""
    source_name: str = ""
    source_url: str = ""
    as_of: str = ""
    sector: str = ""
    industry: str = ""
    description: str = ""
    classification_confidence: float = 0.0
    classification_source: str = ""


@dataclass(frozen=True)
class PortfolioAlias:
    portfolio_symbol: str
    alias_key: str
    alias_type: str
    raw_value: str = ""
    source: str = ""


@dataclass(frozen=True)
class InvestorProfile:
    age: Optional[int] = None
    annual_income: Optional[float] = None
    horizon_years: Optional[int] = None
    cash_buffer: Optional[float] = None
    risk_profile: str = "gebalanceerd"


@dataclass(frozen=True)
class PortfolioAsset:
    asset_type: str
    value: float
    currency: str = "EUR"
    as_of: str = ""
    note: str = ""


@dataclass(frozen=True)
class PortfolioFit:
    summary: str
    position_value: float
    position_weight: float
    max_weight: float
    room_to_max: float
    total_wealth: float
    transaction_action: str = "watchlist"
    transaction_label: str = "Watchlist"
    position_room: float = 0.0
    cash_value: Optional[float] = None
    cash_buffer: Optional[float] = None
    available_cash: Optional[float] = None
    max_new_buy_amount: float = 0.0
    practical_buy_amount: float = 0.0
    buy_room_factor: float = 0.0
    sector: str = "Onbekend"
    sector_value: float = 0.0
    sector_weight: float = 0.0
    theme: str = "Onbekend"
    theme_value: float = 0.0
    theme_weight: float = 0.0
    buy_room_limits: List[str] = field(default_factory=list)
    buy_room_calculation: List[str] = field(default_factory=list)
    transaction_rationale: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeChunk:
    document_id: int
    chunk_index: int
    text: str
    tags: List[str] = field(default_factory=list)
    embedding: List[float] = field(default_factory=list)
    chunk_id: Optional[int] = None


@dataclass(frozen=True)
class KnowledgeHit:
    chunk: KnowledgeChunk
    score: float
    title: str
    source_type: str
    publication_date: Optional[str] = None


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: int
    title: str
    source_type: str
    raw_text: str
    author: Optional[str] = None
    publication_date: Optional[str] = None
    source_path: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    chunk_count: int = 0
    status: str = "vertrouwd"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class Principle:
    title: str
    statement: str
    category: str
    approved: bool = True
    source_document_id: Optional[int] = None
    confidence: float = 1.0
    principle_id: Optional[int] = None


@dataclass(frozen=True)
class DataSource:
    symbol: str
    field_name: str
    value_label: str
    source_name: str
    source_url: str
    source_date: str
    source_quality: str
    note: str = ""
    source_id: Optional[int] = None


@dataclass(frozen=True)
class ScoreBreakdown:
    quality: float
    valuation: float
    momentum: float
    risk: float
    total: float
    flags: List[str] = field(default_factory=list)
    details: Dict[str, List[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class PeerComparisonRow:
    symbol: str
    is_target: bool
    revenue: Optional[float] = None
    operating_margin: Optional[float] = None
    fcf_margin: Optional[float] = None
    debt_to_fcf: Optional[float] = None
    pe_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None
    fcf_yield: Optional[float] = None
    dividend_yield: Optional[float] = None
    momentum_12m: Optional[float] = None
    quality_score: float = 0.0
    valuation_score: float = 0.0


@dataclass(frozen=True)
class PeerAnalysis:
    group_label: str
    summary: str
    rows: List[PeerComparisonRow]
    notes: List[str] = field(default_factory=list)
    available_peer_count: int = 0
    configured_peer_count: int = 0
    max_peer_count: int = 0
    min_peer_count: int = 0


@dataclass(frozen=True)
class PeerCandidate:
    symbol: str
    peer_symbol: str
    peer_group: str
    source: str
    confidence: float
    reason: str = ""
    status: str = "vertrouwd"


@dataclass(frozen=True)
class AdviceReport:
    symbol: str
    verdict: str
    conviction: str
    score: ScoreBreakdown
    summary: str
    evidence: List[KnowledgeHit]
    data_freshness: Dict[str, str]
    assumptions: List[str] = field(default_factory=list)
    data_sources: List[DataSource] = field(default_factory=list)
    portfolio_fit: Optional[PortfolioFit] = None
    peer_analysis: Optional[PeerAnalysis] = None
