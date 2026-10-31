"""JSONL candidate and model-output contract.

The model-output key set and enums match the us-hamexam Stage 8F2
review manifest (schemaVersion 3, model record contract v3). This module
does not import that repository. See docs/COMPATIBILITY.md.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from local_llm_review.errors import ProtocolError, UsageError

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
    "syllabusCodes",
)
RECOMMENDATIONS = frozenset({"keep", "adapt", "reject", "defer"})
JURISDICTION_RISKS = frozenset({"none", "low", "medium", "high"})
FIGURE_WARNINGS = frozenset({"none", "warning"})

DEFAULT_MAX_RECORDS = 10_000
DEFAULT_MAX_LINE_BYTES = 1_000_000


@dataclass(frozen=True)
class SyllabusManifest:
    """Minimal, stdlib-only equivalent of us-hamexam's loadSyllabusManifest.

    Only the fields this runner needs are loaded: the code set used to
    validate model-suggested syllabusCodes, plus identity fields recorded
    in the run metadata. Schema sanity is intentionally small: top-level
    object with a "topics" array whose entries carry a unique non-empty
    "code" and a "title", mirroring editions/india/syllabus.json.
    """

    path: str
    schema_version: Any
    sha256: str
    codes: frozenset[str]
    titles: dict[str, str]


def load_syllabus_manifest(path: str | Path) -> SyllabusManifest:
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise UsageError(f"syllabus manifest not readable: {target} ({exc})") from exc
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UsageError(f"syllabus manifest is malformed JSON: {target} ({exc})") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("topics"), list):
        raise UsageError(
            f"invalid syllabus manifest {target}: top-level object with a topics array required"
        )
    codes: set[str] = set()
    titles: dict[str, str] = {}
    for index, topic in enumerate(parsed["topics"]):
        if not isinstance(topic, dict):
            raise UsageError(f"invalid syllabus manifest {target}: topics[{index}] is not an object")
        code = topic.get("code")
        title = topic.get("title")
        if not _nonempty(code):
            raise UsageError(f"invalid syllabus manifest {target}: topics[{index}] has no non-empty code")
        if code in codes:
            raise UsageError(f"invalid syllabus manifest {target}: duplicate code {code!r}")
        if not _nonempty(title):
            raise UsageError(f"invalid syllabus manifest {target}: topics[{index}] has no title")
        codes.add(code)
        titles[code] = title
    return SyllabusManifest(
        path=str(target),
        schema_version=parsed.get("schemaVersion"),
        sha256=hashlib.sha256(raw).hexdigest(),
        codes=frozenset(codes),
        titles=titles,
    )


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


def validate_model_record(
    record: Any,
    expected_id: str,
    allowed_codes: frozenset[str] | set[str] | None = None,
    *,
    manifest_label: str | None = None,
) -> dict[str, Any]:
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
    # Stage 8E3 Part C: a high jurisdictionRisk and a keep recommendation
    # are mutually exclusive. The deterministic guard (jurisdiction_guard.py)
    # already keeps this combination from reaching here through the normal
    # runtime path, but this is the strict output validator; it must fail
    # closed on its own if some other caller ever hands it this pair.
    if record["jurisdictionRisk"] == "high" and record["recommendation"] == "keep":
        raise ProtocolError(
            f"model output for {expected_id}: recommendation cannot be keep when jurisdictionRisk is high"
        )
    # Stage 8F2 model record contract v3: syllabusCodes is an array of
    # syllabus-manifest codes. Fail closed per record: entries must be
    # non-empty strings with no duplicates; syllabusRelevant true requires
    # at least one code; a non-empty list with syllabusRelevant false is a
    # cross-field contradiction; and codes can only be validated against an
    # explicit manifest -- a record carrying codes when the run loaded no
    # manifest is rejected, never silently accepted.
    codes = record["syllabusCodes"]
    if not isinstance(codes, list):
        raise ProtocolError(
            f"model output for {expected_id}: syllabusCodes must be an array of manifest codes"
        )
    seen: set[str] = set()
    for code in codes:
        if not _nonempty(code):
            raise ProtocolError(
                f"model output for {expected_id}: syllabusCodes entries must be non-empty strings"
            )
        if code in seen:
            raise ProtocolError(
                f"model output for {expected_id}: duplicate syllabus code {code!r}"
            )
        seen.add(code)
        if allowed_codes is None:
            raise ProtocolError(
                f"model output for {expected_id}: syllabus code {code!r} cannot be validated "
                "because no syllabus manifest was provided to this run (fail closed; "
                "pass --syllabus-manifest)"
            )
        if code not in allowed_codes:
            raise ProtocolError(
                f"model output for {expected_id}: unknown syllabus code {code!r} "
                f"(not in manifest {manifest_label or '<not loaded>'})"
            )
    if record["syllabusRelevant"] and not codes:
        raise ProtocolError(
            f"model output for {expected_id}: syllabusRelevant is true but syllabusCodes "
            "is empty (at least one manifest code is required)"
        )
    if not record["syllabusRelevant"] and codes:
        raise ProtocolError(
            f"model output for {expected_id}: syllabusRelevant is false but syllabusCodes "
            "is non-empty (contradictory)"
        )
    return {key: record[key] for key in OUTPUT_KEYS}


def parse_model_output(
    text: str,
    *,
    expected_id: str,
    allowed_codes: frozenset[str] | set[str] | None = None,
    manifest_label: str | None = None,
) -> dict[str, Any]:
    stripped = text.strip()
    if stripped == "":
        raise ProtocolError(f"model output for {expected_id} is empty")
    try:
        value = loads_strict(stripped)
    except ProtocolError as exc:
        raise ProtocolError(
            f"model output for {expected_id} is malformed JSON: {exc}"
        ) from exc
    return validate_model_record(
        value, expected_id, allowed_codes, manifest_label=manifest_label
    )


def dump_model_record(
    record: dict[str, Any],
    allowed_codes: frozenset[str] | set[str] | None = None,
) -> str:
    canonical = validate_model_record(record, record["id"], allowed_codes)
    return json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
