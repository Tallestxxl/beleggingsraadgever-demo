"""Rule-based scoring for the first advice engine."""

from __future__ import annotations

from typing import List

from .models import FinancialSnapshot, MarketSnapshot, ScoreBreakdown


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def score_quality(financial: FinancialSnapshot) -> float:
    score = 50.0

    if financial.operating_margin is not None:
        score += (financial.operating_margin - 0.10) * 120
    if financial.net_margin is not None:
        score += (financial.net_margin - 0.08) * 90
    if financial.free_cash_flow is not None and financial.revenue:
        fcf_margin = financial.free_cash_flow / financial.revenue
        score += (fcf_margin - 0.06) * 140
    if financial.debt is not None and financial.free_cash_flow:
        debt_to_fcf = financial.debt / max(abs(financial.free_cash_flow), 1.0)
        if debt_to_fcf > 5:
            score -= 20
        elif debt_to_fcf < 2:
            score += 8
    if financial.cash is not None and financial.debt is not None and financial.cash > financial.debt:
        score += 5

    return round(clamp(score), 1)


def score_valuation(market: MarketSnapshot) -> float:
    score = 50.0

    if market.pe_ratio is not None:
        if market.pe_ratio <= 12:
            score += 18
        elif market.pe_ratio <= 20:
            score += 8
        elif market.pe_ratio <= 30:
            score -= 4
        else:
            score -= 18

    if market.ev_ebitda is not None:
        if market.ev_ebitda <= 8:
            score += 12
        elif market.ev_ebitda <= 14:
            score += 4
        elif market.ev_ebitda > 22:
            score -= 14

    if market.fcf_yield is not None:
        score += (market.fcf_yield - 0.04) * 220

    return round(clamp(score), 1)


def score_momentum(market: MarketSnapshot) -> float:
    score = 50.0

    if market.momentum_12m is not None:
        score += market.momentum_12m * 80
    if market.volatility_1y is not None:
        score -= max(0.0, market.volatility_1y - 0.25) * 60

    return round(clamp(score), 1)


def risk_flags(financial: FinancialSnapshot, market: MarketSnapshot) -> List[str]:
    flags: List[str] = []

    if financial.free_cash_flow is not None and financial.free_cash_flow < 0:
        flags.append("Negatieve vrije kasstroom")
    if financial.debt is not None and financial.free_cash_flow:
        if financial.debt / max(abs(financial.free_cash_flow), 1.0) > 5:
            flags.append("Hoge schuld ten opzichte van vrije kasstroom")
    if market.pe_ratio is not None and market.pe_ratio > 35:
        flags.append("Hoge multiple vraagt sterke groei")
    if market.volatility_1y is not None and market.volatility_1y > 0.40:
        flags.append("Hoge koersvolatiliteit")
    if market.dividend_yield is not None and market.dividend_yield > 0.08:
        flags.append("Hoog dividendrendement kan dividendvalkuil zijn")

    return flags


def build_score(financial: FinancialSnapshot, market: MarketSnapshot) -> ScoreBreakdown:
    quality = score_quality(financial)
    valuation = score_valuation(market)
    momentum = score_momentum(market)
    flags = risk_flags(financial, market)
    risk = clamp(100 - len(flags) * 15)
    total = quality * 0.40 + valuation * 0.30 + momentum * 0.15 + risk * 0.15

    return ScoreBreakdown(
        quality=quality,
        valuation=valuation,
        momentum=momentum,
        risk=round(risk, 1),
        total=round(total, 1),
        flags=flags,
    )


def verdict_from_score(score: ScoreBreakdown) -> str:
    if score.total >= 78 and not score.flags:
        return "Koopwaardig"
    if score.total >= 68:
        return "Kopen op zwakte"
    if score.total >= 52:
        return "Houden / verder onderzoeken"
    if score.total >= 40:
        return "Afbouwen of vermijden"
    return "Vermijden"


def conviction_from_score(score: ScoreBreakdown) -> str:
    if score.total >= 75 or score.total <= 35:
        return "hoog"
    if score.total >= 60 or score.total <= 45:
        return "middel"
    return "laag"

