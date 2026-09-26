#!/usr/bin/env bash
# Builds both virtualenvs on Python 3.12, then offers to fetch the models.
#
#   ./setup.sh               build .venv and visuals/.venv, then ask once about the models
#   ./setup.sh --yes         the same, fetching the models without asking
#   ./setup.sh --no-models   stop before the models; each downloads on first use instead
#
# .venv is the song tool's (torch 2.5.1, Whisper, Demucs) and visuals/.venv is the
# video's (torch 2.6, transformers, moderngl). They are separate because the two need
# different torch versions; the video runs Demucs from .venv.
#
# Python 3.12 comes from $PYTHON if set, else pyenv's 3.12.7, else python3.12 on PATH.
#
# Two packages in .venv need special handling:
#   openai-whisper - its setup.py imports pkg_resources, which setuptools >= 81
#                    no longer ships, so it is built with --no-build-isolation
#                    against the pinned setuptools below.
#   demucs         - declares torchaudio<2.1, which is stale; installed with
#                    --no-deps and its real runtime deps listed in requirements.
set -euo pipefail

cd "$(dirname "$0")"

MODELS=ask
for arg in "$@"; do
  case "$arg" in
    --yes) MODELS=yes ;;
    --no-models) MODELS=no ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see ./setup.sh --help)" >&2; exit 2 ;;
  esac
done

PY="${PYTHON:-}"
if [ -z "$PY" ] && [ -x "$HOME/.pyenv/versions/3.12.7/bin/python3.12" ]; then
  PY="$HOME/.pyenv/versions/3.12.7/bin/python3.12"
fi
PY="${PY:-$(command -v python3.12 || true)}"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>/dev/null; then
  echo "Python 3.12 is needed: install it (pyenv install 3.12.7, or brew install python@3.12)" >&2
  echo "or name one with PYTHON=/path/to/python3.12 ./setup.sh" >&2
  exit 1
fi
echo "python: $PY ($("$PY" -c 'import platform; print(platform.python_version())'))"

# ------------------------------------------------------------------ .venv: the song tool

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

# ------------------------------------------------------------ visuals/.venv: the video

# Every package the video imports is pinned in its requirements, numpy with them, so
# one resolve installs the set it was built and tested with.
if [ ! -d visuals/.venv ]; then
  "$PY" -m venv visuals/.venv
fi

echo "== visuals/.venv =="
visuals/.venv/bin/python -m pip install --upgrade pip
visuals/.venv/bin/python -m pip install -r visuals/requirements.txt

echo "== smoke test =="
visuals/.venv/bin/python - <<'EOF'
import moderngl, onnxruntime, torch, transformers
import beat_this, librosa, lv_chordia, scipy, soundfile, swift_f0
print("torch", torch.__version__, "| transformers", transformers.__version__)
ctx = moderngl.create_standalone_context(require=330)
print("GL:", ctx.info["GL_VERSION"])
ctx.release()
print("imports OK")
EOF

# ---------------------------------------------------------------------- the models

# Where each one lands, to add them up at the end. The names are the libraries' own.
weights() {
  visuals/.venv/bin/python - <<'EOF'
import os
from pathlib import Path

import torch
from huggingface_hub import constants

hub, ckpt = Path(constants.HF_HUB_CACHE), Path(torch.hub.get_dir()) / "checkpoints"
whisper = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache")) / "whisper"
paths = [hub / "models--laion--larger_clap_music", hub / "models--sentence-transformers--all-MiniLM-L6-v2",
         ckpt / "beat_this-final0.ckpt", Path("visuals/cache/models/nmp.onnx"), ckpt / "955717e8-8726e21a.th",
         ckpt / "model.pt", whisper / "medium.pt", whisper / "large-v3-turbo.pt",
         hub / "models--Systran--faster-whisper-medium"]

def size(p):     # a Hugging Face snapshot is symlinks into blobs/: count each file once
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())


have = [size(p) for p in paths if p.exists()]
print(f"{sum(have) / 1e9:.1f} GB, {len(have)} of {len(paths)} models")
EOF
}

cat <<'EOF'

