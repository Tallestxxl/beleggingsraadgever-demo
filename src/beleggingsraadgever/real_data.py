"""Curated first real-company snapshots for local v1 experiments."""

from __future__ import annotations

from pathlib import Path

from .importer import import_company_snapshot
from .storage import SQLiteRepository

IMPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "imports"


def seed_besi(repository: SQLiteRepository) -> None:
    """Load the curated BESI v1 snapshot into the local database."""

    import_company_snapshot(repository, IMPORTS_DIR / "besi.json")

