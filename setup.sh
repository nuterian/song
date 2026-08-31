#!/usr/bin/env bash
# Creates .venv on Python 3.12 and installs the stack.
#
# Two packages need special handling:
#   openai-whisper - its setup.py imports pkg_resources, which setuptools >= 81
#                    no longer ships, so it is built with --no-build-isolation
#                    against the pinned setuptools below.
#   demucs         - declares torchaudio<2.1, which is stale; installed with
#                    --no-deps and its real runtime deps listed in requirements.
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-$HOME/.pyenv/versions/3.12.7/bin/python3.12}"
PIP="./.venv/bin/pip"

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi

# Pull the pinned spec for a package out of requirements.txt.
req() { grep -E "^$1==" requirements.txt; }

echo "== build tools =="
./.venv/bin/python -m pip install --upgrade pip
$PIP install "setuptools<81" "wheel"

echo "== numeric + torch =="
$PIP install "$(req numpy)" "$(req torch)" "$(req torchaudio)"

echo "== openai-whisper (no build isolation) =="
$PIP install --no-build-isolation "$(req openai-whisper)"

echo "== remaining deps =="
grep -vE '^(#|$)|^(numpy|torch|torchaudio|openai-whisper|demucs)==' requirements.txt \
  | xargs $PIP install

echo "== demucs (no deps) =="
$PIP install --no-deps "$(req demucs)"

echo "== smoke test =="
./.venv/bin/python - <<'EOF'
import torch, torchaudio, whisper, stable_whisper, librosa, faster_whisper
import demucs.pretrained
print("torch", torch.__version__, "| torchaudio", torchaudio.__version__)
print("mps available:", torch.backends.mps.is_available())
print("MMS_FA bundle:", hasattr(torchaudio.pipelines, "MMS_FA"))
print("forced_align:", hasattr(torchaudio.functional, "forced_align"))
print("imports OK")
EOF
