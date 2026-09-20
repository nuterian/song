"""Reading a song workdir, read-only, into features on a regular grid.

The song tool leaves behind everything milestone 1 needs, so this module invents
nothing: it reads `analysis.json`, `beats.json` and `project.json`, puts what it
finds on one 120 Hz grid, and derives the few things that are implied rather than
stored - where sections begin and end, which bar a moment is in, how far through
the current word a singer is.

Nothing here writes into the workdir, and nothing here imports the `song`
package. The coupling is the file format and only the file format.

Milestone 2 replaces this with real listening: its own four-stem separation,
chroma and key, spectral brightness, vocal pitch, and a frozen music embedding
per section, all folded into one beat-synchronous token per beat. What is here is
the subset the existing files already give up, at 120 Hz rather than per beat,
because the renderer wants a smooth envelope more than it wants a token.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# The grid. 120 Hz is what the song tool already sampled its envelopes at, so
# using it means never resampling the inputs, and it is high enough that an
# attack of a millisecond or two is the only thing it cannot express.
RATE = 120

# Continuous channels are interpolated between grid points; impulse channels are
# maxed over the span a frame covers, so a single-sample onset is never stepped
# over; index channels are held.
CONTINUOUS = "lerp"
IMPULSE = "max"
HELD = "hold"

FEATURES: tuple[tuple[str, str], ...] = (
    ("mix", CONTINUOUS),             # mix peak envelope, 0..1
    ("vocal", CONTINUOUS),           # vocal stem peak envelope, 0..1
    ("low", CONTINUOUS),             # low band of the mix, 0..1
    ("high", CONTINUOUS),            # high band of the mix, 0..1
    # The rise of the mix envelope, half-wave rectified and normalised: what the
    # music just *did*, as opposed to where it currently is. A level tells you
    # the song is loud; this tells you it got louder, which is most of what
    # "the picture noticed that" turns out to mean.
    ("flux", CONTINUOUS),
    ("onset", IMPULSE),              # 1 on a vocal onset sample, else 0
    ("beat", IMPULSE),               # 1 on a beat
    ("bar", IMPULSE),                # 1 on a downbeat
    # The phases are sawtooths, and a sawtooth is held rather than interpolated:
    # lerping across the reset would read half way through the beat at the exact
    # instant the beat lands, which is a visible pop once a bar.
    ("beat_phase", HELD),            # 0..1 through the current beat
    ("bar_phase", HELD),             # 0..1 through the current bar
    # Beats elapsed since the song began, as a real number: the musical clock.
    # Everything in the grammar that moves on its own moves on this rather than on
    # seconds, so a rotation is so many turns per bar and a travelling band is so
    # many bars per cycle - and the picture is locked to the music even where no
    # bar of the score is routing anything at it.
    ("beats", CONTINUOUS),
    ("section", HELD),               # section index, as a float
    ("section_progress", HELD),
    ("bar_index", HELD),
    ("line", HELD),                  # line index, or -1 where nothing is sung
    ("word", HELD),                  # 0..1 through the word being sung, else 0
)
FEATURE_NAMES: tuple[str, ...] = tuple(n for n, _ in FEATURES)
FEATURE_INDEX: dict[str, int] = {n: i for i, (n, _) in enumerate(FEATURES)}

# Which feature each routing source listens to. `none` is a constant zero, which
# is why it is the value a bar carrying no routing event must hold.
SOURCE_FEATURE: dict[str, str | None] = {
    "none": None, "mix": "mix", "vocal": "vocal", "low": "low", "high": "high",
    "flux": "flux", "onset": "onset", "beat": "beat", "bar": "bar",
}


@dataclass(frozen=True)
class Section:
    index: int
    name: str
    note: str
    start: float
    end: float
    line_indices: tuple[int, ...]


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Line:
    index: int
    section: int
    text: str
    start: float
    end: float
    words: tuple[Word, ...]


class Track:
    """One song workdir, loaded. Read-only by construction: nothing writes back."""

    def __init__(self, workdir: str | Path) -> None:
        self.workdir = Path(workdir).expanduser().resolve()
        for name in ("project.json", "analysis.json", "beats.json"):
            if not (self.workdir / name).exists():
                raise FileNotFoundError(
                    f"{self.workdir} is missing {name}; is it a song workdir? "
                    f"Build one with:  python -m song <audio> <lyrics>"
                )
        project = self._read("project.json")
        analysis = self._read("analysis.json")
        beats = self._read("beats.json")

        self.name = self.workdir.name
        self.duration = float(project["duration"])
        self.tempo = float(beats["tempo"])
        self.meter = int(beats.get("meter", 4))

        if int(analysis["rate"]) != RATE or int(beats["rate"]) != RATE:
            raise ValueError(
                f"{self.name}: envelopes are at {analysis['rate']}/{beats['rate']} Hz, "
                f"this expects {RATE}"
            )

        self.beats = np.asarray(beats["beats"], dtype=np.float64)
        self.downbeats = np.asarray(beats["downbeats"], dtype=np.float64)
        self.onsets = np.unique(np.asarray(analysis["onsets"], dtype=np.float64))

        # The song tool already leaves these compressed into 0..1, so they are
        # clipped rather than renormalised: guessing at a second normalisation
        # would only move loudness around behind the routing gains.
        self.n = int(round(self.duration * RATE)) + 1
        self.mix = self._grid(analysis["mix_peaks"])
        self.vocal = self._grid(analysis["vocal_peaks"])
        self.low = self._grid(beats["low"])
        self.high = self._grid(beats["high"])

        self.lines = tuple(
            Line(
                index=int(ln["index"]),
                section=int(ln["section"]),
                text=str(ln["text"]),
                start=float(ln["start"]),
                end=float(ln["end"]),
                words=tuple(
                    Word(str(w["text"]), float(w["start"]), float(w["end"]))
                    for w in ln.get("words", ())
                ),
            )
            for ln in project["lines"]
        )
        self.sections = self._sections(project["sections"])

    def _read(self, name: str) -> dict:
        with open(self.workdir / name) as fh:
            return json.load(fh)

    def _grid(self, values) -> np.ndarray:
        """One stored envelope, clipped to 0..1 and trimmed or held to `self.n`.

        The two files disagree about length by a fraction of a second - they were
        written by different passes - so the shorter one holds its last value
        rather than falling to silence.
        """
        x = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
        if len(x) >= self.n:
            return x[: self.n].copy()
        return np.concatenate([x, np.full(self.n - len(x), x[-1] if len(x) else 0.0, "f4")])

    def _sections(self, raw) -> tuple[Section, ...]:
        """Section spans, which the project file implies but does not store.

        A section's own extent is the extent of its lines. That leaves gaps - a
        forty-six second instrumental sits between chorus 1 and verse 2 of the
        sample track - so each gap is split at the downbeat nearest its middle,
        and the first and last sections are stretched to the ends of the song.
        Every boundary lands on a downbeat, so a section change and a bar change
        are the same instant.
        """
        spans = []
        for s in raw:
            idx = [int(i) for i in s["line_indices"]]
            if idx:
                first = min(self.lines[i].start for i in idx)
                last = max(self.lines[i].end for i in idx)
            else:  # an instrumental section, with no lines of its own
                first = last = float("nan")
            spans.append((s, idx, first, last))

        cuts = [0.0]
        for i in range(len(spans) - 1):
            _, _, _, end_i = spans[i]
            _, _, start_j, _ = spans[i + 1]
            if np.isnan(end_i) or np.isnan(start_j):
                middle = start_j if not np.isnan(start_j) else end_i
            else:
                middle = (end_i + start_j) / 2.0 if start_j > end_i else start_j
            cuts.append(self.snap_downbeat(float(middle)))
        cuts.append(self.duration)
        cuts = list(np.maximum.accumulate(cuts))  # monotone even if a snap collides

        return tuple(
            Section(int(s["index"]), str(s["name"]), str(s.get("note", "")),
                    cuts[i], cuts[i + 1], tuple(idx))
            for i, (s, idx, _, _) in enumerate(spans)
        )

    # -- derived positions ------------------------------------------------ #

    def snap_downbeat(self, t: float) -> float:
        """The downbeat closest to `t`, which is where a section change belongs."""
        if not len(self.downbeats):
            return t
        return float(self.downbeats[int(np.argmin(np.abs(self.downbeats - t)))])

    @property
    def n_bars(self) -> int:
        """Bars, one per downbeat. Bar slot j in a score is this bar j."""
        return max(1, len(self.downbeats))

    def bar_spans(self) -> np.ndarray:
        """(n_bars, 2) of bar start and end times.

        Anything before the first downbeat belongs to bar 0, so the count-in is
        directed rather than undirected, and the last bar runs to the end.
        """
        starts = self.downbeats.copy() if len(self.downbeats) else np.array([0.0])
        starts[0] = 0.0
        ends = np.concatenate([starts[1:], [self.duration]])
        return np.stack([starts, np.maximum(ends, starts)], axis=1)

    def section_of(self, t: float) -> int:
        for s in self.sections:
            if s.start <= t < s.end:
                return s.index
        return self.sections[-1].index if self.sections else 0

    # -- the grid --------------------------------------------------------- #

    def timeline(self) -> "Timeline":
        """Every feature, on the 120 Hz grid, as one array."""
        n = self.n
        t = np.arange(n, dtype=np.float64) / RATE
        data = np.zeros((n, len(FEATURES)), dtype=np.float32)
        put = lambda name, v: np.copyto(data[:, FEATURE_INDEX[name]], v)  # noqa: E731

        put("mix", self.mix)
        put("vocal", self.vocal)
        put("low", self.low)
        put("high", self.high)
        put("flux", _flux(self.mix, self.low, self.high))

        for name, times in (("onset", self.onsets), ("beat", self.beats),
                            ("bar", self.downbeats)):
            col = data[:, FEATURE_INDEX[name]]
            i = np.clip(np.round(times * RATE).astype(int), 0, n - 1)
            col[i] = 1.0

        put("beats", _elapsed(t, self.beats, self.tempo))
        put("beat_phase", _phase(t, self.beats, self.duration, self.tempo))
        put("bar_phase", _phase(t, self.downbeats, self.duration,
                                self.tempo / max(1, self.meter)))

        spans = self.bar_spans()
        bar_index = np.clip(np.searchsorted(spans[:, 0], t, side="right") - 1,
                            0, len(spans) - 1)
        put("bar_index", bar_index.astype(np.float32))

        sec = np.zeros(n, dtype=np.float32)
        prog = np.zeros(n, dtype=np.float32)
        for s in self.sections:
            m = (t >= s.start) & (t < s.end)
            if s.index == len(self.sections) - 1:
                m |= t >= s.start
            sec[m] = float(s.index)
            span = max(s.end - s.start, 1e-6)
            prog[m] = np.clip((t[m] - s.start) / span, 0.0, 1.0)
        put("section", sec)
        put("section_progress", prog)

        line = np.full(n, -1.0, dtype=np.float32)
        word = np.zeros(n, dtype=np.float32)
        for ln in self.lines:
            a, b = int(round(ln.start * RATE)), int(round(ln.end * RATE))
            line[max(0, a):min(n, b + 1)] = float(ln.index)
            for w in ln.words:
                wa, wb = int(round(w.start * RATE)), int(round(w.end * RATE))
                wa, wb = max(0, wa), min(n - 1, wb)
                if wb > wa:
                    word[wa:wb + 1] = np.linspace(0.0, 1.0, wb - wa + 1, dtype=np.float32)
                elif 0 <= wa < n:
                    word[wa] = 1.0
        put("line", line)
        put("word", word)

        return Timeline(RATE, FEATURES, data)


def _elapsed(t: np.ndarray, marks: np.ndarray, tempo: float) -> np.ndarray:
    """Beats elapsed, counting from the first one, interpolated within each beat.

    Monotone and continuous, and it advances with the music rather than with the
    clock, so a shader that turns something once every four beats keeps turning it
    once every four beats whatever the tempo does.
    """
    period = 60.0 / max(tempo, 1e-6)
    if not len(marks):
        return (t / period).astype(np.float32)
    edges = np.concatenate([marks, [float(marks[-1]) + period]])
    i = np.clip(np.searchsorted(edges, t, side="right") - 1, 0, len(edges) - 2)
    span = np.maximum(edges[i + 1] - edges[i], 1e-6)
    out = i + (t - edges[i]) / span
    before = t < edges[0]
    out[before] = (t[before] - edges[0]) / period
    return out.astype(np.float32)


def _flux(*bands: np.ndarray) -> np.ndarray:
    """Half-wave-rectified rise across several envelopes, scaled to roughly 0..1.

    The scale is the 99th percentile of the positive rises rather than the
    maximum, so one transient at the loudest moment of the song does not flatten
    every other rise in it. Deterministic, and computed once per track.
    """
    rise = np.zeros(len(bands[0]), dtype=np.float32)
    for band in bands:
        d = np.diff(band, prepend=band[:1])
        rise += np.maximum(d, 0.0)
    top = float(np.percentile(rise, 99.0))
    return np.clip(rise / max(top, 1e-6), 0.0, 1.0).astype(np.float32)


def _phase(t: np.ndarray, marks: np.ndarray, duration: float, per_minute: float) -> np.ndarray:
    """0..1 between consecutive marks, sawtooth, resetting on each one.

    Before the first mark and after the last, the tempo carries the phase, so the
    count-in and the fade-out still have a pulse to be driven by.
    """
    period = 60.0 / max(per_minute, 1e-6)
    if not len(marks):
        return np.float32(1.0) * ((t / period) % 1.0).astype(np.float32)
    edges = np.concatenate([marks, [max(duration, float(marks[-1]) + period)]])
    i = np.clip(np.searchsorted(edges, t, side="right") - 1, 0, len(edges) - 2)
    span = np.maximum(edges[i + 1] - edges[i], 1e-6)
    out = (t - edges[i]) / span
    before = t < edges[0]
    out[before] = ((t[before] - edges[0]) / period) % 1.0
    return np.clip(out, 0.0, 1.0).astype(np.float32)


class Timeline:
    """Features on a regular grid, sampled at arbitrary times.

    `at` and `window` are the only two ways the rest of the tool reads a feature,
    and they differ on purpose: a value is read at an instant, an impulse is read
    over the span of the output frame that is about to be drawn, so a one-sample
    onset between two frames is still seen.
    """

    def __init__(self, rate: int, features: tuple[tuple[str, str], ...], data: np.ndarray) -> None:
        self.rate = rate
        self.features = features
        self.names = tuple(n for n, _ in features)
        self.kinds = tuple(k for _, k in features)
        self.data = np.ascontiguousarray(data, dtype=np.float32)

    @property
    def n(self) -> int:
        return self.data.shape[0]

    @property
    def duration(self) -> float:
        return (self.n - 1) / self.rate

    def column(self, name: str) -> np.ndarray:
        return self.data[:, self.names.index(name)]

    def at(self, t: float) -> dict[str, float]:
        """Every feature at one instant, each read the way its kind says."""
        return self.window(t, t)

    def window(self, t0: float, t1: float) -> dict[str, float]:
        """Every feature over [t0, t1]: lerped at t1, held at t1, maxed over the span."""
        n = self.n
        x = np.clip(t1 * self.rate, 0.0, n - 1)
        i = int(np.floor(x))
        j = min(i + 1, n - 1)
        f = x - i
        lo = int(np.clip(np.floor(t0 * self.rate), 0, n - 1))
        out: dict[str, float] = {}
        for k, (name, kind) in enumerate(self.features):
            if kind == CONTINUOUS:
                a, b = self.data[i, k], self.data[j, k]
                out[name] = float(a + (b - a) * f)
            elif kind == IMPULSE:
                out[name] = float(self.data[lo:max(j, lo + 1), k].max(initial=0.0))
            else:
                out[name] = float(self.data[i, k])
        return out

    def to_bytes(self) -> bytes:
        """The grid as little-endian float32, row-major, for the player to fetch."""
        return np.ascontiguousarray(self.data, dtype="<f4").tobytes()

    def header(self) -> dict:
        return {
            "rate": self.rate,
            "frames": self.n,
            "features": [{"name": n, "kind": k} for n, k in self.features],
        }
