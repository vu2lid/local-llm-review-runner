"""JSONL candidate and model-output contract.

The model-output key set and enums match the us-hamexam Stage 8E1/8E2
review manifest (schemaVersion 2). This module does not import that
repository. See docs/COMPATIBILITY.md.
"""

from __future__ import annotations

import json
from typing import Any

from local_llm_review.errors import ProtocolError

CANDIDATE_KEYS = (
    "id",
    "poolKey",
    "sub",
    "question",
    "choices",
    "correct",
    "correctText",
    "ref",
    "figure",
    "source",
)
CHOICE_KEYS = ("A", "B", "C", "D")
SOURCE_KEYS = ("editionId", "revisionId", "displayName")
OUTPUT_KEYS = (
    "id",
    "syllabusRelevant",
    "indianTopic",
    "recommendation",
    "jurisdictionRisk",
    "figureRightsWarning",
    "rationale",
)
RECOMMENDATIONS = frozenset({"keep", "adapt", "reject", "defer"})
JURISDICTION_RISKS = frozenset({"none", "low", "medium", "high"})
FIGURE_WARNINGS = frozenset({"none", "warning"})

DEFAULT_MAX_RECORDS = 10_000
DEFAULT_MAX_LINE_BYTES = 1_000_000


def loads_strict(text: str) -> Any:
    """Parse one JSON value. Reject duplicate keys and trailing data."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise ProtocolError(f"duplicate key {key!r}")
            obj[key] = value
        return obj

    try:
        return json.loads(text, object_pairs_hook=reject_duplicates)
    except ProtocolError:
        raise
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"malformed JSON ({exc.msg})") from exc


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def validate_candidate(candidate: Any, *, line: int | None = None) -> dict[str, Any]:
    prefix = f"line {line}: " if line is not None else ""
    if not isinstance(candidate, dict):
        raise ProtocolError(f"{prefix}candidate must be a JSON object")
    if "id" not in candidate or not _nonempty(candidate.get("id")):
        raise ProtocolError(f"{prefix}missing id")
    ident = candidate["id"]
    missing = [key for key in CANDIDATE_KEYS if key not in candidate]
    if missing:
        raise ProtocolError(f"{prefix}candidate {ident} missing {', '.join(missing)}")
    if not _nonempty(candidate["poolKey"]) or not _nonempty(candidate["sub"]) or not _nonempty(candidate["question"]):
        raise ProtocolError(f"{prefix}candidate {ident} identity/text is invalid")
    choices = candidate["choices"]
    if not isinstance(choices, dict) or any(not _nonempty(choices.get(key)) for key in CHOICE_KEYS):
        raise ProtocolError(f"{prefix}candidate {ident} choices are invalid")
    if candidate["correct"] not in CHOICE_KEYS:
        raise ProtocolError(f"{prefix}candidate {ident} correct is invalid")
    if candidate["correctText"] != choices[candidate["correct"]]:
        raise ProtocolError(f"{prefix}candidate {ident} correctText does not match choices[correct]")
    if not isinstance(candidate["ref"], str):
        raise ProtocolError(f"{prefix}candidate {ident} ref is invalid")
    if not isinstance(candidate["figure"], bool):
        raise ProtocolError(f"{prefix}candidate {ident} figure must be a boolean")
    if candidate["figure"] is True:
        raise ProtocolError(
            f"{prefix}candidate {ident} has figure true; the us-hamexam Stage 8E manifest "
            "requires figure false, so figure-bearing questions are rejected before review"
        )
    source = candidate["source"]
    if not isinstance(source, dict) or any(not _nonempty(source.get(key)) for key in SOURCE_KEYS):
        raise ProtocolError(f"{prefix}candidate {ident} source metadata is invalid")
    return candidate


def iter_jsonl_lines(text: str) -> list[str]:
    """Split JSONL on LF and drop one trailing CR from each line.

    ``str.splitlines`` also splits on U+2028 and U+2029. Those scalars can
    sit inside a JSON string. us-hamexam splits on ``/\\r?\\n/`` only, so a
    candidate it emits must stay one record here.
    """

    lines: list[str] = []
    for line in text.split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        lines.append(line)
    return lines


def parse_jsonl(
    text: str,
    *,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
) -> list[dict[str, Any]]:
    if text.startswith("\ufeff"):
        raise ProtocolError("JSONL must not start with a BOM")
    records: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for line_no, line in enumerate(iter_jsonl_lines(text), start=1):
        if line.strip() == "":
            continue
        if len(line.encode("utf-8")) > max_line_bytes:
            raise ProtocolError(f"line {line_no}: line exceeds {max_line_bytes} bytes")
        try:
            obj = loads_strict(line)
        except ProtocolError as exc:
            raise ProtocolError(f"line {line_no}: {exc}") from exc
        candidate = validate_candidate(obj, line=line_no)
        prior = seen.get(candidate["id"])
        if prior is not None:
            raise ProtocolError(
                f"duplicate id {candidate['id']!r} on lines {prior} and {line_no}"
            )
        seen[candidate["id"]] = line_no
        records.append(candidate)
        if len(records) > max_records:
            raise ProtocolError(f"input exceeds {max_records} records")
    if not records:
        raise ProtocolError("no input records")
    return records


def validate_model_record(record: Any, expected_id: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ProtocolError(f"model output for {expected_id} is not an object")
    got = set(record)
    expected = set(OUTPUT_KEYS)
    if got != expected:
        missing = sorted(expected - got)
        extra = sorted(got - expected)
        raise ProtocolError(
            f"model output for {expected_id} has an invalid schema "
            f"(missing={missing}, extra={extra})"
        )
    if record["id"] != expected_id:
        raise ProtocolError(
            f"model output id mismatch: expected {expected_id}, got {record['id']}"
        )
    if not isinstance(record["syllabusRelevant"], bool):
        raise ProtocolError(
            f"model output for {expected_id}: syllabusRelevant must be a boolean"
        )
    if not _nonempty(record["indianTopic"]):
        raise ProtocolError(
            f"model output for {expected_id}: indianTopic must be a non-empty string"
        )
    if record["recommendation"] not in RECOMMENDATIONS:
        raise ProtocolError(
            f"model output for {expected_id}: recommendation must be keep|adapt|reject|defer"
        )
    if record["jurisdictionRisk"] not in JURISDICTION_RISKS:
        raise ProtocolError(
            f"model output for {expected_id}: jurisdictionRisk must be none|low|medium|high"
        )
    if record["figureRightsWarning"] not in FIGURE_WARNINGS:
        raise ProtocolError(
            f"model output for {expected_id}: figureRightsWarning must be none|warning"
        )
    if not _nonempty(record["rationale"]):
        raise ProtocolError(
            f"model output for {expected_id}: rationale must be a non-empty string"
        )
    return {key: record[key] for key in OUTPUT_KEYS}


def parse_model_output(text: str, *, expected_id: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped == "":
        raise ProtocolError(f"model output for {expected_id} is empty")
    try:
        value = loads_strict(stripped)
    except ProtocolError as exc:
        raise ProtocolError(
            f"model output for {expected_id} is malformed JSON: {exc}"
        ) from exc
    return validate_model_record(value, expected_id)


def dump_model_record(record: dict[str, Any]) -> str:
    canonical = validate_model_record(record, record["id"])
    return json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
