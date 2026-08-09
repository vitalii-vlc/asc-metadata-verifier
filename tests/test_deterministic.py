"""Tests for LLM-free deterministic checks."""

from asc_metadata_verifier.checks.deterministic import run_deterministic
from asc_metadata_verifier.models import AppMetadata, LocaleMetadata


def _flawed_metadata() -> AppMetadata:
    return AppMetadata(
        app_id="123456789",
        primary_locale="en-US",
        locales=[
            LocaleMetadata(
                locale="en-US",
                app_name="x" * 31,  # over_limit
                subtitle="Do things fast",
                promotional_text="Limited time offer",
                keywords="",  # missing_required (empty after strip)
                description="Lorem ipsum TODO",  # placeholder
                whats_new="Bug fixes and improvements.",
                support_url="notaurl",  # malformed_url
                marketing_url="https://example.com",
                privacy_url="https://example.com/privacy",
            ),
        ],
    )


def _clean_metadata() -> AppMetadata:
    return AppMetadata(
        app_id="123456789",
        primary_locale="en-US",
        locales=[
            LocaleMetadata(
                locale="en-US",
                app_name="My App",
                subtitle="Do things fast",
                promotional_text="Limited time offer",
                keywords="productivity,tasks",
                description="A perfectly reasonable description of the app.",
                whats_new="Bug fixes and improvements.",
                support_url="https://example.com/support",
                marketing_url="https://example.com",
                privacy_url="https://example.com/privacy",
            ),
        ],
    )


class TestRunDeterministicFlawed:
    """Flawed fixture should surface all four finding kinds."""

    def test_finding_kinds_present(self):
        findings = run_deterministic(_flawed_metadata())
        kinds = {f.kind for f in findings}
        assert kinds == {"over_limit", "missing_required", "placeholder", "malformed_url"}

    def test_over_limit_points_at_app_name(self):
        findings = run_deterministic(_flawed_metadata())
        over_limit_findings = [f for f in findings if f.kind == "over_limit"]
        assert len(over_limit_findings) == 1
        assert over_limit_findings[0].field == "app_name"
        assert over_limit_findings[0].locale == "en-US"
        assert "31" in over_limit_findings[0].detail

    def test_placeholder_points_at_description(self):
        findings = run_deterministic(_flawed_metadata())
        placeholder_findings = [f for f in findings if f.kind == "placeholder"]
        assert len(placeholder_findings) == 1
        assert placeholder_findings[0].field == "description"
        assert placeholder_findings[0].locale == "en-US"

    def test_missing_required_points_at_keywords(self):
        findings = run_deterministic(_flawed_metadata())
        missing_findings = [f for f in findings if f.kind == "missing_required"]
        assert len(missing_findings) == 1
        assert missing_findings[0].field == "keywords"

    def test_malformed_url_points_at_support_url(self):
        findings = run_deterministic(_flawed_metadata())
        malformed_findings = [f for f in findings if f.kind == "malformed_url"]
        assert len(malformed_findings) == 1
        assert malformed_findings[0].field == "support_url"
        assert "notaurl" in malformed_findings[0].detail


class TestRunDeterministicClean:
    """Clean fixture should yield no findings."""

    def test_clean_metadata_yields_no_findings(self):
        assert run_deterministic(_clean_metadata()) == []


class TestPlaceholderPatterns:
    """Each placeholder pattern from the brief should be individually detected."""

    def _meta_with_app_name(self, value: str) -> AppMetadata:
        return AppMetadata(
            locales=[LocaleMetadata(locale="en-US", app_name=value)],
        )

    def test_lorem(self):
        findings = run_deterministic(self._meta_with_app_name("Lorem text"))
        assert any(f.kind == "placeholder" and f.field == "app_name" for f in findings)

    def test_ipsum(self):
        findings = run_deterministic(self._meta_with_app_name("ipsum text"))
        assert any(f.kind == "placeholder" and f.field == "app_name" for f in findings)

    def test_todo(self):
        findings = run_deterministic(self._meta_with_app_name("TODO fix name"))
        assert any(f.kind == "placeholder" and f.field == "app_name" for f in findings)

    def test_xxx(self):
        findings = run_deterministic(self._meta_with_app_name("XXX app"))
        assert any(f.kind == "placeholder" and f.field == "app_name" for f in findings)

    def test_fixme(self):
        findings = run_deterministic(self._meta_with_app_name("FIXME app"))
        assert any(f.kind == "placeholder" and f.field == "app_name" for f in findings)

    def test_placeholder_word(self):
        findings = run_deterministic(self._meta_with_app_name("placeholder app"))
        assert any(f.kind == "placeholder" and f.field == "app_name" for f in findings)

    def test_tbd(self):
        findings = run_deterministic(self._meta_with_app_name("TBD"))
        assert any(f.kind == "placeholder" and f.field == "app_name" for f in findings)

    def test_case_insensitive(self):
        findings = run_deterministic(self._meta_with_app_name("lOrEm text"))
        assert any(f.kind == "placeholder" and f.field == "app_name" for f in findings)

    def test_word_boundary_does_not_match_substring(self):
        """`\\blorem\\b` should not match inside a larger word like 'floremont'."""
        findings = run_deterministic(self._meta_with_app_name("Floremont App"))
        assert not any(f.kind == "placeholder" for f in findings)

    def test_one_finding_per_field_even_with_multiple_matches(self):
        """A field matching multiple patterns should still yield exactly one placeholder finding."""
        findings = run_deterministic(self._meta_with_app_name("Lorem ipsum TODO XXX"))
        placeholder_findings = [f for f in findings if f.kind == "placeholder"]
        assert len(placeholder_findings) == 1


