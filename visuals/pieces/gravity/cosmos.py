"""The solar system as a place, and an orrery's camera on it: what the `cosmos` shader
is handed that the flat ones were not.

**The place.** The planets' phases. Their periods follow Kepler's third law for the
distances the picture draws them at, so every one of them visibly moves and the inner
ones lap the outer. The one piece of stagecraft is the alignment: a planet's starting
longitude is a free choice, so each is chosen such that the eight stand in a row, out
to the right of the Sun and half-lit, at the song's climax - wherever the measurements
put it.

**Light is instant; mass is not.** A hit still lands on its frame - but as light: a
flash, a glint, a ring. Anything heavy that moves because of a hit (the Sun swelling,
a planet swelling, the tug on the orbits) is given a rise that *ends* on the hit. That
is possible because nothing here is live: the whole song is known, so a body can begin
to move a twentieth of a second before the beat and arrive exactly on it, which is
both smoother and tighter than answering afterwards. The big transitions are slowed
the same way - the orbits fall back in over a bar and a half, not a third of a second
- because they were, it was said, too quick to appreciate.

**Acts.** Sections are merged along the song until a handful of acts remain, by how
strong each boundary is, and each act's measured character gives it a function -
approach, intimate, wide, eclipse, alignment, pull back. Nothing names a bar of this
song.

**The camera** is an orrery's: it turns about the Sun, tilts over the plane, rolls,
zooms and slides, in parallel projection, so nothing it does distorts anything. In
`fixed` mode it is the view of the picture that worked - the section's tilt and roll,
no zoom, no slide - turned once, to whichever way puts the most of the Milky Way
behind the Sun. `cinematic` mode moves it by act.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import colour, decide, direct
from .listen import RATE

CAMERA = "fixed"            # or "cinematic"; set by the command line

# ------------------------------------------------------------------------ acts


@dataclass
class Act:
    index: int
    sections: list                 # decide.Section
    function: str = "wide"
    subject: int = -1              # a planet, for the shots that have one

    @property
    def start(self) -> float:
        return self.sections[0].start

    @property
    def end(self) -> float:
        return self.sections[-1].end

    @property
    def bars(self) -> int:
        return sum(s.bars for s in self.sections)

    def mean(self, name: str) -> float:
        w = np.array([s.bars for s in self.sections], dtype=float)
        return float((np.array([getattr(s, name) for s in self.sections]) * w).sum() / w.sum())


def boundary_strength(a: decide.Section, b: decide.Section, drops: list[dict]) -> float:
    """How much changes across a boundary: loudness, the kick, the voice, the sound's
    family (its hue is its direction among the sections), and whether the floor
    returns there."""
    hue = abs(((a.hue - b.hue + 0.5) % 1.0) - 0.5) * 2.0
    drop = max((d["strength"] for d in drops if abs(d["t"] - b.start) < 0.5), default=0.0)
    return (abs(a.loud - b.loud) / 0.3 + abs(a.drive - b.drive) + 0.7 * abs(a.voiced - b.voiced)
            + 0.8 * hue + 0.6 * drop)


def find_acts(sections: list, drops: list[dict], most: int = 7, fewest: int = 4,
              min_bars: int = 12) -> list[Act]:
    groups = [[s] for s in sections if s.state != "silent" or s.bars >= 4]
    if sections and sections[0].state == "silent" and sections[0].bars < 4 and groups:
        groups[0].insert(0, sections[0])

    def too_short(g):
        return sum(s.bars for s in g) < min_bars

    while len(groups) > fewest:
        if len(groups) <= most and not any(too_short(g) for g in groups):
            break
        strength = [boundary_strength(groups[i][-1], groups[i + 1][0], drops) for i in range(len(groups) - 1)]
        # a short act gives up its weaker side first; otherwise the weakest boundary goes
        short = [i for i, g in enumerate(groups) if too_short(g)]
        if short:
            g = short[0]
            left = strength[g - 1] if g > 0 else np.inf
            right = strength[g] if g < len(groups) - 1 else np.inf
            k = g - 1 if left <= right else g
        else:
            k = int(np.argmin(strength))
        groups[k:k + 2] = [groups[k] + groups[k + 1]]
    acts = [Act(i, g) for i, g in enumerate(groups)]

    # what each act is for, from what it measures
    energy = np.array([0.5 * (a.mean("loud") - 0.6) / 0.3 + 0.5 * a.mean("drive") for a in acts])
    n = len(acts)
    acts[0].function, acts[-1].function = "approach", "pullback"
    inner = list(range(1, n - 1))
    if inner:
        late = [i for i in inner if acts[i].start > 0.45 * acts[-1].end] or inner
        climax = max(late, key=lambda i: energy[i] + 0.25 * acts[i].mean("voiced"))
        acts[climax].function = "alignment"
        rest = [i for i in inner if i != climax]
        hush = [i for i in rest if acts[i].start > 0.35 * acts[-1].end and i < climax]
        if hush:
            acts[max(hush, key=lambda i: acts[i].mean("void") + 0.5 * (1 - acts[i].mean("drive")))].function = "eclipse"
        subjects = iter((2, 5, 4, 3))                     # Earth, then Saturn, Jupiter, Mars
        for i in rest:
            if acts[i].function == "wide" and acts[i].mean("drive") < 0.4 and acts[i].mean("voiced") > 0.45:
                acts[i].function = "intimate"
        for a in acts:
            if a.function in ("intimate", "eclipse"):
                a.subject = next(subjects, 2)                 # a planet index, Mercury = 0
    return acts


# ---------------------------------------------------------------------- pulses


def anticipating_pulse(times: np.ndarray, amps: np.ndarray, n: int, rise: float, decay: float) -> np.ndarray:
    """A pulse per event that *finishes rising* on the event: a raised-cosine ease
    over `rise` seconds before it, an exponential fall after. Overlaps take the max."""
    out = np.zeros(n)
    k_rise, k_tail = int(rise * RATE), int(6 * decay * RATE)
    up = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, k_rise + 1))
    down = np.exp(-np.arange(1, k_tail + 1) / (decay * RATE))
    shape = np.concatenate([up, down])
    for t, a in zip(times, amps):
        i0 = int(round(t * RATE)) - k_rise
        lo, hi = max(i0, 0), min(i0 + len(shape), n)
        if hi > lo:
            out[lo:hi] = np.maximum(out[lo:hi], a * shape[lo - i0:hi - i0])
    return out


def smootherstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * x * (x * (x * 6 - 15) + 10)


# ---------------------------------------------------------------------- camera


def best_turn(tilt: float, catalogue_dir) -> float:
    """Which way to face: the turn that puts the most of the Milky Way in the frame,
    weighted toward the middle of it, at this tilt. Measured on NASA's map with the
    shader's own projection - the sky is where it is; all that can be chosen is where to
    stand."""
    from . import sky

    image = catalogue_dir / "milkyway_2020_4k_gal_print.jpg"
    if not image.exists():
        return 0.0
    field = sky.milky_way(image)
    g = sky.galactic_frame()
    pole, centre, across = (np.array(g[k]) for k in ("pole", "centre", "across"))
    e, c = tilt, np.sqrt(1 - tilt * tilt)
    ys, xs = np.meshgrid(np.linspace(-0.5, 0.5, 27), np.linspace(-0.889, 0.889, 48), indexing="ij")
    v = np.stack([xs, ys, np.full_like(xs, -1.30)], axis=-1)
    v /= np.linalg.norm(v, axis=-1, keepdims=True)
    u_, v_, up = v[..., 0], v[..., 1] * e - v[..., 2] * c, v[..., 1] * c + v[..., 2] * e
    weight = np.exp(-(xs ** 2 + ys ** 2) / 0.35)
    best, best_score = 0.0, -1.0
    for turn in np.radians(np.arange(0, 360, 3)):
        ct, st = np.cos(-turn), np.sin(-turn)
        x, z = ct * u_ - st * v_, st * u_ + ct * v_
        d = np.stack([x, up, z], axis=-1)
        b = np.arcsin(np.clip(d @ pole, -1, 1))
        l = np.arctan2(d @ across, d @ centre)
        col = ((0.5 - l / (2 * np.pi)) * field.shape[1]).astype(int) % field.shape[1]
        row = np.clip(((0.5 - b / np.pi) * field.shape[0]).astype(int), 0, field.shape[0] - 1)
        score = float((field[row, col] * weight).sum())
        if score > best_score:
            best, best_score = float(turn), score
    return best


# ------------------------------------------------------------------------ bake


def bake(got: dict, mod: tuple[dict, dict] | None) -> direct.Channels:
    """Everything `direct` bakes, plus the place and the camera."""
    from . import ROOT, shader_cosmos

    ch = direct.direct(got, mod)
    a, meta = got["arrays"], got["meta"]
    n, period = int(meta["n"]), float(meta["period"])
    bar = 4 * period
    t = np.arange(n) / RATE
    col = {name: ch.data[:, i].astype(np.float64) for i, name in enumerate(ch.names)}
    extra: dict[str, tuple[str, np.ndarray]] = {}

    acts = find_acts(ch.sections, ch.drops)
    hold = col["uHold"]

    # the orbits widen as the floor goes and fall back when it returns - over a bar and
    # a half, heavily damped: it is the whole solar system moving, and it should look it
    extra["uSpreadSlow"] = (direct.LERP, direct.spring(1.0 + 0.70 * (1.0 - hold), hz=0.45, damping=0.85))

    # mass does not jump: the Sun and the planets swell *into* their hits
    kt, ka = a["ev_kick_t"], a["ev_kick_amp"]
    strong = ka > 0.5
    extra["uSunPulse"] = (direct.LERP, anticipating_pulse(kt[strong], np.clip(ka[strong], 0, 1.2), n, 0.055, 0.13))
    for slot in range(direct.N_SATS):
        tt = np.unique(col[f"uNoteT{slot}"])
        tt = tt[tt > -100]
        amp = np.array([col[f"uNoteA{slot}"][min(int(np.ceil(x * RATE)), n - 1)] for x in tt])
        extra[f"uSwell{slot}"] = (direct.LERP, anticipating_pulse(tt, np.clip(amp, 0, 1.2), n, 0.045, 0.20))

    # ---- the camera -----------------------------------------------------------------
    tilt, roll = col["uTilt"].copy(), col["uIncl"].copy()
    turn = np.full(n, best_turn(float(np.median(tilt)), ROOT / "visuals" / "cache" / "catalogues"))
    # the re-entry pushes in and lets go - eased, and four times slower than it was
    push = anticipating_pulse(np.array([d["t"] for d in ch.drops]),
                              np.array([d["strength"] for d in ch.drops]), n, 0.12, 1.1)
    span = 1.0 - 0.070 * push - 0.008 * extra["uSunPulse"][1]
    cx, cy = np.zeros(n), np.zeros(n)
    if CAMERA == "cinematic":
        turn, tilt, roll, span, cx, cy = cinematic(acts, t, bar, turn, tilt, roll, span)
    for name, track in (("uCamTurn", turn), ("uCamTilt", tilt), ("uCamRoll", roll), ("uCamSpan", span),
                        ("uCamX", cx), ("uCamY", cy)):
        extra[name] = (direct.LERP, track)

    # ---- the planets' phases, and the alignment -------------------------------------------
    # Kepler, for the distances drawn; and each starting longitude chosen so that at the
    # climax they stand in a row to the right of the Sun, in the plane of the screen, half-lit
    rate = np.array([(0.250 / (0.250 + s_)) ** 1.5 for s_ in shader_cosmos.ORBIT_STEP])
    climax = next((x for x in acts if x.function == "alignment"), acts[len(acts) // 2])
    t_c = climax.start + 0.30 * (climax.end - climax.start)
    clock = col["uOrbitSlow"]
    clock_c, turn_c = float(np.interp(t_c, t, clock)), float(np.interp(t_c, t, turn))
    fan = np.radians((np.arange(shader_cosmos.N_PLANETS) - 3.5) * 1.4)
    for i in range(shader_cosmos.N_PLANETS):
        extra[f"uPh{i}"] = (direct.LERP, rate[i] * (clock - clock_c) + (fan[i] - turn_c) / (2 * np.pi))

    names = ch.names + list(extra)
    kinds = ch.kinds + [extra[k][0] for k in extra]
    data = np.concatenate([ch.data, np.stack([extra[k][1] for k in extra], axis=1).astype(np.float32)], axis=1)
    out = direct.Channels(names, kinds, data, ch.drops, ch.duration, ch.sections, ch.info)
    out.acts = acts
    out.climax = t_c
    return out


def cinematic(acts, t, bar, turn, tilt, roll, span):
    """Not yet. The shots are to be agreed from a shot sheet before anything is animated;
    until then cinematic is the fixed camera."""
    return turn, tilt, roll, span, np.zeros(len(t)), np.zeros(len(t))
