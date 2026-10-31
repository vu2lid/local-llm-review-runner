"""Health check. BitNet support is claimed only after the installed help matches."""

from __future__ import annotations

import platform
import shutil
import sys
from typing import Any

from local_llm_review import __version__
from local_llm_review.errors import ReviewError
from local_llm_review.prompt import PROMPT_VERSION, prompt_hash, render_prompt
from local_llm_review.protocol import parse_model_output
from local_llm_review.runtimes.bitnet import verify_bitnet
from local_llm_review.runtimes.fixture import EXAMPLE_CODES, FixtureRuntime, classify

_SAMPLE = {
    "id": "DOCTOR",
    "poolKey": "technician",
    "sub": "T5A",
    "question": "What is the SI unit of electrical resistance?",
    "choices": {"A": "ohm", "B": "volt", "C": "ampere", "D": "watt"},
    "correct": "A",
    "correctText": "ohm",
    "ref": "doctor-sample",
    "figure": False,
    "source": {
        "editionId": "synthetic-doctor",
        "revisionId": "local",
        "displayName": "Doctor sample",
    },
}


def _tool_line(name: str) -> str:
    path = shutil.which(name)
    if not path:
        return f"{name}: not found"
    return f"{name}: {path}"


def _fixture_line() -> str:
    runtime = FixtureRuntime()
    record = classify(_SAMPLE)
    rendered = render_prompt(_SAMPLE)
    if "__CANDIDATE_JSON__" in rendered:
        raise ReviewError("prompt placeholder was not substituted")
    parse_model_output(
        runtime.complete(candidate=_SAMPLE, prompt=rendered, settings=None),
        expected_id="DOCTOR",
        allowed_codes=EXAMPLE_CODES,
    )
    if record["recommendation"] != "keep":
        raise ReviewError("fixture doctor sample did not classify as keep")
    return "ready"


def report_doctor(
    *,
    runtime: str | None = None,
    executable: str | None = None,
    model: str | None = None,
    cwd: str | None = None,
    command: str | None = None,
) -> tuple[int, str]:
    lines = [
        f"runnerVersion: {__version__}",
        f"python: {platform.python_version()}",
        _tool_line("cmake"),
        _tool_line("clang"),
        f"promptVersion: {PROMPT_VERSION}",
        f"promptHash: {prompt_hash()}",
    ]
    exit_code = 0
    try:
        lines.append(f"fixture: {_fixture_line()}")
    except (ReviewError, OSError) as exc:
        lines.append(f"fixture: failed ({exc})")
        exit_code = 1

    if runtime in (None, "fixture") and executable is None and command is None:
        lines.append("bitnet: not configured")
        lines.append("support claimed: no")
        lines.append("reason: pass --runtime bitnet --executable and --model to verify an installed runtime")
    elif runtime == "command" or command:
        from pathlib import Path

        target = command or executable
        if not target:
            lines.append("command: missing path")
            lines.append("support claimed: no")
            exit_code = 2
        else:
            path = Path(target).expanduser()
            if path.is_file():
                lines.append(f"command: present ({path})")
            else:
                lines.append(f"command: not found ({path})")
                exit_code = 2
            lines.append("bitnet: not configured")
            lines.append("support claimed: no")
            lines.append("reason: command runtime does not claim BitNet support")
    else:
        if not executable or not model:
            lines.append("bitnet: not configured")
            lines.append("support claimed: no")
            lines.append("reason: pass --executable and --model; support is not claimed")
            exit_code = 2
        else:
            verification = verify_bitnet(
                executable=executable, model=model, cwd=cwd
            )
            if verification.supported:
                chosen = [flag for flag in verification.flags.values() if flag]
                lines.append("bitnet: flag interface verified")
                lines.append(f"executable: {verification.executable}")
                lines.append(f"model: {verification.model_path}")
                lines.append(f"cwd: {verification.cwd or '(inherited)'}")
                lines.append("flags: " + " ".join(chosen))
                for item in verification.limitations:
                    lines.append(f"limitation: {item}")
                lines.append("support claimed: yes")
            else:
                lines.append("bitnet: unavailable")
                lines.append("support claimed: no")
                lines.append(f"reason: {verification.reason}")
                exit_code = 2
    text = "\n".join(lines) + "\n"
    if "support claimed: yes" in text and "support claimed: no" in text:
        raise ReviewError("doctor report claimed support and denied it")
    return exit_code, text


def toolchain_notes() -> list[str]:
    """Static requirements for the upstream BitNet CPU build. Not a support claim."""

    return [
        "BitNet CPU build requirements observed from microsoft/BitNet README on 2026-10-12:",
        "python >= 3.10, cmake >= 3.22, clang >= 18",
        "x86_64 quant types: i2_s, tl2",
        "arm64 / aarch64 quant types: i2_s, tl1",
        "GPU kernels are a separate upstream tree (BitNet gpu/) and are not claimed here",
    ]
