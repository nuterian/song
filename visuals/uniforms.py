"""From a score and a track to the numbers a shader is handed each frame.

This is where synchronisation actually lives, and it is also where the absence of
cuts lives. The shader says what the picture is made of; these numbers say what it
*does*, and they are the only part of the system that knows a song is playing.

Everything is baked, once, onto the same 120 Hz grid the features live on.

    routing   each lane of each bar names an audio feature, a uniform to drive
              with it, a gain and an envelope. Those are stitched into one
              continuous channel per uniform: a single-pole follower whose attack
              and release change at bar boundaries but whose state carries across
              them, so a route that changes mid-song does not click. When a bar
              stops driving a uniform, its gain and release time are held and only
              the source falls to zero, so the route decays on its own envelope
              instead of being cut off at the bar line.
    levels    every section-level choice - the layer weights, the warp weights,
              the post weights, the density, the energy, the softness, the place
              in the palette - is a number, and the number *ramps* from the
              previous section's value to this one's over a window the section
              chose, on a curve the section chose, beginning on the downbeat the
              section begins on. Nothing steps. There is no frame anywhere in a
              song at which the picture is replaced rather than moved.

Baking has two consequences worth the trouble. Because the follower runs at 120 Hz
over the whole song rather than per frame, the result is frame-rate independent
and no onset can be stepped over however low the output frame rate is. And because
the grid is written to disk as one binary blob, the browser samples exactly the
numbers the mp4 sampled - the two cannot drift, since there is no second
implementation to drift from. All the player does is interpolate.
"""

from __future__ import annotations

import numpy as np

from . import schema
from .listen import CONTINUOUS, HELD, SOURCE_FEATURE, Timeline, Track

# A routing gain of 1.0 means "as loud as the feature". Two is the most a bar may
# ask for, which keeps a maxed-out gain bin emphatic without being unbounded.
GAIN_MAX = 2.0

# The uniforms a bar may drive, in the order their channels are stored.
ROUTED: tuple[str, ...] = tuple(t for t in schema.ROUTE_TARGETS if t != "none")


def _uniform_name(stem: str) -> str:
    return "u" + "".join(part.capitalize() for part in stem.split("_"))


# Section-level vectors, as (uniform name, how to get the vector from a score).
# Every one of these ramps; none of them steps.
LAYER_UNIFORMS = tuple(_uniform_name(f"layer_{n}") for n in schema.LAYERS)
WARP_UNIFORMS = ("uWarpSwirl", "uWarpRipple", "uWarpStretch")
POST_UNIFORMS = tuple(_uniform_name(f"post_{n}") for n in schema.POST_STAGES)

# Section-level scalars: the score slot each one reads, and what it means at the
# silent end of a ramp - which is the state the song opens out of and, if a score
# ever asked for it, the state it could close into.
LEVELS: tuple[tuple[str, str, float], ...] = (
    ("uDensity", "density", 0.25),
    ("uEnergy", "energy", 0.0),
    ("uSoftness", "softness", 0.85),
    ("uPaletteRotate", "palette_rotate", 0.0),
)

# The full uniform set, and how each channel is read between grid points. Order is
# the on-disk column order, so this tuple is the file format.
UNIFORMS: tuple[tuple[str, str], ...] = (
    # Sawtooths and indices are held; everything a follower or a ramp produced is
    # smooth and is interpolated. See the note beside FEATURES in listen.py.
    ("uBeats", CONTINUOUS),
    ("uBeatPhase", HELD),
    ("uBarPhase", HELD),
    ("uSectionProgress", HELD),
    ("uWord", HELD),
    ("uLine", HELD),
    ("uSpinPhase", CONTINUOUS),
    ("uPaletteShift", CONTINUOUS),
    ("uGrain", CONTINUOUS),
    ("uMorph", CONTINUOUS),          # how far through the current ramp, 0..1
) + tuple((n, CONTINUOUS) for n in LAYER_UNIFORMS + WARP_UNIFORMS + POST_UNIFORMS) \
  + tuple((n, CONTINUOUS) for n, _, _ in LEVELS) \
  + tuple((_uniform_name(t), CONTINUOUS) for t in ROUTED)

