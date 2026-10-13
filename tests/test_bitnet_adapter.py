import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support

from local_llm_review.metadata import RunSettings
from local_llm_review.protocol import parse_model_output
from local_llm_review.runtimes.bitnet import (
    _flag_advertised,
    build_argv,
    format_temperature,
    verify_bitnet,
)

# Help text shaped like microsoft/BitNet run_inference.py as observed 2026-10-12.
# The adapter must discover these tokens from the process, not assume them.
UPSTREAM_HELP = """usage: run_inference.py [-h] [-m MODEL] [-n N_PREDICT] -p PROMPT [-t THREADS] [-c CTX_SIZE] [-temp TEMPERATURE] [-cnv]

optional arguments:
  -h, --help            show this help message and exit
  -m MODEL, --model MODEL
                        Path to model file
  -n N_PREDICT, --n-predict N_PREDICT
                        Number of tokens to predict when generating text
  -p PROMPT, --prompt PROMPT
                        Prompt to generate text from
  -t THREADS, --threads THREADS
                        Number of threads to use
  -c CTX_SIZE, --ctx-size CTX_SIZE
                        Size of the prompt context
  -temp TEMPERATURE, --temperature TEMPERATURE
                        Temperature, a hyperparameter that controls the randomness of the generated text
  -cnv, --conversation  Whether to enable chat mode or not
"""


def write_runtime(directory: Path, name: str, help_text: str, *, llama: bool) -> Path:
    path = directory / name
    stamp = directory / "invoked.jsonl"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, re, sys\n"
        f"help_text = {help_text!r}\n"
        f"stamp = {str(stamp)!r}\n"
        "args = sys.argv[1:]\n"
        "if '-h' in args or '--help' in args:\n"
        "    sys.stdout.write(help_text)\n"
        "    raise SystemExit(0)\n"
        "with open(stamp, 'a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps({'cwd': os.getcwd(), 'argv': sys.argv}) + '\\n')\n"
        "blob = '\\n'.join(args)\n"
        "match = re.search(r'\"id\":\"([^\"]+)\"', blob)\n"
        "if not match:\n"
        "    sys.stderr.write('fake runtime: no id in prompt\\n')\n"
        "    raise SystemExit(4)\n"
        "ident = match.group(1)\n"
        "json.dump({\n"
        "    'id': ident,\n"
        "    'syllabusRelevant': True,\n"
        "    'indianTopic': 'electrical principles',\n"
        "    'recommendation': 'keep',\n"
        "    'jurisdictionRisk': 'none',\n"
        "    'figureRightsWarning': 'none',\n"
        "    'rationale': 'Advisory only: stub; this is not publication approval.',\n"
        "}, sys.stdout)\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    if llama:
        binary = directory / "build" / "bin" / "llama-cli"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    model = directory / "model.gguf"
    model.write_bytes(b"GGUF" + b"synthetic-not-a-weight")
    return path


class FlagMatchTest(unittest.TestCase):
    def test_short_flags_do_not_match_inside_long_flags(self):
        self.assertFalse(_flag_advertised("--temperature TEMP", "-temp"))
        self.assertTrue(_flag_advertised("--temperature TEMP", "--temperature"))
        self.assertTrue(_flag_advertised("[-temp TEMPERATURE]", "-temp"))
        self.assertFalse(_flag_advertised("--temp N", "-temp"))
        self.assertTrue(_flag_advertised("--temp N", "--temp"))
        self.assertFalse(_flag_advertised("--model FILE", "-m"))
        self.assertTrue(_flag_advertised("[-m MODEL]", "-m"))

    def test_temperature_format_is_stable(self):
        self.assertEqual(format_temperature(0.0), "0")
        self.assertEqual(format_temperature(0.5), "0.5")


