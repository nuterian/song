"""Vocal-activity analysis of the isolated stem.

Once the vocals are separated, "is anyone singing at time t" becomes a simple,
reliable energy question. That single signal does a lot of work: it catches
lines parked over an instrumental break, trims the trailing silence aligners
love to append to the last word of a phrase, and supplies onsets to snap to.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .audio import rms_envelope


@dataclass
class VocalActivity:
    times: np.ndarray
    db: np.ndarray
    active: np.ndarray
    hop: float
    onsets: np.ndarray
    threshold_db: float

    # ---------- queries ----------

    def _slice(self, start: float, end: float) -> slice:
        i0 = int(np.clip(start / self.hop, 0, len(self.active)))
        i1 = int(np.clip(np.ceil(end / self.hop), 0, len(self.active)))
        return slice(i0, max(i1, i0 + 1))

    def coverage(self, start: float, end: float) -> float:
        """Fraction of the span in which the vocal is active."""
        if end <= start:
            return 0.0
        window = self.active[self._slice(start, end)]
        return float(np.mean(window)) if len(window) else 0.0

    def longest_gap(self, start: float, end: float) -> float:
        """Longest continuous silence inside the span, in seconds."""
        window = self.active[self._slice(start, end)]
        if not len(window):
            return 0.0
        best = run = 0
        for value in window:
            run = 0 if value else run + 1
            best = max(best, run)
        return best * self.hop

    def nearest_onset(self, t: float) -> float:
        if not len(self.onsets):
            return float("inf")
        return float(np.min(np.abs(self.onsets - t)))

    def snap_to_onset(self, t: float, max_shift: float = 0.35) -> float:
        """Move `t` to the nearest vocal onset when one is close enough."""
        if not len(self.onsets):
            return t
        i = int(np.argmin(np.abs(self.onsets - t)))
        candidate = float(self.onsets[i])
        return candidate if abs(candidate - t) <= max_shift else t

    def trim(
        self,
        start: float,
        end: float,
        max_trim: float = 6.0,
        min_duration: float = 0.35,
        tail: float = 0.12,
    ) -> tuple[float, float]:
        """Shrink a span onto the vocal actually inside it.

        Aligners routinely stretch a phrase's last word across the instrumental
        that follows; this pulls the end back to where singing really stops.
        Only trims - never extends - so it cannot invent coverage.
        """
        window = self.active[self._slice(start, end)]
        if not len(window) or not window.any():
            return start, end

        offset = self._slice(start, end).start
        active_idx = np.flatnonzero(window)
        first = (offset + active_idx[0]) * self.hop
        last = (offset + active_idx[-1]) * self.hop

        new_start = start if first - start < 0.25 else min(first, start + max_trim)
        new_end = end if end - last < 0.25 else max(last + tail, end - max_trim)

        if new_end - new_start < min_duration:
            return start, end
        return max(start, new_start), min(end, new_end)


def analyse(samples: np.ndarray, sr: int, hop_seconds: float = 0.01) -> VocalActivity:
    env, hop = rms_envelope(samples, sr, hop_seconds)
    db = 20.0 * np.log10(env + 1e-8)

    # Adaptive gate: above the noise floor, but never more than 34 dB below
    # the loud parts, so quiet sung passages still register.
    floor = float(np.percentile(db, 15))
    peak = float(np.percentile(db, 99))
    threshold = max(floor + 9.0, peak - 34.0)

    active = db > threshold
    active = _smooth(active, min_on=int(0.06 / hop), min_off=int(0.16 / hop))

    times = np.arange(len(db)) * hop

    try:
        import librosa

        onsets = librosa.onset.onset_detect(
            y=samples, sr=sr, units="time", backtrack=True
        )
    except Exception:
        onsets = np.array([])

    return VocalActivity(
        times=times,
        db=db.astype(np.float32),
        active=active,
        hop=hop,
        onsets=np.asarray(onsets, dtype=np.float64),
        threshold_db=threshold,
    )


def _smooth(active: np.ndarray, min_on: int, min_off: int) -> np.ndarray:
    """Drop blips and bridge short gaps so breaths don't read as silence."""
    out = active.copy()

    if min_off > 0:
        idx = np.flatnonzero(out)
        for a, b in zip(idx, idx[1:]):
            if 1 < b - a <= min_off:
                out[a:b] = True

    if min_on > 0:
        start = None
        for i, value in enumerate(out):
            if value and start is None:
                start = i
            elif not value and start is not None:
                if i - start < min_on:
                    out[start:i] = False
                start = None
        if start is not None and len(out) - start < min_on:
            out[start:] = False

    return out
