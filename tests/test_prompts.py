from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge import prompts
from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.models import LocaleMetadata


def test_text_prompt_includes_grounding_and_fields():
    g = Guidelines(available=True, text="2.3 body", sections={"2.3": "2.3 body"}, source="t")
    lm = LocaleMetadata(locale="en-US", description="Also on Android")
    grounding = prompts.grounding_for_text(g, DIMENSIONS[0])
    out = prompts.build_text_prompt(DIMENSIONS[0], lm, grounding)
    assert "Android" in out and "2.3 body" in out


def test_grounding_empty_when_unavailable():
    g = Guidelines(available=False, text="", sections={}, source="off")
    assert prompts.grounding_for_text(g, DIMENSIONS[0]) == ""
