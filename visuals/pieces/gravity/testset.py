"""Test songs made from real ones by taking parts away, so the truth is known.

Nothing is downloaded. Each is a song already separated here, remixed from its own
Demucs stems without some of them - Gravity with no drums still has Gravity's grid,
its bass line and its voice, so what casting and the grid make of it can be checked
against the whole song. Written to visuals/cache/testset/<name>.wav (ignored by git).

    python -m visuals.pieces.gravity.testset            make them all
    python -m visuals make visuals/cache/testset/<name>.wav
"""

from __future__ import annotations

import sys

import numpy as np
import soundfile as sf

from . import ROOT
from .track import GRAVITY_AUDIO, Track

DIR = ROOT / "visuals" / "cache" / "testset"

# name: (the song it comes from, the stems kept)
DERIVED = {
    "gravity-no-drums": (GRAVITY_AUDIO, ("bass", "other", "vocals")),
    "tidal-core-no-drums-no-bass": (None, ("other", "vocals")),        # needs TIDAL CORE's stems
}


def source(name: str) -> Track:
    src, _ = DERIVED[name]
    if src is not None:
        return Track.resolve(src)
    return Track("tidal-core", ROOT / "visuals" / "cache" / "tidal-core" / "audio.wav")


def make(name: str) -> None:
    tr = source(name)
    keep = DERIVED[name][1]
    if not all((tr.stems_dir / f"{s}.wav").exists() for s in keep):
        raise SystemExit(f"{name}: no stems for {tr.slug} yet; run `python -m visuals make` on it first")
    parts = [sf.read(str(tr.stems_dir / f"{s}.wav"), always_2d=True) for s in keep]
    sr = parts[0][1]
    mix = np.sum([p[0] for p in parts], axis=0)
    peak = float(np.abs(mix).max())
    DIR.mkdir(parents=True, exist_ok=True)
    out = DIR / f"{name}.wav"
    sf.write(str(out), mix / max(peak / 0.98, 1.0), sr, subtype="PCM_16")
    print(f"{out.relative_to(ROOT)}: {tr.slug} with only {', '.join(keep)}")


if __name__ == "__main__":
    for n in (sys.argv[1:] or DERIVED):
        make(n)
