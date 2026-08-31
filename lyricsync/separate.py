"""Vocal isolation with Demucs.

Aligning against an isolated vocal stem rather than the full mix is the single
biggest accuracy win on dense, loud productions: the aligners stop locking onto
percussion transients and synth stabs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_MODEL = "htdemucs"


def separate_vocals(
    audio_path: Path | str,
    workdir: Path | str,
    model: str = DEFAULT_MODEL,
    device: str = "cpu",
    force: bool = False,
) -> Path:
    """Return the path to a cached vocals-only wav, running Demucs if needed."""
    audio_path = Path(audio_path)
    workdir = Path(workdir)
    stem_path = workdir / "vocals.wav"

    if stem_path.exists() and not force:
        return stem_path

    raw_out = workdir / "demucs_raw"
    raw_out.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems=vocals",
        "-n", model,
        "-d", device,
        "-o", str(raw_out),
        str(audio_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-12:]
        raise RuntimeError(
            "demucs failed (device=%s):\n%s" % (device, "\n".join(tail))
        )

    produced = sorted(raw_out.rglob("vocals.wav"))
    if not produced:
        raise RuntimeError(f"demucs produced no vocals.wav under {raw_out}")

    stem_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(produced[0], stem_path)

    # The nested demucs tree is large (both stems, full rate); the copy is enough.
    shutil.rmtree(raw_out, ignore_errors=True)
    return stem_path
