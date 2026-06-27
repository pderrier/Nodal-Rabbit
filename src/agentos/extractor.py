"""Decision-tree rule extractor (Phase C) — STORAGE adapter.

Mines deterministic rules from labeled (features, chosen) decisions stored
by AgentOS. The pure CART algorithm (Gini-impurity tree builder, leaf walk,
rule proposals) now lives in the storage-agnostic :mod:`agentos.kernel`;
this module is the thin SQLite adapter that loads samples from the DB and
WIRES them through the kernel.

Rules are *candidates* for promotion: a leaf qualifies when its coverage
meets ``min_coverage`` and class purity meets ``min_precision``. Promotion
to the ``promoted_rules`` table is a separate explicit step (kept manual
for review) — see ``agentos rules promote``.

Public API (unchanged — kernel symbols are re-exported here so existing
imports ``from agentos.extractor import Rule, Sample, extract_rules, ...``
keep working):
    Sample, Predicate, Rule  (re-exported from agentos.kernel)
    extract_rules(samples, *, decision_key, ...) -> list[Rule]  (kernel)
    load_labeled_samples(conn, decision_key) -> list[Sample]    (this module)
    extract_rules_from_db(conn, decision_key, ...) -> list[Rule] (this module)
"""
from __future__ import annotations

import json
import sqlite3

# Re-export the pure kernel symbols at their historical extractor path so
# downstream imports (tests, consumers) keep working unchanged. These are
# aliases, NOT duplicates — the single source of truth is agentos.kernel.
from agentos.kernel import (  # noqa: F401  (re-exported public + internal API)
    Predicate,
    Rule,
    Sample,
    _TreeNode,
    _best_split,
    _build_tree,
    _candidate_splits,
    _class_counts,
    _gini,
    _split_samples,
    _walk_leaves,
    extract_rules,
)

__all__ = [
    # re-exported kernel symbols
    "Sample",
    "Predicate",
    "Rule",
    "extract_rules",
    # storage adapters owned by this module
    "load_labeled_samples",
    "extract_rules_from_db",
]


# ---------------------------------------------------------------------------
# DB loader — SQLite-coupled (storage layer)
# ---------------------------------------------------------------------------


def load_labeled_samples(
    conn: sqlite3.Connection,
    decision_key: str,
    *,
    prompt_version: str | None = None,
) -> list[Sample]:
    """Pull all valid+candidate decisions with features for ``decision_key``
    where the run has a confirmed outcome (status in success/accepted).

    When ``prompt_version`` is provided, only decisions whose
    ``payload_json.prompt_version`` matches are returned. Use this to
    quarantine data made under buggy/stale prompts.
    """
    conn.row_factory = sqlite3.Row
    extra_clause = ""
    params: list = [decision_key]
    if prompt_version is not None:
        extra_clause = "AND json_extract(payload_json, '$.prompt_version') = ?"
        params.append(prompt_version)
    cursor = conn.execute(
        f"""
        SELECT
            COALESCE(
                json_extract(payload_json, '$.output.chosen'),
                json_extract(payload_json, '$.chosen')
            ) AS chosen,
            json_extract(payload_json, '$.features') AS features_raw
        FROM decisions
        WHERE
            decision_key = ?
            AND decision_source IN ('decision_file', 'stdout_marker', 'cli_record', 'sdk_record')
            AND decision_validity = 'valid'
            AND compilation_candidate = 1
            {extra_clause}
            AND EXISTS (
                SELECT 1 FROM outcomes o
                WHERE o.run_id = decisions.run_id
                  AND o.status IN ('success', 'accepted')
            )
        """,
        tuple(params),
    )
    samples: list[Sample] = []
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
        samples.append(Sample(features=features, chosen=str(chosen)))
    return samples


def extract_rules_from_db(
    conn: sqlite3.Connection,
    *,
    decision_key: str,
    prompt_version: str | None = None,
    min_coverage: int = 20,
    min_precision: float = 0.95,
    max_depth: int = 4,
    max_cardinality: int = 10,
) -> list[Rule]:
    """Load samples for a decision_key from the DB and run the extractor.

    ``prompt_version`` filters samples to a specific prompt version — see
    :func:`load_labeled_samples`.
    """
    samples = load_labeled_samples(
        conn, decision_key, prompt_version=prompt_version,
    )
    return extract_rules(
        samples,
        decision_key=decision_key,
        min_coverage=min_coverage,
        min_precision=min_precision,
        max_depth=max_depth,
        max_cardinality=max_cardinality,
    )
