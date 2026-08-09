"""Consensus policies: collapse a panel's per-judge votes into one verdict.

Only `status == "voted"` votes count toward the tally; abstained/error/
not_applicable votes are excluded (but retained by the caller in
`PanelVerdict.votes`). Never fabricate a verdict: an empty voter set yields a
flagged `pass` (confidence 0.0) whose rationale says no judge voted, and
`agreement=None`. The aggregated verdict's descriptive fields come from the
highest-confidence voter that matches the chosen verdict, so the quote can
never contradict the verdict.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable

from asc_metadata_verifier.models import JudgeVote, RubricVerdict

ConsensusPolicy = Callable[..., "tuple[RubricVerdict, float | None]"]

_VERDICT_RANK = {"pass": 0, "warn": 1, "fail": 2}
_RANK_VERDICT = {0: "pass", 1: "warn", 2: "fail"}
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


def _voters(votes: list[JudgeVote]) -> list[RubricVerdict]:
    return [v.verdict for v in votes if v.status == "voted" and v.verdict is not None]


def _empty(locale: str, dimension: str, field: str) -> tuple[RubricVerdict, None]:
    return (
        RubricVerdict(
            dimension=dimension, verdict="pass", severity="low", confidence=0.0,
            rationale="No judge produced a verdict for this unit.",
            locale=locale, field=field,
        ),
        None,
    )


def _assemble(chosen: str, voters: list[RubricVerdict], locale: str, dimension: str):
    matching = [rv for rv in voters if rv.verdict == chosen]
    rep = max(matching, key=lambda rv: rv.confidence)
    severity = max((rv.severity for rv in matching), key=lambda s: _SEVERITY_RANK[s])
    confidence = sum(rv.confidence for rv in matching) / len(matching)
    agreement = sum(1 for rv in voters if rv.verdict == chosen) / len(voters)
    return (
        RubricVerdict(
            dimension=dimension, locale=locale, field=rep.field,
            verdict=chosen, severity=severity, confidence=confidence,
            rationale=rep.rationale, offending_quote=rep.offending_quote,
            guideline_ref=rep.guideline_ref, suggested_fix=rep.suggested_fix,
        ),
        agreement,
    )


def _severe_tiebreak(tied: list[str]) -> str:
    return max(tied, key=lambda vd: _VERDICT_RANK[vd])


def majority_severe(votes, *, locale, dimension, default_field):
    voters = _voters(votes)
    if not voters:
        return _empty(locale, dimension, default_field)
    tally = Counter(rv.verdict for rv in voters)
    top = max(tally.values())
    chosen = _severe_tiebreak([vd for vd, c in tally.items() if c == top])
    return _assemble(chosen, voters, locale, dimension)


def most_severe(votes, *, locale, dimension, default_field):
    voters = _voters(votes)
    if not voters:
        return _empty(locale, dimension, default_field)
    chosen = _RANK_VERDICT[max(_VERDICT_RANK[rv.verdict] for rv in voters)]
    return _assemble(chosen, voters, locale, dimension)


def unanimous(votes, *, locale, dimension, default_field):
    voters = _voters(votes)
    if not voters:
        return _empty(locale, dimension, default_field)
    chosen = _RANK_VERDICT[min(_VERDICT_RANK[rv.verdict] for rv in voters)]
    return _assemble(chosen, voters, locale, dimension)


def confidence_weighted(votes, *, locale, dimension, default_field):
    voters = _voters(votes)
    if not voters:
        return _empty(locale, dimension, default_field)
    weights: dict[str, float] = defaultdict(float)
    for rv in voters:
        weights[rv.verdict] += rv.confidence
    top = max(weights.values())
    chosen = _severe_tiebreak([vd for vd, w in weights.items() if w == top])
    return _assemble(chosen, voters, locale, dimension)


DEFAULT_POLICY = "majority_severe"
POLICIES: dict[str, ConsensusPolicy] = {
    "majority_severe": majority_severe,
    "most_severe": most_severe,
    "unanimous": unanimous,
    "confidence_weighted": confidence_weighted,
}
