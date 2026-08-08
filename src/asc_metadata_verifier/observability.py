"""Logfire observability wiring.

`configure_logfire()` sets up Logfire once at process start. With no
`LOGFIRE_TOKEN` in the environment, `send_to_logfire="if-token-present"`
keeps everything local-only and performs no network I/O — this is what
makes the tool safe to run offline / in CI without credentials.

`span(name, **attrs)` is a thin wrapper around `logfire.span` so callers
elsewhere in the codebase (the CLI, the judge) don't need to import
`logfire` directly.
"""

from __future__ import annotations

from typing import Any

import logfire


def configure_logfire() -> None:
    """Configure Logfire for this process.

    Safe to call with no `LOGFIRE_TOKEN` set: `send_to_logfire="if-token-present"`
    means Logfire configures itself for local-only operation and does not
    attempt any network I/O when no token is present.
    """
    logfire.configure(
        send_to_logfire="if-token-present",
        service_name="asc-metadata-verifier",
    )
    logfire.instrument_pydantic_ai()


def span(name: str, **attrs: Any) -> Any:
    """Return a Logfire span context manager.

    Usage: `with span("ingest", source="fastlane"): ...`
    """
    return logfire.span(name, **attrs)
