"""Optional check against a sibling us-hamexam checkout.

The runner does not import that repository. This test skips when the
checkout or node is absent. A fresh clone of this repo alone still passes.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support


def pipeline_path() -> Path | None:
    import os

    override = os.environ.get("US_HAMEXAM_ROOT")
    if override:
        candidate = Path(override) / "scripts" / "review-pipeline.js"
    else:
        candidate = support.ROOT.parent / "us-hamexam" / "scripts" / "review-pipeline.js"
    return candidate if candidate.is_file() else None


class ManifestCompatibilityTest(unittest.TestCase):
    def test_fixture_pilot_is_accepted_by_review_manifest(self):
        pipeline = pipeline_path()
        if pipeline is None:
            self.skipTest(
                "us-hamexam review pipeline not present; local schema checks still run. "
                "Set US_HAMEXAM_ROOT to enable this check."
            )
        if shutil.which("node") is None:
            self.skipTest("node is not installed; cannot load us-hamexam review-pipeline.js")
        stdin = support.PILOT.read_text(encoding="utf-8")
        result = support.run_cli(["run", "--runtime", "fixture"], stdin)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            candidates = directory / "candidates.jsonl"
            records = directory / "model.jsonl"
            candidates.write_text(stdin, encoding="utf-8")
            records.write_bytes(result.stdout)
            # A real script file keeps argv stable. `node -e` drops the eval
            # source from process.argv, so the JSONL path was compiled as JS.
            checker = directory / "check-manifest.js"
            checker.write_text(
                "const p = require(process.argv[2]);\n"
                "const fs = require('fs');\n"
                "const read = (file) => fs.readFileSync(file, 'utf8').split(/\\n/).filter(Boolean).map((line) => JSON.parse(line));\n"
                "const candidates = read(process.argv[3]);\n"
                "const records = read(process.argv[4]);\n"
                "const manifest = p.createManifest(candidates, records, {adapter: 'command', model: 'local-llm-review'});\n"
                "p.validateManifest(manifest);\n"
                "if (manifest.items.length !== candidates.length) process.exit(2);\n"
                "for (let i = 0; i < candidates.length; i += 1) {\n"
                "  if (manifest.items[i].candidate.id !== candidates[i].id) process.exit(3);\n"
                "  if (manifest.items[i].model.id !== candidates[i].id) process.exit(4);\n"
                "}\n"
                "console.log('manifest-ok ' + manifest.items.length);\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [shutil.which("node"), str(checker), str(pipeline), str(candidates), str(records)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode() + completed.stdout.decode())
        self.assertIn(b"manifest-ok 25", completed.stdout)
        ids = [json.loads(line)["id"] for line in result.stdout.decode().splitlines()]
        self.assertEqual(len(ids), 25)


if __name__ == "__main__":
    unittest.main()
