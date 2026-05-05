"""Import broker portfolio CSV reports."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from .classification import classify_symbol
from .identity import normalize_broker_name
from .models import (
    PortfolioClassification,
    PortfolioPerformanceSummary,
    PortfolioPosition,
    PortfolioPositionPerformance,
    PortfolioPrice,
)
from .storage import SQLiteRepository


@dataclass(frozen=True)
class PortfolioCsvImportResult:
    imported_positions: int = 0
    imported_market_prices: int = 0
    imported_position_performance: int = 0
    imported_performance_summary: bool = False
    skipped_rows: list[str] = field(default_factory=list)
    as_of: str = ""

    @property
    def summary(self) -> str:
        skipped = f", {len(self.skipped_rows)} overgeslagen" if self.skipped_rows else ""
        performance = f", {self.imported_position_performance} resultaatregels"
        total = ", historische samenvatting" if self.imported_performance_summary else ""
        return (
            f"CSV-import klaar: {self.imported_positions} posities, "
            f"{self.imported_market_prices} koersen{performance}{total}{skipped}."
        )


def import_portfolio_csv(repository: SQLiteRepository, path: Path) -> PortfolioCsvImportResult:
    csv_path = Path(path).expanduser()
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV-bestand niet gevonden: {csv_path}")

    rows = list(csv.reader(csv_path.read_text(encoding="utf-8-sig").splitlines()))
    if not rows:
        raise ValueError("CSV-bestand is leeg.")

    as_of = _parse_report_date(rows[0]) or date.today().isoformat()
    header_index = _find_header_index(rows)
    performance_summary = _parse_performance_summary(rows[:header_index], as_of)
    imported_performance_summary = False
    if performance_summary is not None:
        repository.upsert_portfolio_performance_summary(performance_summary)
        imported_performance_summary = True
    headers = [header.strip() for header in rows[header_index]]
    imported_positions = 0
    imported_market_prices = 0
    imported_position_performance = 0
    skipped_rows: list[str] = []

    for row in rows[header_index + 1 :]:
        record = _record_from_row(headers, row)
        name = (record.get("Naam") or "").strip()
        account = (record.get("Beleggen") or "").strip()
        if not name or not account:
            continue
        if name.upper().startswith("DIV "):
            skipped_rows.append(name)
            continue

        symbol = normalize_broker_name(name)
        quantity = _parse_number(record.get("Aantal") or "")
        average_cost = _parse_number(record.get("Kostpr. per eenheid") or "")
        market_price = _parse_number(record.get("Koers") or "")
        currency = (record.get("Valuta koers") or record.get("Valuta kostpr. per eenheid") or "EUR").strip() or "EUR"

        if quantity is None or average_cost is None:
            skipped_rows.append(name)
            continue

        repository.upsert_portfolio_position(
            PortfolioPosition(
                symbol=symbol,
                quantity=quantity,
                average_cost=average_cost,
                currency=currency,
                account=account,
                as_of=as_of,
            )
        )
        classification = classify_symbol(symbol)
        repository.upsert_portfolio_classification(
            PortfolioClassification(symbol=symbol, sector=classification.sector, theme=classification.theme)
        )
        imported_positions += 1

        if market_price is not None and market_price > 0:
            repository.upsert_portfolio_price(
                PortfolioPrice(symbol=symbol, as_of=as_of, close_price=market_price, currency=currency)
            )
            imported_market_prices += 1

        dividend_coupons = _parse_number(record.get("Dividend / Coupons") or "")
        result_pct = _parse_percent(record.get("Resultaat %") or "")
        result_value = _parse_number(record.get("Resultaat EUR") or "")
        if any(value is not None for value in [dividend_coupons, result_pct, result_value]):
            repository.upsert_portfolio_position_performance(
                PortfolioPositionPerformance(
                    symbol=symbol,
                    account=account,
                    as_of=as_of,
                    status=(record.get("Status") or "").strip(),
                    dividend_coupons=dividend_coupons,
                    dividend_currency=(record.get("Valuta Dividend / Coupons") or "EUR").strip() or "EUR",
                    result_pct=result_pct,
                    result_value=result_value,
                    result_currency="EUR",
                )
            )
            imported_position_performance += 1

    return PortfolioCsvImportResult(
        imported_positions=imported_positions,
        imported_market_prices=imported_market_prices,
        imported_position_performance=imported_position_performance,
        imported_performance_summary=imported_performance_summary,
        skipped_rows=skipped_rows,
        as_of=as_of,
    )


def _find_header_index(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows):
        normalized = [cell.strip() for cell in row]
        if "Naam" in normalized and "Aantal" in normalized and "Koers" in normalized:
            return index
    raise ValueError("CSV-header met Naam/Aantal/Koers niet gevonden.")


def _record_from_row(headers: list[str], row: list[str]) -> dict[str, str]:
    padded = row + [""] * max(0, len(headers) - len(row))
    return {header: padded[index].strip() for index, header in enumerate(headers) if header}


def _parse_number(value: str) -> Optional[float]:
    text = value.strip().upper()
    if not text:
        return None
    text = text.replace("ST", "").replace("EUR", "").replace("USD", "").replace("GBP", "").replace("%", "").strip()
    negative = text.startswith("-") or text.startswith("- ")
    text = text.replace("-", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(".", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _parse_percent(value: str) -> Optional[float]:
    number = _parse_number(value)
    if number is None:
        return None
    return number / 100 if "%" in value else number


def _parse_performance_summary(rows: list[list[str]], as_of: str) -> Optional[PortfolioPerformanceSummary]:
    period_label = ""
    total_result = None
    unrealized_result = None
    realized_result = None
    dividend_coupons = None
    currency = "EUR"

    for row in rows:
        if len(row) < 2:
            continue
        label = row[0].strip()
        value_text = row[1].strip()
        if not label or not value_text:
            continue
        parsed_value = _parse_number(value_text)
        if parsed_value is None:
            continue
        parsed_currency = _parse_currency(value_text)
        if parsed_currency:
            currency = parsed_currency
        normalized_label = label.lower()
        if normalized_label.startswith("resultaten"):
            period_label = _summary_period_label(label)
            total_result = parsed_value
        elif normalized_label.startswith("ongerealiseerd resultaat"):
            unrealized_result = parsed_value
        elif normalized_label.startswith("gerealiseerd resultaat"):
            realized_result = parsed_value
        elif normalized_label.startswith("dividend en coupons"):
            dividend_coupons = parsed_value

    if all(value is None for value in [total_result, unrealized_result, realized_result, dividend_coupons]):
        return None
    return PortfolioPerformanceSummary(
        as_of=as_of,
        period_label=period_label or "Onbekend",
        total_result=total_result,
        unrealized_result=unrealized_result,
        realized_result=realized_result,
        dividend_coupons=dividend_coupons,
        currency=currency,
    )


def _summary_period_label(label: str) -> str:
    parts = [part.strip() for part in label.split("|", maxsplit=1)]
    return parts[1] if len(parts) == 2 and parts[1] else label.strip()


def _parse_currency(value: str) -> str:
    match = re.search(r"\b(EUR|USD|GBP|CHF)\b", value.upper())
    return match.group(1) if match else ""


def _parse_report_date(row: list[str]) -> Optional[str]:
    text = " | ".join(row).lower()
    match = re.search(r"(\d{1,2})\s+([a-z.]+)(\d{2})", text)
    if not match:
        return None
    day = int(match.group(1))
    month_token = match.group(2).strip(".")
    year = 2000 + int(match.group(3))
    months = {
        "jan": 1,
        "feb": 2,
        "mrt": 3,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "mei": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "okt": 10,
        "nov": 11,
        "dec": 12,
    }
    month = months.get(month_token)
    if month is None:
        return None
    return date(year, month, day).isoformat()
