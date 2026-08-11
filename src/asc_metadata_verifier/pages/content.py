"""Reduce fetched HTML to clean, script/style-stripped text for the jury to
read. Pure, offline; adapts the reducer proven in guidelines/source.py."""

from __future__ import annotations

import re
from html import unescape


def html_to_text(html: str) -> str:
    without_scripts = re.sub(
        r"<script\b[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE
    )
    without_style = re.sub(
        r"<style\b[^>]*>.*?</style>", " ", without_scripts, flags=re.DOTALL | re.IGNORECASE
    )
    with_breaks = re.sub(r"<[^>]+>", "\n", without_style)
    unescaped = unescape(with_breaks)
    lines = [line.strip() for line in unescaped.splitlines() if line.strip()]
    return "\n".join(lines)
