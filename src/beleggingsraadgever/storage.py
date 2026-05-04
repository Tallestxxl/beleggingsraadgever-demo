"""SQLite repository for local-first storage."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional

from .knowledge import HashingVectorizer, chunk_text, cosine_similarity
from .models import FinancialSnapshot, KnowledgeHit, MacroObservation, MarketSnapshot, Principle

DEFAULT_DB_PATH = Path("data/beleggingsraadgever.sqlite")


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

CREATE TABLE IF NOT EXISTS advice_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  verdict TEXT NOT NULL,
  conviction TEXT NOT NULL,
  report_markdown TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
