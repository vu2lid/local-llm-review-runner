"""Toolchain report and the only command that may use the network."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from local_llm_review.doctor import report_doctor, toolchain_notes
from local_llm_review.errors import UsageError
from local_llm_review.process import capture_process

DEFAULT_REPO = "microsoft/BitNet-b1.58-2B-4T-gguf"


def repository_root() -> Path | None:
    """Find this checkout from the cwd or from this file. None when installed elsewhere."""

    seeds = [Path.cwd().resolve(), Path(__file__).resolve()]
    seen: set[Path] = set()
    for seed in seeds:
        for candidate in (seed, *seed.parents):
            if candidate in seen:
                continue
            seen.add(candidate)
            marker = candidate / "src" / "local_llm_review" / "protocol.py"
            if (candidate / "pyproject.toml").is_file() and marker.is_file():
                return candidate
    return None


def model_dir_inside_repository(model_dir: str) -> bool:
    root = repository_root()
    if root is None:
        return False
    target = Path(model_dir).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _download_argv(repo: str, model_dir: str) -> list[str]:
    if shutil.which("huggingface-cli"):
        tool = "huggingface-cli"
    elif shutil.which("hf"):
        tool = "hf"
    else:
        raise UsageError(
            "huggingface-cli (or hf) is not on PATH. "
            "Install it yourself, then re-run setup --download --confirm-network. "
            "This runner does not install packages and does not download during inference."
        )
    # One argv element so a path that starts with "-" is still a directory.
    return [tool, "download", repo, f"--local-dir={model_dir}"]


def run_setup(
    *,
    download: bool,
    confirm_network: bool,
    model_dir: str | None,
    repo: str,
) -> int:
    code, report = report_doctor()
    sys.stdout.write(report)
    sys.stdout.write("\n".join(toolchain_notes()) + "\n")
    if not download:
        sys.stdout.write(
            "network: not used. Re-run with --download --confirm-network --model-dir DIR "
            "to download weights outside this repository.\n"
        )
        return 0 if code != 1 else code
    if not confirm_network:
        raise UsageError(
            "setup --download contacts the network. Re-run with --confirm-network. "
            "Inference commands never download."
        )
    if not model_dir:
        raise UsageError("setup --download requires --model-dir outside this repository")
    if model_dir_inside_repository(model_dir):
        raise UsageError(
            "setup --download refuses a model directory inside this repository. "
            "Pass --model-dir outside this repository so weights are not committed."
        )
    argv = _download_argv(repo, model_dir)
    sys.stderr.write(
        "local-llm-review: network download starting: " + " ".join(argv) + "\n"
    )
    captured = capture_process(argv, timeout_s=3600)
    sys.stdout.buffer.write(captured.stdout)
    sys.stderr.buffer.write(captured.stderr)
    if captured.returncode != 0:
        raise UsageError(f"model download exited {captured.returncode}")
    sys.stderr.write(
        "local-llm-review: download finished. Keep the weights outside the git tree.\n"
    )
    return 0
