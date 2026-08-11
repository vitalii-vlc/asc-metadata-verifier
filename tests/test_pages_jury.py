"""Tests for the opt-in page jury (v2 sub-project D, Task 7). Fully offline via
FunctionModel; no network, no API keys."""

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from asc_metadata_verifier.models import RubricVerdict
from asc_metadata_verifier.pages.fetch import FetchedPage
from asc_metadata_verifier.pages.jury import PageJudge, PageJury, PageUnit, apply_page_jury
from asc_metadata_verifier.pages.profile import DataCollectionProfile


def _rv(**kw):
    base = dict(dimension="d", verdict="fail", severity="high", confidence=0.9,
                rationale="r", locale="page", field="privacy")
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


def _unit():
    return PageUnit(id="privacy-policy-inadequate", page_type="privacy", url="https://x/p",
                    question="q?", guideline_ref="5.1.1", text="some policy text")


def test_page_judge_error_isolation():
    vote = PageJudge.from_model("j", _boom_model()).run_sync(_unit(), "")
    assert vote.status == "error"


def test_cross_reference_flags_undisclosed_category():
    jury = PageJury(
        [PageJudge.from_model("j", _model(lambda: _rv(verdict="fail", severity="high")))],
        "majority_severe")
    pages = {"privacy": FetchedPage(url="https://x/p", ok=True, text="short policy")}
    profile = DataCollectionProfile(categories=["camera"])
    out = apply_page_jury(pages, profile, jury=jury, grounding="")
    assert any(f.rule_id == "privacy-code-mismatch" and f.category == "camera"
               and f.source == "jury" for f in out)


def test_disclosed_category_adds_nothing():
    jury = PageJury(
        [PageJudge.from_model("j", _model(lambda: _rv(verdict="pass", severity="low")))],
        "majority_severe")
    pages = {"privacy": FetchedPage(url="https://x/p", ok=True, text="we collect camera data")}
    profile = DataCollectionProfile(categories=["camera"])
    out = apply_page_jury(pages, profile, jury=jury, grounding="")
    assert all(f.rule_id != "privacy-code-mismatch" for f in out)
