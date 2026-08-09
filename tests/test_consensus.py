from asc_metadata_verifier.judge.consensus import DEFAULT_POLICY, POLICIES
from asc_metadata_verifier.models import JudgeVote, RubricVerdict


def _vote(judge, verdict, severity="high", confidence=0.9, status="voted", field="description",
          quote="q", ref=None, fix="f", rationale="r"):
    rv = None
    if status == "voted":
        rv = RubricVerdict(dimension="d", verdict=verdict, severity=severity, confidence=confidence,
                           rationale=rationale, offending_quote=quote, guideline_ref=ref,
                           suggested_fix=fix, locale="x", field=field)
    return JudgeVote(judge=judge, status=status, verdict=rv)


def _run(name, votes):
    return POLICIES[name](
        votes, locale="en-US", dimension="placeholder_text", default_field="description"
    )


def test_registry_has_exactly_the_four_named_policies():
    assert set(POLICIES) == {"majority_severe", "most_severe", "unanimous", "confidence_weighted"}
    assert DEFAULT_POLICY == "majority_severe"


def test_majority_plurality_wins():
    votes = [_vote("a", "fail"), _vote("b", "fail"), _vote("c", "pass")]
    cons, agr = _run("majority_severe", votes)
    assert cons.verdict == "fail" and abs(agr - 2 / 3) < 1e-9


def test_majority_tie_breaks_to_more_severe():
    votes = [_vote("a", "fail"), _vote("b", "warn")]
    cons, _ = _run("majority_severe", votes)
    assert cons.verdict == "fail"


def test_most_severe_takes_worst():
    votes = [_vote("a", "pass"), _vote("b", "warn"), _vote("c", "pass")]
    cons, _ = _run("most_severe", votes)
    assert cons.verdict == "warn"


def test_unanimous_requires_all_to_escalate():
    assert _run("unanimous", [_vote("a", "fail"), _vote("b", "fail")])[0].verdict == "fail"
    assert _run("unanimous", [_vote("a", "fail"), _vote("b", "warn")])[0].verdict == "warn"
    assert _run("unanimous", [_vote("a", "fail"), _vote("b", "pass")])[0].verdict == "pass"


def test_confidence_weighted_prefers_high_confidence_side():
    votes = [_vote("a", "fail", confidence=0.4), _vote("b", "pass", confidence=0.55),
             _vote("c", "pass", confidence=0.55)]
    assert _run("confidence_weighted", votes)[0].verdict == "pass"


def test_non_voters_excluded_from_tally_but_agreement_over_voters():
    votes = [_vote("a", "fail"), _vote("b", None, status="error"),
             _vote("c", None, status="not_applicable"), _vote("d", "fail")]
    cons, agr = _run("majority_severe", votes)
    assert cons.verdict == "fail" and agr == 1.0  # 2/2 voters agree


def test_empty_voter_set_is_flagged_pass_not_a_fabricated_fail():
    votes = [_vote("a", None, status="error"), _vote("b", None, status="abstained")]
    cons, agr = _run("most_severe", votes)
    assert cons.verdict == "pass" and cons.confidence == 0.0 and agr is None
    assert "no judge" in cons.rationale.lower()


def test_representative_fields_come_from_highest_confidence_matching_voter():
    votes = [_vote("a", "fail", confidence=0.6, quote="low-conf", fix="fix-a"),
             _vote("b", "fail", confidence=0.95, quote="high-conf", fix="fix-b"),
             _vote("c", "pass", confidence=0.99, quote="ignore")]
    cons, _ = _run("majority_severe", votes)
    assert cons.offending_quote == "high-conf" and cons.suggested_fix == "fix-b"


def test_severity_is_max_and_confidence_is_mean_among_matching():
    votes = [_vote("a", "fail", severity="medium", confidence=0.8),
             _vote("b", "fail", severity="high", confidence=0.6)]
    cons, _ = _run("majority_severe", votes)
    assert cons.severity == "high" and abs(cons.confidence - 0.7) < 1e-9


def test_single_voter_consensus_equals_that_voter_verbatim():
    v = _vote("only", "warn", severity="medium", confidence=0.77, quote="qq", fix="ff")
    cons, agr = _run("majority_severe", [v])
    assert (cons.verdict, cons.severity, cons.confidence) == ("warn", "medium", 0.77)
    assert cons.offending_quote == "qq" and cons.suggested_fix == "ff" and agr == 1.0
