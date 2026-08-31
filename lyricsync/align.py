"""Primary aligner: Whisper-based forced alignment via stable-ts.

We already know the words, so we force-align the supplied lyrics instead of
transcribing and fuzzy-matching. Repeated choruses fall out correctly because
alignment consumes the text strictly in order.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .audio import TARGET_SR, load_mono
from .mapping import group_by_line
from .project import Word

DEFAULT_MODEL = "medium"
_MODEL_CACHE: dict[tuple[str, str], object] = {}


@dataclass
class LineTiming:
    """One aligner's opinion about one lyric line."""

    line_index: int
    start: float
    end: float
    words: list[Word] = field(default_factory=list)

    @property
    def mean_prob(self) -> float:
        if not self.words:
            return 0.0
        return float(np.mean([w.prob for w in self.words]))


def load_aligner(model_name: str = DEFAULT_MODEL, device: str = "cpu"):
    """Load (and cache) a stable-ts Whisper model.

    Whisper's decoder hits unimplemented sparse ops on MPS, so CPU is the
    default here even though Demucs happily uses the GPU.
    """
    key = (model_name, device)
    if key not in _MODEL_CACHE:
        import stable_whisper

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _MODEL_CACHE[key] = stable_whisper.load_model(model_name, device=device)
    return _MODEL_CACHE[key]


def align_lines(
    audio: Path | str | np.ndarray,
    line_texts: list[str],
    line_indices: list[int] | None = None,
    model_name: str = DEFAULT_MODEL,
    device: str = "cpu",
    language: str = "en",
    offset: float = 0.0,
    model=None,
) -> list[LineTiming]:
    """Force-align `line_texts` against `audio`.

    `offset` is added to every timestamp, so a cropped region can be aligned
    and the results placed back on the full-track timeline.
    """
    if not line_texts:
        return []

    if line_indices is None:
        line_indices = list(range(len(line_texts)))

    if not isinstance(audio, np.ndarray):
        audio, _ = load_mono(audio, TARGET_SR)

    model = model or load_aligner(model_name, device)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = model.align(
            audio,
            "\n".join(line_texts),
            language=language,
            original_split=True,
            regroup=False,
            fast_mode=False,
            verbose=None,
        )

    flat: list[Word] = []
    for segment in result.segments:
        for w in getattr(segment, "words", None) or []:
            text = (w.word or "").strip()
            if not text:
                continue
            flat.append(
                Word(
                    text=text,
                    start=float(w.start) + offset,
                    end=float(w.end) + offset,
                    prob=float(getattr(w, "probability", None) or 0.0),
                )
            )

    return _assemble(flat, line_texts, line_indices)


def _assemble(
    flat: list[Word], line_texts: list[str], line_indices: list[int]
) -> list[LineTiming]:
    """Group flat words into per-line timings."""
    groups = group_by_line([w.text for w in flat], line_texts)

    timings: list[LineTiming] = []
    for slot, word_positions in enumerate(groups):
        words = [flat[i] for i in word_positions]
        if words:
            start = min(w.start for w in words)
            end = max(w.end for w in words)
        else:
            start = end = 0.0
        timings.append(
            LineTiming(
                line_index=line_indices[slot],
                start=start,
                end=end,
                words=words,
            )
        )
    return timings
