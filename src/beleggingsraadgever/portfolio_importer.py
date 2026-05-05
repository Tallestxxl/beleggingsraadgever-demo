"""Import broker portfolio CSV reports."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from .models import PortfolioPosition, PortfolioPrice
from .storage import SQLiteRepository


BROKER_NAME_ALIASES = {
    "AALBERTS": "AALB",
    "AKZO NOBEL": "AKZA",
    "ALFEN": "ALFEN",
    "APERAM": "APERAM",
    "ASML HOLDING": "ASML",
    "AVANTIUM": "AVTX",
    "BAM GROEP": "BAMNB",
    "BE SEMICONDUCTOR IND": "BESI",
    "CORBION": "CRBN",
    "DSM FIRMENICH": "DSFIR",
    "EBUSCO HOLDING": "EBUS",
    "FUGRO": "FUGRO",
    "INTUITIVE MACHINES": "LUNR",
    "INVESC FTSE RAFI US": "INVESCO_RAFI_US",
    "KPN": "KPN",
    "NEDAP": "NEDAP",
    "RANDSTAD": "RAND",
    "REDWIRE": "RDW",
    "ROCKET LAB": "RKLB",
    "SHELL": "SHELL",
    "TKH GROUP": "TWEKA",
    "UNILEVER": "UNA",
    "VANG FTSE ALL WORLD": "VWRL",
    "XTRACK HEALTH CARE": "XDWH",
}


@dataclass(frozen=True)
class PortfolioCsvImportResult:
    imported_positions: int = 0
    imported_market_prices: int = 0
    skipped_rows: list[str] = field(default_factory=list)
    as_of: str = ""

    @property
    def summary(self) -> str:
        skipped = f", {len(self.skipped_rows)} overgeslagen" if self.skipped_rows else ""
        return f"CSV-import klaar: {self.imported_positions} posities, {self.imported_market_prices} koersen{skipped}."


def import_portfolio_csv(repository: SQLiteRepository, path: Path) -> PortfolioCsvImportResult:
    csv_path = Path(path).expanduser()
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV-bestand niet gevonden: {csv_path}")

    rows = list(csv.reader(csv_path.read_text(encoding="utf-8-sig").splitlines()))
    if not rows:
        raise ValueError("CSV-bestand is leeg.")

    as_of = _parse_report_date(rows[0]) or date.today().isoformat()
    header_index = _find_header_index(rows)
    headers = [header.strip() for header in rows[header_index]]
    imported_positions = 0
    imported_market_prices = 0
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
        imported_positions += 1

        if market_price is not None and market_price > 0:
            repository.upsert_portfolio_price(
                PortfolioPrice(symbol=symbol, as_of=as_of, close_price=market_price, currency=currency)
            )
            imported_market_prices += 1

    return PortfolioCsvImportResult(
        imported_positions=imported_positions,
        imported_market_prices=imported_market_prices,
        skipped_rows=skipped_rows,
        as_of=as_of,
    )


def normalize_broker_name(name: str) -> str:
    cleaned = _clean_name(name)
    for prefix, symbol in BROKER_NAME_ALIASES.items():
        if cleaned == prefix or cleaned.startswith(prefix + " "):
            return symbol
    return re.sub(r"[^A-Z0-9]+", "_", cleaned).strip("_")[:24]


def _find_header_index(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows):
        normalized = [cell.strip() for cell in row]
        if "Naam" in normalized and "Aantal" in normalized and "Koers" in normalized:
            return index
    raise ValueError("CSV-header met Naam/Aantal/Koers niet gevonden.")


def _record_from_row(headers: list[str], row: list[str]) -> dict[str, str]:
    padded = row + [""] * max(0, len(headers) - len(row))
    return {header: padded[index].strip() for index, header in enumerate(headers) if header}


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.upper().replace("/KON/", "").replace("  ", " ").split())
    cleaned = cleaned.replace(" PLC", "").replace(" /KON/", "")
    return cleaned


def _parse_number(value: str) -> Optional[float]:
    text = value.strip().upper()
    if not text:
        return None
    text = text.replace("ST", "").replace("EUR", "").replace("%", "").strip()
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
