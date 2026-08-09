import pytest
from pydantic import ValidationError

from asc_metadata_verifier.models import (
    AppMetadata,
    DeterministicFinding,
    GateReport,
    LocaleMetadata,
    RubricVerdict,
    Screenshot,
)


def test_app_metadata_round_trip_with_two_locales():
    metadata = AppMetadata(
        app_id="123456789",
        primary_locale="en-US",
        locales=[
            LocaleMetadata(
                locale="en-US",
                app_name="My App",
                subtitle="Do things fast",
                promotional_text="Limited time offer",
                keywords="productivity,tasks",
                description="A long description of the app.",
                whats_new="Bug fixes and improvements.",
                support_url="https://example.com/support",
                marketing_url="https://example.com",
                privacy_url="https://example.com/privacy",
            ),
            LocaleMetadata(
                locale="es-ES",
                app_name="Mi App",
            ),
        ],
        screenshots=[
            Screenshot(locale="en-US", path="/tmp/en-US/1.png", display_type="APP_IPHONE_67"),
        ],
    )

    round_tripped = AppMetadata.model_validate(metadata.model_dump())

    assert round_tripped == metadata


def test_locale_metadata_only_locale_is_required():
    locale = LocaleMetadata(locale="en-US")

    assert locale.locale == "en-US"
    assert locale.app_name is None
    assert locale.subtitle is None
    assert locale.promotional_text is None
    assert locale.keywords is None
    assert locale.description is None
    assert locale.whats_new is None
    assert locale.support_url is None
    assert locale.marketing_url is None
    assert locale.privacy_url is None


def test_screenshot_path_is_str_for_json_round_trip():
    screenshot = Screenshot(locale="en-US", path="/tmp/en-US/1.png")

    dumped = screenshot.model_dump()

    assert isinstance(dumped["path"], str)


def test_rubric_verdict_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        RubricVerdict(
            dimension="tone",
            verdict="pass",
            severity="low",
            confidence=1.5,
            rationale="Looks fine.",
            locale="en-US",
            field="description",
        )


def test_rubric_verdict_rejects_invalid_verdict_literal():
    with pytest.raises(ValidationError):
        RubricVerdict(
            dimension="tone",
            verdict="maybe",
            severity="low",
            confidence=0.9,
            rationale="Looks fine.",
            locale="en-US",
            field="description",
        )


def test_rubric_verdict_accepts_valid_construction():
    verdict = RubricVerdict(
        dimension="tone",
        verdict="warn",
        severity="medium",
        confidence=0.75,
        rationale="Slightly promotional language.",
        offending_quote="the best app ever",
        guideline_ref="2.3.1",
        suggested_fix="Tone down superlatives.",
        locale="en-US",
        field="description",
    )

    assert verdict.verdict == "warn"
    assert verdict.confidence == 0.75


def test_deterministic_finding_construct_and_check():
    finding = DeterministicFinding(
        locale="en-US",
        field="subtitle",
        kind="over_limit",
        detail="Subtitle exceeds 30 characters.",
    )

    assert finding.kind == "over_limit"
    assert finding.locale == "en-US"


def test_gate_report_construct_and_check():
    report = GateReport(
        status="WARN",
        verdicts=[
            RubricVerdict(
                dimension="tone",
                verdict="warn",
                severity="medium",
                confidence=0.6,
                rationale="Borderline promotional claim.",
                locale="en-US",
                field="description",
            )
        ],
        deterministic_findings=[
            DeterministicFinding(
                locale="en-US",
                field="subtitle",
                kind="over_limit",
                detail="Subtitle exceeds 30 characters.",
            )
        ],
        guidelines_available=True,
    )

    assert report.status == "WARN"
    assert len(report.verdicts) == 1
    assert len(report.deterministic_findings) == 1
    assert report.guidelines_available is True
