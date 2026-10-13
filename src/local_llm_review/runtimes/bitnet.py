"""BitNet adapter.

Flag names below are candidates observed in microsoft/BitNet run_inference.py
on 2026-10-12. Nothing in this table is passed unless the installed
executable's own help text advertises that flag. Doctor is the check.
Support is not claimed when the check fails.

Upstream run_inference.py (that date) advertises -m/--model, -n/--n-predict,
-p/--prompt, -t/--threads, -c/--ctx-size, -temp/--temperature, and
-cnv/--conversation. It does not advertise a seed flag. It enables
conversation mode only when asked. This adapter never passes -cnv.

That script launches ./build/bin/llama-cli relative to the process working
directory and lets llama-cli write to the inherited stdout. A verified flag
interface is not a claim that generation stdout is clean JSON. Non-JSON
stdout fails closed in the runner.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from local_llm_review.errors import BitNetUnavailable, ProtocolError, RuntimeFailed, RuntimeTimeout
from local_llm_review.metadata import RuntimeInfo
from local_llm_review.process import capture_process, run_process

# Role -> aliases, first advertised alias wins. Order is a preference among
# flags the installed help actually prints, not permission to invent one.
FLAG_CANDIDATES: dict[str, tuple[str, ...]] = {
    "model": ("--model", "-m"),
    "prompt": ("--prompt", "-p"),
    "max_tokens": ("--n-predict", "--predict", "-n"),
    "threads": ("--threads", "-t"),
    "context": ("--ctx-size", "-c"),
    "temperature": ("--temperature", "--temp", "-temp"),
    "seed": ("--seed",),
    "gpu_layers": ("-ngl", "--gpu-layers"),
}
REQUIRED_ROLES = ("model", "prompt", "max_tokens", "threads", "context", "temperature")
NEVER_PASS = ("-cnv", "--conversation")
HELP_TIMEOUT_S = 20.0
HELP_BYTE_LIMIT = 1_000_000


@dataclass(frozen=True)
class Verification:
    supported: bool
    reason: str
    help_text: str
    argv_prefix: tuple[str, ...]
    flags: dict[str, str | None]
    executable: str
    model_path: str
    model_label: str
    cwd: str
    limitations: tuple[str, ...]


def _flag_advertised(help_text: str, flag: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", help_text) is not None


def _choose(help_text: str, aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        if _flag_advertised(help_text, alias):
            return alias
    return None


def format_temperature(value: float) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError("temperature must be a finite number >= 0")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")) or number < 0:
        raise ProtocolError("temperature must be a finite number >= 0")
    if number.is_integer():
        return str(int(number))
    rendered = format(number, ".6f").rstrip("0").rstrip(".")
    return rendered


def argv_prefix_for(executable: Path, *, role: str = "BitNet executable") -> list[str]:
    if not executable.is_file():
        raise BitNetUnavailable(
            f"{role} not found: {executable}. "
            "Support is not claimed. Pass an explicit local path."
        )
    if os.access(executable, os.X_OK) and executable.suffix != ".py":
        return [str(executable)]
    if executable.suffix == ".py" or _shebang_python(executable):
        import sys

        return [sys.executable, str(executable)]
    if os.access(executable, os.X_OK):
        return [str(executable)]
    raise BitNetUnavailable(
        f"{role} is not runnable: {executable}. "
        "Support is not claimed. Make it executable or pass a Python script."
    )


def _shebang_python(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            first = handle.readline(128)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def default_cwd(executable: Path, override: str | None) -> str | None:
    if override:
        cwd = Path(override).expanduser()
        if not cwd.is_dir():
            raise BitNetUnavailable(f"working directory does not exist: {cwd}")
        return str(cwd.resolve())
    # Upstream run_inference.py loads ./build/bin/llama-cli from the process cwd.
    if executable.name == "run_inference.py":
        return str(executable.parent)
    return None


def _read_help(prefix: list[str], cwd: str | None) -> tuple[int, str]:
    errors: list[str] = []
    for help_flag in ("-h", "--help"):
        try:
            captured = capture_process(
                [*prefix, help_flag],
                timeout_s=HELP_TIMEOUT_S,
                cwd=cwd,
            )
        except (OSError, RuntimeFailed, RuntimeTimeout) as exc:
            errors.append(str(exc))
            continue
        text = captured.stdout.decode("utf-8", "replace")
        if captured.stderr.strip():
            text = text + "\n" + captured.stderr.decode("utf-8", "replace")
        if len(text.encode("utf-8")) > HELP_BYTE_LIMIT:
            errors.append(f"{help_flag} output exceeded {HELP_BYTE_LIMIT} bytes")
            continue
        if captured.returncode == 0 and text.strip():
            return 0, text
        errors.append(f"{help_flag} exited {captured.returncode}: {text.strip()[:400]}")
    return 1, " | ".join(errors)


def gguf_magic(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"GGUF"
    except OSError:
        return False


def verify_bitnet(
    *,
    executable: str,
    model: str,
    model_label: str | None = None,
    cwd: str | None = None,
) -> Verification:
    exec_path = Path(executable).expanduser()
    if not exec_path.is_absolute():
        exec_path = Path.cwd() / exec_path
    exec_path = exec_path.resolve()
    model_path = Path(model).expanduser()
    if not model_path.is_absolute():
        model_path = Path.cwd() / model_path
    model_path = model_path.resolve()
    label = model if model_label is None else model_label
    limitations = [
        "conversation mode is not enabled; -cnv/--conversation is never passed",
    ]
    try:
        prefix = argv_prefix_for(exec_path)
        workdir = default_cwd(exec_path, cwd)
    except BitNetUnavailable as exc:
        return Verification(
            False, str(exc), "", (), {}, str(exec_path), str(model_path), label, cwd or "", (str(exc),)
        )
    if not model_path.is_file() or model_path.stat().st_size <= 0:
        reason = (
            f"BitNet model file is missing or empty: {model_path}. "
            "Support is not claimed. Download weights outside this repository "
            "and pass --model with that path."
        )
        return Verification(
            False, reason, "", tuple(prefix), {}, str(exec_path), str(model_path), label, workdir or "", (reason,)
        )
    status, help_text = _read_help(prefix, workdir)
    flags = {role: _choose(help_text, aliases) for role, aliases in FLAG_CANDIDATES.items()}
    missing = [role for role in REQUIRED_ROLES if not flags.get(role)]
    if status != 0 or missing or not help_text.strip():
        detail = ", ".join(missing) if missing else "help text was empty or the help command failed"
        reason = (
            "BitNet support is not claimed. The installed executable help did not "
            f"verify the required flags ({detail}). "
            "Refusing to guess CLI flags. Point --executable at the local "
            "run_inference.py (or another runtime) and re-run doctor. "
            f"Help check detail: {help_text.strip()[:400]}"
        )
        return Verification(
            False,
            reason,
            help_text,
            tuple(prefix),
            flags,
            str(exec_path),
            str(model_path),
            label,
            workdir or "",
            (reason,),
        )
    if not flags.get("seed"):
        limitations.append(
            "seed is not advertised by this runtime and will not be passed; "
            "temperature 0 is requested, but bit-exact sampling is not guaranteed"
        )
    if not gguf_magic(model_path):
        limitations.append(
            "model file does not start with GGUF magic; the runtime may still accept it"
        )
    if exec_path.name == "run_inference.py":
        # The script launches ./build/bin/llama-cli from the child cwd, not
        # from the directory that happens to contain the script.
        launch_root = Path(workdir) if workdir else exec_path.parent
        llama = launch_root / "build" / "bin" / "llama-cli"
        if not llama.is_file() or llama.stat().st_size <= 0:
            reason = (
                "BitNet support is not claimed. run_inference.py launches "
                f"{llama} from its working directory, and that binary is missing. "
                "Build BitNet before treating the runtime as available. "
                "The help text matched, but the runtime it launches was not found."
            )
            return Verification(
                False,
                reason,
                help_text,
                tuple(prefix),
                flags,
                str(exec_path),
                str(model_path),
                label,
                workdir or "",
                (reason,),
            )
        limitations.append(
            "run_inference.py inherits llama-cli stdout; noisy output fails closed"
        )
    return Verification(
        True,
        "flag interface verified against installed help",
        help_text,
        tuple(prefix),
        flags,
        str(exec_path),
        str(model_path),
        label,
        workdir or "",
        tuple(limitations),
    )


def build_argv(verification: Verification, prompt: str, settings: Any) -> tuple[list[str], RuntimeInfo]:
    if not verification.supported:
        raise BitNetUnavailable(verification.reason)
    argv = list(verification.argv_prefix)
    passed: list[str] = []

    def add(role: str, value: str) -> bool:
        flag = verification.flags.get(role)
        if not flag:
            return False
        if flag in NEVER_PASS:
            raise BitNetUnavailable(f"refusing to pass {flag}")
        argv.extend([flag, value])
        passed.append(flag)
        return True

    for role in REQUIRED_ROLES:
        if role == "model":
            value = verification.model_path
        elif role == "prompt":
            value = prompt
        elif role == "max_tokens":
            value = str(settings.max_tokens)
        elif role == "threads":
            value = str(settings.threads)
        elif role == "context":
            value = str(settings.context_length)
        elif role == "temperature":
            value = format_temperature(settings.temperature)
        else:
            raise BitNetUnavailable(f"unmapped role {role}")
        if not add(role, value):
            raise BitNetUnavailable(
                f"BitNet support is not claimed. Required flag for {role} was not verified."
            )
    seed_applied = add("seed", str(settings.seed))
    gpu_value: int | None = None
    gpu_flag = verification.flags.get("gpu_layers")
    requested = settings.gpu_layers
    if requested is not None and not gpu_flag:
        raise BitNetUnavailable(
            "gpu layers were requested but the runtime help does not advertise "
            "-ngl or --gpu-layers. Support is not claimed."
        )
    if gpu_flag:
        gpu_value = 0 if requested is None else requested
        add("gpu_layers", str(gpu_value))
    for forbidden in NEVER_PASS:
        if forbidden in argv:
            raise BitNetUnavailable(f"refusing to pass {forbidden}")
    info = RuntimeInfo(
        flags_passed=tuple(passed),
        seed_applied=seed_applied,
        support_claimed=True,
        executable=verification.executable,
        cwd=verification.cwd,
        gpu_layers=gpu_value,
    )
    return argv, info


class BitNetRuntime:
    name = "bitnet"

    def __init__(self, verification: Verification, settings: Any) -> None:
        if not verification.supported:
            raise BitNetUnavailable(verification.reason)
        self.verification = verification
        self.settings = settings
        # Build a probe argv with an empty prompt so a bad flag map fails
        # before any candidate is sent. The prompt is replaced per record.
        _, self._info = build_argv(verification, "probe", settings)

    def info(self) -> RuntimeInfo:
        return self._info

    def complete(self, *, candidate: dict[str, Any], prompt: str, settings: Any) -> str:
        del candidate
        argv, info = build_argv(self.verification, prompt, settings)
        self._info = info
        stdout = run_process(
            argv,
            timeout_s=settings.timeout_s,
            stdin_bytes=None,
            max_output_bytes=settings.max_output_bytes,
            cwd=self.verification.cwd or None,
        )
        try:
            return stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("model output is not valid UTF-8") from exc
