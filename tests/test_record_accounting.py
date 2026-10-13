import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from local_llm_review.errors import ProtocolError
from local_llm_review.protocol import parse_jsonl


class RecordAccountingTest(unittest.TestCase):
    def test_duplicate_ids_are_rejected_with_both_lines(self):
        text = support.jsonl([support.candidate("SYN01"), support.candidate("SYN02"), support.candidate("SYN01")])
        with self.assertRaisesRegex(ProtocolError, "duplicate id 'SYN01'"):
            parse_jsonl(text)

    def test_cli_duplicate_does_not_emit_stdout(self):
        text = support.jsonl([support.candidate("SYN01"), support.candidate("SYN01")])
        result = support.run_cli(["run", "--runtime", "fixture"], text)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"duplicate id", result.stderr)

    def test_order_is_preserved(self):
        rows = [support.candidate("Z9"), support.candidate("A1"), support.candidate("M3")]
        result = support.run_cli(["run", "--runtime", "fixture"], support.jsonl(rows))
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        ids = [json.loads(line)["id"] for line in result.stdout.decode().splitlines()]
        self.assertEqual(ids, ["Z9", "A1", "M3"])

    def test_second_record_failure_discards_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            state = directory / "count"
            script = directory / "once.py"
            script.write_text(
                "import json, sys\n"
                "from pathlib import Path\n"
                f"state = Path({str(state)!r})\n"
                "text = sys.stdin.read().splitlines()\n"
                "cand = json.loads([ln for ln in text if ln.strip()][-1])\n"
                "n = int(state.read_text()) if state.exists() else 0\n"
                "n += 1\n"
                "state.write_text(str(n))\n"
                "if n > 1:\n"
                "    sys.stderr.write('second record failed\\n')\n"
                "    raise SystemExit(3)\n"
                "json.dump({'id': cand['id'], 'syllabusRelevant': True,\n"
                " 'indianTopic': 'electrical principles', 'recommendation': 'keep',\n"
                " 'jurisdictionRisk': 'none', 'figureRightsWarning': 'none',\n"
                " 'rationale': 'Advisory only: stub; this is not publication approval.'}, sys.stdout)\n"
                "sys.stdout.write('\\n')\n"
            )
            meta = directory / "meta.json"
            text = support.jsonl([support.candidate("SYN01"), support.candidate("SYN02")])
            result = support.run_cli(
                ["run", "--runtime", "command", "--command", str(script), "--metadata", str(meta), "--timeout", "10"],
                text,
            )
            self.assertEqual(result.returncode, 1, result.stderr.decode())
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"exited 3", result.stderr)
            document = json.loads(meta.read_text())
            self.assertEqual(document["inputCount"], 2)
            self.assertEqual(document["outputCount"], 0)
            self.assertEqual(document["failureCount"], 1)

    def test_extra_json_object_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "extra.py"
            script.write_text(
                "import json, sys\n"
                "text = sys.stdin.read().splitlines()\n"
                "cand = json.loads([ln for ln in text if ln.strip()][-1])\n"
                "row = {'id': cand['id'], 'syllabusRelevant': True,\n"
                " 'indianTopic': 'electrical principles', 'recommendation': 'keep',\n"
                " 'jurisdictionRisk': 'none', 'figureRightsWarning': 'none',\n"
                " 'rationale': 'Advisory only: stub; this is not publication approval.'}\n"
                "sys.stdout.write(json.dumps(row) + '\\n' + json.dumps(row) + '\\n')\n"
            )
            result = support.run_cli(
                ["run", "--runtime", "command", "--command", str(script), "--timeout", "10"],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"malformed JSON", result.stderr)

    def test_command_prompt_is_stdin_not_an_argv_element(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "argv.py"
            script.write_text(
                "import json, sys\n"
                "prompt = sys.stdin.read()\n"
                "if '--literal' not in sys.argv:\n"
                "    sys.stderr.write('command arg was not passed\\n')\n"
                "    raise SystemExit(8)\n"
                "if any('SI unit' in arg for arg in sys.argv):\n"
                "    sys.stderr.write('prompt leaked into argv\\n')\n"
                "    raise SystemExit(7)\n"
                "cand = json.loads([ln for ln in prompt.splitlines() if ln.startswith('{')][-1])\n"
                "json.dump({'id': cand['id'], 'syllabusRelevant': True,\n"
                " 'indianTopic': 'electrical principles', 'recommendation': 'keep',\n"
                " 'jurisdictionRisk': 'none', 'figureRightsWarning': 'none',\n"
                " 'rationale': 'Advisory only: stub; this is not publication approval.'}, sys.stdout)\n"
            )
            result = support.run_cli(
                ["run", "--runtime", "command", "--command", str(script), "--command-arg", "--literal", "--timeout", "10"],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(json.loads(result.stdout.decode())["id"], "SYN01")

    def test_no_input_records(self):
        result = support.run_cli(["run", "--runtime", "fixture"], "\n\n")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"no input records", result.stderr)


if __name__ == "__main__":
    unittest.main()
