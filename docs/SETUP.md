# Setup

The fixture runtime needs Python 3.10+ and nothing else. BitNet is optional and stays outside this git tree.

Observed from the upstream [microsoft/BitNet](https://github.com/microsoft/BitNet) README and `run_inference.py` on 2026-10-12. Re-check that tree before a real build. This runner does not vendor BitNet, llama.cpp, or weights.

## Linux CPU

Requirements from that README:

- Python >= 3.10
- CMake >= 3.22
- clang >= 18
- A C++ toolchain. Debian and Ubuntu can install clang from the LLVM apt script documented upstream.

Quantization types from the same README and `setup_env.py`:

| Architecture | Types |
| --- | --- |
| x86_64 | `i2_s`, `tl2` |
| arm64 / aarch64 | `i2_s`, `tl1` |

`i2_s` is the type used by the published BitNet-b1.58-2B-4T GGUF CPU path.

Build outline, run from a directory that is not this repository:

```sh
git clone --recursive https://github.com/microsoft/BitNet.git
cd BitNet
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Download and compile only when you mean to. The download step is the network step:

```sh
huggingface-cli download microsoft/BitNet-b1.58-2B-4T-gguf \
  --local-dir "$HOME/.cache/local-llm-review/models/BitNet-b1.58-2B-4T"
python setup_env.py \
  -md "$HOME/.cache/local-llm-review/models/BitNet-b1.58-2B-4T" \
  -q i2_s
```

Upstream `setup_env.py` compiles `build/bin/llama-cli` and expects the GGUF at:

```text
$HOME/.cache/local-llm-review/models/BitNet-b1.58-2B-4T/ggml-model-i2_s.gguf
```

Keep that file out of this repo. `.gitignore` ignores `*.gguf`, `*.safetensors`, `*.bin`, `*.pt`, and `models/`.

### Known build failures on a current checkout (observed 2026-10-12)

Re-checked against a BitNet checkout whose `3rdparty/llama.cpp` submodule pinned commit `390c307`. `setup_env.py`'s `compile()` step has no flag to work around either of these, so expect it to fail and finish with the manual `cmake` commands below:

- `CMake Error: ... unable to find a build program corresponding to "Unix Makefiles"`: a bare Ubuntu 24.04 image with clang and cmake installed ships `ninja` but not `make`, and cmake's default generator needs `make`. Install it (`apt-get install -y make`, or equivalent).
- `CMake Error ... UI: llama-ui-embed failed` / `missing required asset(s): loading.html`: the vendored llama.cpp always adds its `tools/ui` target when `-DLLAMA_BUILD_SERVER=ON` (regardless of `-DLLAMA_BUILD_UI`) and that target fetches a prebuilt web-UI bundle from a Hugging Face bucket. That fetch is unreliable here and the UI is not needed to run this project's runtime. Rebuild with `-DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF`, and if a prior attempt already left a partial download behind, remove `build/3rdparty/llama.cpp/tools/ui/dist` first.

Once `make` is installed, re-run the configure and build with the UI disabled:

```sh
cmake -B build -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ \
  -DLLAMA_BUILD_TOOLS=ON -DLLAMA_BUILD_EXAMPLES=ON -DLLAMA_BUILD_COMMON=ON \
  -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF
cmake --build build --config Release -j"$(nproc)"
```

[`docker/bitnet/Dockerfile`](../docker/bitnet/Dockerfile) in this repo reproduces that whole sequence from a clean `ubuntu:24.04` image, model weights excluded.

### llama-cli no longer works as a one-shot runtime; use llama-completion

The rest of this document (and the upstream README) assumes `run_inference.py` launches `build/bin/llama-cli`, which generates once and exits. On the `390c307` checkout, `llama-cli` instead always drops into an interactive chat REPL — with or without `-cnv`/`-no-cnv` — and only returns on EOF or a caller's timeout. Launching `run_inference.py` against that build makes every `local-llm-review run --runtime bitnet` record hang until `--timeout` kills it.

The same build's `llama-completion` binary is the one-shot replacement, and this project's bitnet adapter (`src/local_llm_review/runtimes/bitnet.py`) supports pointing `--executable` at it directly instead of at `run_inference.py`:

```sh
local-llm-review doctor --runtime bitnet \
  --executable "$HOME/.cache/local-llm-review/bitnet/build/bin/llama-completion" \
  --model "$HOME/.cache/local-llm-review/models/BitNet-b1.58-2B-4T/ggml-model-i2_s.gguf"
```

One caveat going the other way: `llama-completion` auto-enables conversation mode whenever the model carries a chat template (BitNet-b1.58-2B-4T does), and it crashes with an unhandled exception applying that template unless `-no-cnv`/`--no-conversation` is passed. The adapter already handles this: whenever the verified executable's help advertises `-no-cnv`/`--no-conversation`, it is always passed, with no corresponding `--no-conversation` CLI flag on `local-llm-review` itself to opt out. `doctor` reports this as a `limitation:` line, and `run`'s metadata records it in `settings.flagsPassed`.

If a future upstream checkout restores one-shot behavior on `llama-cli`, point `--executable` at `run_inference.py` again as before; the doctor check that verifies `build/bin/llama-cli` exists next to it is unchanged.

### Grammar-constrained decoding, and a model-capability verdict (observed 2026-10-13)

Unconstrained decoding of this project's full review prompt was not reliable on BitNet-b1.58-2B-4T: at `--temperature 0` it answered in prose instead of JSON, then looped into repeating fragments of the prompt instead of stopping. `llama-completion` supports `--json-schema` (grammar-constrained decoding), and when the verified executable advertises it, the adapter always passes a schema matching this project's exact output contract (`protocol.OUTPUT_KEYS` and its enums, with the candidate's own `id` pinned via the schema's `enum` so the grammar can't let a wrong id through). Two more wrinkles the adapter also handles automatically whenever advertised: `--no-display-prompt` (`llama-completion` otherwise echoes the full input prompt onto stdout before the answer, which breaks the one-object contract on its own), and a fixed-string strip of the literal `" [end of text]"` that `llama-completion` always appends after the content on a normal stop (hardcoded, no flag suppresses only that line). None of this needs a flag on `local-llm-review` itself; `doctor` reports each as a `limitation:` line, and `run`'s metadata lists the flags actually passed in `settings.flagsPassed`.

With all of that, `run --runtime bitnet` now completes end-to-end against BitNet-b1.58-2B-4T: every record returns a schema-exact object with the correct id. But the **content** is not usable: `indianTopic` and `rationale` come back as generic filler copied from the candidate's source metadata (e.g. `"rationale":"Synthetic pilot"`), not reasoning about the actual question. The same pipeline, same adapter, same decoding strategy, pointed at a conventional (non-1-bit) small instruct model instead — `Qwen2.5-1.5B-Instruct` GGUF, similar parameter count, same CPU-only / no-GPU resource tier as BitNet — produces real, specific, topically-correct rationale every time (e.g. "The question is about measuring current, which is a fundamental concept in electronics... does not depend on US-specific law or institutions").

**Verdict:** the BitNet runtime path in this runner is real infrastructure (reproducible build, correct plumbing, passes the strict JSONL contract end-to-end) but BitNet-b1.58-2B-4T itself is not yet a usable backend for this review task: runtime works, structured-output capability unconfirmed. Do not use its output for candidate decisions. The gap looks specific to this model/1-bit quantization rather than to "small local models can't do this" — a conventional small instruct model at the same resource tier clears the content-quality bar. Anyone adapting this runner for their own local backend should expect to pick the model, not just the runtime, with that in mind.

This runner can perform that download itself, and only when both flags are present:

```sh
local-llm-review setup --download --confirm-network \
  --model-dir "$HOME/.cache/local-llm-review/models/BitNet-b1.58-2B-4T" \
  --hf-repo microsoft/BitNet-b1.58-2B-4T-gguf
```

`local-llm-review setup` with no extra flags prints the toolchain notes and does not contact the network. `local-llm-review run` never downloads.

`run_inference.py` launches `./build/bin/llama-cli` relative to the process working directory. When `--executable` is named `run_inference.py`, this runner sets the child working directory to the script's directory unless you pass `--cwd`. `doctor` does not claim support for that script until `build/bin/llama-cli` exists and is non-empty in that working directory. A binary that sits next to the script does not count when `--cwd` points somewhere else.

`setup --download` refuses `--model-dir` when that path is inside this repository. Put weights under `$HOME/.cache/local-llm-review/models/` or another directory outside the clone.

## Optional GPU

Upstream ships a separate CUDA path under `gpu/` (`compile.sh`, `generate.py`, checkpoints converted from `microsoft/bitnet-b1.58-2B-4T-bf16`). That entry point uses different flags from `run_inference.py`. This runner does not claim GPU support.

If an installed executable's help text advertises `-ngl` or `--gpu-layers`, `run --runtime bitnet` passes `-ngl 0` (CPU) unless you set `--gpu-layers N`. If the help text does not advertise that flag, a request for `--gpu-layers` is refused and support is not claimed. For a GPU entry point whose help does not match the CPU flag set, use the command runtime and pass every argument yourself. That path does not claim BitNet support:

```sh
local-llm-review run --runtime command \
  --command /path/to/your-gpu-wrapper \
  --command-arg --some-flag \
  --metadata /tmp/local-llm-review-metadata.json
```

The command receives the rendered prompt on stdin. Its stdout must be exactly one JSON object.

## Health checks

```sh
local-llm-review doctor
local-llm-review doctor --runtime bitnet \
  --executable /path/to/BitNet/build/bin/llama-completion \
  --model /path/to/ggml-model-i2_s.gguf
```

(Use `--executable /path/to/BitNet/run_inference.py` instead on a checkout where upstream's `llama-cli` still exits after one completion; see the `llama-cli` vs. `llama-completion` note above for why the current one does not.)

Exit 0 and the line `support claimed: yes` mean the installed help text advertised every required flag (`model`, `prompt`, token limit, threads, context, temperature) and the model file exists. Exit 2 and `support claimed: no` mean it did not. `run --runtime bitnet` uses the same check and refuses to start when support is not claimed.

`doctor` does not generate tokens. A verified flag interface is not a claim that the runtime's stdout is clean JSON. `run_inference.py` inherits `llama-cli`'s stdout, and `llama-completion` writes its own stdout directly; either way, if that stream is not exactly one JSON object, the run fails closed and writes nothing to stdout.

The published `run_inference.py` help text does not include a seed flag; `llama-completion --help` does. Metadata records whichever is true for the verified executable in `settings.seedApplied`. Temperature 0 is passed only as `--temperature` or `-temp` when one of those tokens is actually in the help text. `-cnv` / `--conversation` is never passed; `-no-cnv` / `--no-conversation` is always passed when the help advertises it, regardless of what you ask for.

## Invocation

Fixture, no download:

```sh
bin/local-llm-review run --runtime fixture \
  --metadata /tmp/local-llm-review-metadata.json \
  < fixtures/pilot-25.jsonl > /tmp/pilot-model.jsonl
```

BitNet, after `doctor` prints `support claimed: yes`:

```sh
bin/local-llm-review run --runtime bitnet \
  --executable /path/to/BitNet/build/bin/llama-completion \
  --model /path/to/ggml-model-i2_s.gguf \
  --model-id BitNet-b1.58-2B-4T \
  --model-path-label /path/to/ggml-model-i2_s.gguf \
  --temperature 0 \
  --seed 42 \
  --context 2048 \
  --max-tokens 256 \
  --threads 2 \
  --timeout 600 \
  --metadata /tmp/local-llm-review-metadata.json \
  < /tmp/india-candidates.jsonl > /tmp/india-model.jsonl
```

`--model-id` defaults to the model file name. `--model-path-label` defaults to the `--model` string you typed. The child receives an absolute model path.

Exit codes: `0` success, `1` protocol or runtime failure (including timeout and malformed output), `2` usage error or BitNet support not claimed.

Per-record timeout defaults to 600 seconds. The child is started in its own session and killed on timeout. Model stdout is capped at 65536 bytes (`--max-output-bytes`).
