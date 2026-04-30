"""Decision-tree rule extractor (Phase C).

Mines deterministic rules from labeled (features, chosen) decisions stored
by AgentOS. Pure Python, no ML dependency — uses a greedy CART-style tree
builder with Gini impurity, then walks high-precision leaves to produce
rule proposals with conjunctive feature predicates.

Rules are *candidates* for promotion: a leaf qualifies when its coverage
meets ``min_coverage`` and class purity meets ``min_precision``. Promotion
to the ``promoted_rules`` table is a separate explicit step (kept manual
for review) — see ``agentos rules promote``.

Public API:
    load_labeled_samples(conn, decision_key) -> list[Sample]
    extract_rules(samples, *, min_coverage, min_precision, max_depth) -> list[Rule]
    extract_rules_from_db(conn, decision_key, ...) -> list[Rule]
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    """One labeled training sample: structured features + chosen class."""
    features: dict[str, Any]
    chosen: str


@dataclass
class Predicate:
    """A single feature equality test in a rule's conjunction."""
    feature: str
    value: Any  # str | bool | int | float (primitives only — same as features schema)

    def matches(self, features: dict[str, Any]) -> bool:
        return features.get(self.feature) == self.value

    def to_dict(self) -> dict:
        return {"feature": self.feature, "op": "==", "value": self.value}


@dataclass
class Rule:
    """An extracted rule: predicate conjunction → chosen class."""
    decision_key: str
    predicate: list[Predicate]
    chosen: str
    coverage: int
    precision: float
    support_total: int = 0  # total samples for the decision_key

    def to_dict(self) -> dict:
        return {
            "decision_key": self.decision_key,
            "predicate": [p.to_dict() for p in self.predicate],
            "chosen": self.chosen,
            "coverage": self.coverage,
            "precision": round(self.precision, 6),
            "support_total": self.support_total,
            "support_share": round(self.coverage / self.support_total, 6) if self.support_total else 0.0,
        }


@dataclass
class _TreeNode:
    """Internal tree node. Either a split (feature+value+children) or a leaf."""
    samples: list[Sample]
    split_feature: str | None = None
    split_value: Any = None
    match_child: "_TreeNode | None" = None  # samples where features[feature] == value
    other_child: "_TreeNode | None" = None  # samples where features[feature] != value or absent

    @property
    def is_leaf(self) -> bool:
        return self.split_feature is None


# ---------------------------------------------------------------------------
# Tree building
# ---------------------------------------------------------------------------


