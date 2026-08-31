"""Round-trip check: transcribe the vocal blind, then see where the words landed.

The two forced aligners are both *told* the lyrics, so both can be confidently
wrong in the same place. A free transcription is told nothing - it reports what
it actually hears and when. Matching that back against the lyrics gives a third,
genuinely independent opinion, and it is the one that settles disagreements: on
the sample track it correctly picked the winner in all three disputed lines.

Matching is done *locally in time*, inside a window around where the anchor
already thinks the line is. Matching globally on text does not work here: a
chorus that repeats four times gives four identical word sequences, and the
matcher will happily attach a line to the wrong repeat. The window makes the
question "were these words sung here?" instead of "where in the song are these
words?", which is both easier and the question actually being asked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .audio import TARGET_SR, load_mono
from .mapping import map_words_to_lines
from .parse_lyrics import tokenize
from .project import Word

DEFAULT_MODEL = "medium"
_MODEL_CACHE: dict[tuple, object] = {}


@dataclass
class Observation:
    """Where a free transcription thinks a lyric line actually happened."""

    start: float
    end: float
    matched: int
    expected: int

    @property
    def ratio(self) -> float:
        return self.matched / self.expected if self.expected else 0.0

    @property
    def trustworthy(self) -> bool:
        """Enough of the line was heard for its span to mean something."""
        return self.matched >= 2 and self.ratio >= 0.4 and self.end > self.start


@dataclass
class RoundTrip:
    words: list[Word] = field(default_factory=list)
    per_line: dict[int, Observation] = field(default_factory=dict)

    def overlap(self, line_index: int, start: float, end: float) -> float | None:
        """Intersection-over-union of a candidate span with what was heard."""
        obs = self.per_line.get(line_index)
        if obs is None or not obs.trustworthy or end <= start:
            return None
        lo = max(start, obs.start)
        hi = min(end, obs.end)
        inter = max(0.0, hi - lo)
        union = max(end, obs.end) - min(start, obs.start)
        return inter / union if union > 0 else 0.0

    def support(self, line_index: int, start: float, end: float) -> float | None:
        """How well a candidate span matches what was actually heard, 0..1.

        Intersection-over-union, not containment. Containment looks right but
        is trivially gamed: a span stretched over the preceding instrumental
        encloses the heard words completely and scores a perfect 1.0, which is
        exactly the error this signal exists to catch. IoU punishes a span for
        being misplaced *and* for being longer than what was sung.

        A blind transcription does miss quiet lead-in words, so even a perfect
        placement rarely reaches 1.0 - but every candidate for a line is judged
        against the same heard span, so the comparison stays fair.
        """
        iou = self.overlap(line_index, start, end)
        if iou is None:
            return None
        # 0.55 is about the best a correct placement reaches once the
        # transcription's missing lead-in words are accounted for.
        return float(np.clip((iou - 0.05) / 0.50, 0.0, 1.0))

    def start_delta(self, line_index: int, start: float) -> float | None:
        """Signed-magnitude start difference, for diagnostics and reporting."""
        obs = self.per_line.get(line_index)
        if obs is None or not obs.trustworthy:
            return None
        return abs(obs.start - start)

    def unmatched(self) -> list[Word]:
        """Words the blind pass heard that no line claimed.

        Every word here was sung and is not in the lyrics as currently timed.
        Most are lead-in bleed or a hallucination over silence - but a whole
        run of them, inside a gap, confidently transcribed, is a line missing
        from the lyrics file. See gaps.py, which is the only reader.

        This costs nothing to produce: the blind pass already transcribes the
        entire stem once, and these are simply the leftovers.
        """
        claimed = [
            (o.start, o.end) for o in self.per_line.values() if o.trustworthy
        ]
        out = []
        for w in self.words:
            mid = (w.start + w.end) / 2
            if not any(a <= mid <= b for a, b in claimed):
                out.append(w)
        return out

    def to_dict(self) -> dict:
        return {
            "n_words": len(self.words),
            "lines_observed": sum(1 for o in self.per_line.values() if o.trustworthy),
            "unmatched": [
                {
                    "text": w.text,
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "prob": round(w.prob, 3),
                }
                for w in self.unmatched()
            ],
            "per_line": {
                str(k): {
                    "start": round(v.start, 3),
                    "end": round(v.end, 3),
                    "matched": v.matched,
                    "expected": v.expected,
                }
                for k, v in self.per_line.items()
                if v.trustworthy
            },
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "RoundTrip | None":
        """Rebuild the observations from a saved project, so re-scoring after
        manual edits needs no models and still uses independent evidence."""
        if not d or not d.get("per_line"):
            return None
        per_line = {
            int(k): Observation(
                start=float(v["start"]),
                end=float(v["end"]),
                matched=int(v.get("matched", 2)),
                expected=int(v.get("expected", 2)),
            )
            for k, v in d["per_line"].items()
        }
        return cls(
            words=[
                Word(
                    text=w["text"],
                    start=float(w["start"]),
                    end=float(w["end"]),
                    prob=float(w.get("prob", 0.0)),
                )
                for w in d.get("unmatched", [])
            ],
            per_line=per_line,
        )


def _load(model_size: str, device: str):
    key = (model_size, device)
    if key not in _MODEL_CACHE:
        from faster_whisper import WhisperModel

        _MODEL_CACHE[key] = WhisperModel(
            model_size, device=device, compute_type="int8"
        )
    return _MODEL_CACHE[key]


def transcribe(
    audio: Path | str | np.ndarray,
    model_size: str = DEFAULT_MODEL,
    device: str = "cpu",
    language: str = "en",
) -> list[Word]:
    if not isinstance(audio, np.ndarray):
        audio, _ = load_mono(audio, TARGET_SR)

    model = _load(model_size, device)
    segments, _ = model.transcribe(
        np.asarray(audio, dtype=np.float32),
        language=language,
        word_timestamps=True,
        vad_filter=False,
    )

    words: list[Word] = []
    for segment in segments:
        for w in segment.words or []:
            text = (w.word or "").strip()
            if text:
                words.append(
                    Word(
                        text=text,
                        start=float(w.start),
                        end=float(w.end),
                        prob=float(getattr(w, "probability", None) or 0.0),
                    )
                )
    return words


def locate(
    words: list[Word], text: str, lo: float, hi: float
) -> Observation | None:
    """Find `text` among the transcribed words falling inside [lo, hi]."""
    local = [w for w in words if w.end >= lo and w.start <= hi]
    expected = max(1, len(tokenize(text)))
    if not local:
        return None

    assignment = map_words_to_lines(
        [w.text for w in local], [text], strict=True
    )
    matched = [w for w, slot in zip(local, assignment) if slot == 0]
    if not matched:
        return None

    return Observation(
        start=min(w.start for w in matched),
        end=max(w.end for w in matched),
        matched=len(matched),
        expected=expected,
    )


def observe(
    audio: Path | str | np.ndarray,
    line_texts: list[str],
    windows: dict[int, tuple[float, float]],
    line_indices: list[int] | None = None,
    model_size: str = DEFAULT_MODEL,
    device: str = "cpu",
    words: list[Word] | None = None,
) -> RoundTrip:
    """Transcribe blind, then confirm each line inside its own search window.

    `windows` maps a line index to the [start, end] range to search, normally
    the anchor's placement widened by a few seconds. Lines with no window are
    skipped rather than guessed at.
    """
    if line_indices is None:
        line_indices = list(range(len(line_texts)))

    if words is None:
        words = transcribe(audio, model_size=model_size, device=device)
    if not words:
        return RoundTrip()

    per_line: dict[int, Observation] = {}
    for slot, text in enumerate(line_texts):
        index = line_indices[slot]
        window = windows.get(index)
        if window is None:
            continue
        found = locate(words, text, window[0], window[1])
        if found is not None:
            per_line[index] = found

    return RoundTrip(words=words, per_line=per_line)