class BitNetAdapterTest(unittest.TestCase):
    def test_verified_runtime_passes_only_advertised_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            executable = write_runtime(directory, "run_inference.py", UPSTREAM_HELP, llama=True)
            model = directory / "model.gguf"
            result = support.run_cli(
                [
                    "run",
                    "--runtime",
                    "bitnet",
                    "--executable",
                    str(executable),
                    "--model",
                    str(model),
                    "--model-id",
                    "BitNet-b1.58-2B-4T",
                    "--metadata",
                    str(directory / "meta.json"),
                    "--threads",
                    "2",
                    "--timeout",
                    "10",
                ],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            record = parse_model_output(result.stdout.decode(), expected_id="SYN01")
            self.assertEqual(record["recommendation"], "keep")
            invoked = [json.loads(line) for line in (directory / "invoked.jsonl").read_text().splitlines()]
            self.assertEqual(len(invoked), 1)
            argv = invoked[0]["argv"]
            self.assertEqual(invoked[0]["cwd"], str(directory))
            self.assertIn("--model", argv)
            self.assertIn("--prompt", argv)
            self.assertIn("--temperature", argv)
            self.assertIn("--n-predict", argv)
            self.assertIn("--threads", argv)
            self.assertIn("--ctx-size", argv)
            self.assertNotIn("-cnv", argv)
            self.assertNotIn("--conversation", argv)
            self.assertNotIn("--seed", argv)
            self.assertNotIn("-ngl", argv)
            self.assertNotIn("-temp", argv)
            self.assertEqual(argv[argv.index("--temperature") + 1], "0")
            self.assertEqual(Path(invoked[0]["cwd"]).resolve(), directory.resolve())
            document = json.loads((directory / "meta.json").read_text())
            self.assertEqual(document["runtime"], "bitnet")
            self.assertEqual(document["modelId"], "BitNet-b1.58-2B-4T")
            self.assertTrue(document["settings"]["supportClaimed"])
            self.assertFalse(document["settings"]["seedApplied"])
            self.assertEqual(document["outputCount"], 1)
            self.assertEqual(document["failureCount"], 0)

    def test_unverified_help_does_not_claim_support_or_launch_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            executable = write_runtime(
                directory,
                "custom.py",
                "usage: custom [-h] [--foo FOO]\n",
                llama=False,
            )
            model = directory / "model.gguf"
            result = support.run_cli(
                [
                    "run",
                    "--runtime",
                    "bitnet",
                    "--executable",
                    str(executable),
                    "--model",
                    str(model),
                    "--metadata",
                    str(directory / "meta.json"),
                    "--timeout",
                    "10",
                ],
                support.jsonl([support.candidate("SYN01")]),
            )
            self.assertEqual(result.returncode, 2, result.stderr.decode())
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"support is not claimed", result.stderr.lower())
            self.assertFalse((directory / "invoked.jsonl").exists())
            document = json.loads((directory / "meta.json").read_text())
            self.assertEqual(document["failureCount"], 1)
            self.assertEqual(document["outputCount"], 0)
            self.assertFalse(document["settings"]["supportClaimed"])

    def test_run_inference_without_llama_cli_is_not_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            executable = write_runtime(directory, "run_inference.py", UPSTREAM_HELP, llama=False)
            verification = verify_bitnet(executable=str(executable), model=str(directory / "model.gguf"))
            self.assertFalse(verification.supported)
            self.assertIn("not claimed", verification.reason)
            self.assertIn("llama-cli", verification.reason)

    def test_run_inference_cwd_must_contain_llama_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            home = directory / "bitnet"
            home.mkdir()
            elsewhere = directory / "elsewhere"
            elsewhere.mkdir()
            executable = write_runtime(home, "run_inference.py", UPSTREAM_HELP, llama=True)
            verification = verify_bitnet(
                executable=str(executable),
                model=str(home / "model.gguf"),
                cwd=str(elsewhere),
            )
            self.assertFalse(verification.supported)
            self.assertIn("llama-cli", verification.reason)
            self.assertIn(str(elsewhere), verification.reason)

    def test_seed_and_gpu_layers_are_passed_only_when_advertised(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            help_text = UPSTREAM_HELP + "  --seed SEED\n  -ngl N\n"
            executable = write_runtime(directory, "custom.py", help_text, llama=False)
            verification = verify_bitnet(executable=str(executable), model=str(directory / "model.gguf"))
            self.assertTrue(verification.supported, verification.reason)
            settings = RunSettings(gpu_layers=4, seed=7, temperature=0)
            argv, info = build_argv(verification, "prompt text", settings)
            self.assertIn("--seed", argv)
            self.assertIn("7", argv)
            self.assertIn("-ngl", argv)
            self.assertIn("4", argv)
            self.assertNotIn("-cnv", argv)
            self.assertTrue(info.seed_applied)
            self.assertEqual(info.gpu_layers, 4)
            self.assertTrue(info.support_claimed)

    def test_requested_gpu_layers_without_a_flag_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            executable = write_runtime(directory, "custom.py", UPSTREAM_HELP, llama=False)
            verification = verify_bitnet(executable=str(executable), model=str(directory / "model.gguf"))
            self.assertTrue(verification.supported, verification.reason)
            with self.assertRaisesRegex(Exception, "not claimed"):
                build_argv(verification, "prompt", RunSettings(gpu_layers=8))

    def test_missing_executable_is_a_clear_diagnostic(self):
        result = support.run_cli(
            ["run", "--runtime", "bitnet", "--executable", "/no/such/run_inference.py", "--model", "/no/such/model.gguf"],
            support.jsonl([support.candidate("SYN01")]),
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        stderr = result.stderr.decode().lower()
        self.assertIn("not found", stderr)
        self.assertIn("not claimed", stderr)


if __name__ == "__main__":
    unittest.main()
