#!/usr/bin/env bash
# Build the open-source pieces from scratch. Everything lands in this folder.
set -euo pipefail

cd "$(dirname "$0")"

MODEL_URL="${SLOTH_MODEL_URL:-https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true}"
LLAMA_REPO="${SLOTH_LLAMA_REPO:-https://github.com/ggml-org/llama.cpp}"

say() { printf "\n\033[38;5;65m  %s\033[0m\n" "$1"; }

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.9+ is required." >&2
  exit 1
fi

if ! command -v cmake >/dev/null 2>&1; then
  if [ ! -d .venv ]; then
    say "Creating a small Python environment for cmake."
    python3 -m venv .venv
  fi
  say "Fetching cmake (build tool only)."
  .venv/bin/pip install -q --upgrade pip cmake
  CMAKE=".venv/bin/cmake"
else
  CMAKE="cmake"
fi

if [ ! -d vendor/llama.cpp ]; then
  say "Cloning llama.cpp (open-source inference engine)."
  git clone --depth 1 "$LLAMA_REPO" vendor/llama.cpp
fi

if [ ! -x vendor/llama.cpp/build/bin/llama-server ]; then
  say "Compiling llama.cpp. This is the slow part. Make tea."
  "$CMAKE" -B vendor/llama.cpp/build -S vendor/llama.cpp \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_METAL=ON \
    -DLLAMA_CURL=OFF \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=OFF \
    -DLLAMA_BUILD_SERVER=ON > .cache/build.log 2>&1
  "$CMAKE" --build vendor/llama.cpp/build -j "$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)" \
    --target llama-server >> .cache/build.log 2>&1
fi

if [ ! -s models/qwen2.5-1.5b-instruct-q4_k_m.gguf ]; then
  say "Fetching Qwen2.5-1.5B-Instruct (Apache-2.0, open weights). ~1 GB."
  mkdir -p models .cache
  curl -L --fail --retry 3 -C - -o models/qwen2.5-1.5b-instruct-q4_k_m.gguf "$MODEL_URL"
fi

say "Creating a demo folder to practise on."
python3 demo/make_demo.py --force >/dev/null

say "Checking the local pieces."
python3 sloth.py doctor

cat <<'EOF'

  You are ready. Try:

    ./sloth scan            # dry run on the demo folder
    ./sloth ui --open       # the calm dashboard
    ./sloth scan ~/Downloads
    ./sloth night --once --apply   # tidy now, without asking

  No account. No API key. No internet at runtime.

EOF
