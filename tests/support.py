"""Shared helpers for the runner tests. Inserts the source tree on sys.path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
BIN = ROOT / "bin" / "local-llm-review"
PILOT = ROOT / "fixtures" / "pilot-25.jsonl"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def candidate(ident: str = "T2A01", **overrides) -> dict:
    record = {
        "id": ident,
        "poolKey": "technician",
        "sub": "T5A",
        "question": "What is the SI unit of electrical resistance?",
        "choices": {"A": "ohm", "B": "volt", "C": "ampere", "D": "watt"},
        "correct": "A",
        "correctText": "ohm",
        "ref": "synthetic",
        "figure": False,
        "source": {
            "editionId": "synthetic-pilot",
            "revisionId": "2026-10-12",
            "displayName": "Synthetic pilot fixture",
        },
    }
    record.update(overrides)
    return record


def jsonl(records: list[dict]) -> str:
    return "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)


def run_cli(args: list[str], stdin: str = "", env: dict | None = None, timeout: float = 30):
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(SRC)
    merged.pop("BITNET_EXECUTABLE", None)
    merged.pop("BITNET_MODEL", None)
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, "-m", "local_llm_review", *args],
        input=stdin.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged,
        cwd=ROOT,
        timeout=timeout,
        check=False,
    )


def run_bin(args: list[str], stdin: str = "", timeout: float = 30):
    merged = os.environ.copy()
    merged.pop("BITNET_EXECUTABLE", None)
    merged.pop("BITNET_MODEL", None)
    return subprocess.run(
        [str(BIN), *args],
        input=stdin.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged,
        cwd=ROOT,
        timeout=timeout,
        check=False,
    )
