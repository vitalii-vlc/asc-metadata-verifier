"""Content-hash keys for the verdict cache + guideline snapshots.

A cache HIT must be the identical computation. The key folds in `PROMPT_VERSION`
(a hash of the judge SYSTEM prompt, which is not part of the per-call user prompt),
the resolved model name, and the full built prompt string (which already encodes
the rubric dimension, every locale text field, and the grounding actually used).
Any change to any of those changes the key -> a miss -> a fresh judge run."""

from __future__ import annotations

import hashlib

from asc_metadata_verifier.judge import prompts

PROMPT_VERSION = hashlib.sha256(prompts.TEXT_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


def verdict_cache_key(prompt: str, model_name: str) -> str:
    payload = "\x00".join([PROMPT_VERSION, model_name, prompt])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def snapshot_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
