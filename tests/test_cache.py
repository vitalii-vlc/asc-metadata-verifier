from asc_metadata_verifier.models import RubricVerdict
from asc_metadata_verifier.persistence.cache import (
    PROMPT_VERSION,
    VerdictCache,
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


def test_key_depends_on_prompt_version(monkeypatch):
    import asc_metadata_verifier.persistence.cache as cache
    base = cache.verdict_cache_key("p", "m")
    monkeypatch.setattr(cache, "PROMPT_VERSION", "a-different-version")
    assert cache.verdict_cache_key("p", "m") != base


class _FakeRepo:
    """Dict-backed fake satisfying the Repository verdict-cache methods."""

    def __init__(self):
        self.store: dict[str, RubricVerdict] = {}
        self.get_calls = 0
        self.put_calls = 0

    def get_cached_verdict(self, key: str) -> RubricVerdict | None:
        self.get_calls += 1
        return self.store.get(key)

    def put_cached_verdict(self, key: str, verdict: RubricVerdict) -> None:
        self.put_calls += 1
        self.store[key] = verdict


def _verdict() -> RubricVerdict:
    return RubricVerdict(
        dimension="placeholder_text",
        verdict="pass",
        severity="low",
        confidence=0.5,
        rationale="ok",
        locale="en-US",
        field="description",
    )


def test_verdict_cache_get_delegates_to_repo():
    repo = _FakeRepo()
    v = _verdict()
    repo.store["k1"] = v
    cache = VerdictCache(repo)
    assert cache.get("k1") == v
    assert repo.get_calls == 1


def test_verdict_cache_get_miss_returns_none():
    repo = _FakeRepo()
    cache = VerdictCache(repo)
    assert cache.get("missing") is None


def test_verdict_cache_put_delegates_to_repo():
    repo = _FakeRepo()
    v = _verdict()
    cache = VerdictCache(repo)
    cache.put("k1", v)
    assert repo.put_calls == 1
    assert repo.store["k1"] == v
