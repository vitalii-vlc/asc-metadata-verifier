"""Tests for the opt-in code jury layer (Task 9). Fully offline: judges are
built from FunctionModel, no network, no API keys."""

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from asc_metadata_verifier.code.jury import (
    CodeJudge,
    CodeJury,
    InterpretiveUnit,
    apply_jury,
    build_units,
)
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.models import CodeFinding, RubricVerdict


def _rv(**kw):
    base = dict(dimension="d", verdict="fail", severity="high", confidence=0.9,
                rationale="r", locale="code", field="f")
    base.update(kw)
    return RubricVerdict(**base)


def _model(factory):
    def fn(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, factory().model_dump())])
    return FunctionModel(fn)


def _boom_model():
    def fn(messages, info):
        raise RuntimeError("kaboom")
    return FunctionModel(fn)


def _interp_finding():
    return CodeFinding(rule_id="boilerplate-usage-string", category="privacy-permissions",
                       severity="medium", guideline_ref="5.1.1", file="Info.plist", line=None,
                       symbol="NSCameraUsageDescription", evidence="We need access",
                       detail="generic", source="static")


def _unit():
    return InterpretiveUnit(id="d", kind="question", question="q?", file="A.swift", line=1,
                            excerpt="code", guideline_ref="5.1.1")


class _FakeAST:
    def __init__(self, syms):
        self._s = syms

    def symbols(self):
        return self._s

    def imports(self):
        return set()

    def calls(self, n):
        return []

    def string_literals(self):
        return []


def test_build_units_covers_interpretive_findings():
    units = build_units([_interp_finding()], ProjectModel(root="/p"), {})
    assert any(u.finding_ref == "boilerplate-usage-string" for u in units)


def test_apply_jury_no_specs_is_passthrough_offline():
    findings = [_interp_finding()]
    out, used = apply_jury(findings, ProjectModel(root="/p"), {}, judges=None)
    assert out == findings and used is False


def test_code_judge_error_isolation_returns_error_vote():
    judge = CodeJudge.from_model("x", _boom_model())
    vote = judge.run_sync(_unit(), "")
    assert vote.status == "error"


def test_apply_jury_dismisses_boilerplate_when_panel_passes():
    jury = CodeJury(
        [CodeJudge.from_model("j", _model(lambda: _rv(verdict="pass", severity="low")))],
        "majority_severe")
    out, used = apply_jury([_interp_finding()], ProjectModel(root="/p"), {},
                           jury=jury, grounding="")
    assert used is True and out == []  # pass -> interpretive finding dropped


def test_apply_jury_keeps_boilerplate_when_panel_fails():
    jury = CodeJury(
        [CodeJudge.from_model("j", _model(lambda: _rv(verdict="fail", severity="high")))],
        "majority_severe")
    out, used = apply_jury([_interp_finding()], ProjectModel(root="/p"), {},
                           jury=jury, grounding="")
    assert used and len(out) == 1 and out[0].source == "jury" and out[0].panel is not None


def test_apply_jury_adds_question_finding_on_fail():
    proj = ProjectModel(root="/p")
    asts = {"A.swift": _FakeAST({"requireLogin"})}
    jury = CodeJury(
        [CodeJudge.from_model("j", _model(lambda: _rv(verdict="fail", severity="high")))],
        "majority_severe")
    out, used = apply_jury([], proj, asts, jury=jury, grounding="")
    assert used and any(f.source == "jury" and f.rule_id == "account-gating-5.1.1v" for f in out)
