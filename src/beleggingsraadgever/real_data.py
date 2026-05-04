"""Curated first real-company snapshots for local v1 experiments."""

from __future__ import annotations

from pathlib import Path

from .importer import import_company_snapshot
from .storage import SQLiteRepository

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
IMPORTS_DIR = DATA_DIR / "imports"
DRAFTS_DIR = DATA_DIR / "drafts"


def seed_curated_snapshots(repository: SQLiteRepository) -> None:
    """Load all curated company snapshots from the imports folder."""

    for path in sorted(IMPORTS_DIR.glob("*.json")):
        import_company_snapshot(repository, path)


def seed_besi(repository: SQLiteRepository) -> None:
    """Load the curated BESI v1 snapshot into the local database."""

    import_company_snapshot(repository, IMPORTS_DIR / "besi.json")
