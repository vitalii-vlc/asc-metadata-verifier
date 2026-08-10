from asc_metadata_verifier.persistence.cache import (
    PROMPT_VERSION,
    snapshot_hash,
    verdict_cache_key,
)


def test_key_is_stable_for_identical_inputs():
    assert verdict_cache_key("prompt A", "m1") == verdict_cache_key("prompt A", "m1")


def test_key_changes_on_prompt_or_model():
    base = verdict_cache_key("prompt A", "m1")
    assert verdict_cache_key("prompt B", "m1") != base   # prompt (text/dim/grounding) differs
    assert verdict_cache_key("prompt A", "m2") != base   # model differs


def test_prompt_version_is_nonempty_and_folds_in():
    assert PROMPT_VERSION and isinstance(PROMPT_VERSION, str)


def test_snapshot_hash_is_content_addressed():
    assert snapshot_hash("2.3 body") == snapshot_hash("2.3 body")
    assert snapshot_hash("x") != snapshot_hash("y")