UNIFORM_NAMES: tuple[str, ...] = tuple(n for n, _ in UNIFORMS)

# Set per frame rather than read from the grid: uTime is the frame's own instant,
# and uSeed does not vary with it.
PER_FRAME: tuple[str, ...] = ("uTime", "uSeed")


def uniform_names() -> tuple[str, ...]:
    """Every uniform the composer declares, which is every one `at` produces."""
    return UNIFORM_NAMES + PER_FRAME


# --------------------------------------------------------------------------- #
# Ramps
# --------------------------------------------------------------------------- #


def curve(x: np.ndarray, kind: str) -> np.ndarray:
    """Shape a 0..1 ramp.

    All five start at 0 and end at 1, because a transition that did not arrive
    where it was going would leave the section it introduced drawn wrong for the
    rest of its length. What differs is where the movement happens: `early` is
    most of the way there before the bar is out, `late` holds and then goes,
    `sigmoid` is slow at both ends, which is the one that reads as a dissolve.
    """
    x = np.clip(x, 0.0, 1.0)
    if kind == "linear":
        return x
    if kind == "ease":
        return x * x * (3.0 - 2.0 * x)
    if kind == "early":
        return 1.0 - (1.0 - x) ** 3
    if kind == "late":
        return x ** 3
    if kind == "sigmoid":
        return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)
    raise ValueError(f"no such transition curve: {kind!r}")


def _section_vectors(score: schema.Score, i: int) -> dict[str, float]:
    """Every ramped number a section stands for, by uniform name."""
    out: dict[str, float] = {}
    scene = str(score.value("section", "scene", i) or schema.SCENES[0])
    for name, w in zip(LAYER_UNIFORMS, schema.SCENE_LAYERS[scene]):
        out[name] = float(w)
    warp = str(score.value("section", "warp", i) or "none")
    for name, w in zip(WARP_UNIFORMS, schema.WARP_WEIGHTS[warp]):
        out[name] = float(w)
    post = str(score.value("section", "post", i) or schema.POSTS[0])
    for name, w in zip(POST_UNIFORMS, schema.POST_WEIGHTS[post]):
        out[name] = float(w)
    for name, slot_name, _ in LEVELS:
        out[name] = score.unit("section", slot_name, i, default=0.5)
    return out


def _silence() -> dict[str, float]:
    """What the song ramps out of: dark, still, soft, nothing drawn."""
    out = {name: 0.0 for name in LAYER_UNIFORMS + WARP_UNIFORMS}
    out |= {name: 0.0 for name in POST_UNIFORMS}
    out |= {name: rest for name, _, rest in LEVELS}
    # The wash alone, at nothing, so the first thing the ramp does is bring up a
    # gradient rather than materialise a shape.
    out[LAYER_UNIFORMS[0]] = 0.0
    return out


def _follow(x: np.ndarray, attack: np.ndarray, release: np.ndarray, rate: int) -> np.ndarray:
    """A single-pole follower with per-sample attack and release time constants.

    Rising and falling are separate so an impulse source can be given a shape:
    `snap` is a millisecond up and sixty down, which turns a one-sample onset into
    something an eye can see without smearing it over the beat.
    """
    ka = 1.0 - np.exp(-1.0 / np.maximum(attack.astype(np.float64) * rate, 1e-9))
    kr = 1.0 - np.exp(-1.0 / np.maximum(release.astype(np.float64) * rate, 1e-9))
    y = np.empty(len(x), dtype=np.float32)
    acc = 0.0
    for i in range(len(x)):
        v = float(x[i])
        acc += (v - acc) * (ka[i] if v > acc else kr[i])
        y[i] = acc
    return y


