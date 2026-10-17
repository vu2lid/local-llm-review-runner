# Compatibility with us-hamexam Stage 8E1/8E2

This runner does not import `us-hamexam` and does not write into it. The JSONL below is the contract `scripts/review-pipeline.js` enforces in `validateCandidate`, `validateModelRecord`, and `createManifest` for schemaVersion 2. Field names here match that code as reviewed on 2026-10-12.

us-hamexam stays unchanged until someone later points its command path or docs at this runner.

## Candidate JSONL (input)

One JSON object per line. Blank lines are ignored. Lines are split on LF, and one trailing CR is removed, which is the same boundary us-hamexam uses (`/\r?\n/`). A U+2028 or U+2029 inside a JSON string stays inside that record. These keys are required:

| Key | Rule |
| --- | --- |
| `id` | non-empty string, unique in the batch |
| `poolKey`, `sub`, `question` | non-empty strings |
| `choices` | object with non-empty strings `A`, `B`, `C`, `D` |
| `correct` | `A`, `B`, `C`, or `D` |
| `correctText` | must equal `choices[correct]` byte for byte |
| `ref` | string, may be empty |
| `figure` | must be `false`. Extraction already drops figure-bearing questions, and `createManifest` rejects any other value. This runner rejects `figure: true` before a runtime starts and writes no stdout |
| `source.editionId`, `source.revisionId`, `source.displayName` | non-empty strings |

Extra top-level keys are accepted by this runner. us-hamexam also sends `source.element`. The 25-record file in `fixtures/pilot-25.jsonl` is synthetic and uses `figure: false`.

`figureRightsWarning` on the model output is still `none` or `warning`. A warning means a figureless question may need an illustration. It is not a rights clearance, and it does not accept a `figure: true` input.

Duplicate ids, a missing id, malformed JSON, and `figure: true` fail the run before any runtime is started.

## Model JSONL (output)

Exactly one object per input, same order, same ids. `validateModelRecord` requires this key set and no others:

| Key | Rule |
| --- | --- |
| `id` | same string as the candidate |
| `syllabusRelevant` | boolean |
| `indianTopic` | non-empty string |
| `recommendation` | `keep`, `adapt`, `reject`, or `defer` |
| `jurisdictionRisk` | `none`, `low`, `medium`, or `high` |
| `figureRightsWarning` | `none` or `warning` |
| `rationale` | non-empty string |

`createManifest` also rejects duplicate output ids and a set of ids that does not cover the candidates exactly (missing or extra records). This runner fails closed on those cases and writes no stdout, so a partial file cannot be mistaken for a manifest input.

Human decisions remain `pending` until a person acts in the us-hamexam review UI. Nothing in this output approves a question for publication or claims official ASOC status.

## The command us-hamexam should call

Canonical pilot. One runner process reads the sample and writes one metadata file. us-hamexam then reads that model JSONL. It does not spawn the runner once per question.

`review-cli.js pilot --sample 25` takes the first 25 non-blank lines of `--candidates`, in file order. Point `--candidates` at the same sample the runner just classified so the metadata counts and the pilot sample are the same 25 records.

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

To cut that sample out of a larger extract, keep non-blank lines and take the first 25. That matches the pilot slice:

```sh
python3 -c 'from pathlib import Path; src, dst = Path("/tmp/india-candidates.jsonl"), Path("/tmp/india-sample.jsonl"); lines=[ln for ln in src.read_text(encoding="utf-8").splitlines() if ln.strip()]; dst.write_text("".join(ln+"\n" for ln in lines[:25]), encoding="utf-8")'
```

The same model JSONL can build a manifest without a pilot report:

```sh
node scripts/review-cli.js triage \
  --candidates /tmp/india-sample.jsonl \
  --model-output /tmp/india-model.jsonl \
  --adapter fixture \
  --model local-llm-review-fixture \
  --manifest /tmp/india-review.json
```

`pilot --adapter command` is not this integration. us-hamexam would invoke the quoted command once per candidate and overwrite `--metadata` on every call. Use the batch above when the metadata file must describe the sample.

Replace `--runtime fixture` with the BitNet invocation from [SETUP.md](SETUP.md) only after `doctor` prints `support claimed: yes`. Keep it as one batch so the metadata file is written once.

## Prompt hash

This runner's template is `india-review-prompt-v3` (`src/local_llm_review/prompts/india-review-prompt-v3.txt`). The file is a byte copy of us-hamexam `tools/india-review/prompt-v3.txt`. `promptHash` in the metadata file is the sha256 of those bytes, so it matches the `promptHash` us-hamexam stores on a manifest or pilot report from that same template.

Current digest: `278f86d7a8746fa86d49161ebff3844ae941f0162e68189a33518d078b599815`.

Do not reword the template in this repository alone. A prompt change has to land in both files and keep a single version string.

v3 is retained as EXPERIMENTAL, not claimed as an improvement: the 2026-10-14 Qwen2.5-1.5B pilot produced fabricated or self-contradictory rationales on 7 of 19 universal questions and 2 truncation failures. Separately, the deterministic jurisdiction guard in this runner fires before any runtime invocation for non-fixture runtimes and its `reject`/`high` record is emitted without consulting the model, so model output stays advisory and can never override a guard rejection; the runner's strict validator also rejects any model record pairing `jurisdictionRisk: "high"` with `recommendation: "keep"`.

## Metadata

Written only to `--metadata`, never to stdout:

```json
{
  "runnerVersion": "0.1.0",
  "runtime": "fixture",
  "modelId": "fixture",
  "modelPathLabel": "fixture",
  "promptVersion": "india-review-prompt-v3",
  "promptHash": "<sha256 of the template file>",
  "settings": {},
  "inputCount": 25,
  "outputCount": 25,
  "failureCount": 0,
  "elapsedMs": 0
}
```

`settings` holds temperature, seed, context length, token limit, threads, timeout, whether the seed flag was actually passed, the flags that were passed, and `supportClaimed`. For the fixture, `supportClaimed` is false because the fixture is not BitNet. For a BitNet run that was allowed to start, `supportClaimed` is true.

`outputCount` is the number of records written to stdout. A failed run emits nothing, so `outputCount` is 0 and `failureCount` is 1 even when `inputCount` is the size of the parsed batch.
