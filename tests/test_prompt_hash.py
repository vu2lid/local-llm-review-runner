import hashlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from local_llm_review.prompt import PLACEHOLDER, PROMPT_PATH, PROMPT_VERSION, prompt_hash, render_prompt, template_bytes


class PromptHashTest(unittest.TestCase):
    def test_hash_is_sha256_of_file_bytes_and_stable(self):
        first = prompt_hash()
        second = prompt_hash()
        digest = hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()
        self.assertEqual(first, second)
        self.assertEqual(first, digest)
        self.assertEqual(len(first), 64)
        self.assertNotIn(b"\r", template_bytes())

    def test_template_instructions_and_single_placeholder(self):
        text = template_bytes().decode("utf-8")
        self.assertEqual(text.count(PLACEHOLDER), 1)
        self.assertEqual(PROMPT_VERSION, "india-review-prompt-v2")
        for phrase in (
            "India ASOC",
            "jurisdictionRisk",
            "figureRightsWarning",
            "always false",
            "EXACTLY ONE JSON object",
            "keep",
            "adapt",
            "reject",
            "defer",
        ):
            self.assertIn(phrase, text)
        self.assertFalse(text.lstrip().startswith("-"))

    def test_vendored_bytes_match_us_hamexam_when_that_checkout_exists(self):
        override = os.environ.get("US_HAMEXAM_ROOT")
        if override:
            sibling = Path(override) / "tools" / "india-review" / "prompt-v2.txt"
        else:
            sibling = support.ROOT.parent / "us-hamexam" / "tools" / "india-review" / "prompt-v2.txt"
        if not sibling.is_file():
            self.skipTest(
                "us-hamexam prompt-v2.txt is not present. The vendored template is still hashed on its own. "
                "Set US_HAMEXAM_ROOT to compare bytes."
            )
        self.assertEqual(PROMPT_PATH.read_bytes(), sibling.read_bytes())

    def test_rendering_does_not_change_the_template_hash(self):
        before = prompt_hash()
        rendered = render_prompt(support.candidate("SYN01"))
        self.assertNotIn(PLACEHOLDER, rendered)
        self.assertIn('"id":"SYN01"', rendered)
        self.assertEqual(prompt_hash(), before)

    def test_pyproject_version_matches_the_package(self):
        import local_llm_review

        text = (support.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{local_llm_review.__version__}"', text)


if __name__ == "__main__":
    unittest.main()