def _class_counts(samples: list[Sample]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in samples:
        counts[s.chosen] = counts.get(s.chosen, 0) + 1
    return counts


def _gini(samples: list[Sample]) -> float:
    """Gini impurity. Lower is purer."""
    if not samples:
        return 0.0
    counts = _class_counts(samples)
    total = len(samples)
    return 1.0 - sum((c / total) ** 2 for c in counts.values())


def _candidate_splits(samples: list[Sample]) -> list[tuple[str, Any]]:
    """Enumerate (feature, value) pairs to consider as split candidates.

    For boolean/string/int-like features: each unique value becomes a test
    ``feature == value``. For float features (rare in our use case): each
    unique value gets the same treatment (this is a simplification — for
    truly continuous features a quantile-based split would be better, but
    AgentOS features are typically boolean/categorical).
    """
    seen: set[tuple[str, Any]] = set()
    candidates: list[tuple[str, Any]] = []
    for s in samples:
        for k, v in s.features.items():
            # Hash with type to avoid mixing True with 1
            key = (k, type(v).__name__, v)
            if key in seen:
                continue
            seen.add(key)
            candidates.append((k, v))
    return candidates


def _split_samples(
    samples: list[Sample], feature: str, value: Any
) -> tuple[list[Sample], list[Sample]]:
    """Return (matching, non_matching) split."""
    matching: list[Sample] = []
    non_matching: list[Sample] = []
    for s in samples:
        if s.features.get(feature) == value:
            matching.append(s)
        else:
            non_matching.append(s)
    return matching, non_matching


def _best_split(samples: list[Sample]) -> tuple[str, Any, float] | None:
    """Find (feature, value, gain) with highest Gini-impurity reduction.

    Returns None if no useful split exists (gain == 0 or both children empty).
    """
    if len(samples) < 2:
        return None
    base_gini = _gini(samples)
    if base_gini == 0.0:
        return None  # already pure
    total = len(samples)
    best: tuple[str, Any, float] | None = None
    for feature, value in _candidate_splits(samples):
        match, other = _split_samples(samples, feature, value)
        if not match or not other:
            continue
        weighted = (
            len(match) / total * _gini(match)
            + len(other) / total * _gini(other)
        )
        gain = base_gini - weighted
        if gain <= 0:
            continue
        if best is None or gain > best[2]:
            best = (feature, value, gain)
    return best


def _build_tree(
    samples: list[Sample],
    *,
    max_depth: int,
    min_split: int,
    depth: int = 0,
) -> _TreeNode:
    """Build a greedy CART-like tree."""
    node = _TreeNode(samples=samples)
    if len(samples) < min_split or depth >= max_depth:
        return node
    split = _best_split(samples)
    if split is None:
        return node
    feature, value, _gain = split
    match, other = _split_samples(samples, feature, value)
    node.split_feature = feature
    node.split_value = value
    node.match_child = _build_tree(match, max_depth=max_depth, min_split=min_split, depth=depth + 1)
    node.other_child = _build_tree(other, max_depth=max_depth, min_split=min_split, depth=depth + 1)
    return node


# ---------------------------------------------------------------------------
# Rule extraction (walk the tree, keep high-precision leaves only)
# ---------------------------------------------------------------------------


def _walk_leaves(
    node: _TreeNode,
    predicate: list[Predicate],
) -> list[tuple[list[Predicate], list[Sample]]]:
    """Yield (predicate, samples) for every leaf in the tree.

    Note: predicates only accumulate along the *match* path. The "other"
    branch represents "does NOT equal value" which produces a negation
    predicate that's harder to express cleanly — for v1 we drop those
    branches, keeping only positive conjunctions. This loses some rules
    but produces simpler, more reviewable output. (A negation operator
    can be added in a follow-up.)
    """
    out: list[tuple[list[Predicate], list[Sample]]] = []
    if node.is_leaf:
        out.append((list(predicate), node.samples))
        return out
    # match child: extends the conjunction
    assert node.match_child is not None and node.split_feature is not None
    out.extend(_walk_leaves(
        node.match_child,
        predicate + [Predicate(feature=node.split_feature, value=node.split_value)],
    ))
    # other child: skipped (see docstring) — but still walk it for *its*
    # match-path leaves since the subtree may have its own positive splits.
    if node.other_child is not None:
        # The "other" path's predicate is a negation — recurse for downstream
        # match conjunctions, but those rules will lose this implicit context.
        # Conservative: only emit leaves from the other subtree if their own
        # predicate path doesn't depend on the negation. Simpler heuristic
        # for v1: skip the "other" subtree entirely.
        pass
    return out


def extract_rules(
    samples: list[Sample],
    *,
    decision_key: str,
    min_coverage: int = 20,
    min_precision: float = 0.95,
    max_depth: int = 4,
) -> list[Rule]:
    """Build the tree, walk it, and return rule proposals.

    Args:
        samples: labeled samples for ONE decision_key.
        decision_key: the decision_key these samples belong to.
        min_coverage: minimum number of samples a leaf must cover.
        min_precision: minimum class purity at the leaf (1.0 = unanimous).
        max_depth: maximum tree depth (caps predicate-conjunction length).

    Returns rules sorted by (precision desc, coverage desc).
    """
    if not samples:
        return []
    tree = _build_tree(
        samples,
        max_depth=max_depth,
        min_split=max(2, min_coverage),
    )
    rules: list[Rule] = []
    total = len(samples)
    for predicate, leaf_samples in _walk_leaves(tree, predicate=[]):
        if len(leaf_samples) < min_coverage:
            continue
        counts = _class_counts(leaf_samples)
        dominant_class, dominant_count = max(counts.items(), key=lambda kv: kv[1])
        precision = dominant_count / len(leaf_samples)
        if precision < min_precision:
            continue
        rules.append(Rule(
            decision_key=decision_key,
            predicate=predicate,
            chosen=dominant_class,
            coverage=dominant_count,
            precision=precision,
            support_total=total,
        ))
    rules.sort(key=lambda r: (-r.precision, -r.coverage, r.chosen))
    return rules


# ---------------------------------------------------------------------------
# DB loader
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
    )
