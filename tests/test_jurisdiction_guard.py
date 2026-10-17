import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from local_llm_review.jurisdiction_guard import GUARD_TOPIC, RULES, build_guard_record, evaluate_guard


def cand(question: str, correct_text: str, **overrides) -> dict:
    return support.candidate(
        "X1",
        question=question,
        choices={"A": correct_text, "B": "b", "C": "c", "D": "d"},
        correct="A",
        correctText=correct_text,
        **overrides,
    )


class JurisdictionGuardTest(unittest.TestCase):
    def test_rules_have_unique_ids(self):
        ids = [rule.id for rule in RULES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(RULES), 6)

    def test_each_named_category_flags_a_representative_candidate(self):
        cases = [
            ("What does FCC Part 97 say about station identification?", "It requires a call sign.", "fcc-part-97"),
            ("What is RACES?", "A civil defense radio service.", "races-civil-defense"),
            (
                "What is the band plan restriction for US stations in the 48 contiguous states?",
                "No contacts within the 48 contiguous states.",
                "band-plan-us",
            ),
            ("What must a US-licensed operator do when identifying?", "Give the call sign in English.", "callsign-licensing-us"),
            ("What stations are subject to the FCC rules on RF exposure?", "All stations above the threshold.", "rf-exposure-us"),
            ("In the United States, what color is the hot wire?", "Black.", "us-self-declared"),
            ("Why does the FCC require a station log?", "For accountability.", "fcc-reference"),
        ]
        for question, answer, expected_rule in cases:
            guard = evaluate_guard(cand(question, answer))
            self.assertTrue(guard.flagged, question)
            self.assertEqual(guard.rule, expected_rule, question)
            self.assertEqual(guard.verdict, "reject", question)
            self.assertTrue(guard.reason)
            self.assertTrue(guard.category)

    def test_universal_electronics_and_propagation_are_not_flagged(self):
        universal = [
            cand("What is a beam antenna?", "An antenna that concentrates signals in one direction."),
            cand("How does a higher sunspot number affect HF propagation?", "It generally improves propagation at higher frequencies."),
            cand("What electrical component opposes the flow of current in a DC circuit?", "A resistor."),
        ]
        for candidate_record in universal:
            guard = evaluate_guard(candidate_record)
            self.assertFalse(guard.flagged, candidate_record["question"])

    def test_wrong_answer_distractor_naming_the_fcc_does_not_flag(self):
        # Mirrors the real pool question T2C... wait, T7C05: only the WRONG
        # choice B names the FCC; the question and correct answer are pure
        # electronics. The guard scans question+correctText, never choices.
        candidate_record = support.candidate(
            "X1",
            question="Why do most solid-state transmitters reduce output power as SWR increases beyond a certain level?",
            choices={
                "A": "To protect the RF output amplifier transistors",
                "B": "To comply with FCC rules on spectral purity",
                "C": "c",
                "D": "d",
            },
            correct="A",
            correctText="To protect the RF output amplifier transistors",
        )
        guard = evaluate_guard(candidate_record)
        self.assertFalse(guard.flagged)


class GuardRecordShapeTest(unittest.TestCase):
    def test_build_guard_record_uses_the_shared_fixed_topic_label(self):
        guard = evaluate_guard(cand("What is RACES?", "A civil defense radio service."))
        record = build_guard_record({"id": "X1"}, guard)
        self.assertEqual(record["indianTopic"], GUARD_TOPIC)
        self.assertEqual(record["indianTopic"], "Jurisdiction-specific (US) — not syllabus relevant")
        # Never the raw, implementation-specific rule category text -- that
        # was the exact drift the review flagged (the UI showed a
        # different-looking topic depending on which tool produced the
        # record).
        self.assertNotEqual(record["indianTopic"], guard.category)

    def test_build_guard_record_matches_the_shared_convention(self):
        guard = evaluate_guard(cand("What is RACES?", "A civil defense radio service."))
        record = build_guard_record({"id": "X1"}, guard)
        self.assertEqual(record["id"], "X1")
        self.assertIs(record["syllabusRelevant"], False)
        self.assertEqual(record["recommendation"], "reject")
        self.assertEqual(record["jurisdictionRisk"], "high")
        self.assertEqual(record["figureRightsWarning"], "none")
        self.assertIn("races-civil-defense", record["rationale"])
        self.assertIn(guard.reason, record["rationale"])
        self.assertIn("no model involved", record["rationale"])


US_HAMEXAM_REVIEW_PIPELINE = (
    Path(os.environ["US_HAMEXAM_ROOT"]) / "scripts" / "review-pipeline.js"
    if os.environ.get("US_HAMEXAM_ROOT")
    else support.ROOT.parent / "us-hamexam" / "scripts" / "review-pipeline.js"
)


