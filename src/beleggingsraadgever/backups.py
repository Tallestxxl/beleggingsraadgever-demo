"""Versioned local database backups."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class DatabaseBackup:
    path: Path
    metadata_path: Path
    created_at: str
    reason: str
    label: str
    size_bytes: int
    portfolio_positions: int
    portfolio_assets: int
    investor_profiles: int

    @property
    def filename(self) -> str:
        return self.path.name


def create_database_backup(db_path: Path, reason: str, backup_dir: Optional[Path] = None) -> DatabaseBackup:
    """Create a timestamped SQLite backup without overwriting earlier versions."""

    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"Database niet gevonden: {source}")

    label = database_label(source)
    target_dir = backup_dir or default_backup_dir(source)
    target_dir.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now().isoformat(timespec="seconds")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    reason_slug = _slugify(reason)
    target = _unique_path(target_dir / f"{stamp}-{label}-{reason_slug}.sqlite")

    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        target_conn = sqlite3.connect(target)
        try:
            source_conn.backup(target_conn)
            target_conn.commit()
            integrity = target_conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise sqlite3.DatabaseError(f"backup integrity_check failed: {integrity}")
        finally:
            target_conn.close()
    finally:
        source_conn.close()

    counts = _database_counts(target)
    metadata = {
        "created_at": created_at,
        "reason": reason,
        "label": label,
        "source_path": str(source),
        "backup_path": str(target),
        "size_bytes": target.stat().st_size,
        **counts,
    }
    metadata_path = target.with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return DatabaseBackup(
        path=target,
        metadata_path=metadata_path,
        created_at=created_at,
        reason=reason,
        label=label,
        size_bytes=target.stat().st_size,
        portfolio_positions=counts["portfolio_positions"],
        portfolio_assets=counts["portfolio_assets"],
        investor_profiles=counts["investor_profiles"],
    )


def list_database_backups(db_path: Path, backup_dir: Optional[Path] = None) -> list[DatabaseBackup]:
    label = database_label(Path(db_path))
    target_dir = backup_dir or default_backup_dir(Path(db_path))
    if not target_dir.exists():
        return []
    backups: list[DatabaseBackup] = []
    for path in sorted(target_dir.glob(f"*-{label}-*.sqlite")):
        metadata_path = path.with_suffix(".json")
        metadata = _read_metadata(metadata_path)
        counts = _database_counts(path)
        backups.append(
            DatabaseBackup(
                path=path,
                metadata_path=metadata_path,
                created_at=str(metadata.get("created_at") or _created_at_from_name(path)),
                reason=str(metadata.get("reason") or "onbekend"),
                label=str(metadata.get("label") or label),
                size_bytes=path.stat().st_size,
                portfolio_positions=counts["portfolio_positions"],
                portfolio_assets=counts["portfolio_assets"],
                investor_profiles=counts["investor_profiles"],
            )
        )
    return sorted(backups, key=lambda backup: backup.path.name, reverse=True)


def latest_database_backup(db_path: Path, backup_dir: Optional[Path] = None) -> Optional[DatabaseBackup]:
    backups = list_database_backups(db_path, backup_dir=backup_dir)
    return backups[0] if backups else None


def default_backup_dir(db_path: Path) -> Path:
    """Choose the project backup directory, even when the live DB runs from /private/tmp."""

    source = Path(db_path)
    if str(source).startswith("/private/tmp/"):
        project_backup_dir = Path.cwd() / "data" / "local" / "backups"
        if project_backup_dir.parent.exists():
            return project_backup_dir
    return source.parent / "backups"


def database_label(db_path: Path) -> str:
    stem = Path(db_path).stem.lower()
    if "demo" in stem:
        return "demo"
    return "private"


def _database_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {
            "portfolio_positions": _count_table(conn, tables, "portfolio_positions"),
            "portfolio_assets": _count_table(conn, tables, "portfolio_assets"),
            "investor_profiles": _count_table(conn, tables, "investor_profile"),
        }


def _count_table(conn: sqlite3.Connection, tables: set[str], table: str) -> int:
    if table not in tables:
        return 0
    return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _read_metadata(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _created_at_from_name(path: Path) -> str:
    match = re.match(r"(\d{8})-(\d{6})", path.name)
    if not match:
        return ""
    date_part, time_part = match.groups()
    return (
        f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}T"
        f"{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "backup"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index:03d}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Geen vrije backupnaam gevonden voor {path}")
