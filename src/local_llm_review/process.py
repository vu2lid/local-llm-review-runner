"""Subprocess helper. Inference never uses a shell."""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass

from local_llm_review.errors import ProtocolError, RuntimeFailed, RuntimeTimeout


@dataclass(frozen=True)
class Captured:
    returncode: int
    stdout: bytes
    stderr: bytes


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        proc.kill()


def _tail(data: bytes, limit: int = 500) -> str:
    text = data.decode("utf-8", "replace").strip()
    if len(text) > limit:
        return text[-limit:]
    return text


def capture_process(
    argv: list[str],
    *,
    timeout_s: float,
    stdin_bytes: bytes | None = None,
    cwd: str | None = None,
) -> Captured:
    if timeout_s <= 0:
        raise RuntimeTimeout("timeout must be greater than 0 seconds")
    if not argv or not isinstance(argv[0], str):
        raise RuntimeFailed("runtime argv is empty")
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            start_new_session=True,
        )
    except OSError as exc:
        raise RuntimeFailed(f"could not start runtime: {exc}") from exc
    try:
        stdout, stderr = proc.communicate(stdin_bytes, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        _kill_group(proc)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
        raise RuntimeTimeout(f"runtime timed out after {timeout_s} seconds") from exc
    if proc.returncode is None:
        raise RuntimeFailed("runtime exited without a status")
    return Captured(returncode=proc.returncode, stdout=stdout, stderr=stderr)


def run_process(
    argv: list[str],
    *,
    timeout_s: float,
    stdin_bytes: bytes | None = None,
    max_output_bytes: int,
    cwd: str | None = None,
) -> bytes:
    captured = capture_process(
        argv, timeout_s=timeout_s, stdin_bytes=stdin_bytes, cwd=cwd
    )
    if captured.returncode != 0:
        detail = _tail(captured.stderr)
        message = f"runtime exited {captured.returncode}"
        if detail:
            message = f"{message}: {detail}"
        raise RuntimeFailed(message)
    if len(captured.stdout) > max_output_bytes:
        raise ProtocolError(f"model output exceeded {max_output_bytes} bytes")
    return captured.stdout
