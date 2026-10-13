import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from local_llm_review.errors import ProtocolError
from local_llm_review.protocol import OUTPUT_KEYS, dump_model_record, parse_model_output


def good(ident="T2A01", **overrides):
    record = {
        "id": ident,
        "syllabusRelevant": True,
        "indianTopic": "electrical principles",
        "recommendation": "keep",
        "jurisdictionRisk": "none",
        "figureRightsWarning": "none",
        "rationale": "Advisory only: universal topic; this is not publication approval.",
    }
    record.update(overrides)
    return record


class OutputValidationTest(unittest.TestCase):
    def test_canonical_key_order(self):
        encoded = dump_model_record(good())
        self.assertEqual(list(json.loads(encoded)), list(OUTPUT_KEYS))

    def test_extra_key_is_rejected(self):
        record = good()
        record["approved"] = True
        with self.assertRaisesRegex(ProtocolError, "invalid schema"):
            parse_model_output(json.dumps(record), expected_id="T2A01")

    def test_missing_key_is_rejected(self):
        record = good()
        del record["rationale"]
        with self.assertRaisesRegex(ProtocolError, "invalid schema"):
            parse_model_output(json.dumps(record), expected_id="T2A01")

    def test_recommendation_enum(self):
        for recommendation in ("keep", "adapt", "reject", "defer"):
            parsed = parse_model_output(json.dumps(good(recommendation=recommendation)), expected_id="T2A01")
            self.assertEqual(parsed["recommendation"], recommendation)
        with self.assertRaisesRegex(ProtocolError, "recommendation"):
            parse_model_output(json.dumps(good(recommendation="maybe")), expected_id="T2A01")

    def test_syllabus_relevant_must_be_boolean(self):
        with self.assertRaisesRegex(ProtocolError, "syllabusRelevant"):
            parse_model_output(json.dumps(good(syllabusRelevant="yes")), expected_id="T2A01")
        numeric = json.dumps(good()).replace("true", "1", 1)
        with self.assertRaisesRegex(ProtocolError, "syllabusRelevant"):
            parse_model_output(numeric, expected_id="T2A01")
        self.assertIs(parse_model_output(json.dumps(good(syllabusRelevant=False)), expected_id="T2A01")["syllabusRelevant"], False)

    def test_jurisdiction_and_figure_enums(self):
        for risk in ("none", "low", "medium", "high"):
            parsed = parse_model_output(json.dumps(good(jurisdictionRisk=risk)), expected_id="T2A01")
            self.assertEqual(parsed["jurisdictionRisk"], risk)
        for warning in ("none", "warning"):
            parsed = parse_model_output(json.dumps(good(figureRightsWarning=warning)), expected_id="T2A01")
            self.assertEqual(parsed["figureRightsWarning"], warning)
        with self.assertRaisesRegex(ProtocolError, "jurisdictionRisk"):
            parse_model_output(json.dumps(good(jurisdictionRisk="extreme")), expected_id="T2A01")
        with self.assertRaisesRegex(ProtocolError, "figureRightsWarning"):
            parse_model_output(json.dumps(good(figureRightsWarning="cleared")), expected_id="T2A01")

    def test_blank_rationale_and_topic_are_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "rationale"):
            parse_model_output(json.dumps(good(rationale="  ")), expected_id="T2A01")
        with self.assertRaisesRegex(ProtocolError, "indianTopic"):
            parse_model_output(json.dumps(good(indianTopic="")), expected_id="T2A01")

    def test_id_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "id mismatch"):
            parse_model_output(json.dumps(good("OTHER")), expected_id="T2A01")

    def test_duplicate_keys_and_non_objects_are_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "duplicate key"):
            parse_model_output('{"id":"T2A01","id":"T2A01"}', expected_id="T2A01")
        with self.assertRaisesRegex(ProtocolError, "not an object"):
            parse_model_output("[]", expected_id="T2A01")

    def test_empty_output_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "empty"):
            parse_model_output("  \n", expected_id="T2A01")

    def test_trailing_prose_and_a_second_object_are_rejected(self):
        payload = json.dumps(good())
        with self.assertRaisesRegex(ProtocolError, "malformed JSON"):
            parse_model_output(payload + "\nthanks", expected_id="T2A01")
        with self.assertRaisesRegex(ProtocolError, "malformed JSON"):
            parse_model_output(payload + "\n" + payload, expected_id="T2A01")

    def test_markdown_fence_is_rejected(self):
        payload = "```json\n" + json.dumps(good()) + "\n```"
        with self.assertRaisesRegex(ProtocolError, "malformed JSON"):
            parse_model_output(payload, expected_id="T2A01")

    def test_surrounding_whitespace_is_accepted(self):
        payload = "\n" + json.dumps(good()) + "\n"
        parsed = parse_model_output(payload, expected_id="T2A01")
        self.assertEqual(parsed["id"], "T2A01")


if __name__ == "__main__":
    unittest.main()
