"""SQLite repository for local-first storage."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional

from .knowledge import HashingVectorizer, chunk_text, cosine_similarity
from .models import (
    DataSource,
    FinancialSnapshot,
    InvestorProfile,
    KnowledgeHit,
    MacroObservation,
    MarketSnapshot,
    PortfolioAsset,
    PortfolioAlias,
    PortfolioClassification,
    PortfolioPerformanceSummary,
    PortfolioPrice,
    PortfolioPositionPerformance,
    PortfolioPosition,
    Principle,
)

DEFAULT_DB_PATH = Path("data/local/beleggingsraadgever.sqlite")


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_type TEXT NOT NULL,
  title TEXT NOT NULL,
  author TEXT,
  publication_date TEXT,
  source_path TEXT,
  checksum TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  embedding_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS principles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  statement TEXT NOT NULL,
  category TEXT NOT NULL,
  source_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  approved INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tickers (
  symbol TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  exchange TEXT,
  region TEXT,
  currency TEXT,
  sector TEXT,
  industry TEXT
);

CREATE TABLE IF NOT EXISTS financial_snapshots (
  symbol TEXT NOT NULL,
  period_end TEXT NOT NULL,
  period_type TEXT NOT NULL,
  revenue REAL NOT NULL,
  gross_margin REAL,
  operating_margin REAL,
  net_margin REAL,
  free_cash_flow REAL,
  debt REAL,
  cash REAL,
  shares_outstanding REAL,
  dividend_per_share REAL,
  buyback_value REAL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(symbol, period_end, period_type)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
  symbol TEXT NOT NULL,
  as_of TEXT NOT NULL,
  close_price REAL NOT NULL,
  currency TEXT NOT NULL,
  pe_ratio REAL,
  ev_ebitda REAL,
  fcf_yield REAL,
  dividend_yield REAL,
  momentum_12m REAL,
  volatility_1y REAL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(symbol, as_of)
);

CREATE TABLE IF NOT EXISTS macro_observations (
  indicator TEXT NOT NULL,
  region TEXT NOT NULL,
  as_of TEXT NOT NULL,
  value REAL NOT NULL,
  unit TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(indicator, region, as_of)
);

CREATE TABLE IF NOT EXISTS portfolio_positions (
  symbol TEXT NOT NULL,
  quantity REAL NOT NULL,
  average_cost REAL NOT NULL,
  currency TEXT NOT NULL,
  account TEXT NOT NULL,
  as_of TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(symbol, account, as_of)
);

CREATE TABLE IF NOT EXISTS investor_profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  age INTEGER,
  annual_income REAL,
  horizon_years INTEGER,
  cash_buffer REAL,
  risk_profile TEXT NOT NULL DEFAULT 'gebalanceerd',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_assets (
  asset_type TEXT PRIMARY KEY,
  value REAL NOT NULL,
  currency TEXT NOT NULL DEFAULT 'EUR',
  as_of TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_prices (
  symbol TEXT NOT NULL,
  as_of TEXT NOT NULL,
  close_price REAL NOT NULL,
  currency TEXT NOT NULL DEFAULT 'EUR',
  source TEXT NOT NULL DEFAULT 'portfolio_csv',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(symbol, as_of, source)
);

CREATE TABLE IF NOT EXISTS portfolio_performance_summaries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of TEXT NOT NULL,
  period_label TEXT NOT NULL,
  total_result REAL,
  unrealized_result REAL,
  realized_result REAL,
  dividend_coupons REAL,
  currency TEXT NOT NULL DEFAULT 'EUR',
  source TEXT NOT NULL DEFAULT 'portfolio_csv',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(as_of, period_label, source)
);

CREATE TABLE IF NOT EXISTS portfolio_position_performance (
  symbol TEXT NOT NULL,
  account TEXT NOT NULL,
  as_of TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '',
  dividend_coupons REAL,
  dividend_currency TEXT NOT NULL DEFAULT 'EUR',
  result_pct REAL,
  result_value REAL,
  result_currency TEXT NOT NULL DEFAULT 'EUR',
  source TEXT NOT NULL DEFAULT 'portfolio_csv',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(symbol, account, as_of, source)
);

CREATE TABLE IF NOT EXISTS portfolio_classifications (
  symbol TEXT PRIMARY KEY,
  sector TEXT NOT NULL,
  theme TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_aliases (
  alias_key TEXT PRIMARY KEY,
  portfolio_symbol TEXT NOT NULL,
  alias_type TEXT NOT NULL,
  raw_value TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS advice_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  verdict TEXT NOT NULL,
  conviction TEXT NOT NULL,
  report_markdown TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  field_name TEXT NOT NULL,
  value_label TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_date TEXT NOT NULL,
  source_quality TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(symbol, field_name, source_name, source_date)
);

CREATE TABLE IF NOT EXISTS snapshot_imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  imported_from TEXT NOT NULL,
  imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  source_checksum TEXT NOT NULL,
  processed_path TEXT,
  UNIQUE(symbol, source_checksum)
);
"""


