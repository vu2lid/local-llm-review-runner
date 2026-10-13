"""Generic local command. Argv is explicit. The prompt is stdin, not a shell string."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from local_llm_review.errors import ProtocolError, UsageError
from local_llm_review.metadata import RuntimeInfo
from local_llm_review.process import run_process
from local_llm_review.runtimes.bitnet import argv_prefix_for


class CommandRuntime:
    name = "command"

    def __init__(self, command: str, command_args: list[str], cwd: str | None) -> None:
        path = Path(command).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
        try:
            prefix = argv_prefix_for(path, role="command")
        except Exception as exc:
            raise UsageError(str(exc)) from exc
        self.argv = [*prefix, *command_args]
        self.cwd = cwd
        self.executable = str(path)

    def info(self) -> RuntimeInfo:
        return RuntimeInfo(
            support_claimed=False,
            executable=self.executable,
            cwd=self.cwd or "",
        )

    def complete(self, *, candidate: dict[str, Any], prompt: str, settings: Any) -> str:
        del candidate
        stdout = run_process(
            self.argv,
            timeout_s=settings.timeout_s,
            stdin_bytes=prompt.encode("utf-8"),
            max_output_bytes=settings.max_output_bytes,
            cwd=self.cwd,
        )
        try:
            return stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("model output is not valid UTF-8") from exc
