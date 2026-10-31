import hashlib
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
            self.assertIsNone(document["syllabusManifest"])
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

    def test_syllabus_manifest_is_recorded_in_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            manifest_path = directory / "syllabus.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "topics": [
                            {"code": "A.SEMICONDUCTORS", "title": "Semiconductors"},
                            {"code": "A.PROPAGATION", "title": "Propagation"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            metadata_path = directory / "meta.json"
            stdin = support.jsonl([support.candidate("SYN01")])
            result = support.run_cli(
                [
                    "run",
                    "--runtime",
                    "fixture",
                    "--metadata",
                    str(metadata_path),
                    "--syllabus-manifest",
                    str(manifest_path),
                ],
                stdin,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            document = json.loads(metadata_path.read_text(encoding="utf-8"))
            record = document["syllabusManifest"]
            self.assertEqual(record["path"], str(manifest_path))
            self.assertEqual(record["schemaVersion"], 1)
            self.assertEqual(record["codeCount"], 2)
            self.assertEqual(
                record["sha256"], hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            )
            # The same manifest's code set validates the fixture's codes.
            row = json.loads(result.stdout.decode().strip())
            self.assertEqual(row["syllabusCodes"], ["A.SEMICONDUCTORS"])

    def test_missing_syllabus_manifest_is_a_usage_error(self):
        result = support.run_cli(
            ["run", "--runtime", "fixture", "--syllabus-manifest", "/no/such/manifest.json"],
            support.jsonl([support.candidate("SYN01")]),
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"syllabus manifest", result.stderr)

    def test_invalid_syllabus_manifest_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "syllabus.json"
            manifest_path.write_text('{"topics": [{"code": "", "title": "x"}]}', encoding="utf-8")
            result = support.run_cli(
                ["run", "--runtime", "fixture", "--syllabus-manifest", str(manifest_path)],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"non-empty code", result.stderr)

    def test_duplicate_manifest_code_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "syllabus.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "topics": [
                            {"code": "A.X", "title": "x"},
                            {"code": "A.X", "title": "x again"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = support.run_cli(
                ["run", "--runtime", "fixture", "--syllabus-manifest", str(manifest_path)],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"duplicate code", result.stderr)

    def test_code_from_command_runtime_without_manifest_fails_closed(self):
        # Stage 8F2 fail-closed rule: a record carrying syllabusCodes when
        # the run loaded no manifest rejects the whole run (empty stdout,
        # non-zero exit), even when every other field is valid.
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            command = directory / "codes.py"
            command.write_text(
                "#!/usr/bin/env python3\n"
                "import json, re, sys\n"
                "blob = sys.stdin.read()\n"
                "ident = re.findall(r'\"id\":\\s*\"([^\"]+)\"', blob)[-1]\n"
                "json.dump({\n"
                "    'id': ident, 'syllabusRelevant': True, 'indianTopic': 'electronics',\n"
                "    'recommendation': 'keep', 'jurisdictionRisk': 'none',\n"
                "    'figureRightsWarning': 'none',\n"
                "    'rationale': 'advisory only',\n"
                "    'syllabusCodes': ['A.SEMICONDUCTORS'],\n"
                "}, sys.stdout)\n"
            )
            command.chmod(0o755)
            result = support.run_cli(
                ["run", "--runtime", "command", "--command", str(command), "--timeout", "10"],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"no syllabus manifest", result.stderr)

    def test_command_runtime_codes_validate_against_the_given_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            manifest_path = directory / "syllabus.json"
            manifest_path.write_text(
                json.dumps({"topics": [{"code": "A.SEMICONDUCTORS", "title": "Semiconductors"}]}),
                encoding="utf-8",
            )
            command = directory / "codes.py"
            command.write_text(
                "#!/usr/bin/env python3\n"
                "import json, re, sys\n"
                "blob = sys.stdin.read()\n"
                "ident = re.findall(r'\"id\":\\s*\"([^\"]+)\"', blob)[-1]\n"
                "json.dump({\n"
                "    'id': ident, 'syllabusRelevant': True, 'indianTopic': 'electronics',\n"
                "    'recommendation': 'keep', 'jurisdictionRisk': 'none',\n"
                "    'figureRightsWarning': 'none',\n"
                "    'rationale': 'advisory only',\n"
                "    'syllabusCodes': ['A.SEMICONDUCTORS'],\n"
                "}, sys.stdout)\n"
            )
            command.chmod(0o755)
            metadata_path = directory / "meta.json"
            result = support.run_cli(
                [
                    "run",
                    "--runtime",
                    "command",
                    "--command",
                    str(command),
                    "--timeout",
                    "10",
                    "--metadata",
                    str(metadata_path),
                    "--syllabus-manifest",
                    str(manifest_path),
                ],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            row = json.loads(result.stdout.decode().strip())
            self.assertEqual(row["syllabusCodes"], ["A.SEMICONDUCTORS"])
            document = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(document["syllabusManifest"]["codeCount"], 1)

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
