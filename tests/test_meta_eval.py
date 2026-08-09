"""Offline tests for the golden dataset + judge meta-eval (Task 13).

Every model call is served by a `FunctionModel` (pydantic_ai.models.function):
a local function inspects the prompt and returns a controlled `RubricVerdict`.
No network, no API key. The three stubs exercise the meta-eval aggregation:

- ``oracle_model``  : a perfect judge keyed on the golden answers -> accuracy 1.0.
- ``always_pass``   : never flags -> every positive case is a false_negative.
- ``always_fail``   : flags every dimension -> clean controls become false_positives.
"""

import os
import re

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from asc_metadata_verifier.evals.dataset import build_dataset, count_golden_lines
from asc_metadata_verifier.evals.meta_eval import MetaEvalReport, run
from asc_metadata_verifier.judge.rubric import DIMENSIONS

DIM_IDS = {d.id for d in DIMENSIONS}
_DIM_LINE_RE = re.compile(r"Rubric dimension id:\s*(\S+)")
_SEVERITY_FOR = {"warn": "medium", "fail": "high"}


def _user_text(messages) -> str:
    chunks: list[str] = []
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                chunks.append(part.content)
    return "\n".join(chunks)


def _verdict_payload(verdict: str, severity: str, quote: str | None) -> dict:
    return {
        "dimension": "echoed-by-model",
        "verdict": verdict,
        "severity": severity,
        "confidence": 0.9,
        "rationale": "stub",
        "offending_quote": quote,
        "guideline_ref": None,
        "locale": "echoed-by-model",
        "field": "description",
    }


def _model(fn) -> FunctionModel:
    def wrapped(messages, info: AgentInfo) -> ModelResponse:
        verdict, severity, quote = fn(_user_text(messages))
        tool_name = info.output_tools[0].name
        return ModelResponse(
            parts=[ToolCallPart(tool_name, _verdict_payload(verdict, severity, quote))]
        )

    return FunctionModel(wrapped)


def _always_pass() -> FunctionModel:
    return _model(lambda _text: ("pass", "low", None))


def _always_fail() -> FunctionModel:
    return _model(lambda _text: ("fail", "high", "x"))


def _oracle(flag_secondary: bool = False) -> FunctionModel:
    """A perfect judge: flags iff the queried dimension is the case's label.

    When ``flag_secondary`` is True it ALSO flags each case's genuine
    ``also_valid_dimensions`` -- used to prove that an accepted secondary
    detection is not scored as a false positive.
    """
    # (text, expected_dimension, expected_verdict, also_valid), longest-text
    # first so a case text that is a substring of another never shadows it.
    lookup = sorted(
        (
            (
                c.inputs.text,
                c.expected_output.expected_dimension,
                c.expected_output.expected_verdict,
                tuple(c.metadata.get("also_valid_dimensions", [])),
            )
            for c in build_dataset().cases
        ),
        key=lambda t: len(t[0]),
        reverse=True,
    )

    def fn(prompt: str):
        match = _DIM_LINE_RE.search(prompt)
        queried_dim = match.group(1) if match else ""
        for text, exp_dim, exp_verdict, also_valid in lookup:
            if text in prompt:
                if exp_dim == queried_dim and exp_verdict in {"warn", "fail"}:
                    return (exp_verdict, _SEVERITY_FOR[exp_verdict], text[:40])
                if flag_secondary and queried_dim in also_valid:
                    return ("fail", "high", "secondary")
                return ("pass", "low", None)
        return ("pass", "low", None)

    return _model(fn)


def test_build_dataset_loads_all_golden_cases():
    dataset = build_dataset()
    n_lines = count_golden_lines()
    assert n_lines >= 30, "golden set should have at least 30 cases"
    assert len(dataset.cases) == n_lines
    for case in dataset.cases:
        inp = case.inputs
        exp = case.expected_output
        assert inp.text.strip()
        assert inp.locale.strip()
        assert inp.field.strip()
        assert exp.expected_dimension in DIM_IDS or exp.expected_dimension == "none"
        assert exp.expected_verdict in {"pass", "warn", "fail"}
        # label coherence: clean controls pass, positives are flagged
        if exp.expected_dimension == "none":
            assert exp.expected_verdict == "pass"
        else:
            assert exp.expected_verdict in {"warn", "fail"}


def test_every_dimension_has_positive_cases():
    dataset = build_dataset()
    positives = [
        c.expected_output.expected_dimension
        for c in dataset.cases
        if c.expected_output.expected_dimension != "none"
    ]
    for dim in DIM_IDS:
        assert positives.count(dim) >= 3, f"{dim} needs >=3 positive cases"
    n_controls = sum(
        1 for c in dataset.cases if c.expected_output.expected_dimension == "none"
    )
    assert n_controls >= 8


