"""Helpers for matching broker names, tickers and provider symbols."""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from .models import DataSource, PortfolioAlias


BROKER_NAME_ALIASES = {
    "AALBERTS": "AALB",
    "AKZO NOBEL": "AKZA",
    "ALFEN": "ALFEN",
    "APERAM": "APERAM",
    "ASMI": "ASMI",
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


def candidate_portfolio_symbols(symbol: str, data_sources: Iterable[DataSource] = ()) -> list[str]:
    candidates: list[str] = []

    def add(candidate: str) -> None:
        normalized = normalize_symbol(candidate)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    add(symbol)
    add(normalize_broker_name(symbol))
    for source in data_sources:
        for candidate in provider_symbols_from_url(source.source_url):
            add(candidate)
    return candidates


def aliases_for_portfolio_input(
    portfolio_symbol: str,
    *,
    raw_name: str = "",
    source: str = "",
) -> list[PortfolioAlias]:
    aliases: list[PortfolioAlias] = []

    def add(value: str, alias_type: str, raw_value: str = "") -> None:
        alias_key = normalize_symbol(value)
        if not alias_key or any(alias.alias_key == alias_key for alias in aliases):
            return
        aliases.append(
            PortfolioAlias(
                portfolio_symbol=normalize_symbol(portfolio_symbol),
                alias_key=alias_key,
                alias_type=alias_type,
                raw_value=raw_value or value,
                source=source,
            )
        )

    add(portfolio_symbol, "portfolio_symbol", portfolio_symbol)
    if raw_name:
        add(raw_name, "broker_name", raw_name)
        add(clean_investment_name(raw_name), "broker_name_clean", raw_name)
        add(normalize_broker_name(raw_name), "broker_normalized_symbol", raw_name)
    return aliases


def aliases_for_data_sources(
    portfolio_symbol: str,
    data_sources: Iterable[DataSource],
    *,
    source: str = "analysis",
) -> list[PortfolioAlias]:
    aliases: list[PortfolioAlias] = []
    seen: set[str] = set()
    for data_source in data_sources:
        for provider_symbol in provider_symbols_from_url(data_source.source_url):
            alias_key = normalize_symbol(provider_symbol)
            if not alias_key or alias_key in seen:
                continue
            seen.add(alias_key)
            aliases.append(
                PortfolioAlias(
                    portfolio_symbol=normalize_symbol(portfolio_symbol),
                    alias_key=alias_key,
                    alias_type="provider_symbol",
                    raw_value=provider_symbol,
                    source=source,
                )
            )
    return aliases


def normalize_broker_name(name: str) -> str:
    cleaned = clean_investment_name(name)
    for prefix, symbol in BROKER_NAME_ALIASES.items():
        if cleaned == prefix or cleaned.startswith(prefix + " "):
            return symbol
    return re.sub(r"[^A-Z0-9]+", "_", cleaned).strip("_")[:24]


def clean_investment_name(name: str) -> str:
    cleaned = " ".join(name.upper().replace("/KON/", "").replace("  ", " ").split())
    cleaned = cleaned.replace(" PLC", "").replace(" /KON/", "")
    return cleaned


def normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper()
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1]
    if cleaned.endswith((".AS", ".NL")):
        cleaned = cleaned.rsplit(".", 1)[0]
    if "." in cleaned:
        cleaned = cleaned.replace(".", "_")
    return re.sub(r"[^A-Z0-9_]+", "_", cleaned).strip("_")


def provider_symbols_from_url(url: str) -> list[str]:
    if not url:
        return []
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    candidates: list[str] = []
    if len(parts) >= 3 and parts[0].lower() == "quote":
        candidates.append(parts[2])
    if len(parts) >= 2 and parts[0].lower() == "stocks":
        candidates.append(parts[1])
    query_symbol = parse_qs(parsed.query).get("s", [""])[0]
    if query_symbol:
        candidates.append(query_symbol)
    return candidates
