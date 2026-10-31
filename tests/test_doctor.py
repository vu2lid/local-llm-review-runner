import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from test_bitnet_adapter import UPSTREAM_HELP, write_runtime


class DoctorTest(unittest.TestCase):
    def test_default_doctor_does_not_claim_bitnet_support(self):
        result = support.run_bin(["doctor"])
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        text = result.stdout.decode()
        self.assertIn("fixture: ready", text)
        self.assertIn("bitnet: not configured", text)
        self.assertIn("support claimed: no", text)
        self.assertNotIn("support claimed: yes", text)
        self.assertIn("promptVersion: india-review-prompt-v4", text)
        bare = support.run_bin(["doctor", "--runtime", "bitnet"])
        self.assertEqual(bare.returncode, 2)
        bare_text = bare.stdout.decode()
        self.assertIn("support claimed: no", bare_text)
        self.assertNotIn("support claimed: yes", bare_text)

    def test_verified_doctor_claims_support(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            executable = write_runtime(directory, "run_inference.py", UPSTREAM_HELP, llama=True)
            result = support.run_cli(
                [
                    "doctor",
                    "--runtime",
                    "bitnet",
                    "--executable",
                    str(executable),
                    "--model",
                    str(directory / "model.gguf"),
                ]
            )
            self.assertEqual(result.returncode, 0, result.stdout.decode() + result.stderr.decode())
            text = result.stdout.decode()
            self.assertIn("support claimed: yes", text)
            self.assertNotIn("support claimed: no", text)
            self.assertIn("flag interface verified", text)
            self.assertIn("seed is not advertised", text)
            self.assertNotIn("-cnv", text.split("flags: ", 1)[1].splitlines()[0])

    def test_doctor_refuses_a_runtime_whose_help_does_not_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            executable = write_runtime(directory, "custom.py", "usage: nope [-h]\n", llama=False)
            result = support.run_cli(
                [
                    "doctor",
                    "--runtime",
                    "bitnet",
                    "--executable",
                    str(executable),
                    "--model",
                    str(directory / "model.gguf"),
                ]
            )
            self.assertEqual(result.returncode, 2)
            text = result.stdout.decode()
            self.assertIn("support claimed: no", text)
            self.assertNotIn("support claimed: yes", text)
            self.assertIn("not claimed", text.lower())


if __name__ == "__main__":
    unittest.main()
