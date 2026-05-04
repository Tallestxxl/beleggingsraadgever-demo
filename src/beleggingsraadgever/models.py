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
class Principle:
    title: str
    statement: str
    category: str
    approved: bool = True
    source_document_id: Optional[int] = None
    confidence: float = 1.0
    principle_id: Optional[int] = None


@dataclass(frozen=True)
class ScoreBreakdown:
    quality: float
    valuation: float
    momentum: float
    risk: float
    total: float
    flags: List[str] = field(default_factory=list)


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

