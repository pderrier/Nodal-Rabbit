from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass
class PromotedRuleRecord:
    rule_id: str
    decision_key: str
    candidate_choice: str
    status: str
    fallback_enabled: bool
    metrics_json: str
    promoted_at: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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
            decision_source TEXT NOT NULL DEFAULT 'cli_record',
            decision_validity TEXT NOT NULL DEFAULT 'valid',
            compilation_candidate INTEGER NOT NULL DEFAULT 0,
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS promoted_rules (
            rule_id TEXT PRIMARY KEY,
            decision_key TEXT NOT NULL,
            candidate_choice TEXT NOT NULL,
            status TEXT NOT NULL,
            fallback_enabled INTEGER NOT NULL,
            metrics_json TEXT NOT NULL,
            promoted_at TEXT NOT NULL
        )
        """
    )
    # Phase D migration: add predicate_json for feature-conditioned rules.
    # Idempotent — only adds the column if it doesn't already exist.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(promoted_rules)")}
    if "predicate_json" not in cols:
        conn.execute("ALTER TABLE promoted_rules ADD COLUMN predicate_json TEXT")
    conn.commit()
    return conn


def create_run_id(provided_run_id: str | None = None) -> str:
    return provided_run_id or f"run_{uuid.uuid4().hex[:12]}"


def create_rule_id(provided_rule_id: str | None = None) -> str:
    return provided_rule_id or f"rule_{uuid.uuid4().hex[:12]}"


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
    decision_source: str = "cli_record",
    decision_validity: str = "valid",
    compilation_candidate: bool = False,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO decisions(
            run_id, ts, decision_key, decision_source, decision_validity, compilation_candidate, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            utc_now_iso(),
            decision_key,
            decision_source,
            decision_validity,
            int(compilation_candidate),
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def list_decisions(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
        SELECT id, run_id, ts, decision_key, decision_source, decision_validity, compilation_candidate, payload_json
        FROM decisions
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return list(cursor.fetchall())


def list_decision_patterns(
    conn: sqlite3.Connection,
    min_support: int = 2,
    limit: int = 20,
) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
        WITH decision_values AS (
            SELECT
                decision_key,
                json_extract(payload_json, '$.chosen') AS chosen
            FROM decisions
            WHERE
                decision_key IS NOT NULL
                AND decision_source IN ('decision_file', 'stdout_marker', 'cli_record', 'sdk_record')
                AND decision_validity = 'valid'
                AND compilation_candidate = 1
                AND EXISTS (
                    SELECT 1
                    FROM outcomes o
                    WHERE o.run_id = decisions.run_id
                      AND o.status IN ('success', 'accepted')
                )
        ),
        choice_counts AS (
            SELECT
                decision_key,
                chosen,
                COUNT(*) AS chosen_count
            FROM decision_values
            WHERE chosen IS NOT NULL
            GROUP BY decision_key, chosen
        ),
        totals AS (
            SELECT
                decision_key,
                SUM(chosen_count) AS support
            FROM choice_counts
            GROUP BY decision_key
        ),
        ranked AS (
            SELECT
                c.decision_key,
                c.chosen,
                c.chosen_count,
                t.support,
                ROW_NUMBER() OVER (
                    PARTITION BY c.decision_key
                    ORDER BY c.chosen_count DESC, c.chosen ASC
                ) AS rn
            FROM choice_counts c
            JOIN totals t ON t.decision_key = c.decision_key
            WHERE t.support >= ?
        )
        SELECT
            decision_key,
            chosen AS dominant_choice,
            chosen_count AS dominant_count,
            support,
            ROUND(CAST(chosen_count AS REAL) / CAST(support AS REAL), 6) AS confidence
        FROM ranked
        WHERE rn = 1
        ORDER BY support DESC, confidence DESC, decision_key ASC
        LIMIT ?
        """,
        (min_support, limit),
    )
    return list(cursor.fetchall())


