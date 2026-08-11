"""Tests for offline HTML->text extraction (v2 sub-project D, Task 2)."""

from asc_metadata_verifier.pages.content import html_to_text


def test_strips_tags_scripts_and_styles():
    html = (
        "<html><head><style>.a{color:red}</style><script>evil()</script></head>"
        "<body><h1>Privacy Policy</h1><p>We collect your email.</p></body></html>"
    )
    text = html_to_text(html)
    assert "Privacy Policy" in text and "We collect your email." in text
    assert "evil()" not in text and "color:red" not in text


def test_empty_html_is_empty_text():
    assert html_to_text("").strip() == ""
