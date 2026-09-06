"""Vocal-activity analysis of the isolated stem.

Once the vocals are separated, "is anyone singing at time t" becomes a simple,
reliable energy question. That single signal does a lot of work: it catches
lines parked over an instrumental break, trims the trailing silence aligners
love to append to the last word of a phrase, and supplies onsets to snap to.

Reliable, but not precise: what Demucs leaves in the stem - reverb tails, a
pad under the vocal, the harmonies of a layered chorus - is quiet but not
silent, and the energy gate alone reads 15 s of rests inside the sample
track's lines as singing, 52 s more outside them. A voicing probability
from Silero VAD (see `voicing`) halves the first number and quarters the
second while missing under 5% of sung frames - and the 5% it misses are
sustained high notes, which is the one miss the line trim cannot survive.
So it is computed and kept as `voiced`, and `active` stays the energy gate.
Word *ends* are read separately, off the envelope relative to each word's
own peak, in `song.ends`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import ends
from .audio import rms_envelope


# Silero's speech probability at or above this counts as voice. Measured on the
# gold set (frame agreement with "is a word being sung here", inside line
# spans): 0.15 gives 90.4% accuracy with 95.8% recall, 0.3 drops recall to
# 89.7%, 0.5 to 84%. Low on purpose - the model is trained on speech and is
# unsure of a held sung vowel, and a gate that misses singing costs more here
# than one that lets a breath through.
VOICED = 0.15

_SILERO = None


@dataclass
class VocalActivity:
    times: np.ndarray
    db: np.ndarray
    active: np.ndarray
    hop: float
    onsets: np.ndarray
    threshold_db: float
    # Per-frame probability that a voice is sounding, from Silero VAD, on the
    # same hop as `db`; None when the model is not installed or switched off.
    # Not folded into `active` - see analyse() for the measurement that keeps
    # it out - but cached beside the analysis for anything that wants it.
    voiced: np.ndarray | None = None
    # The energy gate on its own; identical to `active` today.
    loud: np.ndarray | None = None
    # librosa's onset strength on the same hop as `db`: spectral flux, which
    # is where the syllables inside a word show up (see pipeline.settle_syllables).
    strength: np.ndarray | None = None

    @property
    def sung(self) -> np.ndarray:
        """Energy gate AND voicing, where voicing is available.

        90.4% frame agreement with gold's "a word is being sung here" inside
        line spans against 88.3% for the energy gate, and a quarter of its
        false positives outside them. Right more often and wrong worse: not
        used by the pipeline, offered to callers that can afford a miss.
        """
        if self.voiced is None:
            return self.active
        return self.active & (self.voiced >= VOICED)

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

    def word_end(self, start: float, limit: float, current: float | None = None) -> float:
        """Where the voice stops between `start` and `limit`, in seconds.

        The rule lives in `song.ends` (stdlib, pinned by tests); this only
        cuts the envelope and puts the offset back on the track timeline.
        `current` is the end already on file, which the rule may pull earlier
        freely and push later only across continuous voice.
        """
        if limit <= start:
            return limit
        i0 = int(start / self.hop)
        i1 = max(i0 + 1, int(limit / self.hop))
        window = self.db[i0:i1].tolist()
        offset = None if current is None else max(0.0, current - start)
        return round(min(limit, start + ends.word_end(window, self.hop, offset)), 3)

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


def analyse(
    samples: np.ndarray, sr: int, hop_seconds: float = 0.01, voicing_model: bool = True
) -> VocalActivity:
    """The vocal activity of a stem. `voicing_model=False` is the energy gate
    alone, kept so the two can be benchmarked against each other."""
    env, hop = rms_envelope(samples, sr, hop_seconds)
    db = 20.0 * np.log10(env + 1e-8)

    # Adaptive gate: above the noise floor, but never more than 34 dB below
    # the loud parts, so quiet sung passages still register.
    floor = float(np.percentile(db, 15))
    peak = float(np.percentile(db, 99))
    threshold = max(floor + 9.0, peak - 34.0)

    loud = db > threshold
    loud = _smooth(loud, min_on=int(0.06 / hop), min_off=int(0.16 / hop))

    times = np.arange(len(db)) * hop

    voiced = voicing(samples, sr, hop, len(db)) if voicing_model else None
    # `active` stays the energy gate. The voiced gate was tried as the gate
    # through the whole pipeline and measured against gold: it fixes two line
    # ends (15 and 32, by 1.1 s and 0.3 s) and moves the start of line 20 by
    # 2.3 s, because Silero drops out of a sustained note at 450-550 Hz and
    # the line trim believes it. A gate that is wrong in a way the trim
    # cannot survive is not a gate; it is data, and it is kept as `voiced`.
    active = loud

    strength = None
    try:
        import librosa

        onsets = librosa.onset.onset_detect(
            y=samples, sr=sr, units="time", backtrack=True
        )
        raw = librosa.onset.onset_strength(y=samples, sr=sr, hop_length=max(1, int(sr * hop)))
        strength = np.interp(
            times, np.arange(len(raw)) * hop, raw
        ).astype(np.float32) if len(raw) else None
    except Exception:
        onsets = np.array([])

    return VocalActivity(
        times=times,
        db=db.astype(np.float32),
        active=active,
        hop=hop,
        onsets=np.asarray(onsets, dtype=np.float64),
        threshold_db=threshold,
        voiced=voiced,
        loud=loud,
        strength=strength,
    )


def voicing(samples: np.ndarray, sr: int, hop: float, n_frames: int) -> np.ndarray | None:
    """Silero VAD's speech probability, resampled onto the envelope's frames.

    Why a speech model on singing, and why this one: the plan expected it to
    lose to pyin's voicing on a sung vocal, and it did the opposite. Against
    the gold set, frame agreement with "a word is being sung here" inside
    line spans is 90.4% for Silero at 0.15, 88.3% for the energy gate, 82.6%
    for pyin's voiced flag (which drops out of held vowels with vibrato and
    misses 13.7 s of singing). Outside the lines, where the stem carries
    reverb tails, pads and the harmonies Demucs leaves behind, the energy
    gate calls 52 s of it singing; Silero calls 14 s. It is 2 MB, ships its
    weights inside the package, and takes 0.9 s on the 4:46 stem on CPU.

    What it is not: a boundary detector. It is already on 100 ms before most
    word starts, because most words are shut against the one before.

    Returns None when `silero_vad` is not installed, and everything downstream
    falls back to the energy gate alone.
    """
    global _SILERO
    try:
        import torch
        from silero_vad import load_silero_vad
    except ImportError:
        return None
    if _SILERO is None:
        _SILERO = load_silero_vad()
    model = _SILERO
    model.reset_states()
    if sr not in (8000, 16000):
        return None
    chunk = 512 if sr == 16000 else 256
    wave = torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32))
    probs = []
    with torch.inference_mode():
        for i in range(0, len(wave) - chunk + 1, chunk):
            probs.append(float(model(wave[i : i + chunk], sr)))
    if not probs:
        return None
    # Each probability describes one chunk; put it at the chunk's centre and
    # read it back at every envelope frame.
    centres = (np.arange(len(probs)) * chunk + chunk / 2) / sr
    frames = np.arange(n_frames) * hop
    return np.interp(frames, centres, np.asarray(probs, dtype=np.float32)).astype(np.float32)


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
