"""Orchestrate one JSONL pass. Stdout is written only after every record succeeds."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any

from local_llm_review.errors import ProtocolError, ReviewError
from local_llm_review.jurisdiction_guard import build_guard_record, evaluate_guard
from local_llm_review.metadata import (
    RunSettings,
    RuntimeInfo,
    build_metadata,
    write_metadata,
)
from local_llm_review.prompt import render_prompt
from local_llm_review.protocol import dump_model_record, parse_jsonl, parse_model_output


def log(message: str) -> None:
    print(f"local-llm-review: {message}", file=sys.stderr)


def execute(
    text: str,
    *,
    runtime_factory: Callable[[], Any],
    settings: RunSettings,
    runtime_name: str,
    model_id: str,
    model_path_label: str,
    metadata_path: str | None,
    allowed_codes: frozenset[str] | set[str] | None = None,
    manifest_label: str | None = None,
    syllabus_manifest: Any = None,
) -> str:
    started = time.perf_counter()
    input_count = 0
    output_count = 0
    failure_count = 0
    info = RuntimeInfo()
    stdout = ""
    error: ReviewError | None = None
    try:
        # Validate the whole batch before starting a runtime so a bad line
        # never launches a model process.
        candidates = parse_jsonl(text)
        input_count = len(candidates)
        runtime = runtime_factory()
        info = runtime.info()
        lines: list[str] = []
        ids: list[str] = []
        for index, candidate in enumerate(candidates, start=1):
            # The deterministic jurisdiction guard runs first and, when it
            # matches, the runtime is never invoked for this record: there
            # is no model result to defer to or be overridden by, by
            # construction. See jurisdiction_guard.py for why (observed
            # 2026-10-14: a model can name a US-only institution correctly
            # in its own rationale and still recommend "keep" for it). The
            # fixture runtime is exempt: it is a documented development
            # double with its own fixed, byte-identical output (invariant
            # #6), never a claim about real model behavior, so there is no
            # real jurisdictional judgment here for the guard to backstop.
            guard = evaluate_guard(candidate) if runtime_name != "fixture" else None
            if guard is not None and guard.flagged:
                log(
                    f"record {index} ({candidate['id']}): deterministic guard matched "
                    f"{guard.rule} ({guard.category}); {runtime.name} was not invoked"
                )
                record = build_guard_record(candidate, guard)
            else:
                log(f"record {index} ({candidate['id']}): invoking {runtime.name}")
                prompt = render_prompt(candidate)
                completion = runtime.complete(candidate=candidate, prompt=prompt, settings=settings)
                record = parse_model_output(
                    completion,
                    expected_id=candidate["id"],
                    allowed_codes=allowed_codes,
                    manifest_label=manifest_label,
                )
            lines.append(dump_model_record(record, allowed_codes))
            ids.append(record["id"])
        if ids != [candidate["id"] for candidate in candidates] or len(lines) != input_count:
            raise ProtocolError(
                f"output records do not match input records "
                f"(input {input_count}, output {len(lines)})"
            )
        stdout = "".join(f"{line}\n" for line in lines)
        if stdout.count("\n") != input_count:
            raise ProtocolError("extra or missing output records")
        output_count = input_count
    except ReviewError as exc:
        error = exc
        failure_count = 1
        output_count = 0
        stdout = ""
    elapsed_ms = int(round((time.perf_counter() - started) * 1000))
    if metadata_path:
        document = build_metadata(
            runtime=runtime_name,
            model_id=model_id,
            model_path_label=model_path_label,
            settings=settings,
            info=info,
            input_count=input_count,
            output_count=output_count,
            failure_count=failure_count,
            elapsed_ms=elapsed_ms,
            syllabus_manifest=syllabus_manifest,
        )
        try:
            write_metadata(metadata_path, document)
        except OSError as exc:
            log(f"could not write metadata: {exc}")
            stdout = ""
            if error is None:
                error = ProtocolError(f"could not write metadata: {exc}")
    if error is not None:
        raise error
    log(f"runtime {runtime_name} records {output_count} elapsed {elapsed_ms} ms")
    return stdout
