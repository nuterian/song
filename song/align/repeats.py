"""A song's repeats vouch for each other.

The lines the score gets most wrong on the sample track are chorus repeats:
lines 18, 19 and 27 score 99.7-100 and are wrong by 0.8-2.8 s, because both
aligners made the same mistake on a held note and the blind transcription
could not tell one chorus from the next. But the song itself has already
sung each of those lyrics three or four times, and the other renditions are
right. Measured on gold: grouped by lyric text *and position within the
section*, the durations of the same word across renditions agree to within
4-15%. (Grouped by text alone they do not: the two "You're my gravity in
motion" lines in a chorus have different melodies, and "gravity" is 1.0 s
in one and 1.5-1.7 s in the other. The plan's "same section type" grouping
was wrong on this track and is not used.)

Two things come out of that, in the order the plan gives them:

1. **Consistency issues** for the audit queue, stdlib-only. A word whose
   duration is more than 1.5x or less than 1/1.5x the median across its
   renditions, by at least 150 ms, while the *other* renditions agree among
   themselves, is an outlier; the issue proposes the boundary after it at
   the median duration. On the sample track: 4 issues, 3 of them the
   squeezed words of line 18 (proposals 71-485 ms closer to gold) and one
   on line 9, whose two siblings are the wrong ones - the majority wins the
   median, and there is nothing in the durations alone to say the majority
   is wrong. Three of four is the precision; it is a queue for a human.

2. **Transfer**, numpy and librosa. For an outlier rendition, take the
   rendition nearest the group's median durations, DTW its stem crop
   against a wide crop around the outlier (MFCC + chroma, cosine,
   subsequence mode, `librosa.sequence.dtw`, about a second a pair), and
   map its word bounds through the warp. Measured with the source chosen
   by *score*, as the plan proposed: better on 8 of 12 renditions and
   catastrophic on 2, because a wrong line with score 100 makes a wrong
   source. Chosen by consistency - source deviation under TRUSTED, target
   over OUTLIER - it fires on lines 8 and 18 (start error 140 -> 24 ms and
   493 -> 14 ms) and on nothing else. So it is not the plan's fourth merge
   candidate: the merge's arbiter is exactly what is uncalibrated on these
   lines, and handing it a candidate it cannot judge is a gamble measured
   at 3 losses in 12. It is a repair, applied to an outlier from a trusted
   sibling, and reported as one.

Deliberately not implemented: transfer into a rendition whose siblings
disagree with each other, and any transfer with fewer than three renditions
- a median of two is a coin flip, and lines 19 and 27 (two wrong, one right)
are exactly the case where the majority is the error. They stay wrong here,
and the plan file says so.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass

from ..project import Project, TimedLine

# A word this much longer or shorter than its siblings' median is an outlier.
RATIO = 1.5
# ...but only when the difference is also at least this, in seconds; a 60 ms
# word and a 100 ms one are within the aligners' own error of each other.
ABS = 0.15
# Fewer renditions than this and the median means nothing.
MIN_RENDITIONS = 3
# Sum of |log(duration / group median)| over a rendition's words: above
# OUTLIER it is a transfer target, below TRUSTED a transfer source.
OUTLIER = 0.5
TRUSTED = 0.3


def normalize(text: str) -> str:
    return re.sub(r"[^a-z' ]", "", text.lower()).strip()


def groups(project: Project) -> dict[tuple[str, int], list[TimedLine]]:
    """Renditions of the same lyric at the same position in their section."""
    position: dict[int, int] = {}
    for section in project.sections:
        for k, index in enumerate(section.line_indices):
            position[index] = k
    out: dict[tuple[str, int], list[TimedLine]] = defaultdict(list)
    for line in project.lines:
        if line.end <= line.start or not line.words:
            continue
        out[(normalize(line.text), position.get(line.index, 0))].append(line)
    return {key: lines for key, lines in out.items()
            if len(lines) >= MIN_RENDITIONS
            and len({len(ln.words) for ln in lines}) == 1}


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def durations(line: TimedLine) -> list[float]:
    return [max(1e-3, w.end - w.start) for w in line.words]


def deviation(line: TimedLine, medians: list[float]) -> float:
    """How far a rendition's word durations sit from the group's medians."""
    return sum(abs(math.log(d / m)) for d, m in zip(durations(line), medians))


def medians(lines: list[TimedLine]) -> tuple[list[float], list[float]]:
    """Per-word median duration and median gap-after across renditions."""
    n = len(lines[0].words)
    dur = [_median([ln.words[k].end - ln.words[k].start for ln in lines]) for k in range(n)]
    gap = [_median([ln.words[k + 1].start - ln.words[k].end for ln in lines])
           for k in range(n - 1)]
    return dur, gap


def _agree(values: list[float]) -> bool:
    """The values are within RATIO of each other (or within ABS)."""
    lo, hi = min(values), max(values)
    return hi - lo < ABS or hi <= lo * RATIO


@dataclass
class Outlier:
    line: int
    word: int            # the outlier word
    text: str
    duration: float
    median: float
    current: float       # the boundary after it: the next word's start
    proposed: float
    siblings: list[int]

    def issue(self) -> dict:
        """The audit queue's shape: an A/B choice on the next word's start."""
        ratio = self.duration / self.median
        how = f"{ratio:.1f}x as long" if ratio > 1 else f"{1 / ratio:.1f}x shorter"
        return {
            "line": self.line,
            "word": self.word + 1,
            "text": self.text,
            "current": round(self.current, 3),
            "proposed": round(self.proposed, 3),
            "reasons": [
                f"'{self.text}' lasts {self.duration:.2f}s here, {how} than in the "
                f"{len(self.siblings)} other renditions ({self.median:.2f}s)"
            ],
            "severity": 2 if ratio > 2 or ratio < 0.5 else 1,
            "scope": "word",
        }


def outliers(project: Project) -> list[Outlier]:
    """Words whose duration disagrees with renditions that agree with each other.

    The boundary proposed is the one *after* the word: for a shut word that
    is the next word's start, which is the bound the review UI already knows
    how to offer and to accept. A line's last word has no such boundary and
    is not queued.
    """
    found: list[Outlier] = []
    for key, lines in groups(project).items():
        n = len(lines[0].words)
        med_dur, med_gap = medians(lines)
        for k in range(n - 1):
            for line in lines:
                d = line.words[k].end - line.words[k].start
                others = [ln.words[k].end - ln.words[k].start for ln in lines if ln is not line]
                if abs(d - med_dur[k]) < ABS:
                    continue
                if not (d > med_dur[k] * RATIO or d < med_dur[k] / RATIO):
                    continue
                if not _agree(others):
                    continue
                found.append(Outlier(
                    line=line.index, word=k, text=line.words[k].text,
                    duration=d, median=med_dur[k],
                    current=line.words[k + 1].start,
                    proposed=line.words[k].start + med_dur[k] + med_gap[k],
                    siblings=[ln.index for ln in lines if ln is not line],
                ))
    return found


def transfer_pairs(project: Project) -> list[tuple[TimedLine, TimedLine, float, float]]:
    """(source, target, source deviation, target deviation) worth transferring."""
    pairs = []
    for key, lines in groups(project).items():
        med_dur, _ = medians(lines)
        devs = {ln.index: deviation(ln, med_dur) for ln in lines}
        trusted = [ln for ln in lines if devs[ln.index] < TRUSTED]
        if not trusted:
            continue
        source = min(trusted, key=lambda ln: devs[ln.index])
        for line in lines:
            if line is source or devs[line.index] <= OUTLIER or line.locked:
                continue
            pairs.append((source, line, devs[source.index], devs[line.index]))
    return pairs


# ---------------------------------------------------------------- transfer

# How much stem either side of the source line goes into the query, and how
# much either side of the target's (possibly wrong) span the subsequence
# search may roam. 2 s covers every miss measured on the sample track (the
# worst is 2.8 s on one word, 1.4 s on a line start).
SOURCE_PAD = 0.3
TARGET_PAD = 2.0


def transfer(samples, sr: int, source: TimedLine, target: TimedLine,
             hop: int = 160) -> list[tuple[float, float]] | None:
    """Map the source's word bounds onto the target through a DTW of the stem.

    MFCC (mean/variance normalised) plus chroma, cosine distance, subsequence
    DTW so the source can land anywhere inside the padded target window.
    Returns one (start, end) per source word on the track timeline, or None
    when the audio is too short to align.
    """
    import numpy as np
    import librosa

    def crop(a: float, b: float):
        return samples[int(max(0.0, a) * sr): int(b * sr)]

    a, b = max(0.0, source.start - SOURCE_PAD), source.end + SOURCE_PAD
    ta, tb = max(0.0, target.start - TARGET_PAD), target.end + TARGET_PAD
    x, y = crop(a, b), crop(ta, tb)
    if len(x) < sr // 2 or len(y) < len(x):
        return None

    def features(wave):
        mf = librosa.feature.mfcc(y=wave, sr=sr, n_mfcc=20, n_fft=1024, hop_length=hop)
        mf = (mf - mf.mean(1, keepdims=True)) / (mf.std(1, keepdims=True) + 1e-6)
        ch = librosa.feature.chroma_stft(y=wave, sr=sr, n_fft=1024, hop_length=hop)
        return np.vstack([mf, ch])

    _, path = librosa.sequence.dtw(X=features(x), Y=features(y), subseq=True, metric="cosine")
    path = path[::-1]                      # (source frame, target frame), increasing
    xs, ys = path[:, 0], path[:, 1]

    def mapped(t: float) -> float:
        frame = int((t - a) * sr / hop)
        i = min(max(int(np.searchsorted(xs, frame)), 0), len(ys) - 1)
        return ta + float(ys[i]) * hop / sr

    return [(mapped(w.start), mapped(w.end)) for w in source.words]
