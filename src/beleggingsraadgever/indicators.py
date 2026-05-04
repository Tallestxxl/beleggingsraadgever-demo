"""Rule-based scoring for the first advice engine."""

from __future__ import annotations

from typing import List, Tuple

from .models import FinancialSnapshot, MarketSnapshot, ScoreBreakdown


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def score_quality(financial: FinancialSnapshot) -> float:
    score, _ = score_quality_with_details(financial)
    return score


def score_quality_with_details(financial: FinancialSnapshot) -> Tuple[float, List[str]]:
    score = 50.0
    details = ["Startscore kwaliteit: 50.0"]

    if financial.operating_margin is not None:
        delta = (financial.operating_margin - 0.10) * 120
        score += delta
        details.append(f"Operationele marge {financial.operating_margin:.1%}: {_format_delta(delta)}")
    if financial.net_margin is not None:
        delta = (financial.net_margin - 0.08) * 90
        score += delta
        details.append(f"Nettomarge {financial.net_margin:.1%}: {_format_delta(delta)}")
    if financial.free_cash_flow is not None and financial.revenue:
        fcf_margin = financial.free_cash_flow / financial.revenue
        delta = (fcf_margin - 0.06) * 140
        score += delta
        details.append(f"Vrije kasstroommarge {fcf_margin:.1%}: {_format_delta(delta)}")
    if financial.debt is not None and financial.free_cash_flow:
        debt_to_fcf = financial.debt / max(abs(financial.free_cash_flow), 1.0)
        if debt_to_fcf > 5:
            details.append(f"Schuld/vrije kasstroom {debt_to_fcf:.1f}x: -20.0")
            score -= 20
        elif debt_to_fcf < 2:
            details.append(f"Schuld/vrije kasstroom {debt_to_fcf:.1f}x: +8.0")
            score += 8
    if financial.cash is not None and financial.debt is not None and financial.cash > financial.debt:
        details.append("Cashpositie groter dan schuld: +5.0")
        score += 5

    return _finalize_score(score, details)


def score_valuation(market: MarketSnapshot) -> float:
    score, _ = score_valuation_with_details(market)
    return score


def score_valuation_with_details(market: MarketSnapshot) -> Tuple[float, List[str]]:
    score = 50.0
    details = ["Startscore waardering: 50.0"]

    if market.pe_ratio is not None:
        if market.pe_ratio <= 12:
            score += 18
            details.append(f"Koers-winstverhouding {market.pe_ratio:.1f}: +18.0")
        elif market.pe_ratio <= 20:
            score += 8
            details.append(f"Koers-winstverhouding {market.pe_ratio:.1f}: +8.0")
        elif market.pe_ratio <= 30:
            score -= 4
            details.append(f"Koers-winstverhouding {market.pe_ratio:.1f}: -4.0")
        else:
            score -= 18
            details.append(f"Koers-winstverhouding {market.pe_ratio:.1f}: -18.0")

    if market.ev_ebitda is not None:
        if market.ev_ebitda <= 8:
            score += 12
            details.append(f"EV/EBITDA {market.ev_ebitda:.1f}: +12.0")
        elif market.ev_ebitda <= 14:
            score += 4
            details.append(f"EV/EBITDA {market.ev_ebitda:.1f}: +4.0")
        elif market.ev_ebitda > 22:
            score -= 14
            details.append(f"EV/EBITDA {market.ev_ebitda:.1f}: -14.0")

    if market.fcf_yield is not None:
        delta = (market.fcf_yield - 0.04) * 220
        score += delta
        details.append(f"FCF-yield {market.fcf_yield:.1%}: {_format_delta(delta)}")

    return _finalize_score(score, details)


def score_momentum(market: MarketSnapshot) -> float:
    score, _ = score_momentum_with_details(market)
    return score


def score_momentum_with_details(market: MarketSnapshot) -> Tuple[float, List[str]]:
    score = 50.0
    details = ["Startscore momentum: 50.0"]

    if market.momentum_12m is not None:
        delta = market.momentum_12m * 80
        score += delta
        details.append(f"12-maands momentum {market.momentum_12m:.1%}: {_format_delta(delta)}")
    if market.volatility_1y is not None:
        delta = -max(0.0, market.volatility_1y - 0.25) * 60
        score += delta
        details.append(f"1-jaars volatiliteit {market.volatility_1y:.1%}: {_format_delta(delta)}")

    return _finalize_score(score, details)


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
    quality, quality_details = score_quality_with_details(financial)
    valuation, valuation_details = score_valuation_with_details(market)
    momentum, momentum_details = score_momentum_with_details(market)
    flags = risk_flags(financial, market)
    risk = clamp(100 - len(flags) * 15)
    total = quality * 0.40 + valuation * 0.30 + momentum * 0.15 + risk * 0.15
    risk_details = ["Startscore risico: 100.0"]
    if flags:
        risk_details.extend(f"{flag}: -15.0" for flag in flags)
    else:
        risk_details.append("Geen risicoflags: +0.0")
    risk_details.append(f"Ruwe risicoscore na flags: {100 - len(flags) * 15:.1f}")
    risk_details.append(f"Eindscore risico na begrenzing 0-100: {risk:.1f}")
    total_details = [
        "Gewichten totaalscore: kwaliteit 40%, waardering 30%, momentum 15%, risico 15%",
        (
            f"Berekening: {quality:.1f}*0.40 + {valuation:.1f}*0.30 + "
            f"{momentum:.1f}*0.15 + {risk:.1f}*0.15 = {round(total, 1):.1f}"
        ),
    ]

    return ScoreBreakdown(
        quality=quality,
        valuation=valuation,
        momentum=momentum,
        risk=round(risk, 1),
        total=round(total, 1),
        flags=flags,
        details={
            "quality": quality_details,
            "valuation": valuation_details,
            "momentum": momentum_details,
            "risk": risk_details,
            "total": total_details,
        },
    )


def _format_delta(delta: float) -> str:
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.1f}"


def _finalize_score(score: float, details: List[str]) -> Tuple[float, List[str]]:
    details.append(f"Ruwe score voor begrenzing: {score:.1f}")
    bounded = round(clamp(score), 1)
    details.append(f"Eindscore na begrenzing 0-100: {bounded:.1f}")
    return bounded, details


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
