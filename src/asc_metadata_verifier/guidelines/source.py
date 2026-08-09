"""Live App Store Review Guidelines source: session-cached, offline-safe.

Fetches https://developer.apple.com/app-store/review/guidelines/ so the judge
(Task 9) can ground its `guideline_ref` citations in the CURRENT guideline
text rather than stale hardcoded prose. Bound by two hard constraints:

- Honesty bar: on fetch failure this module NEVER fabricates guideline text.
  It returns `available=False` with empty text/sections; the caller (judge)
  is expected to omit `guideline_ref` when `available` is False.
- Session-scoped cache only: fetched once per session into a system-temp
  cache directory, reused for the rest of that session, and re-fetched next
  session. Nothing is committed to the repo.
"""

import json
import re
import tempfile
from html import unescape
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict

GUIDELINES_URL = "https://developer.apple.com/app-store/review/guidelines/"

# Session-scoped cache directory. Read via the bare module attribute at call
# time (not imported/aliased) so tests can `monkeypatch.setattr(source,
# "CACHE_DIR", tmp_path / "asc_cache")` and have it take effect.
CACHE_DIR = Path(tempfile.gettempdir()) / "asc_cache"

# A heading line looks like "2.3 Accurate Metadata" or "2.3.1 Inaccurate
# Screenshots" once HTML has been reduced to one heading/paragraph per line.
_SECTION_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)+)\s+(.+)$")

# A line that is *only* a section number, e.g. "2.3" with nothing else on the
# line -- happens when the real markup splits the number from the title via
# inline markup (a tooltip <span>/<img> between them inside <strong>2.3<span
# class="custom-tooltip-icon"><img .../></span> Accurate Metadata</strong>).
_BARE_SECTION_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)+$")

# session_id is interpolated directly into a cache filename; restrict it to
# a safe charset so it can never traverse out of CACHE_DIR.
_SESSION_ID_RE = re.compile(r"^[\w-]+$")


class Guidelines(BaseModel):
    """Result of a guidelines lookup: live fetch, session cache, or override."""

    model_config = ConfigDict(frozen=True)

    available: bool
    text: str
    sections: dict[str, str]
    source: str


def get_guidelines(
    session_id: str,
    override_path: str | Path | None = None,
    client: httpx.Client | None = None,
) -> Guidelines:
    """Return the App Store Review Guidelines text, grounded and offline-safe.

    Resolution order:
      1. `override_path` given -> read that local file, no network, no cache.
      2. Session cache hit (`CACHE_DIR/<session_id>.guidelines.json`) -> load
         it, no network call.
      3. Otherwise fetch `GUIDELINES_URL` via `client` (or a default
         `httpx.Client` if none was injected), cache the result, and return
         it. On any fetch failure, return `available=False` with empty
         text/sections rather than raising or fabricating content.

    `session_id` is validated first (it is interpolated into a cache
    filename) -- an id containing anything outside `[\\w-]` raises
    `ValueError` rather than being used to build a path.
    """
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session_id: {session_id!r}")

    if override_path is not None:
        return _load_override(override_path)

    cached = _load_cache(session_id)
    if cached is not None:
        return cached

    return _fetch_and_cache(session_id, client)


def _load_override(override_path: str | Path) -> Guidelines:
    path = Path(override_path)
    try:
        html = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FileNotFoundError(
            f"Guidelines override_path was given but is not a readable file: {path}"
        ) from exc

    lines = _html_to_lines(html)
    return Guidelines(
        available=True,
        text=" ".join(lines),
        sections=_extract_sections(lines),
        source=str(override_path),
    )


def _load_cache(session_id: str) -> Guidelines | None:
    cache_file = _cache_path(session_id)
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return Guidelines(
        available=bool(data.get("available", True)),
        text=data.get("text", ""),
        sections=data.get("sections", {}),
        source="cache",
    )


def _fetch_and_cache(session_id: str, client: httpx.Client | None) -> Guidelines:
    owns_client = client is None
    active_client = client if client is not None else httpx.Client(timeout=10.0)
    try:
        try:
            response = active_client.get(GUIDELINES_URL)
            response.raise_for_status()
        except httpx.HTTPError:
            # Honesty bar: never fabricate guideline text on fetch failure.
            return Guidelines(available=False, text="", sections={}, source=GUIDELINES_URL)

        lines = _html_to_lines(response.text)
        guidelines = Guidelines(
            available=True,
            text=" ".join(lines),
            sections=_extract_sections(lines),
            source=GUIDELINES_URL,
        )
        _write_cache(session_id, guidelines)
        return guidelines
    finally:
        if owns_client:
            active_client.close()


def _cache_path(session_id: str) -> Path:
    return CACHE_DIR / f"{session_id}.guidelines.json"


def _write_cache(session_id: str, guidelines: Guidelines) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "available": guidelines.available,
        "text": guidelines.text,
        "sections": guidelines.sections,
    }
    _cache_path(session_id).write_text(json.dumps(payload), encoding="utf-8")


def _html_to_lines(html: str) -> list[str]:
    """Reduce HTML to one trimmed, unescaped, non-empty line per element.

    Script/style element *bodies* are dropped first (not just their tag
    delimiters), so embedded JS/CSS text never leaks into the extracted
    text or sections. Afterwards, a line that is a bare section number
    (e.g. "2.3" split from its title by an inline tooltip <span>/<img>) is
    rejoined with the next non-empty line so the heading regex still
    matches it.
    """
    without_scripts = re.sub(
        r"<script\b[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE
    )
    without_style = re.sub(
        r"<style\b[^>]*>.*?</style>", " ", without_scripts, flags=re.DOTALL | re.IGNORECASE
    )
    with_breaks = re.sub(r"<[^>]+>", "\n", without_style)
    unescaped = unescape(with_breaks)
    raw_lines = [line.strip() for line in unescaped.splitlines() if line.strip()]
    return _merge_bare_section_numbers(raw_lines)


def _merge_bare_section_numbers(lines: list[str]) -> list[str]:
    """Rejoin a bare "2.3"-style line with the next line as its title."""
    merged: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _BARE_SECTION_NUMBER_RE.match(line) and index + 1 < len(lines):
            merged.append(f"{line} {lines[index + 1]}")
            index += 2
        else:
            merged.append(line)
            index += 1
    return merged


def _extract_sections(lines: list[str]) -> dict[str, str]:
    """Heuristically extract numbered guideline sections (e.g. "2.3") from
    stripped text lines. A section runs from its heading line up to (but not
    including) the next heading of the same or higher level (same or fewer
    dot-separated components), so nested subsections (e.g. "2.3.1") stay
    folded into their parent's captured text.
    """
    headings: list[tuple[int, str, int]] = []
    for index, line in enumerate(lines):
        match = _SECTION_HEADING_RE.match(line)
        if match:
            number = match.group(1)
            level = number.count(".") + 1
            headings.append((index, number, level))

    sections: dict[str, str] = {}
    for position, (start_index, number, level) in enumerate(headings):
        end_index = len(lines)
        for later_index, _later_number, later_level in headings[position + 1 :]:
            if later_level <= level:
                end_index = later_index
                break
        sections[number] = " ".join(lines[start_index:end_index]).strip()
    return sections
