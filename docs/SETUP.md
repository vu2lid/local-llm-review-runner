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
  --executable /path/to/BitNet/run_inference.py \
  --model /path/to/ggml-model-i2_s.gguf
```

Exit 0 and the line `support claimed: yes` mean the installed help text advertised every required flag (`model`, `prompt`, token limit, threads, context, temperature) and the model file exists. Exit 2 and `support claimed: no` mean it did not. `run --runtime bitnet` uses the same check and refuses to start when support is not claimed.

`doctor` does not generate tokens. A verified flag interface is not a claim that llama-cli's stdout is clean JSON. Upstream `run_inference.py` inherits llama-cli's stdout. If that stream is not exactly one JSON object, the run fails closed and writes nothing to stdout.

The published `run_inference.py` help text does not include a seed flag. Metadata still records the requested seed, with `settings.seedApplied: false`. Temperature 0 is passed only as `--temperature` or `-temp` when one of those tokens is actually in the help text. `-cnv` / `--conversation` is never passed.

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
  --executable /path/to/BitNet/run_inference.py \
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
