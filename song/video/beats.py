"""Tempo, beat times and downbeats, cached beside the analysis payload.

Kept out of `song.analysis` on purpose: that payload is built on every open of
the review UI and has to stay fast, and nothing in the UI draws a beat grid.
This is only wanted when something is being rendered, and it costs a few
seconds, so it is computed on demand and cached the same way.
"""

from __future__ import annotations

import json
from pathlib import Path

import librosa
import numpy as np

from ..audio import load_mono

# Beat tracking wants the drums, and librosa's own default rate is plenty for
# an onset envelope - the alignment models' 16 kHz would only be slower here.
SR = 22050
HOP = 512

# Nothing in librosa tracks downbeats, so bar starts are inferred by assuming
# 4/4 and taking the beat phase with the strongest accents. Wrong metre gives a
# bar pulse that is merely regular rather than musical, which is a much smaller
# failure than not having one.
METER = 4


def _downbeat_phase(beat_frames: np.ndarray, onset_env: np.ndarray) -> int:
    """Which of the METER beat positions carries the accents."""
    strength = onset_env[np.clip(beat_frames, 0, len(onset_env) - 1)]
    totals = [float(strength[phase::METER].sum()) for phase in range(METER)]
    return int(np.argmax(totals))


def build(
    audio_path: Path | str, workdir: Path | str, force: bool = False
) -> dict:
    workdir = Path(workdir)
    cache = workdir / "beats.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text())

    samples, sr = load_mono(audio_path, SR)
    onset_env = librosa.onset.onset_strength(y=samples, sr=sr, hop_length=HOP)
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr, hop_length=HOP, trim=False
    )
    phase = _downbeat_phase(beat_frames, onset_env)
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=HOP)

    data = {
        "tempo": round(float(np.atleast_1d(tempo)[0]), 2),
        "meter": METER,
        "phase": phase,
        # The tracked beats themselves, not a grid synthesized from the tempo.
        # A grid is right for eight bars and then slides: this track measures
        # 123 BPM but no AI render holds a click exactly, and by the last chorus
        # a fixed grid is visibly ahead of the snare.
        "beats": np.round(beats, 3).tolist(),
        "downbeats": np.round(beats[phase::METER], 3).tolist(),
    }

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data
