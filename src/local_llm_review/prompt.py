"""Versioned prompt template. The hash is the sha256 of the file bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from local_llm_review.errors import ProtocolError

PROMPT_VERSION = "india-review-prompt-v2"
PLACEHOLDER = "__CANDIDATE_JSON__"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "india-review-prompt-v2.txt"


def template_bytes() -> bytes:
    return PROMPT_PATH.read_bytes()


def template_text() -> str:
    data = template_bytes()
    if b"\r" in data:
        raise ProtocolError(f"prompt template {PROMPT_PATH.name} must use LF line endings")
    return data.decode("utf-8")


def prompt_hash() -> str:
    return hashlib.sha256(template_bytes()).hexdigest()


def render_prompt(candidate: dict[str, Any]) -> str:
    raw = template_text()
    if raw.count(PLACEHOLDER) != 1:
        raise ProtocolError(
            f"prompt template must contain {PLACEHOLDER} exactly once"
        )
    payload = json.dumps(
        candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if PLACEHOLDER in payload:
        raise ProtocolError(
            f"candidate {candidate.get('id')} contains the prompt placeholder; refusing to substitute"
        )
    return raw.replace(PLACEHOLDER, payload)
