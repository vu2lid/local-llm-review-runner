"""Deterministic jurisdiction guard, run before any model invocation.

Stage 8E3 Part B. A model can describe a US-specific institution correctly
in its own rationale and still recommend "keep" for it: the 2026-10-14
Qwen pilot against this project's own review prompt scored RACES, FCC
RF-exposure rules, and a "48 contiguous states" band-plan restriction all
"jurisdictionRisk": "none"/"low" with "recommendation": "keep", despite
rationale text that named the US-only institution correctly. This guard
runs on the candidate's own text, never on anything the model says, so
there is no model opinion for it to defer to or be overridden by: when it
fires, `runner.execute` skips invoking the runtime for that record
entirely and emits the guard's own record instead (see runner.py).

This file intentionally mirrors scripts/jurisdiction-guard.js in the
sibling us-hamexam checkout rule for rule (same ids, same categories, same
conservative scope) so the two tools agree on what counts as clearly
jurisdiction-specific. They cannot share code across the repository
boundary (this project does not import us-hamexam, and is not imported by
it), so keep both files in sync by hand if a rule changes.

Scope: the question text and the correct answer's text, NOT the other
three choices. Exam distractors routinely name an adjacent but incorrect
US-specific concept on purpose; a guard that scanned every choice would
reject a question for a decoy's sake. Every rule below already fires on
the question text alone against this project's own fixtures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    reason: str
    matches: Callable[[str], bool]


def _regex(pattern: str) -> Callable[[str], bool]:
    compiled = re.compile(pattern, re.IGNORECASE)
    return lambda text: compiled.search(text) is not None


def _all(*checks: Callable[[str], bool]) -> Callable[[str], bool]:
    return lambda text: all(check(text) for check in checks)


RULES: tuple[Rule, ...] = (
    Rule(
        "fcc-part-97",
        "Part 97 references",
        "names FCC Part 97, the US amateur-radio regulations",
        _regex(r"\bpart\s*97\b"),
    ),
    Rule(
        "races-civil-defense",
        "RACES and US civil-defense services",
        "names RACES or a civil-defense service, a US-only amateur radio program",
        _regex(r"\bRACES\b|\bcivil defense\b"),
    ),
    Rule(
        "band-plan-us",
        "US band-plan restrictions",
        "describes a US-specific voluntary band-plan restriction",
        _all(
            _regex(r"\bband\s*plan\b"),
            _regex(r"\b48\s+contiguous\s+states\b|\bUnited States\b|\bUS stations\b"),
        ),
    ),
    Rule(
        "callsign-licensing-us",
        "US call-sign/licensing rules",
        "describes a US-specific call-sign or licensing requirement",
        _regex(r"\bUS[- ]licensed\b|\bvanity call sign\b|\bVolunteer Examiner\b|\bVEC\b"),
    ),
    Rule(
        "rf-exposure-us",
        "US-specific RF-exposure or operating requirements",
        "describes FCC-specific RF-exposure requirements",
        _all(_regex(r"\bRF\s+exposure\b"), _regex(r"\bFCC\b")),
    ),
    Rule(
        "us-self-declared",
        "explicit United States framing",
        "explicitly frames the question as being about the United States",
        _regex(r"\bin the united states\b"),
    ),
    Rule(
        "fcc-reference",
        "FCC-only regulatory references",
        "names the FCC, a US-only regulatory body with no India ASOC analogue",
        _regex(r"\bFCC\b"),
    ),
)


@dataclass(frozen=True)
class GuardResult:
    flagged: bool
    rule: str | None
    category: str | None
    reason: str | None
    verdict: str | None


# verdict is always "reject" when flagged: every rule above only fires on a
# conservative, specific signal, so when one does fire the result is meant
# to be acted on, not treated as a soft hint.
def evaluate_guard(candidate: dict[str, Any]) -> GuardResult:
    text = f"{candidate['question']} {candidate['correctText']}"
    for rule in RULES:
        if rule.matches(text):
            return GuardResult(True, rule.id, rule.category, rule.reason, "reject")
    return GuardResult(False, None, None, None, None)


# Stage 8E3 review fix: this label and the rationale template below must
# read identically to us-hamexam's scripts/review-pipeline.js GUARD_TOPIC
# and guardRecord() -- a prior version of this file used the raw, per-rule
# `rule.category` text here (e.g. "RACES and US civil-defense services"),
# which meant the review UI showed a different-looking "Indian topic" for
# the exact same guarded candidate depending only on which tool produced
# the record. Exposing the matched rule id and its reason inside the
# rationale (not the category) stays intentional and shared: both
# implementations mirror the same RULES table, so those strings already
# agree by construction. See tests/test_jurisdiction_guard.py's
# cross-implementation test for the pinned shape this must keep matching.
GUARD_TOPIC = "Jurisdiction-specific (US) — not syllabus relevant"


def build_guard_record(candidate: dict[str, Any], guard: GuardResult) -> dict[str, Any]:
    return {
        "id": candidate["id"],
        "syllabusRelevant": False,
        "indianTopic": GUARD_TOPIC,
        "recommendation": guard.verdict,
        "jurisdictionRisk": "high",
        "figureRightsWarning": "none",
        "rationale": (
            f"Deterministic pre-invocation guard ({guard.rule}): {guard.reason} "
            "— no model involved; the adapter never saw this candidate"
        ),
    }