def list_decision_patterns_by_features(
    conn: sqlite3.Connection,
    *,
    decision_key: str | None = None,
    min_support: int = 2,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Mine patterns conditioned on the structured ``features`` field.

    Buckets decisions by ``(decision_key, canonical_features)`` where
    canonical_features is the sort-key-stable JSON of the ``features`` dict.
    For each bucket, counts ``output.chosen`` values and returns the dominant
    choice with support + confidence — same shape as
    :func:`list_decision_patterns` but conditioned on feature subspaces.

    This is the input AgentOS Phase C (rule extractor) consumes to propose
    deterministic short-circuits: high-support, high-confidence buckets
    are candidate rules.

    Decisions without a ``features`` field are skipped (handled by
    :func:`list_decision_patterns`).
    """
    conn.row_factory = sqlite3.Row
    where_key = "AND decision_key = ?" if decision_key else ""
    params: tuple = (decision_key,) if decision_key else ()
    cursor = conn.execute(
        f"""
        SELECT
            decision_key,
            COALESCE(
                json_extract(payload_json, '$.output.chosen'),
                json_extract(payload_json, '$.chosen')
            ) AS chosen,
            json_extract(payload_json, '$.features') AS features_raw
        FROM decisions
        WHERE
            decision_key IS NOT NULL
            AND decision_source IN ('decision_file', 'stdout_marker', 'cli_record', 'sdk_record')
            AND decision_validity = 'valid'
            AND compilation_candidate = 1
            {where_key}
            AND EXISTS (
                SELECT 1
                FROM outcomes o
                WHERE o.run_id = decisions.run_id
                  AND o.status IN ('success', 'accepted')
            )
        """,
        params,
    )

    # Bucket in Python — features are arbitrary JSON dicts, easier to
    # canonicalize here than in SQLite.
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in cursor.fetchall():
        chosen = row["chosen"]
        features_raw = row["features_raw"]
        if chosen is None or features_raw is None:
            continue
        try:
            features = json.loads(features_raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(features, dict):
            continue
        canonical = json.dumps(features, sort_keys=True, ensure_ascii=False)
        key = (str(row["decision_key"]), canonical)
        bucket = buckets.setdefault(
            key,
            {
                "decision_key": str(row["decision_key"]),
                "features": features,
                "_canonical": canonical,
                "choices": {},
                "support": 0,
            },
        )
        bucket["support"] += 1
        bucket["choices"][str(chosen)] = bucket["choices"].get(str(chosen), 0) + 1

    results: list[dict[str, Any]] = []
    for bucket in buckets.values():
        if bucket["support"] < min_support:
            continue
        # Dominant: highest count, ties broken alphabetically (stable).
        sorted_choices = sorted(
            bucket["choices"].items(), key=lambda kv: (-kv[1], kv[0])
        )
        dominant_choice, dominant_count = sorted_choices[0]
        confidence = round(dominant_count / bucket["support"], 6)
        results.append(
            {
                "decision_key": bucket["decision_key"],
                "features": bucket["features"],
                "dominant_choice": dominant_choice,
                "dominant_count": dominant_count,
                "support": bucket["support"],
                "confidence": confidence,
            }
        )

    results.sort(
        key=lambda r: (-r["support"], -r["confidence"], r["decision_key"], r["_canonical"] if "_canonical" in r else ""),
    )
    # Drop the internal _canonical key from output rows.
    for r in results:
        r.pop("_canonical", None)
    return results[:limit]


def list_decision_choices(conn: sqlite3.Connection, decision_key: str) -> list[str]:
    cursor = conn.execute(
        """
        SELECT json_extract(payload_json, '$.chosen') AS chosen
        FROM decisions
        WHERE
            decision_key = ?
            AND decision_source IN ('decision_file', 'stdout_marker', 'cli_record', 'sdk_record')
            AND decision_validity = 'valid'
            AND compilation_candidate = 1
            AND EXISTS (
                SELECT 1
                FROM outcomes o
                WHERE o.run_id = decisions.run_id
                  AND o.status IN ('success', 'accepted')
            )
        ORDER BY id ASC
        """,
        (decision_key,),
    )
    return [str(row[0]) for row in cursor.fetchall() if row[0] is not None]


def get_decision(conn: sqlite3.Connection, decision_id: int) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
        SELECT id, run_id, ts, decision_key, decision_source, decision_validity, compilation_candidate, payload_json
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


def record_promoted_rule(conn: sqlite3.Connection, promoted_rule: PromotedRuleRecord) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO promoted_rules(
            rule_id, decision_key, candidate_choice, status, fallback_enabled, metrics_json, promoted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            promoted_rule.rule_id,
            promoted_rule.decision_key,
            promoted_rule.candidate_choice,
            promoted_rule.status,
            int(promoted_rule.fallback_enabled),
            promoted_rule.metrics_json,
            promoted_rule.promoted_at,
        ),
    )
    conn.commit()


def list_promoted_rules(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
        SELECT rule_id, decision_key, candidate_choice, status, fallback_enabled, metrics_json, promoted_at
        FROM promoted_rules
        ORDER BY promoted_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return list(cursor.fetchall())


def get_latest_promoted_rule(conn: sqlite3.Connection, decision_key: str) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
        SELECT rule_id, decision_key, candidate_choice, status, fallback_enabled, metrics_json, promoted_at
        FROM promoted_rules
        WHERE decision_key = ? AND status = 'promoted'
        ORDER BY promoted_at DESC
        LIMIT 1
        """,
        (decision_key,),
    )
    return cursor.fetchone()