def _hold_forward(values: np.ndarray, known: np.ndarray, fallback: float) -> np.ndarray:
    """Carry each known value forward over the samples that follow it.

    This is what lets a route decay: a bar that stops driving a uniform leaves the
    gain and the release time in place, and only the source falls to zero.
    """
    out = values.astype(np.float32, copy=True)
    idx = np.where(known, np.arange(len(known)), -1)
    idx = np.maximum.accumulate(idx)
    before = idx < 0
    out[~before] = values[idx[~before]]
    out[before] = fallback
    return out


def route_channels(score: schema.Score, track: Track, timeline: Timeline) -> np.ndarray:
    """(n, len(ROUTED)) of routed uniform values on the grid."""
    n = timeline.n
    rate = timeline.rate
    out = np.zeros((n, len(ROUTED)), dtype=np.float32)

    spans = track.bar_spans()
    t = np.arange(n) / rate
    bar_of = np.clip(np.searchsorted(spans[:, 0], t, side="right") - 1, 0, len(spans) - 1)
    default_a, default_r = schema.ROUTE_ENVELOPES[schema.ROUTE_ENVS[0]]

    for ti, target in enumerate(ROUTED):
        src = np.zeros(n, dtype=np.float32)
        gain = np.zeros(n, dtype=np.float32)
        attack = np.zeros(n, dtype=np.float32)
        release = np.zeros(n, dtype=np.float32)
        known = np.zeros(n, dtype=bool)

        for b in range(min(len(spans), score.shape.n_bars)):
            for lane in schema.ROUTE_LANES:
                if score.value("bar", f"route_target_{lane}", b) != target:
                    continue
                feature = SOURCE_FEATURE.get(
                    str(score.value("bar", f"route_source_{lane}", b) or "none")
                )
                if feature is None:
                    continue
                m = bar_of == b
                if not m.any():
                    continue
                a, r = schema.ROUTE_ENVELOPES[
                    str(score.value("bar", f"route_env_{lane}", b) or schema.ROUTE_ENVS[0])
                ]
                src[m] = timeline.column(feature)[m]
                gain[m] = GAIN_MAX * score.unit("bar", f"route_gain_{lane}", b, default=0.0)
                attack[m] = a
                release[m] = r
                known |= m

        if not known.any():
            continue
        out[:, ti] = _follow(
            src,
            _hold_forward(attack, known, default_a),
            _hold_forward(release, known, default_r),
            rate,
        ) * _hold_forward(gain, known, 0.0)
    return out


