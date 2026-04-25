from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_HOME = ".agentos"


@dataclass
class RunRecord:
    run_id: str
    intent: str
    source: str
    command: str
    started_at: str
    finished_at: str
    exit_code: int
    duration_ms: int
    trace_path: str


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def resolve_home(agentos_home: str | None = None) -> Path:
    return Path(agentos_home or os.getenv("AGENTOS_HOME") or DEFAULT_HOME)


def db_path(home: Path) -> Path:
    return home / "agentos.db"


def ensure_schema(home: Path) -> sqlite3.Connection:
    home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path(home))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            intent TEXT NOT NULL,
            source TEXT NOT NULL,
            command TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            exit_code INTEGER NOT NULL,
            duration_ms INTEGER NOT NULL,
            trace_path TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            decision_key TEXT,
            payload_json TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        )
        """
    )
    conn.commit()
    return conn


def create_run_id(provided_run_id: str | None = None) -> str:
    return provided_run_id or f"run_{uuid.uuid4().hex[:12]}"


def trace_file(home: Path, run_id: str) -> Path:
    return home / "runs" / run_id / "trace.jsonl"


def append_trace(home: Path, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    path = trace_file(home, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": utc_now_iso(),
                    "run_id": run_id,
                    "type": event_type,
                    "payload": payload,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def record_event(conn: sqlite3.Connection, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO events(run_id, ts, type, payload_json) VALUES (?, ?, ?, ?)",
        (run_id, utc_now_iso(), event_type, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()


def record_run(conn: sqlite3.Connection, run: RunRecord) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO runs(
            run_id, intent, source, command, started_at, finished_at,
            exit_code, duration_ms, trace_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.run_id,
            run.intent,
            run.source,
            run.command,
            run.started_at,
            run.finished_at,
            run.exit_code,
            run.duration_ms,
            run.trace_path,
        ),
    )
    conn.commit()


def list_runs(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
    )
    return list(cursor.fetchall())


def get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    return cursor.fetchone()


def record_decision(
    conn: sqlite3.Connection,
    run_id: str,
    decision_key: str | None,
    payload: dict[str, Any],
) -> int:
    cursor = conn.execute(
        "INSERT INTO decisions(run_id, ts, decision_key, payload_json) VALUES (?, ?, ?, ?)",
        (run_id, utc_now_iso(), decision_key, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    return int(cursor.lastrowid)


def list_decisions(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
        SELECT id, run_id, ts, decision_key, payload_json
        FROM decisions
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return list(cursor.fetchall())


def get_decision(conn: sqlite3.Connection, decision_id: int) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
        SELECT id, run_id, ts, decision_key, payload_json
        FROM decisions
        WHERE id = ?
        """,
        (decision_id,),
    )
    return cursor.fetchone()


def record_outcome(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    payload: dict[str, Any],
) -> int:
    cursor = conn.execute(
        "INSERT INTO outcomes(run_id, ts, status, payload_json) VALUES (?, ?, ?, ?)",
        (run_id, utc_now_iso(), status, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    return int(cursor.lastrowid)