class TestUrlFields:
    """URL validity rules per field."""

    def _meta_with_url(self, field: str, value: str | None) -> AppMetadata:
        kwargs = {"locale": "en-US", field: value}
        return AppMetadata(locales=[LocaleMetadata(**kwargs)])

    def test_valid_https_url_ok(self):
        findings = run_deterministic(self._meta_with_url("marketing_url", "https://example.com"))
        assert not any(f.kind == "malformed_url" for f in findings)

    def test_valid_http_url_ok(self):
        findings = run_deterministic(self._meta_with_url("privacy_url", "http://example.com"))
        assert not any(f.kind == "malformed_url" for f in findings)

    def test_none_url_is_silent(self):
        findings = run_deterministic(self._meta_with_url("support_url", None))
        assert not any(f.kind == "malformed_url" for f in findings)

    def test_empty_url_is_silent(self):
        findings = run_deterministic(self._meta_with_url("support_url", ""))
        assert not any(f.kind == "malformed_url" for f in findings)

    def test_missing_scheme_is_malformed(self):
        findings = run_deterministic(self._meta_with_url("marketing_url", "example.com"))
        assert any(f.kind == "malformed_url" and f.field == "marketing_url" for f in findings)

    def test_non_http_scheme_is_malformed(self):
        findings = run_deterministic(self._meta_with_url("privacy_url", "ftp://example.com"))
        assert any(f.kind == "malformed_url" and f.field == "privacy_url" for f in findings)


class TestPlaceholderAnchoringRegression:
    """Regression tests for anchoring TODO/XXX/FIXME/placeholder with \\b.

    Before this fix, these four patterns were unanchored and matched inside
    longer words/substrings (e.g. "XXX" matched inside "xxxxxxxxxxx...").
    """

    def test_false_positives_are_gone(self):
        """Substrings that used to trigger placeholder patterns must not anymore."""
        meta = AppMetadata(
            locales=[
                LocaleMetadata(
                    locale="en-US",
                    app_name="Maxxx",
                    subtitle="expandable options",
                    promotional_text="All placeholders filled in for launch",
                )
            ],
        )
        findings = run_deterministic(meta)
        assert not any(f.kind == "placeholder" for f in findings)

    def test_real_matches_still_detected(self):
        """Standalone tokens (space/punctuation-delimited) must still match."""
        meta = AppMetadata(
            locales=[
                LocaleMetadata(
                    locale="en-US",
                    description="Draft: TODO, XXX, FIXME, placeholder text.",
                )
            ],
        )
        findings = run_deterministic(meta)
        placeholder_findings = [
            f for f in findings if f.kind == "placeholder" and f.field == "description"
        ]
        assert len(placeholder_findings) == 1
        detail = placeholder_findings[0].detail
        assert "TODO" in detail
        assert "XXX" in detail
        assert "FIXME" in detail
        assert "placeholder" in detail


class TestMultiLocale:
    """run_deterministic must iterate every locale and tag findings correctly."""

    def test_two_locales_each_with_distinct_flaw(self):
        meta = AppMetadata(
            app_id="123456789",
            primary_locale="en-US",
            locales=[
                LocaleMetadata(
                    locale="en-US",
                    app_name="x" * 31,  # over_limit, only in en-US
                    description="A perfectly fine description.",
                    keywords="productivity",
                    support_url="https://example.com/support",
                ),
                LocaleMetadata(
                    locale="es-ES",
                    app_name="Mi App",
                    description="Una descripcion perfectamente valida.",
                    keywords="productividad",
                    support_url="notaurl",  # malformed_url, only in es-ES
                ),
            ],
        )

        findings = run_deterministic(meta)

        en_findings = [f for f in findings if f.locale == "en-US"]
        es_findings = [f for f in findings if f.locale == "es-ES"]

        assert any(f.kind == "over_limit" and f.field == "app_name" for f in en_findings)
        assert not any(f.kind == "over_limit" for f in es_findings)

        assert any(f.kind == "malformed_url" and f.field == "support_url" for f in es_findings)
        assert not any(f.kind == "malformed_url" for f in en_findings)

        # every finding is tagged with one of the two locales, nothing else
        assert {f.locale for f in findings} <= {"en-US", "es-ES"}
