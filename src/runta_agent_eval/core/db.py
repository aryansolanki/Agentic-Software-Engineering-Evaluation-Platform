from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    name TEXT NOT NULL,
    task TEXT NOT NULL,
    candidate_count INTEGER NOT NULL,
    evaluation_mode TEXT NOT NULL,
    request_json TEXT NOT NULL,
    winner_candidate_id TEXT,
    summary_json TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    runtime_id TEXT,
    runtime_name TEXT,
    status TEXT NOT NULL,
    test_exit_code INTEGER,
    deterministic_score REAL,
    ai_score REAL,
    final_score REAL,
    rank INTEGER,
    diff_text TEXT,
    test_output TEXT,
    agent_output TEXT,
    artifact_path TEXT,
    error TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT NOT NULL,
    run_id TEXT
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    async def init(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            def _init() -> None:
                with self._connect() as conn:
                    conn.executescript(SCHEMA)
                    conn.commit()
            await asyncio.to_thread(_init)
        except Exception:
            logger.exception("Database initialization failed")
            raise

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        try:
            def _write() -> None:
                with self._connect() as conn:
                    conn.execute(sql, params)
                    conn.commit()
            await asyncio.to_thread(_write)
        except Exception:
            logger.exception("Database write failed")
            raise

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        try:
            def _read() -> dict[str, Any] | None:
                with self._connect() as conn:
                    row = conn.execute(sql, params).fetchone()
                    return dict(row) if row else None
            return await asyncio.to_thread(_read)
        except Exception:
            logger.exception("Database fetchone failed")
            raise

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        try:
            def _read() -> list[dict[str, Any]]:
                with self._connect() as conn:
                    rows = conn.execute(sql, params).fetchall()
                    return [dict(row) for row in rows]
            return await asyncio.to_thread(_read)
        except Exception:
            logger.exception("Database fetchall failed")
            raise

    async def add_observation(self, created_at: str, category: str, title: str, details: str, run_id: str | None = None) -> None:
        await self.execute(
            "INSERT INTO observations(created_at, category, title, details, run_id) VALUES(?,?,?,?,?)",
            (created_at, category, title, details, run_id),
        )

    async def export_run(self, run_id: str) -> dict[str, Any]:
        try:
            run = await self.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))
            candidates = await self.fetchall("SELECT * FROM candidates WHERE run_id=? ORDER BY ordinal", (run_id,))
            observations = await self.fetchall("SELECT * FROM observations WHERE run_id=? ORDER BY id", (run_id,))
            return {"run": run, "candidates": candidates, "observations": observations}
        except Exception:
            logger.exception("Failed exporting run %s", run_id)
            raise


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
