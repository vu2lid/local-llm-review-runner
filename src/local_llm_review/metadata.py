"""Run metadata written beside the JSONL stream, never mixed into stdout."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from local_llm_review import __version__
from local_llm_review.prompt import PROMPT_VERSION, prompt_hash

METADATA_KEYS = (
    "runnerVersion",
    "runtime",
    "modelId",
    "modelPathLabel",
    "promptVersion",
    "promptHash",
    "syllabusManifest",
    "settings",
    "inputCount",
    "outputCount",
    "failureCount",
    "elapsedMs",
)

SETTINGS_KEYS = (
    "temperature",
    "seed",
    "contextLength",
    "maxTokens",
    "threads",
    "timeoutSeconds",
    "seedApplied",
    "flagsPassed",
    "gpuLayers",
    "supportClaimed",
    "executable",
    "cwd",
)


@dataclass(frozen=True)
class RunSettings:
    temperature: float = 0.0
    seed: int = 42
    context_length: int = 2048
    max_tokens: int = 256
    threads: int = 2
    timeout_s: float = 600.0
    max_output_bytes: int = 65_536
    gpu_layers: int | None = None
    cwd: str | None = None


@dataclass(frozen=True)
class RuntimeInfo:
    flags_passed: tuple[str, ...] = ()
    seed_applied: bool = False
    support_claimed: bool = False
    executable: str = ""
    cwd: str = ""
    gpu_layers: int | None = None


def settings_document(settings: RunSettings, info: RuntimeInfo) -> dict[str, Any]:
    return {
        "temperature": settings.temperature,
        "seed": settings.seed,
        "contextLength": settings.context_length,
        "maxTokens": settings.max_tokens,
        "threads": settings.threads,
        "timeoutSeconds": settings.timeout_s,
        "seedApplied": info.seed_applied,
        "flagsPassed": list(info.flags_passed),
        "gpuLayers": info.gpu_layers,
        "supportClaimed": info.support_claimed,
        "executable": info.executable,
        "cwd": info.cwd,
    }


def build_metadata(
    *,
    runtime: str,
    model_id: str,
    model_path_label: str,
    settings: RunSettings,
    info: RuntimeInfo,
    input_count: int,
    output_count: int,
    failure_count: int,
    elapsed_ms: int,
    syllabus_manifest: Any = None,
) -> dict[str, Any]:
    if syllabus_manifest is None:
        manifest_document = None
    else:
        manifest_document = {
            "path": syllabus_manifest.path,
            "schemaVersion": syllabus_manifest.schema_version,
            "sha256": syllabus_manifest.sha256,
            "codeCount": len(syllabus_manifest.codes),
        }
    document = {
        "runnerVersion": __version__,
        "runtime": runtime,
        "modelId": model_id,
        "modelPathLabel": model_path_label,
        "promptVersion": PROMPT_VERSION,
        "promptHash": prompt_hash(),
        "syllabusManifest": manifest_document,
        "settings": settings_document(settings, info),
        "inputCount": input_count,
        "outputCount": output_count,
        "failureCount": failure_count,
        "elapsedMs": elapsed_ms,
    }
    if tuple(document) != METADATA_KEYS:
        raise RuntimeError("metadata key order drifted from the contract")
    if tuple(document["settings"]) != SETTINGS_KEYS:
        raise RuntimeError("settings key order drifted from the contract")
    return document


def write_metadata(path: str | Path, document: dict[str, Any]) -> None:
    target = Path(path)
    if target.exists() and target.is_dir():
        raise OSError(f"metadata path is a directory: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, target)
