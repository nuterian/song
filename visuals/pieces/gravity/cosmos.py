"""The solar system as a place, and a camera moving through it: everything the 3D
shader is handed that the flat ones were not.

**The place.** The Sun and the eight planets, with their real periods relative to
one another and their real order and character. Distances and sizes are compressed
(a power of about a third on the distances, a little more on the radii), as every orrery
compresses them, because drawn to scale the solar system is a point of light and a
great deal of nothing - and hard enough that the Sun is still the biggest thing in a
frame that holds Saturn. One Earth year is sixty-four bars, so Mercury goes round in
half a minute and Neptune, rightly, hardly moves at all.

**Light is instant; mass is not.** A hit still lands on its frame - but as light: a
flash, a glint, a ring. Anything heavy that moves because of a hit (the Sun swelling,
a planet swelling) is given a rise that *ends* on the hit. That is possible because
nothing here is live: the whole song is known, so a body can begin to move a twentieth
of a second before the beat and arrive exactly on it, which is both smoother and
tighter than answering afterwards. The big transitions are slowed the same way - the
orbits fall back in over a bar and a half, not a third of a second - because they
were, it was said, too quick to appreciate.

**Acts.** Sections are merged along the song until a handful of acts remain, by how
strong each boundary is; each act's measured character gives it a function - approach,
intimate, wide, eclipse, alignment, pull back - and each function is a way of moving
the camera. Nothing names a bar of this song. The one piece of stagecraft is the
alignment: the planets' starting longitudes are free, so they are chosen such that the
planets draw into line at the song's climax, wherever the measurements put it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import colour, decide, direct
from .listen import RATE

EARTH_YEAR_BARS = 64.0

#            name       a (AU)  period (yr)  radius (Earth = 1)
PLANETS = (("Mercury",  0.387,    0.2408,      0.383),
           ("Venus",    0.723,    0.6152,      0.949),
           ("Earth",    1.000,    1.0000,      1.000),
           ("Mars",     1.524,    1.8808,      0.532),
           ("Jupiter",  5.203,   11.862,      11.21),
           ("Saturn",   9.537,   29.457,       9.45),
           ("Uranus",  19.19,    84.01,        4.01),
           ("Neptune", 30.07,   164.8,         3.88))
N_PLANETS = len(PLANETS)
EARTH_RADIUS = 0.036                      # world units; Earth's orbit is 1
SUN_RADIUS = 0.22
DISTANCE_POWER = 0.35                     # how hard distances are compressed: Neptune at 3.3, not 30

# Which planet a note lights. Notes are ranked low to high into eight slots; big bodies
# take the low ones, as big things do.
SLOT_TO_PLANET = (4, 5, 7, 6, 2, 1, 3, 0)


def orbit_radius(a_au: float) -> float:
    return float(a_au ** DISTANCE_POWER)


def body_radius(r_earths: float) -> float:
    return float(EARTH_RADIUS * r_earths ** 0.45)


ORBIT = np.array([orbit_radius(p[1]) for p in PLANETS])
RADIUS = np.array([body_radius(p[3]) for p in PLANETS])
PERIOD = np.array([p[2] for p in PLANETS])


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
                a.subject = next(subjects, 2)
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


def _orbit_cam(centre: np.ndarray, az: np.ndarray, el: np.ndarray, dist: np.ndarray) -> np.ndarray:
    return centre + dist[:, None] * np.stack([np.cos(el) * np.cos(az), np.sin(el), np.cos(el) * np.sin(az)], axis=1)


def shot(act: Act, u: np.ndarray, planets: np.ndarray, idx: np.ndarray, fan: float) -> tuple:
    """Camera position, target and field of view through an act; u is 0..1 across it
    (and runs a little beyond both ends, so neighbouring shots can be blended)."""
    n = len(u)
    sun = np.zeros((n, 3))
    e = smootherstep(u)
    deg = np.radians
    if act.function == "approach":
        return (_orbit_cam(sun, deg(-150 + 35 * e), deg(14 + 10 * e), 11.0 - 6.0 * e), sun, np.full(n, 38.0))
    if act.function == "pullback":
        return (_orbit_cam(sun, deg(60 + 50 * e), deg(28 + 30 * e), 4.8 * np.exp(2.3 * e)), sun, np.full(n, 40.0))
    if act.function == "alignment":
        # Seen from the side, not from beyond Neptune looking in: from out there every
        # planet shows its night side. Side on, they are a row of half-lit worlds with the
        # Sun at one end of it.
        along = np.array([np.cos(fan), 0.0, np.sin(fan)])
        mid = sun + along * 1.55
        az = fan + deg(90.0 - 16.0 * (e - 0.4))
        return (_orbit_cam(mid, az, deg(9.0 + 7.0 * e), 5.2 - 0.7 * e), mid, np.full(n, 36.0))
    if act.function in ("intimate", "eclipse"):
        P = planets[idx, act.subject]                               # (n, 3)
        out_dir = P / np.linalg.norm(P, axis=1, keepdims=True)
        side = np.stack([-out_dir[:, 2], np.zeros(n), out_dir[:, 0]], axis=1)
        r = RADIUS[act.subject]
        if act.function == "eclipse":
            # behind the planet, drifting across the line to the Sun so that the Sun
            # goes behind its disc and comes out the other side
            off = (0.9 - 1.8 * e)[:, None] * r * side
            pos = P + out_dir * (7.0 * r) + off + np.array([0.0, 1.5 * r, 0.0])      # a little above the plane: in it, every ring is a line
            return pos, sun, np.full(n, 24.0)
        # round it, from its twilight side to its day side, the planet a third of the way
        # across the frame and the Sun far off across the rest of it
        ang = deg(115.0 - 75.0 * e)
        pos = P + (np.cos(ang)[:, None] * -out_dir + np.sin(ang)[:, None] * side) * (8.0 * r) \
            + np.array([0.0, 1.6 * r, 0.0])
        look = P - out_dir * (2.2 * r) - side * (1.2 * r)
        return pos, look, np.full(n, 36.0)
    # wide: the whole inner system and the giants, from above and to one side, turning slowly
    return (_orbit_cam(sun, deg(20 + 40 * e + 25 * act.index), deg(32 - 6 * e), np.full(n, 4.8)), sun, np.full(n, 40.0))


def camera_path(acts: list[Act], t: np.ndarray, planets: np.ndarray, fan: float, bar: float,
                blend_bars: float = 10.0) -> tuple:
    """Each act's shot, cross-faded into the next over `blend_bars` centred on the
    boundary. Long, because a move this large wants watching."""
    n = len(t)
    idx = np.arange(n)
    pos, tgt, fov = np.zeros((n, 3)), np.zeros((n, 3)), np.zeros(n)
    weight = np.zeros(n)
    half = 0.5 * blend_bars * bar
    for a in acts:
        u = (t - a.start) / max(a.end - a.start, 1e-6)
        p, g, f = shot(a, u, planets, idx, fan)
        rise = smootherstep((t - (a.start - half)) / (2 * half)) if a.index > 0 else np.ones(n)
        fall = 1.0 - smootherstep((t - (a.end - half)) / (2 * half)) if a.index < len(acts) - 1 else np.ones(n)
        w = rise * fall
        pos += w[:, None] * p
        tgt += w[:, None] * g
        fov += w * f
        weight += w
    weight = np.maximum(weight, 1e-6)
    return pos / weight[:, None], tgt / weight[:, None], fov / weight


# ------------------------------------------------------------------------ bake


def bake(got: dict, mod: tuple[dict, dict] | None) -> direct.Channels:
    """Everything `direct` bakes, plus the place and the camera."""
    ch = direct.direct(got, mod)
    a, meta = got["arrays"], got["meta"]
    n, period = int(meta["n"]), float(meta["period"])
    bar = 4 * period
    t = np.arange(n) / RATE
    col = {name: ch.data[:, i].astype(np.float64) for i, name in enumerate(ch.names)}
    extra: dict[str, tuple[str, np.ndarray]] = {}

    acts = find_acts(ch.sections, ch.drops)

    # the clock the planets keep: Earth years, a little slower when the floor is gone
    hold = col["uHold"]
    years = np.cumsum((0.60 + 0.40 * hold) / (EARTH_YEAR_BARS * bar)) / RATE
    extra["uYears"] = (direct.LERP, years)

    # the orbits widen as the floor goes and fall back when it returns - over a bar and
    # a half, heavily damped: it is the whole solar system moving, and it should look it
    spread = direct.spring(1.0 + 0.28 * (1.0 - hold), hz=0.42, damping=0.85)
    extra["uSpreadSlow"] = (direct.LERP, spread)

    # the alignment: choose where each planet starts so that they stand in a line, seen
    # from a camera with the galaxy's centre behind the Sun, at the climax
    climax = next((x for x in acts if x.function == "alignment"), acts[len(acts) // 2])
    t_c = climax.start + 0.30 * (climax.end - climax.start)
    fan = np.radians(87.0)
    years_c = float(np.interp(t_c, t, years))
    theta0 = fan + np.radians((np.arange(N_PLANETS) - 3.5) * 2.2) - 2 * np.pi * years_c / PERIOD
    theta = theta0[None, :] + 2 * np.pi * years[:, None] / PERIOD[None, :]
    r = ORBIT[None, :] * spread[:, None]
    planets = np.stack([r * np.cos(theta), np.zeros_like(theta), r * np.sin(theta)], axis=2)   # (n, 8, 3)
    for i in range(N_PLANETS):
        extra[f"uP{i}X"] = (direct.LERP, planets[:, i, 0])
        extra[f"uP{i}Z"] = (direct.LERP, planets[:, i, 2])

    # mass does not jump: the Sun and the planets swell *into* their hits
    kt, ka = a["ev_kick_t"], a["ev_kick_amp"]
    strong = ka > 0.5
    extra["uSunPulse"] = (direct.LERP, anticipating_pulse(kt[strong], np.clip(ka[strong], 0, 1.2), n, 0.055, 0.13))
    for slot in range(direct.N_SATS):
        tt = np.unique(col[f"uNoteT{slot}"])
        tt = tt[tt > -100]
        amp = np.array([col[f"uNoteA{slot}"][min(int(np.ceil(x * RATE)), n - 1)] for x in tt])
        extra[f"uSwell{slot}"] = (direct.LERP, anticipating_pulse(tt, np.clip(amp, 0, 1.2), n, 0.045, 0.20))

    # the re-entry pushes the lens in and lets it go - eased, and four times slower than it was
    push = anticipating_pulse(np.array([d["t"] for d in ch.drops]),
                              np.array([d["strength"] for d in ch.drops]), n, 0.12, 1.1)

    pos, tgt, fov = camera_path(acts, t, planets, fan, bar)
    fov = fov * (1.0 - 0.10 * push)
    for k, axis in enumerate("XYZ"):
        extra[f"uCam{axis}"] = (direct.LERP, pos[:, k])
        extra[f"uTgt{axis}"] = (direct.LERP, tgt[:, k])
    extra["uFov"] = (direct.LERP, fov)

    # a comet: a long ellipse, true Kepler motion, then the same compression of distance
    ce, ca, cperiod = 0.90, 9.0, 27.0
    M = 2 * np.pi * (years + 0.46 * cperiod) / cperiod
    E = M.copy()
    for _ in range(12):
        E -= (E - ce * np.sin(E) - M) / (1 - ce * np.cos(E))
    cx, cz = ca * (np.cos(E) - ce), ca * np.sqrt(1 - ce * ce) * np.sin(E)
    rr = np.hypot(cx, cz)
    squeeze = rr ** DISTANCE_POWER / np.maximum(rr, 1e-6) * spread
    lean = np.radians(200.0)
    extra["uCometX"] = (direct.LERP, squeeze * (cx * np.cos(lean) - cz * np.sin(lean)))
    extra["uCometZ"] = (direct.LERP, squeeze * (cx * np.sin(lean) + cz * np.cos(lean)))

    names = ch.names + list(extra)
    kinds = ch.kinds + [extra[k][0] for k in extra]
    data = np.concatenate([ch.data, np.stack([extra[k][1] for k in extra], axis=1).astype(np.float32)], axis=1)
    out = direct.Channels(names, kinds, data, ch.drops, ch.duration, ch.sections, ch.info)
    out.acts = acts
    return out
