"""AgentOS runtime SDK — rule-first decision routing for wrapped workers.

Phase D of the AgentOS rule-mining loop. Provides the consumer-facing API
that wrapped workers call BEFORE invoking an LLM/agent: if a promoted
deterministic rule matches the current input features, the worker returns
that decision directly and skips the model call entirely.

Typical usage in a wrapped worker (e.g. alert_brain's classifier)::

    from agentos.runtime import check_rule

    decision = check_rule("teams.classify_thread", {
        "is_root": True,
        "has_mention": True,
        "sender_is_devops": True,
    })
    if decision is not None:
        # Promoted rule fired — skip the LLM, use the deterministic answer.
        return decision["chosen"]

    # No rule matched — fall through to the model.
    return llm_classify(...)

If ``fallback_enabled=False`` is set on the rule (rare; default is True)
and the predicate doesn't match, the SDK still returns ``None`` — fallback
behavior is the worker's responsibility, not the SDK's.

Design notes:
- This module is the STORAGE/ADAPTER layer: it LOADS promoted rules from the
  SQLite store, then delegates the pure per-clause predicate evaluation to
  the storage-agnostic kernel (:func:`agentos.kernel.predicate_matches`).
  The matching LOGIC lives in the kernel; this layer only wires it to the DB.
- Rules are loaded fresh from the SQLite store on each call (no caching at
  the v1 API). Wrapped workers should batch lookups if hot.
- The SDK never falls back implicitly — when no rule matches, it returns
  ``None`` and the caller decides what to do next.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from agentos.kernel import predicate_matches as _predicate_matches
from agentos.storage import (
    db_path,
    list_promoted_feature_rules,
    resolve_home,
)

# Re-export the pure matcher at its historical path so existing importers
# (e.g. tests, downstream consumers) keep working. The implementation now
# lives in the kernel — this is a thin alias, not a duplicate.
__all__ = ["check_rule", "_predicate_matches"]


def check_rule(
    decision_key: str,
    features: dict[str, Any],
    *,
    agentos_home: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Look up a deterministic rule for ``decision_key`` matching ``features``.

    Args:
        decision_key: Logical decision point (must match what was used at
            decision-recording time).
        features: Structured features for the current input — same shape
            as the ``features`` field on the recorded decision.
        agentos_home: Optional override for the AgentOS home directory.
            Defaults to ``$AGENTOS_HOME`` or ``./.agentos``.
        conn: Optional pre-opened SQLite connection (for hot-path callers
            that want to share a connection across calls).

    Returns:
        A dict ``{"chosen": str, "rule_id": str, "predicate": list, "fallback_enabled": bool}``
        when a rule matches. ``None`` when no rule matches — the caller
        must then invoke its fallback (LLM, manual flow, etc.).

    The rule with the *longest* predicate (most specific) wins ties. This
    mirrors how a decision tree's deeper leaves carry more discriminating
    information than shallower ones. Rows arrive most-specific-first from
    :func:`agentos.storage.list_promoted_feature_rules`; the first whose
    predicate matches wins.
    """
    own_conn = conn is None
    if conn is None:
        home = resolve_home(agentos_home)
        if not db_path(home).exists():
            # No AgentOS DB yet — treat as "no rules promoted".
            return None
        conn = sqlite3.connect(db_path(home))

    try:
        rows = list_promoted_feature_rules(conn, decision_key)
        for row in rows:
            try:
                predicate = json.loads(row["predicate_json"]) if row["predicate_json"] else []
            except (TypeError, ValueError):
                continue
            if _predicate_matches(predicate, features):
                return {
                    "chosen": row["candidate_choice"],
                    "rule_id": row["rule_id"],
                    "predicate": predicate,
                    "fallback_enabled": bool(row["fallback_enabled"]),
                }
        return None
    finally:
        if own_conn:
            conn.close()
