"""Asserts the REAL rule registry once all cluster modules land (Task 7)."""

from asc_metadata_verifier.code.rules import REGISTRY


def test_full_registry_has_all_clusters():
    ids = {r.id for r in REGISTRY}
    assert {
        "idfa-without-att",
        "missing-usage-string",
        "required-reason-api-undeclared",
        "boilerplate-usage-string",
        "uiwebview-usage",
        "private-api-symbol",
        "ats-arbitrary-loads",
        "insecure-http-endpoint",
        "encryption-export-undeclared",
        "canopenurl-undeclared-scheme",
    } <= ids
    assert len(ids) == len(REGISTRY)  # unique ids
