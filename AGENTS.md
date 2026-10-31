# Agent guide for local-llm-review-runner

Instructions for coding agents and human contributors. Read this file before changing the runner. The public behavior is specified in [README.md](README.md), [docs/SETUP.md](docs/SETUP.md), [docs/SECURITY.md](docs/SECURITY.md), and [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Purpose

Provide a reusable, offline command-line runner that accepts candidate JSONL and emits strictly validated classification JSONL. The first target runtime is Microsoft BitNet b1.58 2B 4T. The design must keep room for other local runtimes.

This repository is standalone. Do not import `us-hamexam`, do not add it as a dependency, and do not edit that checkout as part of work here. Compatibility is by the JSONL contract in [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Layout

```
bin/local-llm-review                 # inserts src/ on sys.path and calls cli.main
src/local_llm_review/
  cli.py                             # doctor, run, setup
  protocol.py                        # input and output validation, JSONL parse, syllabus-manifest load
  prompt.py                          # template load, sha256, render
  prompts/india-review-prompt-v4.txt  # byte copy of us-hamexam prompt-v4.txt
  runner.py                          # parse first, then runtime; fail closed
  jurisdiction_guard.py              # deterministic pre-runtime US-jurisdiction guard
  metadata.py                        # separate metadata JSON file
  process.py                         # argv subprocess, no shell, timeout kill
  doctor.py                          # support claimed only after verification
  setup_cmd.py                       # offline notes; download is explicit
  runtimes/fixture.py                # deterministic, no model, no network
  runtimes/bitnet.py                 # flags taken from verified help text
  runtimes/command.py                # explicit argv; prompt on stdin
tests/                               # python3 -m unittest discover -s tests
fixtures/pilot-25.jsonl              # synthetic records only
fixtures/guard-record-golden.json    # pins the guard-record shape (conventionVersion 2)
fixtures/model-record-contract-v3.json  # pins the 8-key model record contract (CI drift detection)
```

## Invariants

1. **Stdlib only.** Runtime and tests use the Python 3.10+ standard library. Do not add a third-party dependency.
2. **No network during inference.** `run` and `doctor` must not download, import an HTTP client, or call Hugging Face. The only built-in networked path is `setup --download` together with `--confirm-network`, and that path must refuse a model directory inside this repository. A caller-supplied command runtime may be a program that uses the network; do not add network calls to the runner to support it.
3. **No shell.** Child processes use an argv list. `shell=True` and `os.system` are not allowed. Candidate text is never interpolated into a command string.
4. **Fail closed.** Parse the full JSONL batch before starting a runtime. Buffer stdout until every record succeeds and, when `--metadata` is set, until that file is written. On duplicate ids, missing ids, malformed JSON, malformed model output, a missing or extra record, a non-zero runtime exit, or a timeout, write nothing to stdout and exit non-zero.
5. **One output per input, same order, same ids.** Output objects use exactly the eight keys in `protocol.OUTPUT_KEYS` (model record contract v3, Stage 8F2; the 8th is `syllabusCodes`). No markdown fence stripping. Duplicate JSON keys are rejected.
6. **Fixture stdout is byte-identical** across repeated runs of the same input. `elapsedMs` in metadata may differ. Do not echo candidate question text into fixture rationales.
7. **Do not claim BitNet support** unless `doctor` has verified the installed executable's own help, the model file, and, for `run_inference.py`, a non-empty `build/bin/llama-cli` in the child working directory (`--cwd`, or the script directory when `--cwd` is omitted). Do not invent CLI flags. Do not pass `-cnv` or `--conversation`. Pass `--seed` only when help advertises it. Record `seedApplied: false` otherwise.
8. **Nothing heavy in git.** No model weights, GGUF or other weight files, runtime binaries, credentials, or real or generated candidate exam banks. The committed pilot fixture stays synthetic, with `figure: false`. Reject `figure: true` before a runtime starts. The India manifest requires `figure: false`.
9. **Prompt hash is the sha256 of the template file bytes.** The file is LF-only and contains `__CANDIDATE_JSON__` (prompt-v4 names it once in a header note in addition to the real substitution site; every occurrence is substituted). If a candidate contains that placeholder, refuse substitution. A prompt edit changes the hash and must keep the version string honest.
10. **Syllabus codes fail closed.** Model-suggested `syllabusCodes` are validated only against an explicit manifest from `run --syllabus-manifest <path>` (minimal schema: top-level object, `topics` array, each topic a unique non-empty `code` plus a `title`). Per record: entries must be unique non-empty strings, `syllabusRelevant: true` requires at least one code, a non-empty list with `syllabusRelevant: false` is contradictory, and unknown codes are rejected naming the code and the manifest path. A record carrying codes when no manifest was provided fails the run (empty stdout, non-zero). The one exception is the fixture runtime, a development double whose records draw from its own pinned built-in example code set (`runtimes/fixture.py`); fixture stdout stays byte-identical across repeated runs.
10. **Advisory only.** Prompt text and fixture rationales must not claim official ASOC status or approve publication. Model output is advisory and never overrides the deterministic jurisdiction guard: when the guard flags a candidate, the runtime is not invoked for that record (fixture exempt) and the guard's own `reject`/`high` record is emitted; `validate_model_record` also fails closed on any `jurisdictionRisk: "high"` + `recommendation: "keep"` pair. The guard rules mirror us-hamexam `scripts/jurisdiction-guard.js`; keep both in sync by hand.

Exit codes: `0` success, `1` protocol or runtime failure (`ProtocolError`, `RuntimeFailed`, `RuntimeTimeout`), `2` usage or unverified BitNet (`UsageError`, `BitNetUnavailable`).

## Commands

```sh
bin/local-llm-review doctor
bin/local-llm-review run --runtime fixture \
  --metadata /tmp/local-llm-review-metadata.json \
  < fixtures/pilot-25.jsonl > /tmp/pilot-model.jsonl
python3 -m unittest discover -s tests -v
```

Run the suite from the repository root. Tests must pass without `BITNET_EXECUTABLE` or `BITNET_MODEL`. The integration test in `tests/test_bitnet_integration.py` skips unless both are set, and the skip message must stay explicit. Unit tests that spawn the CLI clear those variables so a developer machine does not accidentally hit a real model.

Optional: if `../us-hamexam/scripts/review-pipeline.js` or `US_HAMEXAM_ROOT` is present, `tests/test_manifest_compatibility.py` checks `createManifest` and `validateManifest`. That test must skip with a clear reason when the sibling checkout or `node` is absent. Do not vendor `us-hamexam`.

## Changing the prompt

`src/local_llm_review/prompts/india-review-prompt-v4.txt` must stay a byte-for-byte copy of us-hamexam `tools/india-review/prompt-v4.txt`. `PROMPT_VERSION` is `india-review-prompt-v4`. The sha256 of that file is the shared `promptHash`.

Do not reword the template only in this repository. When both trees change together:

1. Keep a single `__CANDIDATE_JSON__` placeholder and a trailing newline. No CR characters.
2. Bump `PROMPT_VERSION` when the instructions change. Do not reuse a version string for different bytes.
3. Update `tests/test_prompt_hash.py` so it checks the new file bytes. The hash is computed from the file, and the sibling comparison must still pass when that checkout is present.

## Adding a runtime

Add a module under `src/local_llm_review/runtimes/` with `complete(...)` and `info()`. Wire it through `cli.py` only with explicit user-supplied paths. A new runtime must:

- take the rendered prompt by an explicit channel (stdin or one verified argv element)
- return one text record for `parse_model_output`
- set `support_claimed` only after a real health check, following `doctor.py`
- stay silent on the network
- leave fixture behavior and its stdout bytes unchanged

Do not special-case flags copied from an unverified README. The BitNet adapter's candidate flags are comments about upstream `run_inference.py` as read on 2026-10-12. Re-read the installed help before treating them as current.

## Tests to keep

When you change validation, accounting, or process control, extend the existing tests rather than weakening them:

- input validation, including duplicate keys, missing ids, and line and batch caps
- output validation, including fences, trailing prose, enums, syllabusCodes rules (duplicates, unknown codes, manifest fail-closed, relevant/code contradictions), and id mismatch
- duplicate, missing, and extra records, with empty stdout
- timeout and non-zero exit, including process-group kill
- fixture end-to-end and byte-identical repeated runs
- prompt-hash determinism
- metadata keys and failure counts (`outputCount` 0 and `failureCount` 1 when nothing is emitted)
- the 25-record pilot
- the no-network fixture test
- BitNet adapter tests that use a fake runtime, plus the skipped integration test

A malformed or incomplete model response must still fail the run. Do not strip markdown fences to "make the model work."

## Review checklist

- `python3 -m unittest discover -s tests -v` from a clean environment with BitNet variables unset.
- `bin/local-llm-review doctor` prints `support claimed: no` when no runtime path is configured.
- `git status` shows no `*.gguf`, `*.safetensors`, `*.bin`, `*.pt`, `*.onnx`, credential files, or copied exam banks.
- Docs that name a command still match `cli.py`.
- `us-hamexam` was not modified unless the task explicitly asked for a command-path or documentation pointer in that repo.
