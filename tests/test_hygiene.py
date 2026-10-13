import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support


class HygieneTest(unittest.TestCase):
    def test_inference_code_does_not_use_a_shell(self):
        for path in (support.SRC / "local_llm_review").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", text, str(path))
            self.assertNotIn("os.system(", text, str(path))

    def test_repository_contains_no_weights_or_runtime_binaries(self):
        banned = {".gguf", ".safetensors", ".onnx", ".pt", ".dll", ".so", ".bin"}
        for path in support.ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(support.ROOT).parts):
                continue
            self.assertNotIn(path.suffix.lower(), banned, str(path))

    def test_gitignore_covers_weights(self):
        text = (support.ROOT / ".gitignore").read_text(encoding="utf-8")
        for token in ("*.gguf", "*.safetensors", "*.bin", "models/"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
