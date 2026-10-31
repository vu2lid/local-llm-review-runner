"""Always-on golden-fixture test for the shared guard-record convention.

The synthetic guard record that jurisdiction_guard.build_guard_record emits
is part of a cross-repository convention: us-hamexam's
scripts/review-pipeline.js guardRecord() must produce the identical shape.
The convention is pinned by fixtures/guard-record-golden.json (a byte-identical
copy lives at us-hamexam tools/india-review/guard-record-golden.json), so CI
detects drift independently of whether the sibling checkout is present. This
test NEVER skips on a missing sibling; only the optional byte-identity check
against the sibling's copy does.
"""

import hashlib
import json
import unittest
from pathlib import Path

import support

from local_llm_review.jurisdiction_guard import build_guard_record, evaluate_guard
from local_llm_review.protocol import parse_model_output

GOLDEN = support.ROOT / "fixtures" / "guard-record-golden.json"
SIBLING_GOLDEN = support.ROOT.parent / "us-hamexam" / "tools" / "india-review" / "guard-record-golden.json"


class GuardRecordGoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.candidate = cls.golden["candidate"]
        cls.expected = cls.golden["expectedRecord"]

    def test_golden_fixture_structure(self):
        self.assertEqual(self.golden["conventionVersion"], 2)
        self.assertTrue(self.golden["notes"])
        for key in (
            "id",
            "syllabusRelevant",
            "indianTopic",
            "recommendation",
            "jurisdictionRisk",
            "figureRightsWarning",
            "rationale",
            "syllabusCodes",
        ):
            self.assertIn(key, self.expected)
        self.assertEqual(self.expected["syllabusCodes"], [])

    def test_evaluate_guard_flags_the_golden_candidate(self):
        guard = evaluate_guard(self.candidate)
        self.assertTrue(guard.flagged)
        self.assertEqual(guard.rule, "fcc-part-97")
        self.assertEqual(guard.verdict, "reject")

    def test_build_guard_record_matches_expected_record_exactly(self):
        guard = evaluate_guard(self.candidate)
        record = build_guard_record(self.candidate, guard)
        self.assertEqual(record, self.expected)

    def test_expected_record_passes_the_strict_output_validator(self):
        # The pinned record must be a valid model output record on its own,
        # i.e. parse_model_output accepts it exactly as a runtime would have
        # to emit it.
        parsed = parse_model_output(
            json.dumps(self.expected, ensure_ascii=False),
            expected_id=self.expected["id"],
        )
        self.assertEqual(parsed, self.expected)

    def test_sibling_golden_bytes_match_when_present(self):
        if not SIBLING_GOLDEN.is_file():
            self.skipTest("us-hamexam sibling checkout's golden fixture is not available")
        ours = hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
        theirs = hashlib.sha256(SIBLING_GOLDEN.read_bytes()).hexdigest()
        self.assertEqual(ours, theirs)


if __name__ == "__main__":
    unittest.main()
