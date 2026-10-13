import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from local_llm_review.metadata import METADATA_KEYS, SETTINGS_KEYS
from local_llm_review.prompt import PROMPT_VERSION, prompt_hash


class MetadataTest(unittest.TestCase):
    def test_success_metadata_matches_the_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "run.json"
            stdin = support.jsonl([support.candidate("SYN01"), support.candidate("SYN02")])
            result = support.run_cli(
                ["run", "--runtime", "fixture", "--metadata", str(path), "--model-id", "fixture-stub"],
                stdin,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(tuple(document), METADATA_KEYS)
            self.assertEqual(tuple(document["settings"]), SETTINGS_KEYS)
            self.assertEqual(document["runtime"], "fixture")
            self.assertEqual(document["modelId"], "fixture-stub")
            self.assertEqual(document["modelPathLabel"], "fixture")
            self.assertEqual(document["promptVersion"], PROMPT_VERSION)
            self.assertEqual(document["promptHash"], prompt_hash())
            self.assertEqual(document["inputCount"], 2)
            self.assertEqual(document["outputCount"], 2)
            self.assertEqual(document["failureCount"], 0)
            self.assertIsInstance(document["elapsedMs"], int)
            self.assertGreaterEqual(document["elapsedMs"], 0)
            self.assertFalse(document["settings"]["supportClaimed"])
            self.assertFalse(document["settings"]["seedApplied"])
            self.assertEqual(document["settings"]["temperature"], 0.0)
            self.assertEqual(document["settings"]["seed"], 42)
            self.assertNotIn(b"runnerVersion", result.stdout)

    def test_failure_metadata_records_zero_emitted_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fail.json"
            result = support.run_cli(
                ["run", "--runtime", "fixture", "--metadata", str(path)],
                "{not json\n",
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["inputCount"], 0)
            self.assertEqual(document["outputCount"], 0)
            self.assertEqual(document["failureCount"], 1)
            self.assertEqual(document["promptHash"], prompt_hash())

    def test_settings_match_across_repeated_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first_path = directory / "a.json"
            second_path = directory / "b.json"
            stdin = support.PILOT.read_text(encoding="utf-8")
            args = ["run", "--runtime", "fixture", "--threads", "3", "--max-tokens", "128"]
            first = support.run_cli([*args, "--metadata", str(first_path)], stdin)
            second = support.run_cli([*args, "--metadata", str(second_path)], stdin)
            self.assertEqual(first.returncode, 0, first.stderr.decode())
            self.assertEqual(first.stdout, second.stdout)
            left = json.loads(first_path.read_text())
            right = json.loads(second_path.read_text())
            left.pop("elapsedMs")
            right.pop("elapsedMs")
            self.assertEqual(left, right)
            self.assertEqual(left["settings"]["threads"], 3)
            self.assertEqual(left["settings"]["maxTokens"], 128)


if __name__ == "__main__":
    unittest.main()
