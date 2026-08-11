"""Tests for the data-collection profile (v2 sub-project D, Task 5)."""

from asc_metadata_verifier.models import CodeFinding
from asc_metadata_verifier.pages.profile import build_profile


def _cf(rule_id, symbol):
    return CodeFinding(rule_id=rule_id, category="c", severity="high", guideline_ref="5.1.1",
                       file="A.swift", line=1, symbol=symbol, evidence="e", detail="d")


def test_usage_string_symbol_maps_to_category():
    p = build_profile([_cf("missing-usage-string", "AVCaptureDevice")])
    assert "camera" in p.categories


def test_idfa_maps_to_advertising_identifier():
    p = build_profile([_cf("idfa-without-att", "ASIdentifierManager")])
    assert "advertising identifier" in p.categories


def test_required_reason_contributes_nothing():
    p = build_profile([_cf("required-reason-api-undeclared", "UserDefaults")])
    assert p.categories == []


def test_categories_are_deduped_and_sorted():
    p = build_profile([_cf("missing-usage-string", "AVCaptureDevice"),
                       _cf("missing-usage-string", "AVCaptureDevice")])
    assert p.categories == ["camera"]
