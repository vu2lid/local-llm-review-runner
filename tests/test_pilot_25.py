import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from local_llm_review.metadata import METADATA_KEYS
from local_llm_review.prompt import PROMPT_VERSION, prompt_hash
from local_llm_review.protocol import parse_model_output

EXPECTED = {
    "SYN01": "keep",
    "SYN02": "keep",
    "SYN03": "keep",
    "SYN04": "keep",
    "SYN05": "keep",
    "SYN06": "keep",
    "SYN07": "keep",
    "SYN08": "keep",
    "SYN09": "keep",
    "SYN10": "keep",
    "SYN11": "keep",
    "SYN12": "keep",
    "SYN13": "keep",
    "SYN14": "keep",
    "SYN15": "keep",
    "SYN16": "keep",
    "SYN17": "keep",
    "SYN18": "keep",
    "SYN19": "keep",
    "SYN20": "adapt",
    "SYN21": "adapt",
    "SYN22": "adapt",
    "SYN23": "reject",
    "SYN24": "reject",
    "SYN25": "reject",
}


class PilotFixtureTest(unittest.TestCase):
    def test_production_style_25_record_pilot(self):
        stdin = support.PILOT.read_text(encoding="utf-8")
        candidates = [json.loads(line) for line in stdin.splitlines() if line.strip()]
        self.assertEqual(len(candidates), 25)
        self.assertTrue(all(item["figure"] is False for item in candidates))
        result = support.run_cli(["run", "--runtime", "fixture"], stdin)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        lines = result.stdout.decode().splitlines()
        self.assertEqual(len(lines), 25)
        ids = []
        for line, candidate in zip(lines, candidates):
            record = parse_model_output(line, expected_id=candidate["id"])
            ids.append(record["id"])
            self.assertEqual(record["recommendation"], EXPECTED[candidate["id"]])
            self.assertIn("not publication approval", record["rationale"])
            self.assertNotIn("official ASOC", record["rationale"])
            self.assertNotIn(candidate["question"], record["rationale"])
            if record["recommendation"] == "keep":
                self.assertIs(record["syllabusRelevant"], True)
                self.assertEqual(record["jurisdictionRisk"], "none")
                self.assertEqual(record["figureRightsWarning"], "none")
            elif record["recommendation"] == "adapt":
                self.assertIs(record["syllabusRelevant"], True)
                self.assertEqual(record["jurisdictionRisk"], "medium")
            else:
                self.assertEqual(record["recommendation"], "reject")
                self.assertIs(record["syllabusRelevant"], False)
                self.assertEqual(record["jurisdictionRisk"], "high")
        self.assertEqual(ids, [item["id"] for item in candidates])
        again = support.run_cli(["run", "--runtime", "fixture"], stdin)
        self.assertEqual(again.stdout, result.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pilot-metadata.json"
            recorded = support.run_cli(
                ["run", "--runtime", "fixture", "--metadata", str(path)],
                stdin,
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr.decode())
            self.assertEqual(recorded.stdout, result.stdout)
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(tuple(document), METADATA_KEYS)
            self.assertEqual(document["inputCount"], 25)
            self.assertEqual(document["outputCount"], 25)
            self.assertEqual(document["failureCount"], 0)
            self.assertEqual(document["promptVersion"], PROMPT_VERSION)
            self.assertEqual(document["promptHash"], prompt_hash())
            self.assertEqual(document["runtime"], "fixture")


if __name__ == "__main__":
    unittest.main()
