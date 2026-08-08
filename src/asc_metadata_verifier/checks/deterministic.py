"""LLM-free deterministic checks for App Store Connect metadata.

This module never calls an LLM or the network: only string/regex/urlparse
logic. It flags mechanical problems (over-limit fields, missing required
fields, placeholder text, malformed URLs) that don't require judgment.
"""

import re
from urllib.parse import urlparse

from asc_metadata_verifier.limits import FIELD_LIMITS, REQUIRED_FIELDS, over_limit
from asc_metadata_verifier.models import AppMetadata, DeterministicFinding, LocaleMetadata

# The 6 length-limited/free-text fields eligible for placeholder scanning.
TEXT_FIELDS: tuple[str, ...] = (
    "app_name",
    "subtitle",
    "promotional_text",
    "keywords",
    "description",
    "whats_new",
)

# The 3 URL fields checked for well-formedness.
URL_FIELDS: tuple[str, ...] = ("support_url", "marketing_url", "privacy_url")

# Placeholder patterns, verbatim from the task brief, case-insensitive.
_PLACEHOLDER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\blorem\b",
        r"\bipsum\b",
        r"TODO",
        r"XXX",
        r"FIXME",
        r"placeholder",
        r"\bTBD\b",
    )
]


def _check_over_limit(locale: str, field: str, value: str | None) -> DeterministicFinding | None:
    overflow = over_limit(field, value)
    if overflow is None:
        return None

    limit = FIELD_LIMITS[field]
    detail = f"exceeds {limit}-char limit by {overflow} (len {len(value or '')})"
    return DeterministicFinding(locale=locale, field=field, kind="over_limit", detail=detail)


def _check_missing_required(
    locale: str, field: str, value: str | None
) -> DeterministicFinding | None:
    if value is None or value.strip() == "":
        return DeterministicFinding(
            locale=locale,
            field=field,
            kind="missing_required",
            detail="required field is empty",
        )
    return None


def _check_placeholder(locale: str, field: str, value: str | None) -> DeterministicFinding | None:
    if not value:
        return None

    matches: list[str] = []
    for pattern in _PLACEHOLDER_PATTERNS:
        match = pattern.search(value)
        if match:
            matches.append(match.group(0))

    if not matches:
        return None

    matched_text = ", ".join(f"'{m}'" for m in matches)
    detail = f"contains placeholder-like text: {matched_text}"
    return DeterministicFinding(locale=locale, field=field, kind="placeholder", detail=detail)


def _is_malformed_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme not in ("http", "https") or not parsed.netloc


def _check_malformed_url(
    locale: str, field: str, value: str | None
) -> DeterministicFinding | None:
    if not value:
        return None

    if _is_malformed_url(value):
        detail = f"'{value}' is not a valid URL"
        return DeterministicFinding(locale=locale, field=field, kind="malformed_url", detail=detail)

    return None


def _run_for_locale(locale_meta: LocaleMetadata) -> list[DeterministicFinding]:
    locale = locale_meta.locale
    findings: list[DeterministicFinding] = []

    for field in FIELD_LIMITS:
        value = getattr(locale_meta, field)
        finding = _check_over_limit(locale, field, value)
        if finding is not None:
            findings.append(finding)

    for field in REQUIRED_FIELDS:
        value = getattr(locale_meta, field)
        finding = _check_missing_required(locale, field, value)
        if finding is not None:
            findings.append(finding)

    for field in TEXT_FIELDS:
        value = getattr(locale_meta, field)
        finding = _check_placeholder(locale, field, value)
        if finding is not None:
            findings.append(finding)

    for field in URL_FIELDS:
        value = getattr(locale_meta, field)
        finding = _check_malformed_url(locale, field, value)
        if finding is not None:
            findings.append(finding)

    return findings


def run_deterministic(meta: AppMetadata) -> list[DeterministicFinding]:
    """Run all LLM-free deterministic checks across every locale.

    Checks performed per locale, independently:
      - over_limit: length-limited fields (FIELD_LIMITS) that exceed their cap.
      - missing_required: REQUIRED_FIELDS that are None or empty after strip().
      - placeholder: TEXT_FIELDS containing placeholder-like text (Lorem
        ipsum, TODO, XXX, FIXME, "placeholder", TBD).
      - malformed_url: URL_FIELDS that are present but not a valid http(s) URL.

    A single field may produce multiple findings of different kinds (e.g. an
    over-limit field that also contains "TODO" yields both an over_limit and
    a placeholder finding).

    This function is pure: no LLM calls, no network access.
    """
    findings: list[DeterministicFinding] = []
    for locale_meta in meta.locales:
        findings.extend(_run_for_locale(locale_meta))
    return findings
