# Security

Vulnerability reports go to the repository [security policy](../SECURITY.md). This document is the design: what the runner does with untrusted input.

Candidate text is untrusted. A question or answer choice can contain instructions aimed at the model, shell metacharacters, or a second JSON document. The runner's job is to fail closed on structure. It does not decide that a schema-valid classification is true.

## Untrusted candidate text

The full candidate, including `correct` and `correctText`, is embedded in the prompt. That matches the Stage 8E candidate schema. Redact fields before piping if the local process must not see the answer key.

The rendered prompt is sent only to the selected local runtime:

- fixture: no subprocess; a fixed classifier reads the parsed object
- bitnet: the prompt is one argv element of the verified `--prompt` / `-p` flag, because that is the flag upstream `run_inference.py` advertises
- command: the prompt is the child process stdin

The prompt can appear in the process list for the BitNet path. Do not log it. This runner does not write the prompt to stderr.

Candidate lines are capped at 1_000_000 bytes. A batch is capped at 10_000 records. Model stdout is capped (`--max-output-bytes`, default 65536) and must be valid UTF-8.

## Prompt injection

The template tells the model to return one JSON object and to refuse publication approval and official ASOC claims. A model can ignore that. Validation does not detect a persuasive but wrong `keep`.

What validation does enforce, for every record:

- exactly one JSON value, no markdown fence, no trailing prose, no second object
- no duplicate keys
- exactly the seven output keys
- `id` equal to the candidate id
- `syllabusRelevant` a boolean
- `recommendation` one of `keep`, `adapt`, `reject`, `defer`
- `jurisdictionRisk` one of `none`, `low`, `medium`, `high`
- `figureRightsWarning` one of `none`, `warning`
- `indianTopic` and `rationale` non-empty strings

Anything else fails the whole run. Stdout stays empty, so a caller that only keeps a successful exit cannot accept a partial stream.

The fixture classifier does not follow instructions inside the question. It matches a fixed phrase list. That is a development double, not a claim that BitNet will do the same.

If the candidate JSON contains the literal placeholder `__CANDIDATE_JSON__`, substitution is refused. The template is required to contain that placeholder exactly once. The prompt hash is the sha256 of the template file bytes.

## Shell command handling

Inference does not use a shell. `subprocess` is called with an argv list and `shell` left at its default false. Candidate text is never interpolated into a command string.

`--command` is a path to an executable file (or a Python script). Each `--command-arg` is one argv element, including a value that starts with `-` (`--command-arg --literal` and `--command-arg=--literal` are the same element). There is no combined command string.

BitNet flags are appended only after `doctor` sees them in the installed help text. Unknown flags are not guessed. `-cnv` and `--conversation` are never passed.

On timeout the child session is killed with `SIGKILL`. A non-zero child status fails the run. The child's stderr is copied into the runner's stderr, truncated, and is not parsed as JSON.

`setup --download` is the only built-in path that may use the network, and only with `--confirm-network`. It execs `huggingface-cli` or `hf` with an argv list and refuses a destination inside this repository. `run` and `doctor` do not call it. A `--runtime command` child is a program you named. This runner does not give it a network client, and it does not stop that program from contacting the network.

us-hamexam's pilot command adapter launches its command string with a shell. The documented command in [COMPATIBILITY.md](COMPATIBILITY.md) is a fixed quoted path. Do not build that string from candidate text.

## Output validation

Stdout is buffered until every input record has one validated output. The emitted lines use a fixed key order and compact JSON so repeated fixture runs are byte-identical. Metadata (`runnerVersion`, prompt hash, counts, settings) is written only to the `--metadata` file. It is not mixed into the JSONL stream.

A successful exit means the id sequence matches the input and every record passed the schema. It does not mean a human approved the question, that figure rights are clear, or that the text is an official ASOC item. The schema cannot force a model to tell the truth, so a person still reviews every record. `figure: true` is rejected before a runtime starts, because this India workflow only reviews figureless candidates. `figureRightsWarning: warning` on an accepted record is a human warning, not a clearance.
