"""Tests for field limits and required fields validation."""

from asc_metadata_verifier.limits import FIELD_LIMITS, REQUIRED_FIELDS, over_limit


class TestFieldLimits:
    """Test FIELD_LIMITS constant."""

    def test_field_limits_contains_all_expected_fields(self):
        """FIELD_LIMITS should contain all character-limited fields."""
        assert "app_name" in FIELD_LIMITS
        assert "subtitle" in FIELD_LIMITS
        assert "promotional_text" in FIELD_LIMITS
        assert "keywords" in FIELD_LIMITS
        assert "description" in FIELD_LIMITS
        assert "whats_new" in FIELD_LIMITS

    def test_field_limits_exact_values(self):
        """FIELD_LIMITS should have exact character limits."""
        assert FIELD_LIMITS["app_name"] == 30
        assert FIELD_LIMITS["subtitle"] == 30
        assert FIELD_LIMITS["promotional_text"] == 170
        assert FIELD_LIMITS["keywords"] == 100
        assert FIELD_LIMITS["description"] == 4000
        assert FIELD_LIMITS["whats_new"] == 4000


class TestRequiredFields:
    """Test REQUIRED_FIELDS constant."""

    def test_required_fields_contains_app_name(self):
        """app_name should be in REQUIRED_FIELDS."""
        assert "app_name" in REQUIRED_FIELDS

    def test_required_fields_contains_description(self):
        """description should be in REQUIRED_FIELDS."""
        assert "description" in REQUIRED_FIELDS

    def test_required_fields_contains_keywords(self):
        """keywords should be in REQUIRED_FIELDS."""
        assert "keywords" in REQUIRED_FIELDS

    def test_required_fields_exact_set(self):
        """REQUIRED_FIELDS should contain exactly app_name, description, keywords."""
        assert REQUIRED_FIELDS == {"app_name", "description", "keywords"}


class TestOverLimit:
    """Test over_limit function."""

    def test_over_limit_exceeds_by_one(self):
        """over_limit should return overflow count when value exceeds limit by 1."""
        result = over_limit("app_name", "x" * 31)
        assert result == 1

    def test_over_limit_exceeds_by_many(self):
        """over_limit should return correct overflow count for larger overages."""
        result = over_limit("app_name", "x" * 50)
        assert result == 20

    def test_over_limit_within_limit(self):
        """over_limit should return None when value is within limit."""
        result = over_limit("app_name", "ok")
        assert result is None

    def test_over_limit_at_exact_limit(self):
        """over_limit should return None when value is exactly at limit."""
        result = over_limit("app_name", "x" * 30)
        assert result is None

    def test_over_limit_with_none_value(self):
        """over_limit should return None when value is None."""
        result = over_limit("app_name", None)
        assert result is None

    def test_over_limit_unknown_field(self):
        """over_limit should return None for fields not in FIELD_LIMITS."""
        result = over_limit("support_url", "x" * 500)
        assert result is None

    def test_over_limit_empty_string(self):
        """over_limit should return None for empty string."""
        result = over_limit("app_name", "")
        assert result is None

    def test_over_limit_description_field(self):
        """over_limit should work correctly with description field."""
        # Within limit
        assert over_limit("description", "x" * 4000) is None
        # Over limit by 10
        assert over_limit("description", "x" * 4010) == 10

    def test_over_limit_keywords_field(self):
        """over_limit should work correctly with keywords field."""
        # Within limit
        assert over_limit("keywords", "x" * 100) is None
        # Over limit by 1
        assert over_limit("keywords", "x" * 101) == 1

    def test_over_limit_subtitle_field(self):
        """over_limit should work correctly with subtitle field."""
        assert over_limit("subtitle", "x" * 31) == 1

    def test_over_limit_promotional_text_field(self):
        """over_limit should work correctly with promotional_text field."""
        assert over_limit("promotional_text", "x" * 171) == 1

    def test_over_limit_whats_new_field(self):
        """over_limit should work correctly with whats_new field."""
        assert over_limit("whats_new", "x" * 4001) == 1
