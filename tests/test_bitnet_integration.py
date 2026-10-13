import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from local_llm_review.protocol import parse_model_output

EXECUTABLE = os.environ.get("BITNET_EXECUTABLE")
MODEL = os.environ.get("BITNET_MODEL")
SKIP = (
    "BitNet integration skipped: set BITNET_EXECUTABLE and BITNET_MODEL to the "
    "installed runtime and model file. The adapter does not claim support "
    "unless doctor verifies that runtime."
)


@unittest.skipUnless(EXECUTABLE and MODEL, SKIP)
class BitNetIntegrationTest(unittest.TestCase):
    def test_doctor_then_one_record(self):
        timeout = os.environ.get("BITNET_TIMEOUT", "180")
        doctor = support.run_cli(
            [
                "doctor",
                "--runtime",
                "bitnet",
                "--executable",
                EXECUTABLE,
                "--model",
                MODEL,
            ],
            env={"BITNET_EXECUTABLE": EXECUTABLE, "BITNET_MODEL": MODEL},
            timeout=60,
        )
        self.assertEqual(doctor.returncode, 0, doctor.stderr.decode() + doctor.stdout.decode())
        self.assertIn(b"support claimed: yes", doctor.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "meta.json"
            result = support.run_cli(
                [
                    "run",
                    "--runtime",
                    "bitnet",
                    "--executable",
                    EXECUTABLE,
                    "--model",
                    MODEL,
                    "--metadata",
                    str(meta),
                    "--timeout",
                    timeout,
                ],
                support.jsonl([support.candidate("SYN01")]),
                env={"BITNET_EXECUTABLE": EXECUTABLE, "BITNET_MODEL": MODEL},
                timeout=float(timeout) + 30,
            )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        parse_model_output(result.stdout.decode(), expected_id="SYN01")
        document = json.loads(meta.read_text(encoding="utf-8"))
        self.assertEqual(document["inputCount"], 1)
        self.assertEqual(document["outputCount"], 1)
        self.assertEqual(document["failureCount"], 0)
        self.assertTrue(document["settings"]["supportClaimed"])


if __name__ == "__main__":
    unittest.main()
