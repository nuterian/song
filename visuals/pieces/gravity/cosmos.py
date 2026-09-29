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
zooms and slides, in parallel projection, so nothing it does distorts anything. There
are three of it, all baked, so a player can switch between them while it plays:
`static` is the view of the picture that worked, turned once to whichever way puts the
most of the Milky Way behind the Sun; `cinematic` takes a shot per act; `hybrid` is the
static view kept gently moving, leaning part of the way toward the cinematic one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import colour, decide, direct
from .listen import RATE

CAMERA = "static"           # which camera the plain uCam* channels carry: static, hybrid or cinematic

# ------------------------------------------------------------------------ acts


@dataclass
class Act:
    index: int
    sections: list                 # decide.Section
    function: str = "wide"
    subject: int = -1              # a planet, for the shots that have one
    t0: float | None = None        # an act the direction sheet drew: its own bounds
    t1: float | None = None

    @property
    def start(self) -> float:
        return self.sections[0].start if self.t0 is None else self.t0

    @property
    def end(self) -> float:
        return self.sections[-1].end if self.t1 is None else self.t1

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


def arriving(x: np.ndarray, before: float, after: float) -> np.ndarray:
    """A level followed the way a mass would, by something that knows the score.

    Where `x` falls, the output has *finished* falling at that moment, having begun
    `before` seconds ahead of it; where `x` rises, the output begins to rise at that
    moment and takes `after` seconds over it. Both are S-curves with no corner in them
    (a box filter run twice). So the solar system has drawn itself in by the time the
    floor comes back, lands on the downbeat, and lets go slowly when the floor leaves.
    """
    def eased(width: float, shift: float) -> np.ndarray:
        k = max(int(width * RATE / 2), 1)
        pad = 2 * k + int(abs(shift) * RATE) + 2
        y = np.pad(x.astype(np.float64), pad, mode="edge")
        box = np.ones(k) / k
        y = np.convolve(np.convolve(y, box, mode="same"), box, mode="same")
        j = pad + np.arange(len(x)) + int(round(shift * RATE))
        return y[j]
    return np.minimum(eased(before, 0.5 * before), eased(after, -0.5 * after))


