"""Deterministic classifier used for CI and development. No model and no network."""

from __future__ import annotations

import re
from typing import Any

from local_llm_review.metadata import RuntimeInfo
from local_llm_review.protocol import dump_model_record

_GROUPS = {
    "0": "electrical safety",
    "1": "licensing rules",
    "2": "operating practice",
    "3": "radio-wave characteristics",
    "4": "station practice",
    "5": "electrical principles",
    "6": "electronic components",
    "7": "practical circuits",
    "8": "signals and modulation",
    "9": "antennas and feed lines",
}
TOPICS = {f"{band}{number}": label for band in "TGE" for number, label in _GROUPS.items()}

# Stage 8F2: the fixture's synthetic records carry syllabusCodes from this
# tiny built-in example set (a subset of the real us-hamexam
# editions/india/syllabus.json code set, so sibling-manifest compatibility
# tests accept them). The rule is deterministic and never echoes candidate
# text: a record that classifies as not syllabus-relevant gets [], a
# relevant record gets the single fixed code below. The set doubles as the
# allowed-code set for fixture runs that pass no --syllabus-manifest: the
# fixture is a documented development double (like its guard exemption and
# byte-identical output), not a model making real syllabus judgments.
EXAMPLE_CODES = frozenset({"A.SEMICONDUCTORS"})
FIXED_EXAMPLE_CODE = "A.SEMICONDUCTORS"

# Jurisdiction phrases are matched against question, choices, and ref only.
# poolKey and source are ignored so a pool name cannot trip the classifier.
_HIGH = (
    re.compile(r"\bfcc\b", re.IGNORECASE),
    re.compile(r"\bpart\s+97\b", re.IGNORECASE),
    re.compile(r"\b47\s+cfr\b", re.IGNORECASE),
    re.compile(r"\bvolunteer examiner\b", re.IGNORECASE),
    re.compile(r"\bvanity call sign\b", re.IGNORECASE),
)
_MEDIUM = (
    re.compile(r"\barrl\b", re.IGNORECASE),
    re.compile(r"\bitu region 2\b", re.IGNORECASE),
    re.compile(r"\bextra class\b", re.IGNORECASE),
    re.compile(r"\bgeneral class\b", re.IGNORECASE),
    re.compile(r"\btechnician class\b", re.IGNORECASE),
    re.compile(r"\bband plan\b", re.IGNORECASE),
)


def topic_for(sub: str) -> str:
    prefix = sub.strip().upper()[:2]
    return TOPICS.get(prefix, "radio fundamentals")


def _blob(candidate: dict[str, Any]) -> str:
    choices = candidate["choices"]
    parts = [candidate["question"], candidate["ref"]]
    parts.extend(choices[key] for key in ("A", "B", "C", "D"))
    return "\n".join(parts).casefold()


def _matches(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def classify(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return one contract record. The rationale is a fixed template, not model text.

    The CLI rejects ``figure: true`` before a runtime starts. This function
    still refuses to keep a figure if it is called directly.
    """

    text = _blob(candidate)
    high = _matches(text, _HIGH)
    medium = _matches(text, _MEDIUM)
    figure = candidate["figure"] is True
    topic = topic_for(candidate["sub"])
    if high:
        risk = "high"
        relevant = False
        recommendation = "defer" if figure else "reject"
    elif medium:
        risk = "medium"
        relevant = True
        recommendation = "defer" if figure else "adapt"
    else:
        risk = "none"
        relevant = True
        recommendation = "defer" if figure else "keep"
    warning = "warning" if figure else "none"
    if figure and high:
        rationale = (
            "Advisory only: jurisdiction-specific content plus an unresolved "
            "figure-rights flag needs a human; this is not publication approval."
        )
    elif figure:
        rationale = (
            "Advisory only: a figure-rights concern is unresolved and needs a human; "
            "this is not publication approval."
        )
    elif high:
        rationale = (
            "Advisory only: the question depends on jurisdiction-specific rules rather "
            "than a universal concept; this is not publication approval."
        )
    elif medium:
        rationale = (
            f"Advisory only: {topic} is mostly universal but the wording looks "
            "jurisdiction-specific and needs a human edit; this is not publication approval."
        )
    else:
        rationale = (
            f"Advisory only: {topic} is a universal radio or electronics concept; "
            "this is not publication approval."
        )
    return {
        "id": candidate["id"],
        "syllabusRelevant": relevant,
        "indianTopic": topic,
        "recommendation": recommendation,
        "jurisdictionRisk": risk,
        "figureRightsWarning": warning,
        "rationale": rationale,
        "syllabusCodes": [FIXED_EXAMPLE_CODE] if relevant else [],
    }


class FixtureRuntime:
    """Classifies from the candidate object. The rendered prompt is not consulted."""

    name = "fixture"

    def info(self) -> RuntimeInfo:
        return RuntimeInfo(support_claimed=False)

    def complete(self, *, candidate: dict[str, Any], prompt: str, settings: Any) -> str:
        del prompt, settings
        return dump_model_record(classify(candidate), EXAMPLE_CODES)
