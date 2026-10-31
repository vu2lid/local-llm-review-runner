"""Command line. JSONL runs read stdin and write stdout. Diagnostics go to stderr."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from local_llm_review import __version__
from local_llm_review.doctor import report_doctor
from local_llm_review.errors import ReviewError, UsageError
from local_llm_review.metadata import RunSettings
from local_llm_review.protocol import load_syllabus_manifest
from local_llm_review.runner import execute, log
from local_llm_review.runtimes.bitnet import BitNetRuntime, verify_bitnet
from local_llm_review.runtimes.command import CommandRuntime
from local_llm_review.runtimes.fixture import EXAMPLE_CODES, FixtureRuntime
from local_llm_review.setup_cmd import DEFAULT_REPO, run_setup


def _finite_float(text: str, *, lower: float | None, name: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{name} must be a number") from exc
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError(f"{name} must be finite")
    if lower is not None and value < lower:
        raise argparse.ArgumentTypeError(f"{name} must be >= {lower}")
    return value


def temperature_value(text: str) -> float:
    return _finite_float(text, lower=0.0, name="temperature")


def timeout_value(text: str) -> float:
    value = _finite_float(text, lower=None, name="timeout")
    if value <= 0:
        raise argparse.ArgumentTypeError("timeout must be > 0")
    return value


def positive_int(text: str) -> int:
    try:
        value = int(text, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("expected an integer >= 1")
    return value


def any_int(text: str) -> int:
    try:
        return int(text, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc


def bind_command_arg_values(argv: list[str]) -> list[str]:
    """Keep the token after --command-arg even when it starts with a dash.

    argparse otherwise treats `--command-arg --literal` as a missing value.
    The command runtime must be able to pass flag-like argv elements.
    `--command-arg=--literal` is left unchanged.
    """
    bound: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--command-arg" and index + 1 < len(argv):
            bound.append("--command-arg=" + argv[index + 1])
            index += 2
            continue
        bound.append(token)
        index += 1
    return bound


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-llm-review",
        description=(
            "Classify candidate-review JSONL with a local runtime. "
            "Reads JSONL on stdin and writes JSONL on stdout. Diagnostics go to stderr."
        ),
    )
    parser.add_argument("--version", action="version", version=f"local-llm-review {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    doctor = sub.add_parser("doctor", help="check the fixture and, when asked, a BitNet runtime")
    doctor.add_argument("--runtime", choices=("fixture", "bitnet", "command"))
    doctor.add_argument("--executable", help="BitNet runtime script or binary")
    doctor.add_argument("--model", help="model file path")
    doctor.add_argument("--command", help="command runtime executable")
    doctor.add_argument("--cwd", help="working directory for the runtime")

    run = sub.add_parser("run", help="read candidate JSONL on stdin and write classification JSONL")
    run.add_argument("--runtime", required=True, choices=("fixture", "bitnet", "command"))
    run.add_argument("--model", help="model file path (required for bitnet)")
    run.add_argument("--executable", help="BitNet runtime script or binary (required for bitnet)")
    run.add_argument("--model-id", help="model identifier recorded in metadata")
    run.add_argument("--model-path-label", help="model path label recorded in metadata")
    run.add_argument("--temperature", type=temperature_value, default=0.0)
    run.add_argument("--seed", type=any_int, default=42)
    run.add_argument("--context", type=positive_int, default=2048)
    run.add_argument("--max-tokens", type=positive_int, default=256)
    run.add_argument("--threads", type=positive_int, default=2)
    run.add_argument("--timeout", type=timeout_value, default=600.0)
    run.add_argument("--gpu-layers", type=any_int, default=None)
    run.add_argument("--metadata", help="write the run metadata JSON here, not to stdout")
    run.add_argument(
        "--syllabus-manifest",
        help="syllabus manifest JSON whose topic codes validate model-suggested syllabusCodes",
    )
    run.add_argument("--command", help="executable for --runtime command")
    run.add_argument("--command-arg", action="append", default=None, help="one argv element, repeatable")
    run.add_argument("--cwd", help="working directory for the runtime")
    run.add_argument("--max-output-bytes", type=positive_int, default=65536)

    setup = sub.add_parser("setup", help="report toolchain requirements; download only when asked")
    setup.add_argument("--download", action="store_true")
    setup.add_argument("--confirm-network", action="store_true")
    setup.add_argument("--model-dir")
    setup.add_argument("--hf-repo", default=DEFAULT_REPO)
    return parser


def settings_from(args: argparse.Namespace) -> RunSettings:
    return RunSettings(
        temperature=args.temperature,
        seed=args.seed,
        context_length=args.context,
        max_tokens=args.max_tokens,
        threads=args.threads,
        timeout_s=args.timeout,
        max_output_bytes=args.max_output_bytes,
        gpu_layers=args.gpu_layers,
        cwd=args.cwd,
    )


def _identities(args: argparse.Namespace) -> tuple[str, str]:
    if args.runtime == "fixture":
        model_id = args.model_id or "fixture"
        if args.model_path_label is not None:
            label = args.model_path_label
        elif args.model:
            label = args.model
        else:
            label = "fixture"
        return model_id, label
    if args.runtime == "command":
        model_id = args.model_id or "command"
        label = args.model_path_label if args.model_path_label is not None else (args.model or "")
        return model_id, label
    if not args.model:
        raise UsageError("bitnet runtime requires --model")
    model_id = args.model_id or Path(args.model).name
    label = args.model_path_label if args.model_path_label is not None else args.model
    return model_id, label


def build_runtime(args: argparse.Namespace, settings: RunSettings):
    if args.runtime == "fixture":
        return FixtureRuntime()
    if args.runtime == "command":
        if not args.command:
            raise UsageError("command runtime requires --command")
        return CommandRuntime(args.command, list(args.command_arg or []), args.cwd)
    if not args.executable:
        raise UsageError(
            "bitnet runtime requires --executable. Support is not claimed until doctor "
            "verifies that path."
        )
    if not args.model:
        raise UsageError("bitnet runtime requires --model. Support is not claimed.")
    verification = verify_bitnet(
        executable=args.executable,
        model=args.model,
        model_label=args.model_path_label,
        cwd=args.cwd,
    )
    if not verification.supported:
        raise UsageError(verification.reason)
    return BitNetRuntime(verification, settings)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        source = list(sys.argv[1:] if argv is None else argv)
        args = parser.parse_args(bind_command_arg_values(source))
        if args.cmd == "doctor":
            code, report = report_doctor(
                runtime=args.runtime,
                executable=args.executable,
                model=args.model,
                cwd=args.cwd,
                command=args.command,
            )
            sys.stdout.write(report)
            return code
        if args.cmd == "setup":
            return run_setup(
                download=args.download,
                confirm_network=args.confirm_network,
                model_dir=args.model_dir,
                repo=args.hf_repo,
            )
        if args.cmd != "run":
            raise UsageError(f"unknown command {args.cmd}")
        settings = settings_from(args)
        model_id, label = _identities(args)
        # Stage 8F2: model-suggested syllabusCodes are validated against an
        # explicit manifest only. Without one, any record carrying codes
        # fails closed inside parse_model_output -- except the fixture
        # runtime, a documented development double whose records draw from
        # its own pinned built-in example code set (see runtimes/fixture.py).
        allowed_codes = None
        manifest_label = None
        syllabus_manifest = None
        if args.syllabus_manifest:
            syllabus_manifest = load_syllabus_manifest(args.syllabus_manifest)
            allowed_codes = syllabus_manifest.codes
            manifest_label = syllabus_manifest.path
        elif args.runtime == "fixture":
            allowed_codes = EXAMPLE_CODES
            manifest_label = "fixture built-in example code set"
        raw = sys.stdin.buffer.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UsageError("stdin is not valid UTF-8") from exc
        stdout = execute(
            text,
            runtime_factory=lambda: build_runtime(args, settings),
            settings=settings,
            runtime_name=args.runtime,
            model_id=model_id,
            model_path_label=label,
            metadata_path=args.metadata,
            allowed_codes=allowed_codes,
            manifest_label=manifest_label,
            syllabus_manifest=syllabus_manifest,
        )
        sys.stdout.write(stdout)
        return 0
    except ReviewError as exc:
        log(str(exc))
        return exc.exit_code
    except BrokenPipeError:
        return 0
