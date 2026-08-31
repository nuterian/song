"""Precomputed visuals for the review UI.

The UI's job is to make a wrong timestamp *obvious*. That means showing, on one
timeline: the mix (so you can see song structure), the isolated vocal (so you
can see exactly where singing starts), the detected vocal-active regions, and
onset ticks to snap to. All of it is computed once here and cached.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import vad
from .audio import TARGET_SR, load_mono, probe_duration

BUCKETS_PER_SECOND = 120


def _peaks(samples: np.ndarray, sr: int, rate: int = BUCKETS_PER_SECOND) -> list[float]:
    """Max absolute amplitude per time bucket, normalized to 0..1."""
    bucket = max(1, int(sr / rate))
    usable = (len(samples) // bucket) * bucket
    if usable == 0:
        return []
    blocks = np.abs(samples[:usable]).reshape(-1, bucket).max(axis=1)
    peak = float(blocks.max()) or 1.0
    return np.round(blocks / peak, 4).tolist()


def _intervals(active: np.ndarray, hop: float, min_len: float = 0.08) -> list[list[float]]:
    """Boolean activity mask as [start, end] spans - far smaller than a bitmap."""
    out: list[list[float]] = []
    start = None
    for i, value in enumerate(active):
        if value and start is None:
            start = i
        elif not value and start is not None:
            if (i - start) * hop >= min_len:
                out.append([round(start * hop, 3), round(i * hop, 3)])
            start = None
    if start is not None:
        out.append([round(start * hop, 3), round(len(active) * hop, 3)])
    return out


def build(
    audio_path: Path | str, stem_path: Path | str, workdir: Path | str, force: bool = False
) -> dict:
    workdir = Path(workdir)
    cache = workdir / "analysis.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text())

    mix, _ = load_mono(audio_path, TARGET_SR)
    stem, _ = load_mono(stem_path, TARGET_SR)
    activity = vad.analyse(stem, TARGET_SR)

    data = {
        "duration": probe_duration(audio_path),
        "rate": BUCKETS_PER_SECOND,
        "mix_peaks": _peaks(mix, TARGET_SR),
        "vocal_peaks": _peaks(stem, TARGET_SR),
        "vocal_spans": _intervals(activity.active, activity.hop),
        "onsets": np.round(activity.onsets, 3).tolist(),
        "threshold_db": round(activity.threshold_db, 2),
    }

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data
