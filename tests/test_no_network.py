import io
import os
import socket
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support


class NoNetworkTest(unittest.TestCase):
    def test_fixture_sources_do_not_refer_to_network_clients(self):
        banned = ("urllib", "requests", "http.client", "socket.create_connection", "httpx")
        package = support.SRC / "local_llm_review"
        for path in package.rglob("*.py"):
            if path.name == "setup_cmd.py":
                continue
            text = path.read_text(encoding="utf-8")
            for token in banned:
                self.assertNotIn(token, text, str(path))
        setup = (package / "setup_cmd.py").read_text(encoding="utf-8")
        self.assertIn("huggingface-cli", setup)
        self.assertNotIn("urllib", setup)
        self.assertNotIn("socket.create_connection", setup)

    def test_fixture_cli_does_not_open_sockets_or_call_huggingface(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            bindir = directory / "bin"
            bindir.mkdir()
            stamp = directory / "stamp"
            fake = bindir / "huggingface-cli"
            fake.write_text(f"#!/bin/sh\necho called >> {stamp}\n")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            env = {"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
            result = support.run_cli(
                ["run", "--runtime", "fixture"],
                support.PILOT.read_text(encoding="utf-8"),
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertFalse(stamp.exists())

        original = {
            "getaddrinfo": socket.getaddrinfo,
            "create_connection": socket.create_connection,
            "connect": socket.socket.connect,
            "stdin": sys.stdin,
            "stdout": sys.stdout,
            "stderr": sys.stderr,
        }

        def blocked(*_args, **_kwargs):
            raise AssertionError("network access attempted during fixture run")

        socket.getaddrinfo = blocked
        socket.create_connection = blocked
        socket.socket.connect = blocked
        payload = support.jsonl([support.candidate("SYN01")])
        sys.stdin = io.TextIOWrapper(io.BytesIO(payload.encode()))
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            from local_llm_review.cli import main

            code = main(["run", "--runtime", "fixture"])
        finally:
            socket.getaddrinfo = original["getaddrinfo"]
            socket.create_connection = original["create_connection"]
            socket.socket.connect = original["connect"]
            sys.stdin = original["stdin"]
            sys.stdout = original["stdout"]
            sys.stderr = original["stderr"]
        self.assertEqual(code, 0)

    def test_setup_without_download_does_not_invoke_huggingface(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            bindir = directory / "bin"
            bindir.mkdir()
            stamp = directory / "stamp"
            fake = bindir / "huggingface-cli"
            fake.write_text(f"#!/bin/sh\necho called >> {stamp}\n")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            env = {"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
            result = support.run_cli(["setup"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b"network: not used", result.stdout)
            self.assertFalse(stamp.exists())
            denied = support.run_cli(
                ["setup", "--download", "--model-dir", str(directory / "models")],
                env=env,
            )
            self.assertEqual(denied.returncode, 2)
            self.assertIn(b"--confirm-network", denied.stderr)
            self.assertFalse(stamp.exists())
            inside = support.run_cli(
                [
                    "setup",
                    "--download",
                    "--confirm-network",
                    "--model-dir",
                    str(support.ROOT / "models"),
                ],
                env=env,
            )
            self.assertEqual(inside.returncode, 2, inside.stderr.decode())
            self.assertIn(b"outside this repository", inside.stderr)
            self.assertFalse(stamp.exists())
            self.assertFalse((support.ROOT / "models").exists())


if __name__ == "__main__":
    unittest.main()
