import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from local_llm_review.errors import ProtocolError
from local_llm_review.protocol import OUTPUT_KEYS, dump_model_record, parse_model_output

EXAMPLE_CODES = frozenset({"A.EXAMPLE"})


def parse(text: str, ident: str, allowed_codes=EXAMPLE_CODES):
    return parse_model_output(text, expected_id=ident, allowed_codes=allowed_codes)


def good(ident="T2A01", **overrides):
    record = {
        "id": ident,
        "syllabusRelevant": True,
        "indianTopic": "electrical principles",
        "recommendation": "keep",
        "jurisdictionRisk": "none",
        "figureRightsWarning": "none",
        "rationale": "Advisory only: universal topic; this is not publication approval.",
        "syllabusCodes": ["A.EXAMPLE"],
    }
    record.update(overrides)
    return record


class OutputValidationTest(unittest.TestCase):
    def test_canonical_key_order(self):
        encoded = dump_model_record(good(), EXAMPLE_CODES)
        self.assertEqual(list(json.loads(encoded)), list(OUTPUT_KEYS))

    def test_extra_key_is_rejected(self):
        record = good()
        record["approved"] = True
        with self.assertRaisesRegex(ProtocolError, "invalid schema"):
            parse(json.dumps(record), "T2A01")

    def test_missing_key_is_rejected(self):
        record = good()
        del record["rationale"]
        with self.assertRaisesRegex(ProtocolError, "invalid schema"):
            parse(json.dumps(record), "T2A01")
        no_codes = good()
        del no_codes["syllabusCodes"]
        with self.assertRaisesRegex(ProtocolError, "invalid schema"):
            parse(json.dumps(no_codes), "T2A01")

    def test_eight_key_exactness(self):
        self.assertEqual(len(OUTPUT_KEYS), 8)
        self.assertEqual(len(set(OUTPUT_KEYS)), 8)
        self.assertIn("syllabusCodes", OUTPUT_KEYS)
        parsed = parse(json.dumps(good()), "T2A01")
        self.assertEqual(set(parsed), set(OUTPUT_KEYS))
        self.assertEqual(parsed["syllabusCodes"], ["A.EXAMPLE"])

    def test_recommendation_enum(self):
        for recommendation in ("keep", "adapt", "reject", "defer"):
            parsed = parse(json.dumps(good(recommendation=recommendation)), "T2A01")
            self.assertEqual(parsed["recommendation"], recommendation)
        with self.assertRaisesRegex(ProtocolError, "recommendation"):
            parse(json.dumps(good(recommendation="maybe")), "T2A01")

    def test_syllabus_relevant_must_be_boolean(self):
        with self.assertRaisesRegex(ProtocolError, "syllabusRelevant"):
            parse(json.dumps(good(syllabusRelevant="yes")), "T2A01")
        numeric = json.dumps(good()).replace("true", "1", 1)
        with self.assertRaisesRegex(ProtocolError, "syllabusRelevant"):
            parse(numeric, "T2A01")
        self.assertIs(parse(json.dumps(good(syllabusRelevant=False, syllabusCodes=[])), "T2A01")["syllabusRelevant"], False)

    def test_jurisdiction_and_figure_enums(self):
        for risk in ("none", "low", "medium"):
            parsed = parse(json.dumps(good(jurisdictionRisk=risk)), "T2A01")
            self.assertEqual(parsed["jurisdictionRisk"], risk)
        # "high" is a valid jurisdictionRisk value, but Stage 8E3 Part C
        # forbids pairing it with recommendation="keep" (see
        # test_high_jurisdiction_risk_cannot_be_kept below), so exercise the
        # enum value itself with a recommendation that is always compatible.
        parsed = parse(json.dumps(good(jurisdictionRisk="high", recommendation="defer")), "T2A01")
        self.assertEqual(parsed["jurisdictionRisk"], "high")
        for warning in ("none", "warning"):
            parsed = parse(json.dumps(good(figureRightsWarning=warning)), "T2A01")
            self.assertEqual(parsed["figureRightsWarning"], warning)
        with self.assertRaisesRegex(ProtocolError, "jurisdictionRisk"):
            parse(json.dumps(good(jurisdictionRisk="extreme")), "T2A01")
        with self.assertRaisesRegex(ProtocolError, "figureRightsWarning"):
            parse(json.dumps(good(figureRightsWarning="cleared")), "T2A01")

    def test_high_jurisdiction_risk_cannot_be_kept(self):
        # Stage 8E3 Part C: a high-risk candidate cannot receive "keep",
        # regardless of which path produced the record (deterministic guard
        # or a model). Every other recommendation stays legal with "high".
        with self.assertRaisesRegex(ProtocolError, "cannot be keep"):
            parse(json.dumps(good(jurisdictionRisk="high", recommendation="keep")), "T2A01")
        for recommendation in ("adapt", "reject", "defer"):
            parsed = parse(json.dumps(good(jurisdictionRisk="high", recommendation=recommendation)), "T2A01")
            self.assertEqual(parsed["recommendation"], recommendation)
        # "keep" is still legal at every OTHER risk level.
        for risk in ("none", "low", "medium"):
            parsed = parse(json.dumps(good(jurisdictionRisk=risk, recommendation="keep")), "T2A01")
            self.assertEqual(parsed["recommendation"], "keep")

    def test_blank_rationale_and_topic_are_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "rationale"):
            parse(json.dumps(good(rationale="  ")), "T2A01")
        with self.assertRaisesRegex(ProtocolError, "indianTopic"):
            parse(json.dumps(good(indianTopic="")), "T2A01")

    def test_syllabus_codes_must_be_an_array_of_strings(self):
        with self.assertRaisesRegex(ProtocolError, "must be an array"):
            parse(json.dumps(good(syllabusCodes="A.EXAMPLE")), "T2A01")
        with self.assertRaisesRegex(ProtocolError, "non-empty strings"):
            parse(json.dumps(good(syllabusCodes=[""])), "T2A01")
        with self.assertRaisesRegex(ProtocolError, "non-empty strings"):
            parse(json.dumps(good(syllabusCodes=[42])), "T2A01")

    def test_syllabus_codes_reject_duplicates(self):
        with self.assertRaisesRegex(ProtocolError, "duplicate syllabus code"):
            parse(json.dumps(good(syllabusCodes=["A.EXAMPLE", "A.EXAMPLE"])), "T2A01")

    def test_unknown_syllabus_code_is_rejected_naming_code_and_manifest(self):
        with self.assertRaises(ProtocolError) as caught:
            parse(json.dumps(good(syllabusCodes=["A.BOGUS"])), "T2A01", allowed_codes=EXAMPLE_CODES)
        message = str(caught.exception)
        self.assertIn("unknown syllabus code", message)
        self.assertIn("A.BOGUS", message)

    def test_code_without_manifest_fails_closed(self):
        # Stage 8F2: codes can only be validated against an explicit
        # manifest. A record carrying codes when the run loaded none is
        # rejected, never silently accepted.
        with self.assertRaisesRegex(ProtocolError, "no syllabus manifest"):
            parse_model_output(json.dumps(good()), expected_id="T2A01")

    def test_relevant_requires_at_least_one_code(self):
        with self.assertRaisesRegex(ProtocolError, "syllabusRelevant is true but syllabusCodes is empty"):
            parse(json.dumps(good(syllabusCodes=[])), "T2A01")

    def test_relevant_false_with_codes_is_a_contradiction(self):
        with self.assertRaisesRegex(ProtocolError, "contradictory"):
            parse(json.dumps(good(syllabusRelevant=False)), "T2A01")

    def test_guard_style_record_with_empty_codes_is_valid(self):
        # Guard-forced records carry syllabusCodes: [] with
        # syllabusRelevant: false (see jurisdiction_guard.py and the golden
        # guard fixture).
        record = good(syllabusRelevant=False, recommendation="reject", jurisdictionRisk="high", syllabusCodes=[])
        parsed = parse_model_output(json.dumps(record), expected_id="T2A01")
        self.assertEqual(parsed["syllabusCodes"], [])

    def test_id_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "id mismatch"):
            parse(json.dumps(good("OTHER")), "T2A01")

    def test_duplicate_keys_and_non_objects_are_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "duplicate key"):
            parse('{"id":"T2A01","id":"T2A01"}', "T2A01")
        with self.assertRaisesRegex(ProtocolError, "not an object"):
            parse("[]", "T2A01")

    def test_empty_output_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "empty"):
            parse("  \n", "T2A01")

    def test_trailing_prose_and_a_second_object_are_rejected(self):
        payload = json.dumps(good())
        with self.assertRaisesRegex(ProtocolError, "malformed JSON"):
            parse(payload + "\nthanks", "T2A01")
        with self.assertRaisesRegex(ProtocolError, "malformed JSON"):
            parse(payload + "\n" + payload, "T2A01")

    def test_markdown_fence_is_rejected(self):
        payload = "```json\n" + json.dumps(good()) + "\n```"
        with self.assertRaisesRegex(ProtocolError, "malformed JSON"):
            parse(payload, "T2A01")

    def test_surrounding_whitespace_is_accepted(self):
        payload = "\n" + json.dumps(good()) + "\n"
        parsed = parse(payload, "T2A01")
        self.assertEqual(parsed["id"], "T2A01")


if __name__ == "__main__":
    unittest.main()
