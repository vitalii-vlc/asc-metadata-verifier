"""Rejection-risk rubric dimensions for the App Store metadata judge (Task 9).

Each dimension names one recurring reason Apple rejects an app's metadata. The
judge (``agent.py``) runs one verdict per (locale, dimension).

Honesty note: ``guideline_hint`` is ONLY prompt scaffolding -- a coarse, real
top-level guideline section used to help the judge *locate* grounding text. It
is deliberately imprecise and MUST NEVER be auto-copied into an output
``RubricVerdict.guideline_ref``. A ``guideline_ref`` may be cited only from the
grounding text actually shown to the model, and must be null when none is.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RubricDimension:
    """One rejection-risk dimension the judge evaluates a field against."""

    id: str
    description: str
    guideline_hint: str


# EXACTLY these 8 ids, in this order. `guideline_hint` values are coarse, real
# top-level sections: 2.3 "Accurate Metadata", 2.3.10 other-platform mentions,
# 5.2 intellectual property. They scaffold the prompt only (see module docstring).
DIMENSIONS: list[RubricDimension] = [
    RubricDimension(
        id="placeholder_text",
        description=(
            "Placeholder or unfinished copy (lorem ipsum, TODO, 'sample text') "
            "left in a shipped field."
        ),
        guideline_hint="2.3",
    ),
    RubricDimension(
        id="other_platform_mentions",
        description=(
            "References to other mobile platforms (Android, Google Play, "
            "'also available on...')."
        ),
        guideline_hint="2.3.10",
    ),
    RubricDimension(
        id="misleading_claims",
        description=(
            "Claims the app cannot back up, or exaggerated or deceptive "
            "descriptions of what it does."
        ),
        guideline_hint="2.3",
    ),
    RubricDimension(
        id="price_terms_in_description",
        description=(
            "Prices, discounts, or 'free'/'sale' terms embedded in the "
            "description or other text fields."
        ),
        guideline_hint="2.3",
    ),
    RubricDimension(
        id="keyword_stuffing",
        description=(
            "Competitor names, irrelevant terms, or repetition stuffed into "
            "keywords or other fields."
        ),
        guideline_hint="2.3",
    ),
    RubricDimension(
        id="beta_demo_mentions",
        description=(
            "'beta', 'demo', 'test', or 'trial build' language indicating an "
            "unfinished app."
        ),
        guideline_hint="2.3",
    ),
    RubricDimension(
        id="unauthorized_contact_links",
        description=(
            "Unauthorized contact information or off-platform purchase or "
            "support links."
        ),
        guideline_hint="2.3",
    ),
    RubricDimension(
        id="third_party_trademark",
        description="Third-party trademarks or intellectual property used without authorization.",
        guideline_hint="5.2",
    ),
]