def _js_guard_record(candidate: dict) -> dict | None:
    """Run the sibling repo's own evaluateGuard+guardRecord on the same
    candidate and return its record, or None if node/the sibling checkout
    isn't available. Keeping this a subprocess call (not a hand-translated
    copy of the JS) is the whole point: it exercises the REAL shipped
    guardRecord(), so the two implementations can never silently drift
    without this test catching it."""
    if not US_HAMEXAM_REVIEW_PIPELINE.is_file() or not shutil.which("node"):
        return None
    script = (
        "const p=require(process.argv[1]);"
        "const candidate=JSON.parse(process.argv[2]);"
        "const guard=p.evaluateGuard?p.evaluateGuard(candidate):require(require('path').join(require('path').dirname(process.argv[1]),'jurisdiction-guard.js')).evaluateGuard(candidate);"
        "console.log(JSON.stringify(p.guardRecord(candidate,guard)));"
    )
    result = subprocess.run(
        ["node", "-e", script, str(US_HAMEXAM_REVIEW_PIPELINE), json.dumps(candidate)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(f"us-hamexam guardRecord() failed: {result.stderr}")
    return json.loads(result.stdout)


class CrossImplementationGuardRecordTest(unittest.TestCase):
    """Pins the shared guard-record shape across both repositories so a
    future hand edit to either jurisdiction_guard.py or
    scripts/review-pipeline.js can't silently drift them apart again --
    skips cleanly when the sibling checkout or node isn't available,
    exactly like test_prompt_hash.py's cross-repo byte comparison."""

    def test_guard_record_shape_matches_us_hamexam(self):
        candidate = support.candidate(
            "RACES01",
            question="What is RACES?",
            choices={"A": "A civil defense radio service.", "B": "b", "C": "c", "D": "d"},
            correct="A",
            correctText="A civil defense radio service.",
        )
        guard = evaluate_guard(candidate)
        self.assertTrue(guard.flagged)
        py_record = build_guard_record(candidate, guard)
        js_record = _js_guard_record(candidate)
        if js_record is None:
            self.skipTest(
                "us-hamexam scripts/review-pipeline.js or node is not available. "
                "Set US_HAMEXAM_ROOT to compare against the sibling checkout."
            )
        for key in ("id", "syllabusRelevant", "indianTopic", "recommendation", "jurisdictionRisk", "figureRightsWarning"):
            self.assertEqual(py_record[key], js_record[key], key)
        # Both rationale templates intentionally embed the same matched
        # rule id and reason (the two RULES tables are hand-mirrored), so
        # requiring those substrings to agree catches drift in either the
        # synthesis template OR the underlying rule tables.
        self.assertIn(guard.rule, js_record["rationale"])
        self.assertIn(guard.reason, js_record["rationale"])
        self.assertIn("no model involved", js_record["rationale"])


def write_always_keep_command(directory: Path) -> Path:
    """A fake runtime that always answers keep/none, and stamps every
    invocation it actually received -- used to prove the guard skips
    invoking it entirely for a flagged candidate, not merely overrides
    its output afterward."""
    script = directory / "always_keep.py"
    stamp = directory / "invoked.txt"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, re, sys\n"
        f"stamp = {str(stamp)!r}\n"
        "blob = sys.stdin.read()\n"
        "with open(stamp, 'a', encoding='utf-8') as handle:\n"
        "    handle.write('invoked\\n')\n"
        "matches = list(re.finditer(r'\"id\":\\s*\"([^\"]+)\"', blob))\n"
        "ident = matches[-1].group(1) if matches else 'UNKNOWN'\n"
        "json.dump({\n"
        "    'id': ident, 'syllabusRelevant': True, 'indianTopic': 'electronics',\n"
        "    'recommendation': 'keep', 'jurisdictionRisk': 'none',\n"
        "    'figureRightsWarning': 'none', 'rationale': 'the model insists this is fine',\n"
        "}, sys.stdout)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


class JurisdictionGuardRunnerIntegrationTest(unittest.TestCase):
    def test_flagged_candidate_is_rejected_without_invoking_the_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            command = write_always_keep_command(directory)
            races_candidate = support.candidate(
                "RACES01",
                question="What is RACES?",
                choices={"A": "A civil defense radio service.", "B": "b", "C": "c", "D": "d"},
                correct="A",
                correctText="A civil defense radio service.",
            )
            result = support.run_cli(
                ["run", "--runtime", "command", "--command", str(command), "--timeout", "10"],
                support.jsonl([races_candidate]),
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            record = __import__("json").loads(result.stdout.decode())
            self.assertEqual(record["recommendation"], "reject")
            self.assertEqual(record["jurisdictionRisk"], "high")
            self.assertIn("races-civil-defense", record["rationale"])
            self.assertFalse((directory / "invoked.txt").exists(), "the command runtime must never run for a guard-flagged record")

    def test_unflagged_candidate_still_reaches_the_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            command = write_always_keep_command(directory)
            result = support.run_cli(
                ["run", "--runtime", "command", "--command", str(command), "--timeout", "10"],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            record = __import__("json").loads(result.stdout.decode())
            self.assertEqual(record["recommendation"], "keep")
            self.assertTrue((directory / "invoked.txt").exists())

    def test_fixture_runtime_is_exempt_from_the_guard(self):
        # Invariant #6: fixture stdout is byte-identical and ignores
        # prompt-injection-shaped content; the guard must not touch it.
        races_candidate = support.candidate(
            "RACES01",
            question="What is RACES?",
            choices={"A": "A civil defense radio service.", "B": "b", "C": "c", "D": "d"},
            correct="A",
            correctText="A civil defense radio service.",
        )
        result = support.run_cli(["run", "--runtime", "fixture"], support.jsonl([races_candidate]))
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        record = __import__("json").loads(result.stdout.decode())
        self.assertNotIn("Deterministic guard", record["rationale"])


if __name__ == "__main__":
    unittest.main()
