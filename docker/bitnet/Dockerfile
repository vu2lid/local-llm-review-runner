# Reproduces the BitNet b1.58 CPU build this project pilots as a local
# runtime. See ../../docs/SETUP.md for the equivalent bare-metal steps and
# for the known-issue notes this Dockerfile works around.
#
# Model weights are never baked into the image (this repo keeps weights out
# of git and keeps the model download an explicit, confirmed step). Mount
# or download the GGUF into /models at `docker run` time and point
# local-llm-review's --model at it.
#
# Build:
#   docker build -t bitnet-b158 docker/bitnet
# Run (model already downloaded to $HOME/.cache/local-llm-review/models/BitNet-b1.58-2B-4T):
#   docker run --rm -it -v "$HOME/.cache/local-llm-review/models:/models" bitnet-b158
#   # inside the container:
#   build/bin/llama-completion -m /models/BitNet-b1.58-2B-4T/ggml-model-i2_s.gguf \
#     -p "..." -n 256 -t 4 -c 2048 --temperature 0 --no-conversation

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# clang/cmake/python3 are upstream's documented requirements (docs/SETUP.md).
# make and ninja-build are not: a bare clang+cmake Ubuntu 24.04 image ships
# ninja but not make, and cmake's default generator is Unix Makefiles, so
# the configure step fails with "CMAKE_MAKE_PROGRAM is not set" without it.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates clang cmake make ninja-build \
        python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/bitnet
RUN git clone --recursive https://github.com/microsoft/BitNet.git .

RUN python3 -m venv .venv \
    && .venv/bin/pip install --no-cache-dir -r requirements.txt \
    && .venv/bin/pip install --no-cache-dir 3rdparty/llama.cpp/gguf-py

# Generate the TL2 lookup-table kernel header before compiling. This is the
# exact invocation setup_env.py's gen_code() runs for BitNet-b1.58-2B-4T on
# x86_64 (it maps that model to the "bitnet_b1_58-3B" kernel shape). We call
# it directly instead of going through setup_env.py, because that script's
# compile() step offers no way to pass the two cmake defines below and
# always fails on them (see next step).
RUN .venv/bin/python utils/codegen_tl2.py \
        --model bitnet_b1_58-3B --BM 160,320,320 --BK 96,96,96 --bm 32,32,32

# -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF: the vendored llama.cpp's
# tools/ui target always runs (tools/CMakeLists.txt adds it whenever
# LLAMA_BUILD_SERVER=ON, regardless of LLAMA_BUILD_UI) and by default tries
# to fetch a prebuilt web-UI bundle from an HF bucket. That fetch is flaky
# in this environment and unneeded for a backend pilot; these flags make
# the asset step skip straight to an empty placeholder instead of crashing
# the build on a missing/partial download.
RUN cmake -B build \
        -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ \
        -DLLAMA_BUILD_TOOLS=ON -DLLAMA_BUILD_EXAMPLES=ON -DLLAMA_BUILD_COMMON=ON \
        -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF \
    && cmake --build build --config Release -j"$(nproc)"

# llama-cli (the binary upstream's run_inference.py launches) no longer
# exits after one completion on this llama.cpp commit: it always drops into
# an interactive chat REPL and only returns on EOF or a caller's timeout.
# llama-completion is the one-shot replacement, but BitNet-b1.58-2B-4T
# carries a chat template that llama-completion auto-applies and crashes
# on unless -no-cnv is passed. Point local-llm-review's --executable at
# build/bin/llama-completion; the bitnet adapter (src/local_llm_review/
# runtimes/bitnet.py) always passes -no-cnv/--no-conversation on its own
# once it sees the installed executable advertise that flag.
ENTRYPOINT ["/bin/bash"]