def flares(note_t: np.ndarray, note_a: np.ndarray, note_k: np.ndarray, beats: np.ndarray, n: int, bar: float,
           every_bars: float = 2.0, leak_bars: float = 4.0, rest_bars: float = 0.0) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Integrate and fire. Each bass note adds its loudness to a charge that leaks away
    over `leak_bars`; when the charge is over the threshold *and a note lands on a beat*,
    it fires on that note and the charge is spent. So a flare is always a played note, on
    the beat, and it comes when the bass has been insisting for a while.

    The threshold is not a number chosen for this song. It is found, by bisection, as the
    one at which the song fires about once in `every_bars` bars of the time its bass line
    is actually playing - so a sparse bass line and a relentless one both get flares that
    are events, neither a strobe nor a rarity.

    Returns the flares' times, sizes (0..1) and places (the note's place round the limb),
    and the charge as a level 0..1 at RATE: what the corona shows building.
    """
    if len(note_t) == 0:
        return np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(n)
    amp = note_a / max(float(np.percentile(note_a, 90)), 1e-6)
    on_beat = np.abs(note_t[:, None] - beats[None, :]).min(axis=1) < 0.040 if len(beats) else np.ones(len(note_t), bool)
    tau = leak_bars * bar
    # the time the bass is playing: bars that have a note in them
    playing = len(np.unique(np.floor(note_t / bar))) * bar
    want = max(playing / (every_bars * bar), 1.0)

    def run(theta: float):
        q, last, fired, spent, since = 0.0, note_t[0], [], [], -1e9
        for i, (t, a_) in enumerate(zip(note_t, amp)):
            q = q * np.exp(-(t - last) / tau) + a_
            last = t
            if q >= theta and on_beat[i] and t - since >= rest_bars * bar:
                since = t
                fired.append(i)
                spent.append(q)
                q = 0.0
        return fired, spent

    lo, hi = 0.5, float(amp.sum())
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if len(run(mid)[0]) > want:
            lo = mid
        else:
            hi = mid
    theta = 0.5 * (lo + hi)
    fired, spent = run(theta)
    fired = np.array(fired, dtype=int)
    # the charge, as it would be read off a gauge: 0 empty, 1 at the threshold
    level = np.zeros(n)
    q, last, j = 0.0, 0.0, 0
    order = np.argsort(note_t)
    idx = np.ceil(note_t[order] * RATE).astype(int)
    steps = np.zeros(n)
    fire_at = set(fired.tolist())
    t_axis = np.arange(n) / RATE
    decay = np.exp(-1.0 / (tau * RATE))
    note_at = {}
    for i, k in zip(order, idx):
        if 0 <= k < n:
            note_at.setdefault(int(k), []).append(int(i))
    for k in range(n):
        q *= decay
        for i in note_at.get(k, ()):
            q += amp[i]
            if i in fire_at:
                q = 0.0
        level[k] = q
    size = np.clip(np.array(spent) / max(theta, 1e-6), 1.0, 1.6) / 1.6 if len(spent) else np.zeros(0)
    return note_t[fired], size, note_k[fired], np.clip(level / max(theta, 1e-6), 0.0, 1.0)


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


def acts_from(sheet: dict, sections: list, bar_t: np.ndarray, duration: float) -> list[Act]:
    """The direction sheet's acts, bounded exactly as the director's own would be."""
    from .sheet import PLANETS, span

    acts = []
    for i, entry in enumerate(sheet["acts"]):
        t0, t1 = span(bar_t, duration, entry["bars"])
        mine = [s for s in sections if s.bar0 < entry["bars"][1] and s.bar1 > entry["bars"][0]] or sections[:1]
        subject = PLANETS.index(entry["subject"]) if entry.get("subject") in PLANETS else -1
        acts.append(Act(i, mine, entry["shot"], subject, t0, t1))
    return acts


def bake(got: dict, mod: tuple[dict, dict] | None, sheet: dict | None = None) -> direct.Channels:
    """Everything `direct` bakes, plus the place and the camera. With a direction sheet,
    its decisions are the ones made (sheet.py); without, the director's own."""
    from . import ROOT, shader_cosmos
    from .sheet import FEEL

    feel = {k: v[0] for k, v in FEEL.items()} | ((sheet or {}).get("feel") or {})
    ch = direct.direct(got, mod, reentries=sheet["reentries"] if sheet else None)
    a, meta = got["arrays"], got["meta"]
    n, period = int(meta["n"]), float(meta["period"])
    bar = int(meta.get("meter", 4)) * period
    t = np.arange(n) / RATE
    col = {name: ch.data[:, i].astype(np.float64) for i, name in enumerate(ch.names)}
    extra: dict[str, tuple[str, np.ndarray]] = {}

    acts = acts_from(sheet, ch.sections, a["bar_t"], float(meta["duration"])) if sheet else find_acts(ch.sections, ch.drops)
    hold = col["uHold"]

    # The orbits widen when the floor goes and draw in when it returns - and it is the
    # whole solar system moving, so it moves like one. It knows the score: it has drawn in
    # by the downbeat the floor lands on, having taken the bar before to do it; and when
    # the floor leaves it takes two bars to let go. A re-entry is that, in three parts:
    # the draw-in, the hit (which is light: the shock, the flash, the sky), and a release -
    # the system a little tighter than it rests, easing back over the next two bars.
    drop_t = np.array([d["t"] for d in ch.drops])
    drop_a = np.array([d["strength"] for d in ch.drops])
    reentry = anticipating_pulse(drop_t, drop_a, n, bar, 1.1 * bar)
    wide = arriving(1.0 - hold, bar, 2 * bar)
    spread = 1.0 + feel["orbits_breathe"] * wide - 0.055 * reentry

    # mass does not jump: the Sun and the planets swell *into* their hits
    kt, ka = a["ev_kick_t"], a["ev_kick_amp"]
    strong = ka > 0.5
    from . import dance, ease
    extra["uSunPulse"] = (direct.LERP, ease.envelope(kt[strong], np.clip(ka[strong], 0, 1.2), n, 0.085, 0.36))
    slot_notes = []
    for slot in range(direct.N_SATS):
        tt = np.unique(col[f"uNoteT{slot}"])
        tt = tt[tt > -100]
        amp = np.array([col[f"uNoteA{slot}"][min(int(np.ceil(x * RATE)), n - 1)] for x in tt])
        slot_notes.append((tt, amp))
    planet_notes = dance.balance(slot_notes, shader_cosmos.SLOT_TO_PLANET)     # every planet plays

    # ---- nothing is instant: the levels that used to snap are eased, and each peaks on its sound ----
    extra["uKickE"] = (direct.LERP, ease.envelope(kt[strong], np.clip(ka[strong], 0, 1.2), n, 0.085, 0.34))
    sy_t, sy_a = a["ev_syllable_t"].astype(np.float64), a["ev_syllable_amp"].astype(np.float64)
    extra["uSyllE"] = (direct.LERP, ease.envelope(sy_t[sy_a > 0.25], np.clip(sy_a[sy_a > 0.25], 0, 1), n, 0.085, 0.42))
    hat_t = np.unique(col["uHatT"]); hat_t = hat_t[hat_t > -100]
    at = np.minimum(np.ceil(hat_t * RATE).astype(int), n - 1)
    hat_a, hat_k = col["uHatA"][at], np.round(col["uHatK"][at]).astype(int) % 3
    for k in range(3):
        extra[f"uHatE{k}"] = (direct.LERP, ease.envelope(hat_t[hat_k == k], hat_a[hat_k == k], n, 0.090, 0.42))
    cr_t = np.unique(col["uCrashT"]); cr_t = cr_t[cr_t > -100]
    extra["uCrashE"] = (direct.LERP, ease.envelope(cr_t, col["uCrashA"][np.minimum(np.ceil(cr_t * RATE).astype(int), n - 1)], n, 0.12, 2.4))

    # ---- the bass line's notes are prominences; the voice's syllables, gusts of solar wind -------
    # Where round the limb a prominence stands is its pitch - the twelve pitch classes round
    # the clock from the tonic at twelve o'clock, so a bass line draws its own shape on the
    # Sun. The models say what was played; the stem says when.
    m_arr = mod[0] if mod else {}
    bt, ba = a["ev_bass_note_t"].astype(np.float64), a["ev_bass_note_amp"].astype(np.float64)
    where = np.arange(len(bt)) * 0.381966 % 1.0                      # no transcription: golden-angle steps
    if "bass_t" in m_arr and len(m_arr["bass_t"]):
        # the note that is sounding when the attack lands - or, failing that, the nearest one
        mt, me = m_arr["bass_t"], m_arr.get("bass_end", m_arr["bass_t"] + 0.2)
        j = np.clip(np.searchsorted(mt, bt + 0.06) - 1, 0, len(mt) - 1)
        sounding = (mt[j] <= bt + 0.06) & (me[j] >= bt - 0.03)
        near = np.clip(np.searchsorted(mt, bt), 1, len(mt) - 1)
        near = np.where(np.abs(mt[near - 1] - bt) < np.abs(mt[near] - bt), near - 1, near)
        j = np.where(sounding, j, near)
        heard = sounding | (np.abs(mt[j] - bt) < 0.25)
        tonic = int((mod[1].get("key") or {}).get("tonic", 0)) if len(mod) > 1 and isinstance(mod[1], dict) else 0
        where = np.where(heard, ((np.round(m_arr["bass_midi"][j]).astype(int) - tonic) % 12) / 12.0, where)
    keep = ba > 0.12
    PT, PA = direct.held_events(bt[keep], np.clip(0.25 + 0.75 * ba[keep] / max(np.percentile(ba, 95), 1e-6), 0, 1), n, shader_cosmos.N_PROM)
    _, PK = direct.held_events(bt[keep], where[keep], n, shader_cosmos.N_PROM)
    yt, ya = a["ev_syllable_t"].astype(np.float64), a["ev_syllable_amp"].astype(np.float64)
    keep = ya > 0.25
    WT, WA = direct.held_events(yt[keep], np.clip(ya[keep], 0, 1), n, shader_cosmos.N_WIND)
    _, WK = direct.held_events(yt[keep], (np.arange(keep.sum()) * 0.381966 + 0.11) % 1.0, n, shader_cosmos.N_WIND)
    for k in range(shader_cosmos.N_PROM):
        extra[f"uPromT{k}"], extra[f"uPromA{k}"], extra[f"uPromK{k}"] = (direct.HOLD, PT[:, k]), (direct.HOLD, PA[:, k]), (direct.HOLD, PK[:, k])
    for k in range(shader_cosmos.N_WIND):
        extra[f"uWindT{k}"], extra[f"uWindA{k}"], extra[f"uWindK{k}"] = (direct.HOLD, WT[:, k]), (direct.HOLD, WA[:, k]), (direct.HOLD, WK[:, k])
    # ---- charge, and the flare ----------------------------------------------------------------------
    # The bass line charges the corona; past a threshold it discharges - a flare, thrown out
    # along the plane from where that note's prominence stands, which crosses the system
    # and strikes whatever planets lie in its way. The threshold is the song's own: see
    # `flares`. The charge is drawn (the corona stands further out and hotter as it builds,
    # and snaps back on the discharge), so a flare is seen coming.
    fl_t, fl_a, _, charge = flares(bt, ba, where, a["beats"].astype(np.float64), n, bar, every_bars=feel["flares_every_bars"])
    flare_times, flare_sizes = fl_t, fl_a           # where each is thrown is decided below, once the planets are placed
    extra["uCharge"] = (direct.LERP, ease.smooth(charge, 0.30))       # it is spent over a third of a second, not in a sample

    # the bar before a re-entry, the sky holds its breath: up over that bar, gone on the downbeat
    extra["uBrace"] = (direct.LERP, ease.envelope(drop_t, np.clip(drop_a, 0, 1), n, bar, 0.45, rise=ease.EASE_SLOW))
    extra["uOpened"] = (direct.LERP, ease.envelope(drop_t, np.clip(drop_a, 0, 1), n, 0.16, 2 * bar))
    extra["uFlashE"] = (direct.LERP, ease.envelope(drop_t, np.clip(drop_a, 0, 1), n, 0.12, 0.9))

    # ---- where the planets are: the real orbits (see `orrery`), and the alignment ---------------
    # Each planet runs on its own oval, tipped as it is, by Kepler's equation; its mean
    # anomaly at the climax is chosen so that *there* the eight stand in a row to the right
    # of the Sun, in the plane of the screen, half-lit. Every camera agrees on its heading at
    # that moment (`turn0`), so the alignment is one event, the same in all of them.
    from . import orrery

    tilt_s, roll_s = col["uTilt"].copy(), col["uIncl"].copy()
    turn0 = best_turn(float(np.median(tilt_s)), ROOT / "visuals" / "cache" / "catalogues")
    climax = next((x for x in acts if x.function == "alignment"), acts[len(acts) // 2])
    t_c = climax.start + 0.30 * (climax.end - climax.start)
    clock = col["uOrbitSlow"]                               # in revolutions of Mercury
    clock_c = float(np.interp(t_c, t, clock))
    fan = np.radians((np.arange(shader_cosmos.N_PLANETS) - 3.5) * 1.4)
    rates = orrery.rate()
    lon, off, rise = [], [], []
    for i in range(shader_cosmos.N_PLANETS):
        at_climax = orrery.mean_from_true(fan[i] - turn0 - orrery.PERI[i], orrery.ECC[i])
        l_, d_, z_ = orrery.track(orrery.ELEMENTS[i], at_climax + 2 * np.pi * rates[i] * (clock - clock_c))
        lon.append(l_); off.append(d_); rise.append(z_)
        extra[f"uPh{i}"] = (direct.LERP, l_ / (2 * np.pi))
        extra[f"uPd{i}"] = (direct.LERP, d_)
        extra[f"uPz{i}"] = (direct.LERP, z_)
    lon, off, rise = np.stack(lon, 1), np.stack(off, 1), np.stack(rise, 1)
    phases = lon / (2 * np.pi)
    # Pluto: no part in the row - it is where it is
    pl_l, pl_d, pl_z = orrery.track(orrery.PLUTO, 3.9 + 2 * np.pi * float(orrery.rate(orrery.PLUTO[6])) * (clock - clock_c))
    extra["uPlutoPh"], extra["uPlutoD"], extra["uPlutoZ"] = (direct.LERP, pl_l / (2 * np.pi)), (direct.LERP, pl_d), (direct.LERP, pl_z)

    # The Sun cues its players. A discharge is thrown at the planet that has the tune - the
    # one whose note sounded last - so the flare crosses the system *to* someone, who answers.
    aim, targets, strikes = [], [], []
    for ft, fs in zip(flare_times, flare_sizes):
        k = min(int(np.ceil(ft * RATE)), n - 1)
        last = [float(pt[pt <= ft][-1]) if np.any(pt <= ft) else -1e9 for pt, _ in planet_notes]
        planet = int(np.argmax(last)) if max(last) > ft - 4 * bar else 4
        targets.append(planet)
        aim.append((lon[k, planet] / (2 * np.pi)) % 1.0)
        reach = (max(0.255, 0.156 / float(np.clip(tilt_s[k], 0.2, 0.98))) + off[k, planet]) * spread[k]
        strikes.append((float(ft) + max(reach - 0.09 - 0.05, 0.0) / 0.95, planet, float(fs)))
    FT, FA = direct.held_events(flare_times, flare_sizes, n, shader_cosmos.N_FLARE)
    _, FK = direct.held_events(flare_times, np.array(aim), n, shader_cosmos.N_FLARE)
    for k in range(shader_cosmos.N_FLARE):
        extra[f"uFlareT{k}"], extra[f"uFlareA{k}"], extra[f"uFlareK{k}"] = (direct.HOLD, FT[:, k]), (direct.HOLD, FA[:, k]), (direct.HOLD, FK[:, k])
    fl_t = flare_times

    # ---- the dancers ---------------------------------------------------------------------------
    beats = a["beats"].astype(np.float64)
    downbeats = a["downbeats"].astype(np.float64)
    grid = np.sort(np.concatenate([beats, 0.5 * (beats[:-1] + beats[1:])])) if len(beats) > 1 else beats
    # The score they dance together (`dance.score`): phrases counted from every re-entry and
    # every section's start; in steps where the kick is in; as large as the song is full -
    # from 0.4 in its quietest part to 1 in its fullest, by its own loudness - and still in silence.
    silent = np.zeros(n)
    for s_ in ch.sections or []:
        if s_.state == "silent":
            silent[int(s_.start * RATE):int(s_.end * RATE)] = 1.0
    full = a["energy"].astype(np.float64)
    lo, hi = np.percentile(full[silent < 0.5] if (silent < 0.5).any() else full, [5, 95])
    level = ease.smooth((0.4 + 0.6 * np.clip((full - lo) / max(hi - lo, 1e-6), 0.0, 1.0)) * (1.0 - silent), bar)
    anchors = [d["t"] for d in ch.drops] + [s_.start for s_ in ch.sections or []]
    gesture = dance.score(downbeats, beats, anchors, ease.smooth(hold, 2 * bar), level, bar)
    # how fast each planet goes along its orbit, at the least it could be drawn: what sway may not take back
    along = np.gradient(lon, axis=0) * RATE * (0.255 + off) * np.minimum(spread, 1.0)[:, None]
    # Where the Sun's waves meet what goes round it, as the shader draws them from the home
    # distance: the Sun's limb, and how far out each orbit stands
    sun_r = 0.078 * (0.50 + 0.80 * col["uMass"]) * (1.0 + 0.22 * extra["uSunPulse"][1])
    a0_home = np.maximum(0.255, 0.156 / np.clip(tilt_s, 0.20, 0.98))
    # A wave of hops runs out through the planets on an important moment. On a re-entry, as
    # the shock's front reaches each planet (the shader's front: it is there when the planet's
    # bow wave is), that planet's hop tops out: Mercury first, Neptune a second later. At the
    # start of every other phrase, and of every section, that is not a re-entry, a lighter
    # one, travelling out from the downbeat as a kick's pull does.
    fronts = None
    if feel["wave"]:
        at_drop = np.abs(downbeats[:, None] - drop_t[None, :]).min(1) < bar / 2 if len(drop_t) else np.zeros(len(downbeats), bool)
        light = downbeats[(dance.phrase_bars(downbeats, anchors, 2 * dance.PHRASE_BARS) == 0) & ~at_drop]
        light = light[silent[np.minimum(np.round(light * RATE).astype(int), n - 1)] < 0.5]

        def fronts(lean):
            waves = []
            for i in range(shader_cosmos.N_PLANETS):
                takes = (np.maximum((a0_home + off[:, i]) * spread + lean[:, i] - sun_r, 0.0) / 0.60) ** (1.0 / 0.70)
                met = []
                for td in drop_t:
                    k = np.arange(int(np.ceil(td * RATE)), min(int((td + 5.0) * RATE), n))
                    k = k[t[k] - td >= takes[k]]
                    met.append(t[k[0]] if len(k) else np.nan)
                times = np.concatenate([met, light + (dance.R_MEAN[i] - dance.R_MEAN[0]) / orrery.PULL_SPEED])
                tops = feel["wave"] * np.concatenate([dance.WAVE_HOP * np.clip(drop_a, 0.0, 1.0), np.full(len(light), dance.WAVE_LIGHT)])
                ok = np.isfinite(times)
                waves.append((times[ok], tops[ok]))
            return waves
    danced = dance.simulate(planet_notes, (kt[strong], ka[strong]), strikes, downbeats, grid, n, bar, flares,
                            rings_every_bars=feel["planet_rings_every_bars"], gesture=gesture,
                            breathe=feel["planets_breathe"], sway=feel["planets_sway"], kick_pull=feel["kick_pull"],
                            accents=feel["accents"], orbit_speed=along,
                            arc=dance.arc(downbeats, anchors, level), rise=feel["planets_arc"], fronts=fronts)
    # The belts dance the score too (`dance.belts`); and as a kick's pull passes through a belt,
    # its rocks stand larger for a moment - eased onto the moment the pull's front (the stars'
    # ripple's, from the Sun's limb) reaches its middle. (Baked, a belt at a time: the shader
    # knows only the last kick, and at 125 BPM the next one comes before the front is out as
    # far as the Kuiper belt.)
    belt_lean = dance.belts(gesture, n, feel["belts_breathe"])
    k_at = np.minimum(np.round(kt[strong] * RATE).astype(int), n - 1)
    for b in range(len(dance.BELT_MID)):
        extra[f"uBeltLean{b}"] = (direct.LERP, belt_lean[:, b])
        reach = (a0_home[k_at] + dance.BELT_MID[b]) * spread[k_at] - sun_r[k_at]
        extra[f"uBeltSwell{b}"] = (direct.LERP, feel["belts_breathe"] * dance.BELT_SWELL
                                   * ease.envelope(kt[strong] + reach / orrery.PULL_SPEED, np.clip(ka[strong], 0, 1), n, 0.10, 0.36)
                                   if feel["belts_breathe"] else np.zeros(n))
    # The sky answers the phrase: the score's slow part, with nothing of the beat left in it
    # (a bar's box, twice), at 1 where the song swells furthest out. The shader moves the stars
    # out from the middle of the frame by it, the nearest furthest.
    slow = ease.smooth(gesture(t)[0], 2 * bar)
    extra["uSky"] = (direct.LERP, feel["sky_breathes"] * slow / max(np.abs(slow).max(), 1e-9) if feel["sky_breathes"] else np.zeros(n))
    # In a close shot a planet's dance is sized to the body, not only to the frame (the shader's
    # pullGain); and where the planets rise and fall together, a planet's trail rises with it
    extra["uNearDance"] = (direct.LERP, np.full(n, float(feel["near_dance"])))
    extra["uTrailRise"] = (direct.LERP, np.full(n, 1.0 if feel["planets_arc"] > 0 else 0.0))
    ping_cols = []
    for i in range(shader_cosmos.N_PLANETS):
        for name in ("uLean", "uHop", "uSway", "uGlow", "uBig", "uSwing", "uSpin"):
            extra[f"{name}{i}"] = (direct.LERP, danced[f"{name}{i}"])
        rt, ra = danced["rings"][i]
        hit_t = np.array([s_[0] for s_ in strikes if s_[1] == i])
        every_t = np.concatenate([rt, hit_t]); every_a = np.concatenate([0.55 + 0.45 * ra, np.ones(len(hit_t))])
        o = np.argsort(every_t)
        PT, PA = direct.held_events(every_t[o], every_a[o], n, 1)
        extra[f"uPingT{i}"], extra[f"uPingA{i}"] = (direct.HOLD, PT[:, 0]), (direct.HOLD, PA[:, 0])

    # ---- the cameras: all three are baked, so a player can change between them as it plays.
    # Each has its own solar system, in one respect: a gesture of the whole system - the
    # spread, the tug of a kick - is sized for the frame it is seen in. Close on Saturn, a
    # spread that is handsome from afar would throw the Sun across the picture at three
    # frame-heights a second (it did); so the closer the camera, the less the system heaves.
    cams = cameras(acts, t, bar, t_c, turn0, tilt_s, roll_s, phases, spread, off, rise,
                   blend_bars=feel["camera_move_bars"], turn_bars=feel["hybrid_turn_bars"])
    pulse = extra["uSunPulse"][1]
    for mode, cam in cams.items():
        # (a kick's pull on the planets is the shader's and `orrery`'s: inverse-square, and it travels)
        cam["uCamSpan"] = cam["uCamSpan"] * (1.0 - 0.050 * reentry - 0.008 * pulse)
        for name, track in cam.items():
            extra[f"{name}.{mode}"] = (direct.LERP, track)
    for name in PER_CAMERA:
        extra[name] = (direct.LERP, extra[f"{name}.{CAMERA}"][1])

    base = {name: c for c, name in enumerate(ch.names)}
    keep = [c for c, name in enumerate(ch.names) if name not in extra]            # (what is re-baked here replaces direct's)
    names = [ch.names[c] for c in keep] + list(extra)
    kinds = [ch.kinds[c] for c in keep] + [extra[k][0] for k in extra]
    data = np.concatenate([ch.data[:, keep], np.stack([extra[k][1] for k in extra], axis=1).astype(np.float32)], axis=1)
    early = [c for c, name in enumerate(names) if name.rstrip("0123456789") in (
        "uRingT", "uRingA", "uRingM", "uPromT", "uPromA", "uPromK", "uWindT", "uWindA", "uWindK",
        "uFlareT", "uFlareA", "uFlareK", "uMetT", "uMetA", "uMetS", "uPingT", "uPingA")]
    ease.advance(data, early, 1.6 * ease.LEAD)                                     # a flare's tongue needs the longest run-up
    out = direct.Channels(names, kinds, data, ch.drops, ch.duration, ch.sections, ch.info)
    out.acts = acts
    out.flares = fl_t
    out.flare_targets = targets
    out.planet_notes = planet_notes
    out.rings = danced["rings"]
    out.restless = danced["restless"]
    out.climax = t_c
    out.variants = {"camera": {"default": CAMERA,
                               "choices": {mode: {name: f"{name}.{mode}" for name in PER_CAMERA} for mode in cams}}}
    return out


# The frame's shape. Everything is decided for the wide frame, 16:9. The tall one, 9:16, is
# the same picture with the camera turned a quarter turn about its own line of sight, the
# long side of the frame now its height: so every shot, every move and every edit is the
# same in both, and the tall frame needs nothing baked for it. (The alternatives cut the
# planets' row and the two-shots at the frame's sides: NOTES, "The tall frame".)
SHAPES = {"wide": 16 / 9, "tall": 9 / 16}           # width over height
TURNED = ("uCamRoll", "uCamSpan", "uCamX", "uCamY")  # what `turned` takes and gives, in this order


def turned(roll, span, x, y):
    """The camera of the tall frame, from the wide frame's: rolled a quarter turn, as far
    off as makes the frame's height what its width was, looking at the same place."""
    return roll + np.pi / 2, span * 16 / 9, y, -x


CAMERA_UNIFORMS = ("uCamTurn", "uCamTilt", "uCamRoll", "uCamSpan", "uCamX", "uCamY")
PER_CAMERA = CAMERA_UNIFORMS + ("uSpreadSlow",)      # what changes when the player changes camera
MODES = ("static", "hybrid", "cinematic")
KICK_TUG = 0.030                                     # how far a kick pulls the orbits in, seen from the home distance


def _shot(act: Act, e: np.ndarray, tilt_s: float) -> dict:
    """One act's way of looking, through its length (e eases 0..1 across it): how far the
    camera has turned from its home heading, its tilt, its zoom (log of the span: 0 is the
    static framing, negative is closer), what it looks at - the Sun (-1) or a planet, and
    how far from the Sun toward it - and where in the frame that sits."""
    n = len(e)
    full = np.ones(n)
    if act.function == "approach":          # from far out and low, coming in and up to the home view
        return dict(dturn=-0.9 * (1 - e), tilt=0.32 + (tilt_s - 0.32) * e, lspan=np.log(2.3) * (1 - e),
                    subject=-1, toward=0 * full, off=(0.0, 0.0))
    if act.function == "pullback":          # up over the plane and away, until the system is a mark on the galaxy
        return dict(dturn=0.8 * e, tilt=tilt_s + (0.90 - tilt_s) * e, lspan=np.log(3.2) * e,
                    subject=-1, toward=0 * full, off=(0.0, 0.0))
    if act.function == "alignment":         # the row, filling the frame, the Sun at its left end; level at the climax
        return dict(dturn=0.22 * (e - 0.30), tilt=tilt_s * full, lspan=np.log(0.66) * full,
                    subject=-2, toward=full, off=(0.0, 0.0))
    if act.function == "intimate":          # a two-shot: the Sun, which is singing, and the planet the act is about,
        return dict(dturn=0.35 * (e - 0.5), tilt=(tilt_s + 0.06) * full, lspan=np.log(0.60) * full,   # framed to fit them both
                    subject=act.subject, toward=full, off=(0.0, 0.0), fit=True)
    if act.function == "eclipse":           # close on a giant, while the ripples sweep past it
        return dict(dturn=0.40 * (e - 0.5), tilt=0.50 * full, lspan=np.log(0.26) * full,
                    subject=act.subject, toward=full, off=(-0.10, 0.0))
    # wide: home, turning slowly, breathing in - and coming down low over the plane in the
    # middle of the act, where the orbits' tilts show: Mercury riding high over it, Venus and
    # Saturn dipping under, Pluto far off it altogether
    low = np.sin(np.pi * e) ** 2
    return dict(dturn=0.55 * (e - 0.5), tilt=tilt_s + (0.36 - tilt_s) * low, lspan=np.log(1.0 - 0.10 * np.sin(np.pi * e)),
                subject=-1, toward=0 * full, off=(0.0, 0.0))


def cameras(acts, t, bar, t_c, turn0, tilt_s, roll_s, phases, spread, offsets, heights, blend_bars: float = 8.0,
            turn_bars: float = 96.0) -> dict:
    """Three ways of watching the same system.

    static      the picture that worked: the section's tilt and roll, no zoom, no slide.
    cinematic   a shot per act. It travels to the next shot during the last bars of this
                one and *arrives on the bar line* the next act begins on - the move belongs
                to the build, the downbeat to a settled frame.
    hybrid      the static framing, never still: it turns all the way round once in
                ninety-six bars, and at each act leans in or out a little, and tips a
                little, the way the cinematic one does a lot. It follows nothing.

    All three hold the same heading at the climax, so the planets' row is the same event.
    Each camera's tracks include the spread of the orbits *as that camera sees it*.
    """
    from . import shader_cosmos

    n = len(t)
    home = float(np.median(tilt_s))
    acc = {k: np.zeros(n) for k in ("dturn", "tilt", "lspan", "ox", "oy")}
    weight = np.zeros(n)
    shots = []
    for k, a in enumerate(acts):
        u = np.clip((t - a.start) / max(a.end - a.start, 1e-6), -0.5, 1.5)
        sh = _shot(a, smootherstep(u), home)
        # the way in: the last bars of the act before, never more than half of it
        into = min(blend_bars * bar, 0.5 * (acts[k - 1].end - acts[k - 1].start)) if k else 0.0
        out = min(blend_bars * bar, 0.5 * (a.end - a.start)) if k < len(acts) - 1 else 0.0
        rise = smootherstep((t - (a.start - into)) / into) if k else np.ones(n)
        fall = 1.0 - smootherstep((t - (a.end - out)) / out) if k < len(acts) - 1 else np.ones(n)
        w = rise * fall
        for key in ("dturn", "tilt", "lspan"):
            acc[key] += w * sh[key]
        acc["ox"] += w * sh["off"][0]
        acc["oy"] += w * sh["off"][1]
        weight += w
        shots.append((sh, w))
    weight = np.maximum(weight, 1e-9)
    cin = {k: v / weight for k, v in acc.items()}
    # The blend between shots leaves the heading a degree or two off at the climax; the
    # row of planets is one event, so every camera is looking exactly the same way then.
    cin["dturn"] = cin["dturn"] - float(np.interp(t_c, t, cin["dturn"]))

    def seen_from(lspan):
        """The spread of the orbits, sized for a frame this wide: whole at the home
        distance and beyond, and less the closer the camera is."""
        return 1.0 + (spread - 1.0) * np.clip(np.exp(lspan) / 0.80, 0.0, 1.0) ** 1.5

    def on_screen(i, turn, e, toward, spread_):
        """Where planet i is in the camera's turned frame: across, and up the screen."""
        a0 = np.maximum(0.255, 0.156 / e)
        r = (a0 + offsets[:, i]) * spread_ * toward
        th = 2 * np.pi * phases[:, i] + turn
        return r * np.cos(th), r * (np.sin(th) * e + heights[:, i] * np.sqrt(1 - e * e))

    # A shot that must hold two bodies is framed from where they are: wide enough for the
    # Sun, its corona and the planet with half as much again round them, and never
    # cutting either at the edge. Measured with the cinematic camera's own turn and tilt,
    # and - since how wide the frame is decides how far the orbits spread in it - twice.
    SUN, PLANET = 0.150, 0.045
    for _ in range(2):
        mine = seen_from(cin["lspan"])
        lspan = np.zeros(n)
        for sh, w in shots:
            ls = sh["lspan"]
            if sh.get("fit"):
                sx, sy = on_screen(sh["subject"], turn0 + cin["dturn"], np.clip(cin["tilt"], 0.2, 0.98), 1.0, mine)
                wide = np.maximum(sx + PLANET, SUN) - np.minimum(sx - PLANET, -SUN)
                high = np.maximum(sy + PLANET, SUN) - np.minimum(sy - PLANET, -SUN)
                ls = np.log(np.maximum(1.45 * high, 1.45 * wide * 9.0 / 16.0))
            lspan += w / weight * ls
        cin["lspan"] = lspan

    def finish(dturn, tilt, lspan, lean, roll):
        turn = turn0 + dturn
        e = np.clip(tilt, 0.20, 0.98)
        mine = seen_from(lspan)
        # what each shot looks at, on screen in the camera's turned frame, blended like the rest
        tx, ty = np.zeros(n), np.zeros(n)
        for sh, w in shots:
            if sh["subject"] == -1 or lean == 0.0:
                continue
            if sh["subject"] == -2:                       # the middle of the row
                px, py = 0.37 * mine, np.zeros(n)
            else:
                px, py = on_screen(sh["subject"], turn, e, sh["toward"], mine)
                if sh.get("fit"):                         # the middle of the two of them, edge to edge
                    px = 0.5 * (np.maximum(px + PLANET, SUN) + np.minimum(px - PLANET, -SUN))
                    py = 0.5 * (np.maximum(py + PLANET, SUN) + np.minimum(py - PLANET, -SUN))
            tx += w / weight * px
            ty += w / weight * py
        span = np.exp(lspan)
        sx, sy = lean * (tx + cin["ox"] * span), lean * (ty + cin["oy"] * span)
        # The shader un-rolls a pixel with its rot2(-roll), and its rot2 turns clockwise; so
        # the point that lands in the middle of the frame is this one turned clockwise by roll.
        cr, sr = np.cos(roll), np.sin(roll)
        return {"uCamTurn": turn, "uCamTilt": tilt, "uCamRoll": roll, "uCamSpan": span,
                "uCamX": cr * sx + sr * sy, "uCamY": -sr * sx + cr * sy, "uSpreadSlow": mine}

    zero = np.zeros(n)
    drift = 2 * np.pi * (t - t_c) / (turn_bars * bar)
    lean_in = np.clip(0.35 * cin["lspan"], np.log(0.85), np.log(1.50))
    return {
        "static": finish(zero, tilt_s, zero, 0.0, roll_s),
        "hybrid": finish(drift + 0.25 * cin["dturn"], tilt_s + 0.25 * (cin["tilt"] - tilt_s), lean_in, 0.0, roll_s),
        "cinematic": finish(cin["dturn"], cin["tilt"], cin["lspan"], 1.0, 0.5 * roll_s),
    }
