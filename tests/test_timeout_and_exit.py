import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support


class TimeoutAndExitTest(unittest.TestCase):
    def test_timeout_kills_the_runtime_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            pid_path = directory / "pid"
            script = directory / "sleep.py"
            script.write_text(
                "import os, sys, time\n"
                f"open({str(pid_path)!r}, 'w').write(str(os.getpid()))\n"
                "time.sleep(30)\n"
            )
            result = support.run_cli(
                ["run", "--runtime", "command", "--command", str(script), "--timeout", "1"],
                support.jsonl([support.candidate("SYN01")]),
                timeout=15,
            )
            self.assertEqual(result.returncode, 1, result.stderr.decode())
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"timed out", result.stderr)
            self.assertTrue(pid_path.exists(), result.stderr.decode())
            pid = int(pid_path.read_text())
            with self.assertRaises(OSError):
                os.kill(pid, 0)

    def test_nonzero_exit_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fail.py"
            script.write_text("import sys\nsys.stderr.write('boom from runtime\\n')\nraise SystemExit(3)\n")
            result = support.run_cli(
                ["run", "--runtime", "command", "--command", str(script), "--timeout", "10"],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"exited 3", result.stderr)
            self.assertIn(b"boom from runtime", result.stderr)

    def test_oversized_output_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "big.py"
            script.write_text("sys_out = 'x' * 100000\nimport sys\nsys.stdout.write(sys_out)\n")
            result = support.run_cli(
                ["run", "--runtime", "command", "--command", str(script), "--max-output-bytes", "128", "--timeout", "10"],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"exceeded", result.stderr)

    def test_zero_timeout_is_rejected_without_hanging(self):
        result = support.run_cli(
            ["run", "--runtime", "fixture", "--timeout", "0"],
            support.jsonl([support.candidate()]),
            timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")

    def test_wrong_id_and_empty_completion_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            wrong = directory / "wrong.py"
            wrong.write_text(
                "import json, sys\n"
                "json.dump({'id': 'WRONG', 'syllabusRelevant': True,\n"
                " 'indianTopic': 'x', 'recommendation': 'keep',\n"
                " 'jurisdictionRisk': 'none', 'figureRightsWarning': 'none',\n"
                " 'rationale': 'x'}, sys.stdout)\n"
            )
            result = support.run_cli(
                ["run", "--runtime", "command", "--command", str(wrong), "--timeout", "10"],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"id mismatch", result.stderr)
            empty = directory / "empty.py"
            empty.write_text("raise SystemExit(0)\n")
            result = support.run_cli(
                ["run", "--runtime", "command", "--command", str(empty), "--timeout", "10"],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"empty", result.stderr)


if __name__ == "__main__":
    unittest.main()