class SQLiteRepository:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH, vectorizer: Optional[HashingVectorizer] = None) -> None:
        self.db_path = Path(db_path)
        self.vectorizer = vectorizer or HashingVectorizer()

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._backfill_portfolio_aliases(conn)

    def _upsert_portfolio_alias(self, conn: sqlite3.Connection, alias: PortfolioAlias) -> None:
        from .identity import normalize_symbol

        alias_key = normalize_symbol(alias.alias_key)
        portfolio_symbol = normalize_symbol(alias.portfolio_symbol)
        if not alias_key or not portfolio_symbol:
            return
        conn.execute(
            """
            INSERT INTO portfolio_aliases (alias_key, portfolio_symbol, alias_type, raw_value, source)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(alias_key) DO UPDATE SET
              portfolio_symbol=excluded.portfolio_symbol,
              alias_type=excluded.alias_type,
              raw_value=excluded.raw_value,
              source=excluded.source,
              updated_at=CURRENT_TIMESTAMP
            """,
            (alias_key, portfolio_symbol, alias.alias_type, alias.raw_value, alias.source),
        )

    def _backfill_portfolio_aliases(self, conn: sqlite3.Connection) -> None:
        from .identity import BROKER_NAME_ALIASES, aliases_for_portfolio_input

        rows = conn.execute("SELECT DISTINCT symbol FROM portfolio_positions").fetchall()
        existing_symbols = {row["symbol"] for row in rows}
        for symbol in existing_symbols:
            for alias in aliases_for_portfolio_input(symbol, source="backfill"):
                self._upsert_portfolio_alias(conn, alias)

        for broker_name, portfolio_symbol in BROKER_NAME_ALIASES.items():
            if portfolio_symbol not in existing_symbols:
                continue
            for alias in aliases_for_portfolio_input(portfolio_symbol, raw_name=broker_name, source="known_alias"):
                self._upsert_portfolio_alias(conn, alias)

    def add_document(
        self,
        *,
        title: str,
        source_type: str,
        raw_text: str,
        author: Optional[str] = None,
        publication_date: Optional[str] = None,
        source_path: Optional[str] = None,
        tags: Iterable[str] = (),
    ) -> int:
        checksum = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT id FROM documents
                WHERE source_type = ? AND checksum = ?
                LIMIT 1
                """,
                (source_type, checksum),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])

            cursor = conn.execute(
                """
                INSERT INTO documents
                  (source_type, title, author, publication_date, source_path, checksum, raw_text)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (source_type, title, author, publication_date, source_path, checksum, raw_text),
            )
            document_id = int(cursor.lastrowid)

            chunks = chunk_text(raw_text, document_id=document_id, tags=tags)
            for chunk in chunks:
                embedding = self.vectorizer.vectorize(chunk.text)
                conn.execute(
                    """
                    INSERT INTO knowledge_chunks
                      (document_id, chunk_index, text, tags_json, embedding_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        chunk.chunk_index,
                        chunk.text,
                        json.dumps(chunk.tags),
                        json.dumps(embedding),
                    ),
                )

        return document_id

    def add_principle(self, principle: Principle) -> int:
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT id FROM principles
                WHERE title = ? AND category = ? AND statement = ?
                LIMIT 1
                """,
                (principle.title, principle.category, principle.statement),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])

            cursor = conn.execute(
                """
                INSERT INTO principles
                  (title, statement, category, source_document_id, confidence, approved)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    principle.title,
                    principle.statement,
                    principle.category,
                    principle.source_document_id,
                    principle.confidence,
                    1 if principle.approved else 0,
                ),
            )
            return int(cursor.lastrowid)

    def approved_principles(self) -> List[Principle]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, statement, category, source_document_id, confidence, approved
                FROM principles
                WHERE approved = 1
                ORDER BY category, title
                """
            ).fetchall()

        return [
            Principle(
                principle_id=row["id"],
                title=row["title"],
                statement=row["statement"],
                category=row["category"],
                source_document_id=row["source_document_id"],
                confidence=row["confidence"],
                approved=bool(row["approved"]),
            )
            for row in rows
        ]

    def search_knowledge(self, query: str, limit: int = 5) -> List[KnowledgeHit]:
        query_vector = self.vectorizer.vectorize(query)
        hits: List[KnowledgeHit] = []

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  kc.id AS chunk_id,
                  kc.document_id,
                  kc.chunk_index,
                  kc.text,
                  kc.tags_json,
                  kc.embedding_json,
                  d.title,
                  d.source_type,
                  d.publication_date
                FROM knowledge_chunks kc
                JOIN documents d ON d.id = kc.document_id
                """
            ).fetchall()

        for row in rows:
            embedding = json.loads(row["embedding_json"])
            score = cosine_similarity(query_vector, embedding)
            if score <= 0:
                continue
            from .models import KnowledgeChunk

            hits.append(
                KnowledgeHit(
                    chunk=KnowledgeChunk(
                        chunk_id=row["chunk_id"],
                        document_id=row["document_id"],
                        chunk_index=row["chunk_index"],
                        text=row["text"],
                        tags=json.loads(row["tags_json"]),
                        embedding=embedding,
                    ),
                    score=score,
                    title=row["title"],
                    source_type=row["source_type"],
                    publication_date=row["publication_date"],
                )
            )

        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]

    def upsert_financial_snapshot(self, snapshot: FinancialSnapshot) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO financial_snapshots (
                  symbol, period_end, period_type, revenue, gross_margin, operating_margin,
                  net_margin, free_cash_flow, debt, cash, shares_outstanding,
                  dividend_per_share, buyback_value
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, period_end, period_type) DO UPDATE SET
                  revenue=excluded.revenue,
                  gross_margin=excluded.gross_margin,
                  operating_margin=excluded.operating_margin,
                  net_margin=excluded.net_margin,
                  free_cash_flow=excluded.free_cash_flow,
                  debt=excluded.debt,
                  cash=excluded.cash,
                  shares_outstanding=excluded.shares_outstanding,
                  dividend_per_share=excluded.dividend_per_share,
                  buyback_value=excluded.buyback_value
                """,
                (
                    snapshot.symbol,
                    snapshot.period_end,
                    snapshot.period_type,
                    snapshot.revenue,
                    snapshot.gross_margin,
                    snapshot.operating_margin,
                    snapshot.net_margin,
                    snapshot.free_cash_flow,
                    snapshot.debt,
                    snapshot.cash,
                    snapshot.shares_outstanding,
                    snapshot.dividend_per_share,
                    snapshot.buyback_value,
                ),
            )

    def upsert_market_snapshot(self, snapshot: MarketSnapshot) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO market_snapshots (
                  symbol, as_of, close_price, currency, pe_ratio, ev_ebitda,
                  fcf_yield, dividend_yield, momentum_12m, volatility_1y
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, as_of) DO UPDATE SET
                  close_price=excluded.close_price,
                  currency=excluded.currency,
                  pe_ratio=excluded.pe_ratio,
                  ev_ebitda=excluded.ev_ebitda,
                  fcf_yield=excluded.fcf_yield,
                  dividend_yield=excluded.dividend_yield,
                  momentum_12m=excluded.momentum_12m,
                  volatility_1y=excluded.volatility_1y
                """,
                (
                    snapshot.symbol,
                    snapshot.as_of,
                    snapshot.close_price,
                    snapshot.currency,
                    snapshot.pe_ratio,
                    snapshot.ev_ebitda,
                    snapshot.fcf_yield,
                    snapshot.dividend_yield,
                    snapshot.momentum_12m,
                    snapshot.volatility_1y,
                ),
            )

    def upsert_macro_observation(self, observation: MacroObservation) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO macro_observations (indicator, region, as_of, value, unit)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(indicator, region, as_of) DO UPDATE SET
                  value=excluded.value,
                  unit=excluded.unit
                """,
                (
                    observation.indicator,
                    observation.region,
                    observation.as_of,
                    observation.value,
                    observation.unit,
                ),
            )

    def save_investor_profile(self, profile: InvestorProfile) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO investor_profile (
                  id, age, annual_income, horizon_years, cash_buffer, risk_profile
                )
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  age=excluded.age,
                  annual_income=excluded.annual_income,
                  horizon_years=excluded.horizon_years,
                  cash_buffer=excluded.cash_buffer,
                  risk_profile=excluded.risk_profile,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (
                    profile.age,
                    profile.annual_income,
                    profile.horizon_years,
                    profile.cash_buffer,
                    profile.risk_profile,
                ),
            )

    def investor_profile(self) -> Optional[InvestorProfile]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT age, annual_income, horizon_years, cash_buffer, risk_profile
                FROM investor_profile
                WHERE id = 1
                """
            ).fetchone()
        if row is None:
            return None
        return InvestorProfile(
            age=row["age"],
            annual_income=row["annual_income"],
            horizon_years=row["horizon_years"],
            cash_buffer=row["cash_buffer"],
            risk_profile=row["risk_profile"],
        )

    def upsert_portfolio_asset(self, asset: PortfolioAsset) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_assets (asset_type, value, currency, as_of, note)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(asset_type) DO UPDATE SET
                  value=excluded.value,
                  currency=excluded.currency,
                  as_of=excluded.as_of,
                  note=excluded.note,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (asset.asset_type, asset.value, asset.currency, asset.as_of, asset.note),
            )

    def portfolio_assets(self) -> List[PortfolioAsset]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT asset_type, value, currency, as_of, note
                FROM portfolio_assets
                ORDER BY asset_type
                """
            ).fetchall()
        return [
            PortfolioAsset(
                asset_type=row["asset_type"],
                value=row["value"],
                currency=row["currency"],
                as_of=row["as_of"],
                note=row["note"],
            )
            for row in rows
        ]

    def upsert_portfolio_position(self, position: PortfolioPosition) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_positions (
                  symbol, quantity, average_cost, currency, account, as_of
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, account, as_of) DO UPDATE SET
                  quantity=excluded.quantity,
                  average_cost=excluded.average_cost,
                  currency=excluded.currency
                """,
                (
                    position.symbol.upper(),
                    position.quantity,
                    position.average_cost,
                    position.currency,
                    position.account,
                    position.as_of,
                ),
            )
            from .identity import aliases_for_portfolio_input

            for alias in aliases_for_portfolio_input(position.symbol, source="portfolio_position"):
                self._upsert_portfolio_alias(conn, alias)

    def upsert_portfolio_price(self, price: PortfolioPrice) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_prices (symbol, as_of, close_price, currency, source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol, as_of, source) DO UPDATE SET
                  close_price=excluded.close_price,
                  currency=excluded.currency
                """,
                (price.symbol.upper(), price.as_of, price.close_price, price.currency, price.source),
            )

    def upsert_portfolio_performance_summary(self, summary: PortfolioPerformanceSummary) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_performance_summaries (
                  as_of, period_label, total_result, unrealized_result, realized_result,
                  dividend_coupons, currency, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(as_of, period_label, source) DO UPDATE SET
                  total_result=excluded.total_result,
                  unrealized_result=excluded.unrealized_result,
                  realized_result=excluded.realized_result,
                  dividend_coupons=excluded.dividend_coupons,
                  currency=excluded.currency,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (
                    summary.as_of,
                    summary.period_label,
                    summary.total_result,
                    summary.unrealized_result,
                    summary.realized_result,
                    summary.dividend_coupons,
                    summary.currency,
                    summary.source,
                ),
            )

    def latest_portfolio_performance_summary(self) -> Optional[PortfolioPerformanceSummary]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT as_of, period_label, total_result, unrealized_result, realized_result,
                       dividend_coupons, currency, source
                FROM portfolio_performance_summaries
                ORDER BY as_of DESC, updated_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return PortfolioPerformanceSummary(
            as_of=row["as_of"],
            period_label=row["period_label"],
            total_result=row["total_result"],
            unrealized_result=row["unrealized_result"],
            realized_result=row["realized_result"],
            dividend_coupons=row["dividend_coupons"],
            currency=row["currency"],
            source=row["source"],
        )

    def upsert_portfolio_position_performance(self, performance: PortfolioPositionPerformance) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_position_performance (
                  symbol, account, as_of, status, dividend_coupons, dividend_currency,
                  result_pct, result_value, result_currency, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, account, as_of, source) DO UPDATE SET
                  status=excluded.status,
                  dividend_coupons=excluded.dividend_coupons,
                  dividend_currency=excluded.dividend_currency,
                  result_pct=excluded.result_pct,
                  result_value=excluded.result_value,
                  result_currency=excluded.result_currency,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (
                    performance.symbol.upper(),
                    performance.account,
                    performance.as_of,
                    performance.status,
                    performance.dividend_coupons,
                    performance.dividend_currency,
                    performance.result_pct,
                    performance.result_value,
                    performance.result_currency,
                    performance.source,
                ),
            )

    def latest_portfolio_position_performances(self) -> List[PortfolioPositionPerformance]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.symbol, p.account, p.as_of, p.status, p.dividend_coupons,
                       p.dividend_currency, p.result_pct, p.result_value,
                       p.result_currency, p.source
                FROM portfolio_position_performance p
                JOIN (
                  SELECT symbol, account, source, MAX(as_of) AS max_as_of
                  FROM portfolio_position_performance
                  GROUP BY symbol, account, source
                ) latest
                  ON latest.symbol = p.symbol
                 AND latest.account = p.account
                 AND latest.source = p.source
                 AND latest.max_as_of = p.as_of
                ORDER BY p.symbol, p.account
                """
            ).fetchall()
        return [
            PortfolioPositionPerformance(
                symbol=row["symbol"],
                account=row["account"],
                as_of=row["as_of"],
                status=row["status"],
                dividend_coupons=row["dividend_coupons"],
                dividend_currency=row["dividend_currency"],
                result_pct=row["result_pct"],
                result_value=row["result_value"],
                result_currency=row["result_currency"],
                source=row["source"],
            )
            for row in rows
        ]

    def upsert_portfolio_classification(self, classification: PortfolioClassification) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_classifications (symbol, sector, theme)
                VALUES (?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                  sector=excluded.sector,
                  theme=excluded.theme,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (classification.symbol.upper(), classification.sector, classification.theme),
            )

    def portfolio_classification(self, symbol: str) -> Optional[PortfolioClassification]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT symbol, sector, theme
                FROM portfolio_classifications
                WHERE symbol = ?
                """,
                (symbol.upper(),),
            ).fetchone()
        if row is None:
            return None
        return PortfolioClassification(symbol=row["symbol"], sector=row["sector"], theme=row["theme"])

    def portfolio_classifications(self) -> List[PortfolioClassification]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol, sector, theme
                FROM portfolio_classifications
                ORDER BY symbol
                """
            ).fetchall()
        return [
            PortfolioClassification(symbol=row["symbol"], sector=row["sector"], theme=row["theme"])
            for row in rows
        ]

    def upsert_portfolio_alias(self, alias: PortfolioAlias) -> None:
        with self.connect() as conn:
            self._upsert_portfolio_alias(conn, alias)

    def upsert_portfolio_aliases(self, aliases: Iterable[PortfolioAlias]) -> None:
        with self.connect() as conn:
            for alias in aliases:
                self._upsert_portfolio_alias(conn, alias)

    def resolve_portfolio_aliases(self, aliases: Iterable[str]) -> dict[str, str]:
        from .identity import normalize_symbol

        normalized = []
        seen = set()
        for alias in aliases:
            key = normalize_symbol(alias)
            if key and key not in seen:
                normalized.append(key)
                seen.add(key)
        if not normalized:
            return {}

        placeholders = ", ".join("?" for _ in normalized)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT alias_key, portfolio_symbol
                FROM portfolio_aliases
                WHERE alias_key IN ({placeholders})
                """,
                normalized,
            ).fetchall()
        return {row["alias_key"]: row["portfolio_symbol"] for row in rows}

    def portfolio_aliases(self) -> List[PortfolioAlias]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT portfolio_symbol, alias_key, alias_type, raw_value, source
                FROM portfolio_aliases
                ORDER BY portfolio_symbol, alias_type, alias_key
                """
            ).fetchall()
        return [
            PortfolioAlias(
                portfolio_symbol=row["portfolio_symbol"],
                alias_key=row["alias_key"],
                alias_type=row["alias_type"],
                raw_value=row["raw_value"],
                source=row["source"],
            )
            for row in rows
        ]

    def portfolio_aliases_for_symbol(self, symbol: str) -> List[PortfolioAlias]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT portfolio_symbol, alias_key, alias_type, raw_value, source
                FROM portfolio_aliases
                WHERE portfolio_symbol = ?
                ORDER BY alias_type, alias_key
                """,
                (symbol.upper(),),
            ).fetchall()
        return [
            PortfolioAlias(
                portfolio_symbol=row["portfolio_symbol"],
                alias_key=row["alias_key"],
                alias_type=row["alias_type"],
                raw_value=row["raw_value"],
                source=row["source"],
            )
            for row in rows
        ]

    def latest_portfolio_price(self, symbol: str) -> Optional[PortfolioPrice]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT symbol, as_of, close_price, currency, source
                FROM portfolio_prices
                WHERE symbol = ?
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (symbol.upper(),),
            ).fetchone()
        if row is None:
            return None
        return PortfolioPrice(
            symbol=row["symbol"],
            as_of=row["as_of"],
            close_price=row["close_price"],
            currency=row["currency"],
            source=row["source"],
        )

    def latest_portfolio_positions(self) -> List[PortfolioPosition]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.symbol, p.quantity, p.average_cost, p.currency, p.account, p.as_of
                FROM portfolio_positions p
                JOIN (
                  SELECT symbol, account, MAX(as_of) AS max_as_of
                  FROM portfolio_positions
                  GROUP BY symbol, account
                ) latest
                  ON latest.symbol = p.symbol
                 AND latest.account = p.account
                 AND latest.max_as_of = p.as_of
                ORDER BY p.symbol, p.account
                """
            ).fetchall()
        return [
            PortfolioPosition(
                symbol=row["symbol"],
                quantity=row["quantity"],
                average_cost=row["average_cost"],
                currency=row["currency"],
                account=row["account"],
                as_of=row["as_of"],
            )
            for row in rows
        ]

    def upsert_data_source(self, source: DataSource) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO data_sources (
                  symbol, field_name, value_label, source_name, source_url,
                  source_date, source_quality, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, field_name, source_name, source_date) DO UPDATE SET
                  value_label=excluded.value_label,
                  source_url=excluded.source_url,
                  source_quality=excluded.source_quality,
                  note=excluded.note
                """,
                (
                    source.symbol.upper(),
                    source.field_name,
                    source.value_label,
                    source.source_name,
                    source.source_url,
                    source.source_date,
                    source.source_quality,
                    source.note,
                ),
            )

    def record_snapshot_import(
        self,
        *,
        symbol: str,
        imported_from: str,
        source_checksum: str,
        processed_path: Optional[str] = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO snapshot_imports (
                  symbol, imported_from, source_checksum, processed_path
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol, source_checksum) DO UPDATE SET
                  imported_from=excluded.imported_from,
                  imported_at=CURRENT_TIMESTAMP,
                  processed_path=COALESCE(excluded.processed_path, snapshot_imports.processed_path)
                """,
                (symbol.upper(), imported_from, source_checksum, processed_path),
            )

    def data_sources_for_symbol(self, symbol: str) -> List[DataSource]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, field_name, value_label, source_name, source_url,
                       source_date, source_quality, note
                FROM data_sources
                WHERE symbol = ?
                ORDER BY field_name, source_quality, source_date DESC
                """,
                (symbol.upper(),),
            ).fetchall()

        return [
            DataSource(
                source_id=row["id"],
                symbol=row["symbol"],
                field_name=row["field_name"],
                value_label=row["value_label"],
                source_name=row["source_name"],
                source_url=row["source_url"],
                source_date=row["source_date"],
                source_quality=row["source_quality"],
                note=row["note"],
            )
            for row in rows
        ]

    def latest_financial_snapshot(self, symbol: str) -> FinancialSnapshot:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM financial_snapshots
                WHERE symbol = ?
                ORDER BY period_end DESC
                LIMIT 1
                """,
                (symbol.upper(),),
            ).fetchone()
        if row is None:
            raise LookupError(f"No financial snapshot found for {symbol}")
        return FinancialSnapshot(
            symbol=row["symbol"],
            period_end=row["period_end"],
            period_type=row["period_type"],
            revenue=row["revenue"],
            gross_margin=row["gross_margin"],
            operating_margin=row["operating_margin"],
            net_margin=row["net_margin"],
            free_cash_flow=row["free_cash_flow"],
            debt=row["debt"],
            cash=row["cash"],
            shares_outstanding=row["shares_outstanding"],
            dividend_per_share=row["dividend_per_share"],
            buyback_value=row["buyback_value"],
        )

    def latest_market_snapshot(self, symbol: str) -> MarketSnapshot:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM market_snapshots
                WHERE symbol = ?
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (symbol.upper(),),
            ).fetchone()
        if row is None:
            raise LookupError(f"No market snapshot found for {symbol}")
        return MarketSnapshot(
            symbol=row["symbol"],
            as_of=row["as_of"],
            close_price=row["close_price"],
            currency=row["currency"],
            pe_ratio=row["pe_ratio"],
            ev_ebitda=row["ev_ebitda"],
            fcf_yield=row["fcf_yield"],
            dividend_yield=row["dividend_yield"],
            momentum_12m=row["momentum_12m"],
            volatility_1y=row["volatility_1y"],
        )

    def symbols_with_snapshots(self) -> List[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT financial.symbol AS symbol
                FROM financial_snapshots financial
                INNER JOIN market_snapshots market
                   ON market.symbol = financial.symbol
                ORDER BY financial.symbol
                """
            ).fetchall()
        return [row["symbol"] for row in rows]
