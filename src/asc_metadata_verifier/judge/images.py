"""Local screenshot reading for the vision judge.

Extracted verbatim from `judge/vision.py` so a future `JudgeClient` can read
and sanity-check screenshot bytes without depending on `judge.vision`
directly. Pure move -- no behavior change.
"""

from __future__ import annotations

import logging
from pathlib import Path

from asc_metadata_verifier.models import Screenshot

logger = logging.getLogger(__name__)

# Recognized image signatures, and the media type each one identifies.
# Deliberately minimal (no OCR, no image preprocessing, no third-party image
# library) -- just enough to avoid handing a non-image file to the vision
# model. This is the SINGLE SOURCE OF TRUTH for `BinaryContent.media_type`:
# it is derived from the matched signature (the actual bytes), never from the
# file's extension, which can lie (a `.jpg`-named file containing PNG bytes,
# or vice versa) -- `BinaryContent.media_type` is sent to the model verbatim
# and is not re-sniffed downstream, so an extension-derived type can silently
# mislabel the image.
IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def read_image(screenshot: Screenshot) -> tuple[bytes, str] | None:
    """Read and sanity-check local image bytes, or return None to skip.

    Returns `(data, media_type)`, where `media_type` is derived from the
    matched entry in `IMAGE_SIGNATURES` (the actual bytes), NOT the file's
    extension -- see the module-level comment on `IMAGE_SIGNATURES`. Returns
    None (logging a warning) when the path is a remote URL, the file is
    missing/unreadable, or the bytes don't match a recognized image
    signature. Never raises.
    """
    if screenshot.path.startswith("http://") or screenshot.path.startswith("https://"):
        logger.warning(
            "vision judge: skipping remote screenshot URL (Phase 2+ limitation, "
            "not fetched): %s",
            screenshot.path,
        )
        return None

    path = Path(screenshot.path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.warning("vision judge: skipping unreadable screenshot %s: %s", path, exc)
        return None

    for signature, media_type in IMAGE_SIGNATURES:
        if data.startswith(signature):
            return data, media_type

    logger.warning(
        "vision judge: skipping %s -- not a decodable image (unrecognized signature)",
        path,
    )
    return None