def record_promoted_feature_rule(
    conn: sqlite3.Connection,
    *,
    rule_id: str,
    decision_key: str,
    predicate: list[dict[str, Any]],
    chosen: str,
    metrics: dict[str, Any],
    fallback_enabled: bool = True,
    status: str = "promoted",
) -> None:
    """Persist a feature-conditioned rule (Phase D).

    The predicate is a list of equality tests, e.g.::

        [{"feature": "is_root", "op": "==", "value": True},
         {"feature": "has_mention", "op": "==", "value": True}]

    Stored next to the existing key-only promoted rules. ``predicate_json``
    distinguishes the two: feature rules have it set, key-only rules don't.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO promoted_rules(
            rule_id, decision_key, candidate_choice, status, fallback_enabled,
            metrics_json, promoted_at, predicate_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rule_id,
            decision_key,
            chosen,
            status,
            int(fallback_enabled),
            json.dumps(metrics, ensure_ascii=False),
            utc_now_iso(),
            json.dumps(predicate, ensure_ascii=False),
        ),
    )
    conn.commit()


def list_promoted_feature_rules(
    conn: sqlite3.Connection, decision_key: str
) -> list[sqlite3.Row]:
    """Load active feature-conditioned rules for a decision_key.

    Returned rules are ordered most-specific-first (longest predicate first).
    Most-specific rules win at runtime, matching how a decision tree's deeper
    leaves carry more discriminating information than shallower ones.
    """
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
        SELECT rule_id, decision_key, candidate_choice, status, fallback_enabled,
               metrics_json, promoted_at, predicate_json
        FROM promoted_rules
        WHERE decision_key = ?
          AND status = 'promoted'
          AND predicate_json IS NOT NULL
        """,
        (decision_key,),
    )
    rows = list(cursor.fetchall())
    # Sort by predicate length desc (most specific first), then promoted_at desc.
    def _len(row: sqlite3.Row) -> int:
        try:
            pred = json.loads(row["predicate_json"]) if row["predicate_json"] else []
            return len(pred) if isinstance(pred, list) else 0
        except (TypeError, ValueError):
            return 0
    rows.sort(key=lambda r: (-_len(r), r["promoted_at"]), reverse=False)
    rows.sort(key=lambda r: -_len(r))  # primary: longest predicate first
    return rows
