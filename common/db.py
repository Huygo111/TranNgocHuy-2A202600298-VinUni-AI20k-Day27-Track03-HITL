"""SQLite helpers: connection + audit-event writer.

The `audit_events` table lives in the same .db file as the LangGraph
SQLite checkpointer tables — different schemas, same file.

`init_schema()` is idempotent and runs on the first connection, so students
don't need a separate setup step.
"""

from __future__ import annotations

import os
import sqlite3
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

from common.schemas import AuditEntry


SCHEMA_FILE = Path(__file__).resolve().parent.parent / "audit" / "schema.sql"
DEFAULT_DB_NAME = "hitl_audit.db"
FALLBACK_DB_NAME = "hitl_audit_runtime.db"
DEFAULT_CHECKPOINT_DB_NAME = "hitl_checkpoints.db"
FALLBACK_CHECKPOINT_DB_NAME = "hitl_checkpoints_runtime.db"
_RESOLVED_DB_PATH: str | None = None
_RESOLVED_CHECKPOINT_DB_PATH: str | None = None


def db_path() -> str:
    """Return the audit SQLite file path (override with HITL_DB_PATH env var)."""
    override = os.environ.get("HITL_DB_PATH")
    if override:
        return override

    global _RESOLVED_DB_PATH
    if _RESOLVED_DB_PATH is not None:
        return _RESOLVED_DB_PATH

    preferred = Path(DEFAULT_DB_NAME)
    fallback = Path(FALLBACK_DB_NAME)
    _RESOLVED_DB_PATH = str(preferred if _sqlite_usable(preferred) else fallback)
    return _RESOLVED_DB_PATH


def checkpoint_db_path() -> str:
    """Return the checkpoint SQLite file path."""
    override = os.environ.get("HITL_CHECKPOINT_DB_PATH")
    if override:
        return override

    global _RESOLVED_CHECKPOINT_DB_PATH
    if _RESOLVED_CHECKPOINT_DB_PATH is not None:
        return _RESOLVED_CHECKPOINT_DB_PATH

    preferred = Path(DEFAULT_CHECKPOINT_DB_NAME)
    fallback = Path(FALLBACK_CHECKPOINT_DB_NAME)
    _RESOLVED_CHECKPOINT_DB_PATH = str(
        preferred if _sqlite_usable(preferred) else fallback
    )
    return _RESOLVED_CHECKPOINT_DB_PATH


def _sqlite_usable(path: Path) -> bool:
    """Return True if the path can be used for SQLite writes in this environment."""
    try:
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=MEMORY")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("CREATE TABLE IF NOT EXISTS __db_probe (x INTEGER)")
        conn.commit()
        conn.execute("DROP TABLE __db_probe")
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error:
        return False


async def _ensure_schema(conn: aiosqlite.Connection) -> None:
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA journal_mode=MEMORY")
    await conn.execute("PRAGMA synchronous=NORMAL")
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'"
    ) as cur:
        if await cur.fetchone() is not None:
            return
    await conn.executescript(SCHEMA_FILE.read_text())
    await conn.commit()


@asynccontextmanager
async def db_conn() -> AsyncIterator[aiosqlite.Connection]:
    """Open an aiosqlite connection, applying schema if first use."""
    conn = await aiosqlite.connect(db_path())
    conn.row_factory = aiosqlite.Row
    try:
        await _ensure_schema(conn)
        yield conn
    finally:
        await conn.close()


async def write_audit_event(
    *,
    thread_id: str,
    pr_url: str,
    entry: AuditEntry,
) -> None:
    """Append one structured audit row.

    `thread_id` and `pr_url` are session-context columns (used for grouping
    and filtering); all other fields come from the `AuditEntry` so they map
    1-to-1 with first-class SQL columns.
    """
    for attempt in range(5):
        try:
            async with db_conn() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_events (
                        timestamp, thread_id, pr_url,
                        agent_id, action, confidence, risk_level,
                        reviewer_id, decision, reason, execution_time_ms
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.timestamp.isoformat(), thread_id, pr_url,
                        entry.agent_id, entry.action, entry.confidence, entry.risk_level,
                        entry.reviewer_id, entry.decision, entry.reason, entry.execution_time_ms,
                    ),
                )
                await conn.commit()
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 4:
                raise
            await asyncio.sleep(0.1 * (attempt + 1))


async def replay_events(thread_id: str) -> list[dict[str, Any]]:
    """Return every event for a thread, ordered by time. Used by audit/replay.py."""
    async with db_conn() as conn:
        async with conn.execute(
            """
            SELECT id, timestamp, agent_id, action, confidence, risk_level,
                   reviewer_id, decision, reason, execution_time_ms
              FROM audit_events
             WHERE thread_id = ?
             ORDER BY id
            """,
            (thread_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]