class UniformTrack:
    """The whole per-frame story for one score on one track, baked."""

    def __init__(self, score: schema.Score, track: Track) -> None:
        if score.shape.n_sections != len(track.sections):
            raise ValueError(
                f"score has {score.shape.n_sections} sections, "
                f"{track.name} has {len(track.sections)}"
            )
        if score.shape.n_bars != track.n_bars:
            raise ValueError(
                f"score has {score.shape.n_bars} bars, {track.name} has {track.n_bars}"
            )
        self.score = score
        self.track = track
        self.features = track.timeline()
        self.bar_seconds = 60.0 * track.meter / max(track.tempo, 1e-6)
        self.seed = float((score.seed or 0) % 4096)
        self.grid = self._bake()

    # -- the ramp --------------------------------------------------------- #

    def transition(self, i: int) -> tuple[float, str]:
        """How long section `i` takes to arrive, in seconds, and on what curve."""
        bars = float(self.score.value("section", "transition_bars", i) or 2)
        kind = str(self.score.value("section", "transition_curve", i) or "ease")
        # Never longer than the section it introduces: a ramp still going when the
        # next one starts would mean the section never actually got there.
        s = self.track.sections[i]
        return min(bars * self.bar_seconds, max(s.end - s.start, 1e-3)), kind

    def _ramped(self, t: np.ndarray) -> tuple[dict[str, np.ndarray], np.ndarray]:
        """Every section-level uniform, ramped across the whole song.

        Each section's target vector is held until the next section's downbeat,
        and then the ramp carries it to the next one. The first section ramps out
        of silence, so the song opens rather than starting.
        """
        names = list(LAYER_UNIFORMS + WARP_UNIFORMS + POST_UNIFORMS) + \
            [n for n, _, _ in LEVELS]
        targets = [_section_vectors(self.score, s.index) for s in self.track.sections]
        out = {name: np.empty(len(t), dtype=np.float32) for name in names}
        morph = np.ones(len(t), dtype=np.float32)

        for s in self.track.sections:
            m = (t >= s.start) & (t < s.end)
            if s.index == len(self.track.sections) - 1:
                m |= t >= s.start
            if not m.any():
                continue
            window, kind = self.transition(s.index)
            x = curve(np.clip((t[m] - s.start) / window, 0.0, 1.0), kind)
            morph[m] = x.astype(np.float32)
            previous = targets[s.index - 1] if s.index > 0 else _silence()
            for name in names:
                a, b = previous[name], targets[s.index][name]
                out[name][m] = (a + (b - a) * x).astype(np.float32)
        return out, morph

    def _bake(self) -> Timeline:
        f = self.features
        n, rate = f.n, f.rate
        t = np.arange(n) / rate
        col: dict[str, np.ndarray] = {}

        for name in ("beats", "beat_phase", "bar_phase", "section_progress", "word", "line"):
            col[_uniform_name(name)] = f.column(name)

        routed = route_channels(self.score, self.track, f)
        for i, target in enumerate(ROUTED):
            col[_uniform_name(target)] = routed[:, i]
        # Spin is a rate, so the shader is given its running integral: an angle
        # that only ever moves forward, which is what a rotation wants.
        spin = routed[:, ROUTED.index("spin")]
        col["uSpinPhase"] = (np.cumsum(spin, dtype=np.float64) / rate).astype(np.float32)

        ramped, morph = self._ramped(t)
        col |= ramped
        col["uMorph"] = morph

        col["uPaletteShift"] = np.full(n, self.score.unit("song", "palette_shift", 0, 0.0), "f4")
        col["uGrain"] = np.full(n, self.score.unit("song", "grain", 0, 0.0), "f4")

        data = np.stack([col[name] for name in UNIFORM_NAMES], axis=1).astype(np.float32)
        return Timeline(rate, UNIFORMS, data)

    # -- reading it ------------------------------------------------------- #

    @property
    def duration(self) -> float:
        return self.track.duration

    def section_at(self, t: float) -> int:
        return self.track.section_of(t)

    def at(self, t: float, dt: float = 1.0 / 60.0) -> dict[str, float]:
        """The uniform dictionary for the frame at `t`.

        `dt` is accepted and ignored: every channel is already followed or ramped
        at 120 Hz, so there is nothing left for a frame's span to catch. It stays
        in the signature because callers reason in frames.
        """
        u = self.grid.at(t)
        u["uTime"] = float(t)
        u["uSeed"] = self.seed
        return u

    # -- what the player needs -------------------------------------------- #

    def frames_bytes(self) -> bytes:
        """The baked grid as little-endian float32, row-major."""
        return self.grid.to_bytes()

    def plan(self) -> dict:
        """Everything the browser needs except the audio and the shader source."""
        return {
            "version": schema.VERSION,
            "track": self.track.name,
            "duration": self.duration,
            "tempo": self.track.tempo,
            "meter": self.track.meter,
            "seed": self.seed,
            "grid": self.grid.header(),
            "per_frame": list(PER_FRAME),
            "sections": [
                {
                    "index": s.index,
                    "name": s.name,
                    "start": s.start,
                    "end": s.end,
                    "scene": self.score.value("section", "scene", s.index),
                    "transition_bars": self.score.value("section", "transition_bars", s.index),
                    "transition_curve": self.score.value("section", "transition_curve", s.index),
                    "transition_seconds": self.transition(s.index)[0],
                }
                for s in self.track.sections
            ],
            "score": self.score.to_dict(),
        }
