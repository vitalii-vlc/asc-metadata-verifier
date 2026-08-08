"""App Store field limits and required fields validation."""

FIELD_LIMITS: dict[str, int] = {
    "app_name": 30,
    "subtitle": 30,
    "promotional_text": 170,
    "keywords": 100,
    "description": 4000,
    "whats_new": 4000,
}

REQUIRED_FIELDS: set[str] = {"app_name", "description", "keywords"}


def over_limit(field: str, value: str | None) -> int | None:
    """
    Return the overflow count when a field value exceeds its character limit.

    Args:
        field: The field name to check against FIELD_LIMITS.
        value: The value to check, or None.

    Returns:
        The overflow count (len(value) - FIELD_LIMITS[field]) when the value
        exceeds its limit; None when the value is within the limit, when
        value is None, or when the field is not in FIELD_LIMITS (e.g., URL
        fields have no length limit).
    """
    if value is None or field not in FIELD_LIMITS:
        return None

    limit = FIELD_LIMITS[field]
    value_length = len(value)

    if value_length > limit:
        return value_length - limit

    return None
