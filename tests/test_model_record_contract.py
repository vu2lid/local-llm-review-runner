"""Always-on golden-fixture test for the Stage 8F2 model record contract v3.

fixtures/model-record-contract-v3.json pins the exact 8-key contract shared
with us-hamexam's scripts/review-pipeline.js validateModelRecord (review
manifest schemaVersion 3): the sorted key set, the validation rules as data,
an inline example manifest, one fully-worked valid example record, and a list
of deliberately-broken variants with their expected errors. Every assertion
here runs without the us-hamexam sibling checkout; only the optional
cross-implementation check at the bottom invokes node against the sibling,
and only that one test skips when the sibling or node is absent.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from local_llm_review.errors import ProtocolError
from local_llm_review.protocol import OUTPUT_KEYS, parse_model_output

GOLDEN = support.ROOT / "fixtures" / "model-record-contract-v3.json"


class ModelRecordContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.example_codes = frozenset(cls.golden["exampleManifest"])

    def test_output_keys_match_the_golden_key_set(self):
        self.assertEqual(sorted(OUTPUT_KEYS), self.golden["outputKeys"])
        self.assertEqual(len(OUTPUT_KEYS), 8)

    def test_rules_flags_are_all_true(self):
        for name, flag in self.golden["rules"].items():
            self.assertIs(flag, True, name)

    def test_example_record_is_accepted_under_the_example_code_set(self):
        parsed = parse_model_output(
            json.dumps(self.golden["exampleRecord"], ensure_ascii=False),
            expected_id=self.golden["exampleRecord"]["id"],
            allowed_codes=self.example_codes,
        )
        self.assertEqual(parsed, self.golden["exampleRecord"])

    def test_broken_variants_are_rejected(self):
        for variant in self.golden["brokenVariants"]:
            record = dict(self.golden["exampleRecord"])
            record.update(variant["change"])
            with self.assertRaisesRegex(ProtocolError, variant["expectedError"], msg=variant["name"]):
                parse_model_output(
                    json.dumps(record, ensure_ascii=False),
                    expected_id=record["id"],
                    allowed_codes=self.example_codes,
                )

    def test_codes_fail_closed_without_a_manifest(self):
        record = dict(self.golden["exampleRecord"])
        with self.assertRaisesRegex(ProtocolError, "no syllabus manifest"):
            parse_model_output(
                json.dumps(record, ensure_ascii=False),
                expected_id=record["id"],
            )

    def test_unknown_code_error_names_the_code_and_manifest_path(self):
        record = dict(self.golden["exampleRecord"])
        with self.assertRaises(ProtocolError) as caught:
            parse_model_output(
                json.dumps(record, ensure_ascii=False),
                expected_id=record["id"],
                allowed_codes=frozenset(),
                manifest_label="/example/syllabus.json",
            )
        message = str(caught.exception)
        self.assertIn("A.EXAMPLE", message)
        self.assertIn("/example/syllabus.json", message)


US_HAMEXAM_REVIEW_PIPELINE = (
    Path(os.environ["US_HAMEXAM_ROOT"]) / "scripts" / "review-pipeline.js"
    if os.environ.get("US_HAMEXAM_ROOT")
    else support.ROOT.parent / "us-hamexam" / "scripts" / "review-pipeline.js"
)


class CrossImplementationContractTest(unittest.TestCase):
    """Pins the golden's example record against us-hamexam's real
    validateModelRecord via a node child invocation, so the two
    implementations cannot silently drift. Skips (this class only) when the
    sibling checkout or node is absent; everything above runs regardless."""

    def test_example_record_passes_us_hamexam_validate_model_record(self):
        if not US_HAMEXAM_REVIEW_PIPELINE.is_file() or not shutil.which("node"):
            self.skipTest(
                "us-hamexam scripts/review-pipeline.js or node is not available. "
                "Set US_HAMEXAM_ROOT to compare against the sibling checkout."
            )
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "syllabus.json"
            # Must satisfy us-hamexam's own assertSyllabusManifest, which is
            # stricter than this runner's minimal loader.
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "editionKey": "contract-example",
                        "source": {
                            "document": "synthetic contract example",
                            "date": "2026-10-28",
                            "annexure": "synthetic",
                            "title": "Contract example",
                        },
                        "currency": "Synthetic example manifest for the contract golden only.",
                        "notOfficialExamConfig": True,
                        "topics": [
                            {
                                "code": code,
                                "title": title,
                                "section": "A",
                                "grades": "both",
                                "sourceRef": "synthetic §example",
                                "evidenceStatus": "confirmed-2010-om",
                                "mvpIncluded": True,
                            }
                            for code, title in golden["exampleManifest"].items()
                        ],
                    }
                ),
                encoding="utf-8",
            )
            script = (
                "const p=require(process.argv[1]);"
                "const record=JSON.parse(process.argv[2]);"
                "const manifest=p.loadSyllabusManifest(process.argv[3]);"
                "console.log(JSON.stringify(p.validateModelRecord(record,record.id,manifest)));"
            )
            result = subprocess.run(
                [
                    shutil.which("node"),
                    "-e",
                    script,
                    str(US_HAMEXAM_REVIEW_PIPELINE),
                    json.dumps(golden["exampleRecord"]),
                    str(manifest_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            accepted = json.loads(result.stdout)
            self.assertEqual(accepted["syllabusCodes"], golden["exampleRecord"]["syllabusCodes"])
            self.assertEqual(sorted(accepted), golden["outputKeys"])


if __name__ == "__main__":
    unittest.main()
