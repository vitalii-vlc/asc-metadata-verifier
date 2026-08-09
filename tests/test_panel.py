import asyncio

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge.consensus import POLICIES
from asc_metadata_verifier.judge.panel import JudgePanel
from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.judge.vision import VISION_DIMENSIONS
from asc_metadata_verifier.models import (
    AppMetadata,
    JudgeVote,
    LocaleMetadata,
    RubricVerdict,
    Screenshot,
)

G = Guidelines(available=False, text="", sections={}, source="off")


class FakeClient:
    def __init__(self, name, verdict="fail", supports_vision=False, raise_text=False, tracker=None):
        self.name = name
        self.supports_vision = supports_vision
        self._verdict = verdict
        self._raise = raise_text
        self._t = tracker

    async def _vote(self):
        if self._t is not None:
            self._t["cur"] += 1
            self._t["max"] = max(self._t["max"], self._t["cur"])
            await asyncio.sleep(0.01)
            self._t["cur"] -= 1
        if self._raise:
            return JudgeVote(judge=self.name, status="error", error="boom")
        rv = RubricVerdict(dimension="d", verdict=self._verdict, severity="high",
                           confidence=0.9, rationale="r", locale="x", field="description")
        return JudgeVote(judge=self.name, status="voted", verdict=rv)

    async def run_text(self, dimension, locale_meta, grounding):
        return await self._vote()

    async def run_vision(self, screenshot, image_bytes, media_type, dimension, grounding):
        if not self.supports_vision:
            return JudgeVote(judge=self.name, status="not_applicable")
        return await self._vote()


def _panel(clients, name="majority_severe", mc=8):
    return JudgePanel(clients, POLICIES[name], name, max_concurrency=mc)


def _meta():
    return AppMetadata(locales=[LocaleMetadata(locale="en-US", description="x")])


def test_text_panel_one_paneleverdict_per_locale_dimension():
    panel = _panel([FakeClient("a"), FakeClient("b")])
    out = asyncio.run(panel.judge_text(_meta(), G, DIMENSIONS[:2]))
    assert len(out) == 2
    assert all(len(p.votes) == 2 and p.consensus.verdict == "fail" for p in out)
    assert out[0].policy == "majority_severe"


def test_error_isolation_one_judge_errors_other_still_votes():
    panel = _panel([FakeClient("ok"), FakeClient("bad", raise_text=True)])
    out = asyncio.run(panel.judge_text(_meta(), G, DIMENSIONS[:1]))
    p = out[0]
    assert p.consensus.verdict == "fail"           # the one voter carries it
    assert {v.status for v in p.votes} == {"voted", "error"}
    assert p.agreement == 1.0                       # over the single voter


def test_semaphore_caps_concurrency():
    tracker = {"cur": 0, "max": 0}
    clients = [FakeClient(f"c{i}", tracker=tracker) for i in range(6)]
    panel = _panel(clients, mc=2)
    asyncio.run(panel.judge_text(_meta(), G, DIMENSIONS[:3]))   # 3 units x 6 clients = 18 calls
    assert tracker["max"] <= 2


def test_vision_skipped_entirely_when_no_vision_client(tmp_path):
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    panel = _panel([FakeClient("text-only", supports_vision=False)])
    out = asyncio.run(
        panel.judge_vision([Screenshot(locale="en-US", path=str(png))], G, VISION_DIMENSIONS[:1])
    )
    assert out == []


def test_vision_runs_when_a_vision_client_present(tmp_path):
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    panel = _panel([FakeClient("v", supports_vision=True), FakeClient("t", supports_vision=False)])
    out = asyncio.run(
        panel.judge_vision([Screenshot(locale="en-US", path=str(png))], G, VISION_DIMENSIONS[:1])
    )
    assert len(out) == 1 and out[0].field == "screenshot"
    assert {v.status for v in out[0].votes} == {"voted", "not_applicable"}


def test_run_panel_twice_on_same_instance_does_not_raise_loop_error():
    """Fix 2: `asyncio.Semaphore` binds to the running loop on first use.
    Each `run_panel()` call opens a fresh loop via `asyncio.run`, so a
    semaphore built once in `__init__` (and actually contended, i.e. blocked
    on) would raise `RuntimeError: ... bound to a different event loop` on a
    second `run_panel()` call on the SAME panel instance. mc=2 with 18
    concurrent calls (3 units x 6 clients) forces real blocking, not just an
    uncontended acquire."""
    tracker = {"cur": 0, "max": 0}
    clients = [FakeClient(f"c{i}", tracker=tracker) for i in range(6)]
    panel = _panel(clients, mc=2)
    meta = _meta()

    out1 = panel.run_panel(meta, G, DIMENSIONS[:3])
    assert len(out1) == 3
    assert all(len(p.votes) == 6 and p.consensus.verdict == "fail" for p in out1)
    assert tracker["max"] <= 2

    out2 = panel.run_panel(meta, G, DIMENSIONS[:3])
    assert len(out2) == 3
    assert all(len(p.votes) == 6 and p.consensus.verdict == "fail" for p in out2)
    assert tracker["max"] <= 2


def test_run_panel_sync_concatenates_text_and_vision(tmp_path):
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    panel = _panel([FakeClient("v", supports_vision=True)])
    meta = AppMetadata(locales=[LocaleMetadata(locale="en-US", description="x")],
                       screenshots=[Screenshot(locale="en-US", path=str(png))])
    out = panel.run_panel(meta, G, DIMENSIONS[:1],
                          screenshots=meta.screenshots, vision_dimensions=VISION_DIMENSIONS[:1])
    fields = {p.field for p in out}
    assert "screenshot" in fields and len(out) == 2   # 1 text + 1 vision


def test_run_panel_no_vision_flag_skips_vision(tmp_path):
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    panel = _panel([FakeClient("v", supports_vision=True)])
    meta = AppMetadata(locales=[LocaleMetadata(locale="en-US", description="x")],
                       screenshots=[Screenshot(locale="en-US", path=str(png))])
    out = panel.run_panel(meta, G, DIMENSIONS[:1], screenshots=meta.screenshots,
                          vision_dimensions=VISION_DIMENSIONS[:1], no_vision=True)
    assert all(p.field != "screenshot" for p in out) and len(out) == 1


def test_single_real_client_panel_matches_v1_judge_field():
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from asc_metadata_verifier.judge.agent import judge_field
    from asc_metadata_verifier.judge.client import JudgeClient

    def factory(_text):
        return RubricVerdict(dimension="echo", verdict="warn", severity="medium", confidence=0.8,
                             rationale="r", offending_quote="Android", guideline_ref=None,
                             suggested_fix="fix", locale="echo", field="description")

    def make_model():
        def fn(messages, info: AgentInfo):
            chunks = []
            for m in messages:
                for p in getattr(m, "parts", []):
                    if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                        chunks.append(p.content)
            output = factory("\n".join(chunks)).model_dump()
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])
        return FunctionModel(fn)

    meta = AppMetadata(locales=[LocaleMetadata(locale="en-US", description="Also on Android")])
    v1 = judge_field(meta, G, DIMENSIONS[:1], model=make_model())[0]
    panel = _panel([JudgeClient.from_model("solo", make_model())])
    p = asyncio.run(panel.judge_text(meta, G, DIMENSIONS[:1]))[0]
    assert (p.consensus.verdict, p.consensus.severity, p.consensus.confidence) == \
           (v1.verdict, v1.severity, v1.confidence)
    assert p.consensus.locale == v1.locale and p.consensus.dimension == v1.dimension
    assert p.consensus.offending_quote == v1.offending_quote
