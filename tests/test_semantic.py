from asc_metadata_verifier.persistence.semantic import InMemoryIndex, StubEmbedder


def test_stub_embedder_deterministic_fixed_dim():
    e = StubEmbedder()
    assert e.embed(["a"]) == e.embed(["a"])
    assert len(e.embed(["a"])[0]) == len(e.embed(["bb"])[0])


def test_in_memory_index_returns_nearest():
    idx = InMemoryIndex(StubEmbedder())
    idx.add([
        ("placeholder lorem ipsum", {"run_id": "r1", "dimension": "placeholder_text"}),
        ("also available on android", {"run_id": "r2", "dimension": "other_platform_mentions"}),
    ])
    hits = idx.query("lorem ipsum placeholder", k=1)
    assert hits and hits[0]["run_id"] == "r1"
