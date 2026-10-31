# local-llm-review-runner

Offline command-line runner for structured candidate-review tasks. It reads candidate JSONL on stdin and writes one validated classification JSON object per input on stdout. Diagnostics go to stderr. Run metadata is a separate JSON file.

Version 0.1.0. The first local runtime target is Microsoft BitNet b1.58 2B 4T. A fixture runtime is included so a fresh clone can run the 25-record pilot with no model download and no network. Other local runtimes can be attached later through an explicit argv command.

This repository does not import or modify [us-hamexam](https://github.com/vu2lid/us-hamexam). The JSONL contract those review manifests expect is described in [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Boundaries

Classifications are advisory. The runner does not claim official ASOC status, syllabus adoption, or exam faithfulness, and it does not approve content for publication. A human reviews every recommendation.

`run` and `doctor` do not open a network connection. The only built-in networked command is `setup --download`, and it also requires `--confirm-network`. It refuses a model directory inside this repository. A caller-supplied `--runtime command` program can still contact the network on its own; this runner does not add a client for it. Model weights, runtime binaries, credentials, and generated candidate extracts are not part of this repository. `fixtures/pilot-25.jsonl` is synthetic.

`doctor` does not claim BitNet support until it has verified the installed executable and model. With no BitNet paths it reports `support claimed: no` and `fixture: ready`.

## Evaluation status (Stage 8E3 / contract v3)

- The active template is `india-review-prompt-v4`, byte-identical to us-hamexam `tools/india-review/prompt-v4.txt` (Stage 8F2; sha256 `2ababd33d3e1d573730fb3c9ba5f7057fb39896c1a7c4a3eb1678d31b57e48c0`). v4 adds the `syllabusCodes` array (model-suggested syllabus codes) to the model record contract (v3, exactly 8 keys) and its prompt text; **v4's own quality is unevaluated** — do not claim it improves on v3. The 2026-10-14 Qwen2.5-1.5B pilot was run under the v3 prompt and found v3 is **not** an improvement: 7 of 19 universal questions got fabricated or self-contradictory rationales, and 2 records hit truncation failures. v3 was retained as **EXPERIMENTAL** on that evidence; that evaluation says nothing about v4.
- Model records now carry `syllabusCodes`, an array of codes from a syllabus manifest (us-hamexam pins `editions/india/syllabus.json`). Validation is fail-closed per record: entries must be unique non-empty strings, `syllabusRelevant: true` requires at least one code, a non-empty list with `syllabusRelevant: false` is rejected as contradictory, and every code must exist in the manifest given via `run --syllabus-manifest <path>`. A record carrying codes when no manifest was provided fails the run (empty stdout, non-zero exit) — codes are only validated against an explicit manifest. The one exception is the fixture runtime, a documented development double whose synthetic records draw from its own pinned built-in example code set. The manifest's path, schemaVersion, sha256, and code count are recorded in the metadata JSON under `syllabusManifest`.
- A deterministic jurisdiction guard (`src/local_llm_review/jurisdiction_guard.py`) runs on the candidate's own text **before** any runtime (fixture excepted) is invoked. On a match the runtime is never called for that record and the guard's own `reject`/`high` record is emitted, so model output is advisory and can never override or un-guard a deterministic rejection; `validate_model_record` additionally fails closed on any `high` + `keep` pair. In the same pilot the guard caught all 6 known US-specific questions.
- BitNet b1.58 2B 4T is plumbing-valid but unsuitable for content triage (see [docs/SETUP.md](docs/SETUP.md)). Qwen2.5-1.5B output is usable only together with the deterministic guard and human review of every recommendation.

The synthetic guard record's shape is a cross-repository convention shared with us-hamexam's `guardRecord()`, and it is pinned by the checked-in golden fixture `fixtures/guard-record-golden.json` (a byte-identical copy lives at us-hamexam `tools/india-review/guard-record-golden.json`). `tests/test_guard_golden.py` always runs — it never skips on a missing sibling checkout — so CI detects guard-record drift independently; when the sibling checkout is present the same test additionally asserts the two golden files are byte-identical. Changing the guard-record shape requires updating the golden fixture in both repositories together and bumping its `conventionVersion`.

## Requirements

- Python 3.10 or newer for the fixture and the test suite. No third-party packages and no `pip install` are required.
- Optional BitNet CPU path: CMake, clang, and a separate BitNet checkout. See [docs/SETUP.md](docs/SETUP.md).

## Quick start

```sh
bin/local-llm-review doctor
bin/local-llm-review run --runtime fixture \
  --metadata /tmp/local-llm-review-metadata.json \
  < fixtures/pilot-25.jsonl > /tmp/pilot-model.jsonl
python3 -m unittest discover -s tests -v
```

The same entry point is available as `python3 -m local_llm_review`. An install from this tree also exposes the `local-llm-review` console script:

```sh
pip install --no-deps -e .
```

That install is optional. The fixture works from `bin/local-llm-review` without it.

## Commands

```sh
local-llm-review doctor
local-llm-review doctor --runtime bitnet --executable /path/to/BitNet/build/bin/llama-completion --model /path/to/model.gguf
local-llm-review run --runtime fixture --metadata /tmp/local-llm-review-metadata.json
local-llm-review run --runtime fixture --syllabus-manifest /path/to/us-hamexam/editions/india/syllabus.json \
  --metadata /tmp/local-llm-review-metadata.json
local-llm-review run --runtime bitnet \
  --executable /path/to/BitNet/build/bin/llama-completion \
  --model /path/to/ggml-model-i2_s.gguf \
  --model-id BitNet-b1.58-2B-4T \
  --temperature 0 --seed 42 --context 2048 --max-tokens 256 --threads 2 \
  --metadata /tmp/local-llm-review-metadata.json
local-llm-review setup
local-llm-review setup --download --confirm-network \
  --model-dir "$HOME/.cache/local-llm-review/models/BitNet-b1.58-2B-4T"
```

`run` is a filter: JSONL in on stdin, JSONL out on stdout, logs on stderr. It preserves input order and requires exactly one output object per input. It exits non-zero on duplicate ids, missing ids, malformed JSON, malformed model output, a missing or extra record, a non-zero runtime exit, or a timeout. On any of those failures it writes nothing to stdout.

Exit codes: `0` success, `1` protocol or runtime failure, `2` usage error or an unverified BitNet runtime.

## Contract

Input records contain at least `id`, `poolKey`, `sub`, `question`, `choices` (A–D), `correct`, `correctText`, `ref`, `figure`, and `source.editionId`, `source.revisionId`, `source.displayName`. `correctText` must equal `choices[correct]`. `figure` must be `false`. The India review manifest rejects figure-bearing questions, and this runner rejects `figure: true` before starting a runtime.

Each output record has exactly these keys (model record contract v3, Stage 8F2):

```json
{"id":"T2A01","syllabusRelevant":true,"indianTopic":"basic electronics","recommendation":"keep","jurisdictionRisk":"none","figureRightsWarning":"none","rationale":"...","syllabusCodes":["A.SEMICONDUCTORS"]}
```

`recommendation` is `keep`, `adapt`, `reject`, or `defer`. `jurisdictionRisk` is `none`, `low`, `medium`, or `high`. `figureRightsWarning` is `none` or `warning`. `syllabusRelevant` is a boolean. `indianTopic` and `rationale` are non-empty strings. `syllabusCodes` is an array of codes from the syllabus manifest passed with `--syllabus-manifest` (see "Evaluation status" above for the fail-closed rules). The prompt version is `india-review-prompt-v4`, the same template and sha256 as us-hamexam `tools/india-review/prompt-v4.txt`. That digest is `promptHash` in the metadata file.

The contract itself is pinned by the checked-in golden fixture `fixtures/model-record-contract-v3.json` (sorted key set, validation rules as data, an example manifest, one worked example record, and deliberately-broken variants with their expected errors). `tests/test_model_record_contract.py` always runs — it never skips on a missing sibling checkout — so CI detects contract drift independently; when the sibling checkout and node are present, the same file additionally asserts the example record passes us-hamexam's real `validateModelRecord`.

## Calling it from us-hamexam

The canonical pilot is one batch. The runner writes one metadata file for that sample, then us-hamexam reads the model JSONL. It does not call the runner once per candidate.

```sh
/path/to/local-llm-review-runner/bin/local-llm-review run \
  --runtime fixture \
  --metadata /tmp/local-llm-review-metadata.json \
  < /tmp/india-sample.jsonl > /tmp/india-model.jsonl

node scripts/review-cli.js pilot \
  --candidates /tmp/india-sample.jsonl \
  --sample 25 \
  --adapter fixture \
  --model-output /tmp/india-model.jsonl \
  --model local-llm-review-fixture \
  --model-path fixture \
  --out /tmp/india-pilot-report.json
```

`/tmp/india-sample.jsonl` is the 25 records under review. How to slice a larger extract, and why `--adapter command` is not this path, is in [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Repository layout

```
local-llm-review-runner/
├── bin/local-llm-review          # Entry point; no install required
├── src/local_llm_review/         # CLI, protocol, prompt, runtimes
│   └── prompts/                  # Versioned prompt template
├── tests/                        # unittest suite, stdlib only
├── fixtures/pilot-25.jsonl       # Synthetic 25-record pilot
├── fixtures/guard-record-golden.json  # Cross-repo guard-record shape pin
├── fixtures/model-record-contract-v3.json  # 8-key model record contract pin
├── docs/                         # Setup, security design, compatibility
├── AGENTS.md                     # Instructions for coding agents
├── CONTRIBUTING.md
├── SECURITY.md                   # How to report a vulnerability
├── AUTHORS.md
├── LICENSE                       # MIT
└── pyproject.toml                # Version 0.1.0, no dependencies
```

## Documentation

- [docs/SETUP.md](docs/SETUP.md) — Linux CPU build, optional GPU note, model location, compiler requirements, health checks, invocation
- [docs/SECURITY.md](docs/SECURITY.md) — untrusted candidate text, prompt injection, shell handling, output validation
- [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) — JSONL contract for us-hamexam Stage 8F2 (review manifest schemaVersion 3, model record contract v3)
- [AGENTS.md](AGENTS.md) — constraints for people and coding agents changing this tree
- [CONTRIBUTING.md](CONTRIBUTING.md) — tests and what must stay out of git
- [SECURITY.md](SECURITY.md) — vulnerability reports
- [AUTHORS.md](AUTHORS.md) — project maintainership

## Development

```sh
python3 -m unittest discover -s tests -v
```

The BitNet integration test runs only when `BITNET_EXECUTABLE` and `BITNET_MODEL` are set. Otherwise it skips and says why. Unit tests never download a model. Repeated fixture runs of the same input are byte-identical on stdout.

## Security

Candidate text is untrusted. The design notes are in [docs/SECURITY.md](docs/SECURITY.md). To report a vulnerability in this runner, use [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Copyright (c) 2026 vu2lid.