== models ==
Each is fetched by the library that runs it, to its usual cache (~/.cache/huggingface,
~/.cache/torch, ~/.cache/whisper; visuals/cache/models for basic-pitch). Without this
step each downloads the first time it is needed. Everything runs locally after.

  the video                     for                            licence       size
  laion/larger_clap_music       what each passage sounds like  Apache-2.0    1.6 GB
  all-MiniLM-L6-v2              what each lyric line is about  Apache-2.0     92 MB
  Beat This! (final0)           beats and downbeats            MIT            81 MB
  basic-pitch (nmp.onnx)        notes                          Apache-2.0    0.2 MB
  Demucs htdemucs               the four stems (both tools)    MIT            84 MB

  the song tool (lyrics)
  wav2vec2 MMS_FA (torchaudio)  the alignment's structure      CC-BY-NC-4.0  1.3 GB
  Whisper medium                aligning within each section   MIT           1.5 GB
  Whisper large-v3-turbo        re-aligning weak sections      MIT           1.6 GB
  faster-whisper medium         the blind transcription        MIT           1.5 GB

  in all about 7.8 GB. SwiftF0, lv-chordia and Silero VAD (all MIT) ship in their wheels.
  MMS_FA's licence is non-commercial: see the README.
EOF

if [ "$MODELS" = ask ]; then
  if [ -t 0 ]; then
    read -r -p "Fetch them now? [y/N] " answer
    case "$answer" in [yY]*) MODELS=yes ;; *) MODELS=no ;; esac
  else
    echo "not asked (no terminal); ./setup.sh --yes fetches them"
    MODELS=no
  fi
fi

if [ "$MODELS" = yes ]; then
  echo "== fetching the video's models =="
  visuals/.venv/bin/python - <<'EOF'
# Each through the call the video makes, on a moment of silence, so the names and
# places are the ones it will look for.
import numpy as np

from visuals.pieces.gravity import MODELS, grid, models

print("basic-pitch:", models.basic_pitch_model(MODELS))
grid.tracked_beats(np.zeros(4 * 22050, np.float32), 22050)
print("Beat This!: ok")
models.text_similarity(["light"], ["dark"])
print("all-MiniLM-L6-v2: ok")
models.clap_scores(np.zeros(2 * 48000, np.float32), 48000, [(0.0, 2.0)], ["quiet"])
print("larger_clap_music: ok")
EOF

  echo "== fetching the song tool's models, and Demucs =="
  ./.venv/bin/python - <<'EOF'
# The same loaders alignment uses, with its default choices; each is let go once loaded.
import demucs.pretrained

from song.align import ctc, pipeline, roundtrip, whisper

cfg = pipeline.Config()
demucs.pretrained.get_model(cfg.demucs_model)
print(f"Demucs {cfg.demucs_model}: ok")
ctc._load_bundle(cfg.device)
ctc._BUNDLE_CACHE.clear()
print("MMS_FA: ok")
for name in (cfg.whisper_model, cfg.whisper_model_retry):
    whisper.load_aligner(name, cfg.device)
    whisper._MODEL_CACHE.clear()
    print(f"Whisper {name}: ok")
roundtrip._load(cfg.roundtrip_model, cfg.device)
roundtrip._MODEL_CACHE.clear()
print(f"faster-whisper {cfg.roundtrip_model}: ok")
EOF
fi

# ---------------------------------------------------------------------- summary

echo
echo "== done in $((SECONDS / 60)) min $((SECONDS % 60)) s =="
echo "  .venv          $(du -sh .venv | cut -f1)  the song tool"
echo "  visuals/.venv  $(du -sh visuals/.venv | cut -f1)  the video"
echo "  model weights  $(weights)"
if command -v ffmpeg >/dev/null; then
  echo "  ffmpeg         $(command -v ffmpeg)"
else
  echo "  ffmpeg         missing, and both tools need it: brew install ffmpeg"
fi
cat <<'EOF'

  ./.venv/bin/python -m song                               align lyrics: http://127.0.0.1:8420
  visuals/.venv/bin/python -m visuals studio <song file>   the video: http://127.0.0.1:8777
EOF
