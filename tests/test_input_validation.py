import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from local_llm_review.errors import ProtocolError
from local_llm_review.protocol import parse_jsonl, validate_candidate


class InputValidationTest(unittest.TestCase):
    def test_accepts_a_complete_candidate(self):
        record = validate_candidate(support.candidate())
        self.assertEqual(record["id"], "T2A01")

    def test_missing_id_is_rejected(self):
        raw = support.candidate()
        del raw["id"]
        with self.assertRaisesRegex(ProtocolError, "missing id"):
            parse_jsonl(support.jsonl([raw]))

    def test_blank_id_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "missing id"):
            parse_jsonl(support.jsonl([support.candidate("  ")]))

    def test_missing_field_names_the_field(self):
        raw = support.candidate()
        del raw["question"]
        with self.assertRaisesRegex(ProtocolError, "missing question"):
            validate_candidate(raw)

    def test_choices_must_have_non_empty_letters(self):
        raw = support.candidate()
        raw["choices"] = {"A": "ohm", "B": "volt", "C": "", "D": "watt"}
        with self.assertRaisesRegex(ProtocolError, "choices are invalid"):
            validate_candidate(raw)

    def test_correct_text_must_match_the_keyed_choice(self):
        raw = support.candidate(correctText="volt")
        with self.assertRaisesRegex(ProtocolError, "correctText does not match"):
            validate_candidate(raw)

    def test_figure_must_be_boolean(self):
        with self.assertRaisesRegex(ProtocolError, "figure must be a boolean"):
            validate_candidate(support.candidate(figure="false"))

    def test_figure_true_is_rejected_before_a_runtime(self):
        with self.assertRaisesRegex(ProtocolError, "figure true"):
            parse_jsonl(support.jsonl([support.candidate(figure=True)]))
        result = support.run_cli(
            ["run", "--runtime", "fixture"],
            support.jsonl([support.candidate("FIG1", figure=True)]),
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"figure true", result.stderr)
        self.assertIn(b"figure false", result.stderr)

    def test_source_requires_display_name(self):
        raw = support.candidate()
        del raw["source"]["displayName"]
        with self.assertRaisesRegex(ProtocolError, "source metadata is invalid"):
            validate_candidate(raw)

    def test_malformed_json_reports_the_line(self):
        text = support.jsonl([support.candidate("SYN01")]) + "{bad\n"
        with self.assertRaisesRegex(ProtocolError, r"line 2: malformed JSON"):
            parse_jsonl(text)

    def test_duplicate_keys_are_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "duplicate key"):
            parse_jsonl('{"id":"SYN01","id":"SYN01"}\n')

    def test_non_object_line_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "JSON object"):
            parse_jsonl("[1, 2, 3]\n")

    def test_blank_lines_are_ignored(self):
        text = "\n" + support.jsonl([support.candidate("SYN01")]) + "\n"
        records = parse_jsonl(text)
        self.assertEqual([item["id"] for item in records], ["SYN01"])

    def test_crlf_and_an_embedded_line_separator_stay_one_record(self):
        crlf = support.jsonl([support.candidate("SYN01")]).replace("\n", "\r\n")
        self.assertEqual(parse_jsonl(crlf)[0]["id"], "SYN01")
        question = "keeps a \u2028 line separator inside the string"
        raw = support.candidate("SYN02", question=question)
        records = parse_jsonl(support.jsonl([raw]))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["question"], question)

    def test_bom_empty_ref_and_bad_correct_letter(self):
        with self.assertRaisesRegex(ProtocolError, "BOM"):
            parse_jsonl("\ufeff" + support.jsonl([support.candidate()]))
        empty_ref = parse_jsonl(support.jsonl([support.candidate(ref="")]))
        self.assertEqual(empty_ref[0]["ref"], "")
        with self.assertRaisesRegex(ProtocolError, "correct is invalid"):
            parse_jsonl(support.jsonl([support.candidate(correct="E", correctText="ohm")]))

    def test_extra_top_level_fields_are_allowed(self):
        raw = support.candidate()
        raw["note"] = "optional caller field"
        validate_candidate(raw)

    def test_line_byte_cap(self):
        with self.assertRaisesRegex(ProtocolError, "exceeds 32 bytes"):
            parse_jsonl(support.jsonl([support.candidate()]), max_line_bytes=32)

    def test_record_cap(self):
        rows = [support.candidate(f"SYN{i:02d}") for i in range(1, 4)]
        with self.assertRaisesRegex(ProtocolError, "exceeds 2 records"):
            parse_jsonl(support.jsonl(rows), max_records=2)

    def test_cli_malformed_json_fails_closed(self):
        result = support.run_cli(["run", "--runtime", "fixture"], "{not json\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"malformed JSON", result.stderr)

    def test_cli_missing_id_fails_closed(self):
        raw = support.candidate()
        del raw["id"]
        result = support.run_cli(["run", "--runtime", "fixture"], support.jsonl([raw]))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"missing id", result.stderr)


if __name__ == "__main__":
    unittest.main()
