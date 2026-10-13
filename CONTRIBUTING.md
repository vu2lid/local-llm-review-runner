# Contributing

Thank you for considering a change. This runner is a small stdlib Python program. The useful contributions are protocol fixes, clearer diagnostics, fixture coverage, and carefully verified local-runtime adapters.

## Setup

Install Python 3.10 or newer. From a clone:

```sh
bin/local-llm-review doctor
python3 -m unittest discover -s tests -v
```

No virtualenv and no package install are required. Optional editable install, still with no third-party dependencies:

```sh
pip install --no-deps -e .
```

BitNet is optional. Build and download it outside this tree, then point `doctor` at that executable and model. [docs/SETUP.md](docs/SETUP.md) has the Linux CPU outline. Do not commit the checkout, the weights, or `llama-cli`.

## Tests

Run the full suite from the repository root before opening a pull request:

```sh
python3 -m unittest discover -s tests -v
```

The BitNet integration test skips unless both `BITNET_EXECUTABLE` and `BITNET_MODEL` are set. Leave them unset for the default run. A skip must name that reason. Do not mark a failing integration test as skipped to get a green suite.

The manifest compatibility test talks to a sibling `us-hamexam` checkout when one is present. It must keep skipping cleanly when that checkout is absent.

## What stays out of git

- Model weights and archives (`*.gguf`, `*.safetensors`, `*.bin`, `*.pt`, `*.onnx`)
- BitNet, llama.cpp, or other runtime binaries
- Credentials, tokens, and local environment files
- Real exam banks and generated candidate extracts
- Metadata and log files produced by a run (`*.metadata.json`, `logs/`)

`fixtures/pilot-25.jsonl` is synthetic on purpose. Replace it only with other synthetic records.

## Changing behavior

- Match the surrounding style. Keep the public modules free of third-party imports.
- A protocol or CLI change needs a unit test that would fail on the old behavior, plus a docs update when a command or JSON field changes.
- Prompt edits belong in a versioned file under `src/local_llm_review/prompts/`. Update `PROMPT_VERSION` when the instructions change, keep LF line endings, and let `tests/test_prompt_hash.py` track the file hash.
- Do not teach the parser to accept markdown fences or trailing prose. Malformed model output fails closed.
- Do not claim BitNet support from a README flag list. `doctor` must observe the installed `--help` output.
- Inference paths must not gain network access. A new download belongs under `setup` and must require `--confirm-network`.

## Pull requests

Describe the user-visible change and how you tested it. If you did not run the BitNet integration test, say so.

By submitting a contribution you agree that it is licensed under the [MIT License](LICENSE).

## Security reports

Use the process in [SECURITY.md](SECURITY.md). Please do not file candidate text, credentials, or model weights in a public issue.
