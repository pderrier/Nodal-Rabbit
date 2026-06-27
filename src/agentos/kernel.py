"""AgentOS KERNEL — PURE, storage-agnostic source of truth.

This module is the single shared source of truth for AgentOS's decision
schema and pure algorithms (CART rule mining, walk-forward backtest
metrics, deterministic rule matching). It is **vendored verbatim by Loom**,
which is stdlib-only and fully self-contained.

INVARIANT — n'ajouter ici QUE du pur stdlib sans I/O:
    * imports limited to the standard library (json / math / dataclasses /
      typing). NO sqlite3, NO filesystem access, NO `open(...)`, NO network.
    * every function operates on in-memory structures (``list[Sample]``,
      ``list[Rule]``, ``dict`` of features) and returns in-memory structures.
    * zero side effects, zero I/O. This is what makes the kernel safe to
      copy verbatim into Loom's stdlib-only runtime.

If you need to touch storage (SQLite), the filesystem, or the network, that
code belongs in the storage/adapter layer (``storage.py`` / ``extractor.py``
/ ``runtime.py`` / ``cli.py``), which WIRES this kernel — it must never
re-implement the logic that lives here.

Contents:
    Decision/rule schema:
        Sample, Predicate, Rule, _TreeNode
    CART rule mining:
        _class_counts, _gini, _candidate_splits, _split_samples,
        _best_split, _build_tree, _walk_leaves, extract_rules
    Backtest metrics (pure, list-based):
        dominant_choice, compute_backtest_metrics
    Deterministic rule matching (pure):
        predicate_matches, sort_rules_by_specificity, match_rule
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Types — decision / rule schema
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
# Tree building (CART, Gini impurity)
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


def _candidate_splits(
    samples: list[Sample],
    *,
    max_cardinality: int = 10,
) -> list[tuple[str, Any]]:
    """Enumerate (feature, value) pairs to consider as split candidates.

    For boolean/string/int-like features: each unique value becomes a test
    ``feature == value``. For float features (rare in our use case): each
    unique value gets the same treatment (this is a simplification — for
    truly continuous features a quantile-based split would be better, but
    AgentOS features are typically boolean/categorical).

    Features with more than ``max_cardinality`` distinct values are skipped —
    high-cardinality features (e.g. channel_id) create fine-grained splits
    that don't generalize into useful rules.
    """
    # First pass: count distinct values per feature
    feature_values: dict[str, set[tuple[str, Any]]] = {}
    for s in samples:
        for k, v in s.features.items():
            key = (type(v).__name__, v)
            feature_values.setdefault(k, set()).add(key)

    # Second pass: build candidates, skipping high-cardinality features
    seen: set[tuple[str, Any]] = set()
    candidates: list[tuple[str, Any]] = []
    for s in samples:
        for k, v in s.features.items():
            if len(feature_values.get(k, ())) > max_cardinality:
                continue
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


def _best_split(
    samples: list[Sample],
    *,
    max_cardinality: int = 10,
) -> tuple[str, Any, float] | None:
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
    for feature, value in _candidate_splits(samples, max_cardinality=max_cardinality):
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
    max_cardinality: int = 10,
    depth: int = 0,
) -> _TreeNode:
    """Build a greedy CART-like tree."""
    node = _TreeNode(samples=samples)
    if len(samples) < min_split or depth >= max_depth:
        return node
    split = _best_split(samples, max_cardinality=max_cardinality)
    if split is None:
        return node
    feature, value, _gain = split
    match, other = _split_samples(samples, feature, value)
    node.split_feature = feature
    node.split_value = value
    node.match_child = _build_tree(match, max_depth=max_depth, min_split=min_split, max_cardinality=max_cardinality, depth=depth + 1)
    node.other_child = _build_tree(other, max_depth=max_depth, min_split=min_split, max_cardinality=max_cardinality, depth=depth + 1)
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
    max_cardinality: int = 10,
) -> list[Rule]:
    """Build the tree, walk it, and return rule proposals.

    Args:
        samples: labeled samples for ONE decision_key.
        decision_key: the decision_key these samples belong to.
        min_coverage: minimum number of samples a leaf must cover.
        min_precision: minimum class purity at the leaf (1.0 = unanimous).
        max_depth: maximum tree depth (caps predicate-conjunction length).
        max_cardinality: features with more distinct values than this are
            excluded from splits (prevents high-cardinality features like
            channel_id from dominating the tree).

    Returns rules sorted by (precision desc, coverage desc).
    """
    if not samples:
        return []
    tree = _build_tree(
        samples,
        max_depth=max_depth,
        min_split=max(2, min_coverage),
        max_cardinality=max_cardinality,
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
# Backtest metrics — pure walk-forward evaluation over a choice sequence
# ---------------------------------------------------------------------------


def dominant_choice(choices: list[str]) -> tuple[str, float]:
    """Return the most frequent choice and its share of the sequence.

    Ties broken deterministically by (count desc, label asc).
    """
    counts = Counter(choices)
    winner, winner_count = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return winner, winner_count / len(choices)


def compute_backtest_metrics(
    decision_key: str,
    choices: list[str],
    min_history: int,
    min_confidence: float,
) -> dict[str, object]:
    """Walk-forward backtest of a "majority of history" predictor.

    For each observation at index ``idx``, predict the dominant choice of the
    prior history (``choices[:idx]``) when (a) enough history exists
    (``idx >= min_history``) and (b) the dominant choice's share meets
    ``min_confidence``; otherwise abstain. Accuracy is measured over
    predicted (non-abstained) observations only.

    Pure: operates on a list of choice labels and returns a metrics dict.
    """
    total = len(choices)
    if total < 2:
        return {
            "decision_key": decision_key,
            "error": "not_enough_data",
            "total_observations": total,
        }

    correct = 0
    predicted = 0
    abstained = 0

    for idx in range(total):
        if idx < min_history:
            abstained += 1
            continue

        history = choices[:idx]
        dominant, confidence = dominant_choice(history)
        if confidence < min_confidence:
            abstained += 1
            continue

        predicted += 1
        if choices[idx] == dominant:
            correct += 1

    final_dominant, final_confidence = dominant_choice(choices)
    accuracy = (correct / predicted) if predicted else 0.0
    abstain_rate = abstained / total
    coverage_rate = predicted / total

    return {
        "decision_key": decision_key,
        "total_observations": total,
        "min_history": min_history,
        "min_confidence": min_confidence,
        "candidate_choice": final_dominant,
        "candidate_confidence": round(final_confidence, 6),
        "predictions": predicted,
        "abstentions": abstained,
        "correct_predictions": correct,
        "accuracy": round(accuracy, 6),
        "abstain_rate": round(abstain_rate, 6),
        "coverage_rate": round(coverage_rate, 6),
        "promote_ready": predicted > 0 and accuracy == 1.0,
    }


# ---------------------------------------------------------------------------
# Deterministic rule matching — pure (no storage/loading)
# ---------------------------------------------------------------------------


def predicate_matches(predicate: list[dict[str, Any]], features: dict[str, Any]) -> bool:
    """Evaluate a list of equality tests as a conjunction.

    A predicate is a list of ``{"feature": str, "op": "==", "value": <prim>}``
    dicts. ``op`` is currently always ``==`` — extending to ``!=`` / ``in``
    is a follow-up. An empty predicate (``[]``) matches everything; this
    represents an unconditional rule for a decision_key.
    """
    if not isinstance(predicate, list):
        return False
    for clause in predicate:
        if not isinstance(clause, dict):
            return False
        feature = clause.get("feature")
        op = clause.get("op", "==")
        value = clause.get("value")
        if not isinstance(feature, str):
            return False
        if op != "==":
            # Unknown op — be conservative and reject.
            return False
        if features.get(feature) != value:
            return False
    return True


def sort_rules_by_specificity(
    rules: list[tuple[list[dict[str, Any]], Any]],
) -> list[tuple[list[dict[str, Any]], Any]]:
    """Order ``(predicate, payload)`` pairs most-specific-first.

    Specificity = predicate length: the rule with the *longest* predicate
    (most conditions) wins ties, mirroring how a decision tree's deeper
    leaves carry more discriminating information than shallower ones.
    Sort is stable, preserving the caller's order among equal-length
    predicates.
    """
    return sorted(rules, key=lambda item: -len(item[0]))


def match_rule(
    rules: list[tuple[list[dict[str, Any]], Any]],
    features: dict[str, Any],
) -> Any | None:
    """Return the payload of the most-specific rule matching ``features``.

    ``rules`` is a list of ``(predicate, payload)`` pairs. Rules are ranked
    most-specific-first via :func:`sort_rules_by_specificity`, then the first
    whose predicate matches ``features`` (per :func:`predicate_matches`) wins.
    Returns ``None`` when no rule matches.

    Pure: the caller is responsible for LOADING the rules (e.g. from a DB)
    and for shaping each payload. The kernel only decides which one fires.
    """
    for predicate, payload in sort_rules_by_specificity(rules):
        if predicate_matches(predicate, features):
            return payload
    return None