def test_run_returns_report_with_keys_and_numeric_accuracy():
    report = run(model=_oracle())
    assert isinstance(report, MetaEvalReport)
    # per-dimension precision/recall have all 8 dimension keys
    assert set(report.per_dimension_precision) == DIM_IDS
    assert set(report.per_dimension_recall) == DIM_IDS
    for value in report.per_dimension_precision.values():
        assert 0.0 <= value <= 1.0
    for value in report.per_dimension_recall.values():
        assert 0.0 <= value <= 1.0
    assert isinstance(report.accuracy, float)
    assert 0.0 <= report.accuracy <= 1.0


def test_oracle_is_a_perfect_judge():
    """Sanity: a judge that matches the labels scores 1.0 and logs no failures."""
    report = run(model=_oracle())
    assert report.accuracy == 1.0
    for dim in DIM_IDS:
        assert report.per_dimension_precision[dim] == 1.0
        assert report.per_dimension_recall[dim] == 1.0
    assert report.total_failures() == 0


def test_failure_taxonomy_captures_deliberate_false_negative_miss():
    """always-pass stub misses every positive case -> false_negative taxonomy."""
    report = run(model=_always_pass())
    fn_misses = report.failure_taxonomy["false_negative"]
    assert fn_misses, "always-pass judge must produce false negatives"
    # every recorded miss must be debuggable and correctly categorized
    a_miss = fn_misses[0]
    assert a_miss.category == "false_negative"
    assert a_miss.expected_verdict in {"warn", "fail"}
    assert a_miss.got_verdict == "pass"
    assert a_miss.text_snippet
    # recall collapses to 0 for every dimension (all positives missed)
    for dim in DIM_IDS:
        assert report.per_dimension_recall[dim] == 0.0
    # clean controls are still handled correctly (they should all pass)
    assert 0.0 < report.accuracy < 1.0


def test_failure_taxonomy_captures_false_positives_on_clean_controls():
    """always-fail stub flags clean controls -> false_positive taxonomy."""
    report = run(model=_always_fail())
    fps = report.failure_taxonomy["false_positive"]
    assert fps, "always-fail judge must produce false positives on clean controls"
    assert fps[0].category == "false_positive"
    assert fps[0].got_verdict in {"warn", "fail"}
    assert fps[0].text_snippet


def test_dataset_carries_multi_label_ground_truth():
    """The 4 audited cross-dimension cases expose their genuine second label."""
    by_name = {c.name: c for c in build_dataset().cases}
    expected = {
        "15-keyword_stuffing": ["third_party_trademark"],
        "17-keyword_stuffing": ["third_party_trademark"],
        "24-unauthorized_contact_links": ["price_terms_in_description"],
        "25-unauthorized_contact_links": ["third_party_trademark"],
    }
    n_multi = 0
    for case in by_name.values():
        also = case.metadata.get("also_valid_dimensions", [])
        # every also_valid entry is a real dimension distinct from the primary
        for entry in also:
            assert entry in DIM_IDS
            assert entry != case.expected_output.expected_dimension
        if also:
            n_multi += 1
    assert n_multi == 4
    for name, also in expected.items():
        assert by_name[name].metadata["also_valid_dimensions"] == also


def test_also_valid_flag_is_accepted_not_false_positive():
    """A judge flag on a case's genuine SECOND dimension must NOT be an FP.

    The stub flags each case's `also_valid_dimensions` in addition to its
    primary label. Under single-label scoring the 3 third_party_trademark
    secondary flags would drag its precision to 4/(4+3)=0.571; multi-label
    ground truth keeps it at 1.0 and records zero false positives.
    """
    report = run(model=_oracle(flag_secondary=True))
    # the judge DID flag secondary dimensions ...
    assert report.accepted_secondary_detections == 4
    # ... yet none of those are counted as false positives (rule works) ...
    assert report.failure_taxonomy["false_positive"] == []
    assert report.total_failures() == 0
    # ... and precision on the "hardest" dimension is not depressed.
    assert report.per_dimension_precision["third_party_trademark"] == 1.0
    assert report.per_dimension_precision["price_terms_in_description"] == 1.0
    assert report.accuracy == 1.0
    # recall stays keyed on the PRIMARY label only (secondary flags never TP/FN)
    for dim in DIM_IDS:
        assert report.per_dimension_recall[dim] == 1.0


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY; real-model meta-eval skipped in offline runs",
)
def test_real_model_meta_eval():  # pragma: no cover - network-gated, skipped offline
    """Real-model meta-eval: build_judge default (Anthropic). Gated behind a key.

    NOT run in the dev environment. Task 15 records the real actuals in
    BUILD_LOG.md. We keep the bar low here (smoke, not a hard accuracy gate) so
    the gated test never encodes a fabricated expectation.
    """
    report = run(model=None)
    assert isinstance(report, MetaEvalReport)
    assert 0.0 <= report.accuracy <= 1.0
    assert set(report.per_dimension_precision) == DIM_IDS
