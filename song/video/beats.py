"""Tempo, beats, downbeats and a two-band split, cached beside the analysis.

Kept out of `song.analysis` on purpose: that payload is built on every open of
the review UI and has to stay fast, and nothing in the UI draws a beat grid or
a spectrum. This is only wanted when something is being rendered, and it costs a
few seconds, so it is computed on demand and cached the same way.

The bands are here rather than in analysis.json for the same reason. A kick and
a hi-hat are the same number in a peak envelope, which is why a picture driven
by peaks alone cannot tell you what kind of loud it is looking at.
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

# Where the split falls. Below this is what you feel; above it is what you hear
# on top. Both are wide on purpose - this is for driving a picture, not for
# analysis, and narrow bands would make it twitch on one instrument.
CROSSOVER = 260.0        # Hz
AIR = 3500.0             # Hz, and up

# The bands are resampled to this so they index exactly like analysis.json's
# peaks do, which is the only rate anything downstream knows about.
BAND_RATE = 120

# Bumped when the shape of this file changes, so an older cache is rebuilt
# rather than read back missing half its keys.
VERSION = 2

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


def _band(spectrum: np.ndarray, freqs: np.ndarray, low: float, high: float,
          frames: int, duration: float) -> list[float]:
    """One frequency band's energy over time, at BAND_RATE, normalized to 0..1."""
    rows = (freqs >= low) & (freqs < high)
    energy = spectrum[rows].sum(axis=0) if rows.any() else np.zeros(spectrum.shape[1])
    # Onto the same grid the peaks use, so a frame number means one thing.
    at = np.linspace(0.0, duration, frames, endpoint=False)
    grid = np.linspace(0.0, duration, energy.size, endpoint=False)
    energy = np.interp(at, grid, energy)
    loud = float(np.percentile(energy, 97)) or 1.0
    return np.round(np.clip(energy / loud, 0.0, 1.0), 3).tolist()


def build(
    audio_path: Path | str, workdir: Path | str, force: bool = False
) -> dict:
    workdir = Path(workdir)
    cache = workdir / "beats.json"
    if cache.exists() and not force:
        data = json.loads(cache.read_text())
        if data.get("version") == VERSION:
            return data

    samples, sr = load_mono(audio_path, SR)
    onset_env = librosa.onset.onset_strength(y=samples, sr=sr, hop_length=HOP)
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr, hop_length=HOP, trim=False
    )
    phase = _downbeat_phase(beat_frames, onset_env)
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=HOP)

    spectrum = np.abs(librosa.stft(samples, n_fft=2048, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    duration = samples.size / sr
    frames = int(round(duration * BAND_RATE))

    data = {
        "version": VERSION,
        "rate": BAND_RATE,
        "low": _band(spectrum, freqs, 0.0, CROSSOVER, frames, duration),
        "high": _band(spectrum, freqs, AIR, sr / 2, frames, duration),
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
