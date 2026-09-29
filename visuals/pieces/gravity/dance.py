"""The planets as dancers: bodies with weight, not lamps that are switched.

A planet used to *display* its note: a flash, a swell and a ring, all at once, whole on
the frame, up to ten times a second. Here each planet is a small simulated body - a few
numbers on springs - and the music and the Sun act on it as forces. What is seen is what
the body does about them. Nothing in it can jump, because a mass cannot.

    lean    how far it is drawn in toward the Sun or thrown out from it, along its orbit's radius
    hop     how far it rises off the plane
    glow    how much its day side lifts
    swell   how much bigger it stands
    swing   how far out its moons are swung (it lags the swell: they are on strings)
    spin    how much further round it has turned than its day alone would turn it

What acts on it:

    its own notes     a push upward - timed *early*, by exactly as long as this body takes to
                      reach the top of its hop, so that the top is on the note. A heavy planet
                      starts sooner and rises slower; all of them arrive together.
    the Sun           the pull of a kick: inverse-square of the distance drawn, and it travels,
                      so the planets answer in turn, outward (`orrery`). A flare that strikes
                      it throws it outward and makes it ring.
    its neighbours    each is coupled, weakly, to the planets either side of it: a disturbance
                      passes along the system and dies away.
    itself            left alone for long enough a planet gets restless, and does something
                      small on a bar line - each at its own interval, so an idle system is
                      never all still and never all moving at once.

Temperament is mass. Mercury is light: quick, a little bouncy. Jupiter is heavy: slow to
start, slow to stop, hardly moved by a kick at all.

Rings are rare now, and mean something. A planet's notes charge it (a leaky sum, as the
bass charges the corona); past its threshold, the next strong note *on the grid* throws a
ring - about one in a bar and a half of the time that planet is playing, the threshold
being found from the song (`cosmos.flares` does the same for the Sun).

And they dance together, to a score (`score`, with the sheet's `planets_breathe`): all of
them go out and in with the bars, each by its share of the room it has, the gesture
travelling outward from the Sun as the kick's pull does, and each following it through
its own spring - Mercury on time and a little past, Jupiter late to start and slow to
settle, and each started early by as much as it lags, so that they arrive together. With
`planets_sway` a planet also surges ahead along its orbit as it comes in and falls back
as it goes out (`uSway`), never so far that it goes backward. With `accents` a planet
answers not every note but the one that stands out in each bar, and more.

With `planets_arc` they also rise and fall together, once in a phrase (`arc`), and the
notes' hops ride on that. With `wave`, on an important moment a hop runs out through them
one after another, Mercury first (`simulate`'s `fronts`). And the belts dance as the
heaviest bodies of all (`belts`).
"""

from __future__ import annotations

import numpy as np

from . import ease, orrery
from .direct import RATE

N = len(orrery.NAMES)
# temperament: natural frequency (Hz) and damping, from size - a proxy for mass
FREQ = 3.0 * (orrery.SIZE.min() / orrery.SIZE) ** 0.75          # Mercury 3.0 ... Jupiter 1.1
DAMP = 0.52 + 0.26 * (orrery.SIZE - orrery.SIZE.min()) / (orrery.SIZE.max() - orrery.SIZE.min())
COUPLING = 0.16                  # how strongly a planet is tied to its neighbours
HOP = 0.55                       # the top of a full note's hop, in the planet's own radii
RESTLESS_AFTER_BARS = 6.0
ACCENT_HOP = 1.0                 # the top of an accent's hop, in radii: larger...
ACCENT_PUSH = 0.24               # ...and slower, pushed over this long
GAP = np.convolve(np.pad(np.diff(orrery.MEAN_STEP), 1, mode="edge"), [0.5, 0.5], mode="valid")   # the room each planet has: the mean gap either side
AHEAD = 0.8                      # sway never takes back more than this share of a planet's own speed along its orbit
MERCURY_IN = 0.5                 # the deepest Mercury is drawn in, in full kicks' pulls (orrery.PULL): less than the kicks alone drew it (0.75)
MERCURY_UP = 0.1                 # and it rises and falls with the others (`arc`) a tenth as far: any further, and it came nearer the Sun's limb than it ever had
R_MEAN = 0.255 + orrery.MEAN_STEP               # each planet's mean distance from the Sun, as drawn from the home distance
WAVE_HOP = 1.2                   # the top of a re-entry's wave, in the planet's own radii, at full strength...
WAVE_LIGHT = 0.5                 # ...and of the lighter one at a phrase's or a section's start


def time_to_peak(freq: np.ndarray, damp: np.ndarray) -> np.ndarray:
    """How long after a push a damped spring reaches its furthest: what a note is advanced by."""
    w = 2 * np.pi * freq
    wd = w * np.sqrt(1 - damp ** 2)
    return np.arctan2(np.sqrt(1 - damp ** 2), damp) / wd


def peak_of_unit_push(freq: np.ndarray, damp: np.ndarray) -> np.ndarray:
    """How far a unit impulse (of velocity) carries it."""
    w = 2 * np.pi * freq
    wd = w * np.sqrt(1 - damp ** 2)
    tp = time_to_peak(freq, damp)
    return np.exp(-damp * w * tp) * np.sin(wd * tp) / wd


def balance(slot_events: list[tuple[np.ndarray, np.ndarray]], slot_to_planet) -> list[tuple[np.ndarray, np.ndarray]]:
    """Share the notes out so that every planet plays.

    Notes come in eight bands of pitch, low to high, and a band belongs to a planet (low
    notes to the giants). But a song in one key leans on a few pitches: here one band had
    four hundred notes and another had two. Bands keep their order, and an overfull one
    shares its notes with its neighbour - alternately through time, so two planets trade
    the same note back and forth rather than one falling silent."""
    total = sum(len(t) for t, _ in slot_events)
    room = [total / N] * N
    out_t: list[list[float]] = [[] for _ in range(N)]
    out_a: list[list[float]] = [[] for _ in range(N)]
    seat = 0
    for slot, (t, a) in enumerate(slot_events):
        m, owners = len(t), []
        left = m
        while left > 0:
            take = int(min(left, max(np.ceil(room[seat]), 1))) if seat < N - 1 else left
            owners.append((seat, take))
            room[seat] -= take
            left -= take
            if room[seat] <= 0.5 and seat < N - 1:
                seat += 1
        keys = np.concatenate([(np.arange(c) + 0.5) / c for _, c in owners]) if owners else np.zeros(0)
        who = np.concatenate([np.full(c, s) for s, c in owners]).astype(int) if owners else np.zeros(0, int)
        who = who[np.argsort(keys, kind="stable")]
        for k, (ti, ai) in enumerate(zip(t, a)):
            out_t[who[k]].append(float(ti)); out_a[who[k]].append(float(ai))
    by_planet: list = [None] * N
    for seat_i in range(N):
        o = np.argsort(out_t[seat_i], kind="stable")                  # a planet may hold notes from two bands: in time order
        by_planet[slot_to_planet[seat_i]] = (np.array(out_t[seat_i])[o], np.array(out_a[seat_i])[o])
    return by_planet


PUSH_TIME = 0.10                 # a push is not a blow: it is applied over a tenth of a second


def _bell(width: float) -> np.ndarray:
    k = max(int(width * RATE), 3)
    bell = 1.0 - np.cos(2 * np.pi * (np.arange(k) + 0.5) / k)
    return bell / bell.sum()


def _impulses(times, amps, n: int, width: float = PUSH_TIME) -> np.ndarray:
    """Pushes, as velocity per sample: each spread over `width` (a raised cosine, centred
    on its moment), so that not even the *velocity* of a body has a corner in it."""
    out = np.zeros(n)
    i = np.round(np.asarray(times) * RATE).astype(int)
    ok = (i >= 0) & (i < n)
    np.add.at(out, i[ok], np.asarray(amps)[ok])
    return np.convolve(out, _bell(width), mode="same")


def _answer(freq: float, damp: float, width: float) -> tuple[float, float]:
    """`time_to_peak` and `peak_of_unit_push` for a push spread over `width`: worked out,
    since a long push arrives at its top later than a blow would."""
    w = 2 * np.pi * freq
    wd = w * np.sqrt(1 - damp ** 2)
    s = np.arange(int(3 * RATE)) / RATE
    y = np.convolve(_bell(width), np.exp(-damp * w * s) * np.sin(wd * s) / wd)
    top = int(np.argmax(y))
    return (top - (len(_bell(width)) - 1) / 2) / RATE, float(y[top])


def accented(t: np.ndarray, a: np.ndarray, downbeats: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The notes that stand out: in each bar a planet plays in, its strongest, if that is
    at least its usual (median) note."""
    if len(t) == 0:
        return t, a
    bar_of = np.searchsorted(downbeats, t, side="right")
    o = np.lexsort((-a, bar_of))                        # by bar, the strongest first
    first = o[np.r_[True, np.diff(bar_of[o]) > 0]]
    keep = np.sort(first[a[first] >= np.median(a)])
    return t[keep], a[keep]


# ---- the score ---------------------------------------------------------------------------------
# What they dance together, from the grid. The system is at its tightest on the downbeat of
# every other bar and at its widest on the one between, and travels from one to the other
# over the whole bar: it breathes once in two bars, biased outward, so that the orbits hardly
# ever stand inside where they rest. A phrase is four bars, and its second pair goes out
# further than its first, so a phrase swells; and the draw-in over its last bar is the run-up
# to the next phrase's downbeat. There are no phrase marks, so phrases are counted in fours
# from every re-entry and every section's start, afresh at the next. Where the kick is in,
# the travel across a bar is a step to a beat, each arriving on its beat; where it is not, one
# glide across the bar; in between, a blend of the two - never a switch.
IN, OUT = -0.3, 1.0              # the score at its tightest and at its widest: the dial is how far out it goes
SWELL = (0.7, 1.0)               # how far out the first and the second pair of a phrase's bars go
PHRASE_BARS = 4
STEP = 0.55                      # a step takes this share of its beat, and ends on it


def phrase_bars(downbeats: np.ndarray, anchors, bars: int = PHRASE_BARS) -> np.ndarray:
    """Each bar's place in its phrase, 0 to 3: counted in fours from every anchor (a bar
    line nearest a re-entry or a section's start), afresh at the next. (In `bars`, for
    other counts: in eights, every other phrase.)"""
    k = np.arange(len(downbeats))
    anchors = np.asarray(anchors, dtype=np.float64)
    at = np.unique(np.abs(downbeats[:, None] - anchors[None, :]).argmin(0)) if len(anchors) else np.zeros(0, int)
    start = np.concatenate([[0], at])[np.searchsorted(at, k, side="right")]
    return (k - start) % bars


def score(downbeats: np.ndarray, beats: np.ndarray, anchors, stepping: np.ndarray, level: np.ndarray, bar: float):
    """The gesture every planet dances, as a function of time: at any times (each planet
    reads it at its own), how far out the system stands (`IN`..`OUT`), and how far ahead
    along the orbits (the same gesture, gliding, a quarter of its two bars away: ahead as it
    comes in, behind as it goes out). `stepping` (0..1, at RATE) is how far the kick is in;
    `level` (at RATE) how full the song is: the size of the whole gesture."""
    d = np.asarray(downbeats, dtype=np.float64)
    place = phrase_bars(d, anchors)
    v = np.where(place % 2 == 0, IN, OUT * np.where(place < 2, SWELL[0], SWELL[1]))
    beat_no = lambda x: np.interp(x, beats, np.arange(len(beats), dtype=np.float64))
    d_beat = np.round(beat_no(d))
    frames = np.arange(len(level), dtype=np.float64)

    def glide(t):
        k = np.clip(np.searchsorted(d, t, side="right") - 1, 0, len(d) - 2)
        u = np.clip((t - d[k]) / (d[k + 1] - d[k]), 0.0, 1.0)
        return k, v[k] + (v[k + 1] - v[k]) * ease.EASE_IN(u)

    def at(t):
        t = np.asarray(t, dtype=np.float64)
        k, glided = glide(t)
        s = np.clip(beat_no(t) - d_beat[k], 0.0, None) + STEP          # beats since the downbeat, a step early
        steps = np.floor(s) - 1.0 + ease.EASE_IN(np.minimum((s % 1.0) / STEP, 1.0))
        stepped = v[k] + (v[k + 1] - v[k]) * np.clip(steps / (d_beat[k + 1] - d_beat[k]), 0.0, 1.0)
        w, size = np.interp(t * RATE, frames, stepping), np.interp(t * RATE, frames, level)
        ahead = 0.5 * (IN + OUT) - glide(t - bar / 2)[1]
        return size * ((1.0 - w) * glided + w * stepped), size * ahead
    return at


def arc(downbeats: np.ndarray, anchors, level: np.ndarray):
    """The slow rise and fall they make together off the plane, as a function of time: -1
    on a phrase's first downbeat, 1 on its third bar's, one glide from each to the next
    (a phrase cut short holds where it is), as large as the song is full (`level`, at RATE).
    Its cycle is a phrase, the breath's is two bars, so the figure a planet draws does not
    come round every two bars."""
    d = np.asarray(downbeats, dtype=np.float64)
    place = phrase_bars(d, anchors)
    kt, kv = d[place % 2 == 0], np.where(place[place % 2 == 0] == 0, -1.0, 1.0)
    frames = np.arange(len(level), dtype=np.float64)

    def at(t):
        t = np.asarray(t, dtype=np.float64)
        if len(kt) < 2:
            return np.zeros_like(t)
        k = np.clip(np.searchsorted(kt, t, side="right") - 1, 0, len(kt) - 2)
        u = np.clip((t - kt[k]) / (kt[k + 1] - kt[k]), 0.0, 1.0)
        return np.interp(t * RATE, frames, level) * (kv[k] + (kv[k + 1] - kv[k]) * ease.EASE_IN(u))
    return at


# ---- the belts ----------------------------------------------------------------------------------
# The asteroid belt and the Kuiper belt dance the score as a planet does, out and in, as the
# heaviest bodies there are: each is taken to weigh half as much again as Jupiter, and given
# the temperament that size would give a planet. Each goes as far as the planet just inside
# it does (that planet's GAP), so at the same dial it keeps its distance from it: Mars does
# not lean into the asteroid belt, nor Neptune into the Kuiper belt. (The belt's own room -
# its width, or the mean of its distances to the orbits either side - left Mars a thousandth
# of the frame inside it.)
BELT_MID = np.array([orrery.displayed(lo) + orrery.displayed(hi) for lo, hi in orrery.BELTS]) / 2   # beyond Mercury's orbit
BELT_ROOM = np.array([GAP[np.flatnonzero(orrery.MEAN_STEP < m)[-1]] for m in BELT_MID])  # Mars's and Neptune's
BELT_SIZE = 1.5 * orrery.SIZE.max()
BELT_FREQ = 3.0 * (orrery.SIZE.min() / BELT_SIZE) ** 0.75                                # 0.81 Hz, as FREQ has it
BELT_DAMP = 0.52 + 0.26 * (BELT_SIZE - orrery.SIZE.min()) / (orrery.SIZE.max() - orrery.SIZE.min())   # 0.96, as DAMP has it
BELT_SWELL = 0.5                 # how much larger a rock stands as a full kick's pull passes it


def belts(gesture, n: int, breathe: float) -> np.ndarray:
    """How far each belt leans out (+) or in, every rock of it together, in scene units at
    the home distance (n x 2): the score, read as late as the pull reaches the belt's middle
    and as early as its spring lags, followed through its spring, as far as `breathe` of its room."""
    out = np.zeros((n, len(BELT_MID)))
    if gesture is None or not breathe:
        return out
    dt, w = 1.0 / RATE, 2 * np.pi * BELT_FREQ
    read = np.arange(n) * dt
    for b, mid in enumerate(BELT_MID):
        target = breathe * BELT_ROOM[b] * gesture(read - (0.255 + mid - R_MEAN[0]) / orrery.PULL_SPEED + 2 * BELT_DAMP / w)[0]
        x, v = 0.0, 0.0
        for k in range(n):
            v += dt * (-2 * BELT_DAMP * w * v - w ** 2 * (x - target[k]))
            x += dt * v
            out[k, b] = x
    return out


def _hops(push: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Every planet off the plane: a damped spring tied to its neighbours (semi-implicit Euler),
    pushed by `push` (velocity per sample) and drawn toward `high` (both n x N)."""
    dt, w = 1.0 / RATE, 2 * np.pi * FREQ
    hop, y, vy = np.zeros_like(push), np.zeros(N), np.zeros(N)
    for k in range(len(push)):
        ny = np.concatenate([[y[0]], y, [y[-1]]])
        cy = COUPLING * w ** 2 * (ny[:-2] + ny[2:] - 2 * y)
        vy += dt * (-2 * DAMP * w * vy - w ** 2 * (y - high[k]) + cy) + push[k]
        y += dt * vy
        hop[k] = y
    return hop


def simulate(notes: list[tuple[np.ndarray, np.ndarray]], kicks: tuple[np.ndarray, np.ndarray],
             strikes: list[tuple[float, int, float]], downbeats: np.ndarray, grid: np.ndarray,
             n: int, bar: float, find_threshold, rings_every_bars: float = 1.5, gesture=None,
             breathe: float = 0.0, sway: float = 0.0, kick_pull: float = 1.0, accents: float = 0.0,
             orbit_speed: np.ndarray | None = None, arc=None, rise: float = 0.0, fronts=None) -> dict:
    """Run the eight bodies through the song. `notes[i]` are planet i's (times, sizes);
    `strikes` are (arrival time, planet, size) of flares; `grid` is the lattice a ring may
    be thrown on. `gesture` is the score (`score`), danced as far as `breathe` and `sway`
    say; `orbit_speed` (scene units a second, each planet's slowest along its orbit) is what
    sway may not take back. `arc` (`arc`) is how high they stand off the plane together, as
    far as `rise` says. `fronts`, given how far each planet leans (n x N), says when a wave
    reaches each and how high it throws it: for each planet (times, tops in its radii).
    Returns the channels, and what was decided (rings, restless moments)."""
    dt = 1.0 / RATE
    w = 2 * np.pi * FREQ
    r_mean = R_MEAN
    radius = orrery.SIZE
    stand_out = [accented(t, a, downbeats) for t, a in notes]

    # ---- what each planet decides to do: its rings, and its restless moments -----------------
    rings, restless = [], []
    for i, (t, a) in enumerate(notes):
        if len(t) == 0:
            rings.append((np.zeros(0), np.zeros(0)))
        else:
            rt, ra, _, _ = find_threshold(t, a, np.zeros(len(t)), grid, n, bar, every_bars=rings_every_bars, leak_bars=2.0, rest_bars=1.0)
            rings.append((rt, ra))
        # restless: in a long silence, something small on a bar line, at this planet's own interval
        every = (5 + (3 * i) % 4) * bar
        marks = np.concatenate([[0.0], t, [n * dt]])
        mine = []
        for g0, g1 in zip(marks[:-1], marks[1:]):
            if g1 - g0 > RESTLESS_AFTER_BARS * bar:
                at = g0 + every * (0.5 + 0.13 * i)
                while at < g1 - 2 * bar:
                    mine.append(float(downbeats[np.argmin(np.abs(downbeats - at))]) if len(downbeats) else at)
                    at += every
        restless.append(np.array(mine))

    # ---- the forces -----------------------------------------------------------------------------
    tp = time_to_peak(FREQ, DAMP)
    tpa, peak_a = np.array([_answer(FREQ[i], DAMP[i], ACCENT_PUSH) for i in range(N)]).T
    push = np.zeros((n, N))                     # upward pushes: notes (advanced, so the top is on the note) and restlessness
    for i, (t, a) in enumerate(notes):
        unit = HOP * radius[i] / peak_of_unit_push(FREQ[i], DAMP[i])
        push[:, i] += (1.0 - accents) * unit * _impulses(t - tp[i], np.clip(a, 0, 1.2), n)
        push[:, i] += unit * 0.55 * _impulses(restless[i] - tp[i], np.ones(len(restless[i])), n)
        if accents:
            ta, aa = stand_out[i]
            push[:, i] += accents * ACCENT_HOP * radius[i] / peak_a[i] * _impulses(ta - tpa[i], np.clip(aa, 0, 1.2), n, ACCENT_PUSH)
    kt, ka = kicks
    pull = np.zeros((n, N))                     # the Sun's pull: a smooth bump, arriving later the further out
    bump = ease.envelope(kt, np.clip(ka, 0, 1.2), n, 0.06, 0.24)
    for i in range(N):
        late = int(round((r_mean[i] - r_mean[0]) / orrery.PULL_SPEED * RATE))
        pull[late:, i] = -orrery.pull_depth(r_mean[i], r_mean[0]) * bump[:n - late] if late else -orrery.pull_depth(r_mean[i], r_mean[0]) * bump
    pull *= kick_pull
    throw = np.zeros((n, N))                    # struck by a flare: thrown outward
    for at, planet, size in strikes:
        throw[:, planet] += 1.1 * radius[planet] * size / peak_of_unit_push(FREQ[planet], DAMP[planet]) * _impulses([at - tp[planet]], [1.0], n)
    # the score: each planet reads it as late as it travels out from the Sun, and as early as
    # its own spring lags a slow gesture, so that it arrives on time
    along = np.zeros((n, N))
    high = np.zeros((n, N))                     # where each would stand off the plane, left to the arc alone
    read = np.arange(n) * dt
    for i in range(N):
        early = read - (r_mean[i] - r_mean[0]) / orrery.PULL_SPEED + 2 * DAMP[i] / w[i]
        if gesture is not None and breathe > 0:
            out_i, along_i = gesture(early)
            pull[:, i] += breathe * GAP[i] * out_i
            along[:, i] = sway * breathe * GAP[i] * along_i
        if arc is not None and rise > 0:
            high[:, i] = rise * GAP[i] * arc(early) * (MERCURY_UP if i == 0 else 1.0)

    # ---- the bodies: two damped springs each, coupled along the chain (semi-implicit Euler), --------
    # and a third for the sway along the orbit, on its own. In the plane first, since where a
    # planet leans says when a wave reaches it; then off it.
    lean, ahead = np.zeros((n, N)), np.zeros((n, N))
    x, vx, z, vz = np.zeros(N), np.zeros(N), np.zeros(N), np.zeros(N)
    swayed = along.any()
    for k in range(n):
        nx = np.concatenate([[x[0]], x, [x[-1]]])
        cx = COUPLING * w ** 2 * (nx[:-2] + nx[2:] - 2 * x)
        vx += dt * (-2 * DAMP * w * vx - w ** 2 * (x - pull[k]) + cx) + throw[k]
        x += dt * vx
        lean[k] = x
        if swayed:
            vz += dt * (-2 * DAMP * w * vz - w ** 2 * (z - along[k]))
            z += dt * vz
            ahead[k] = z
    if breathe:
        # Mercury, which a steady draw-in could take across the Sun's limb, is held back from
        # it: softly, with no corner
        room = MERCURY_IN * orrery.PULL
        lean[:, 0] = np.where(lean[:, 0] < 0, -room * np.tanh(-lean[:, 0] / room), lean[:, 0])
    if fronts is not None:
        # a wave: pushed as an accent is, early by as long as the planet takes to top out - tied
        # to its neighbours, which stiffen it, so sooner than `_answer` says
        for i, (ft, fa) in enumerate(fronts(lean)):
            one = np.zeros((int(3 * RATE), N))
            one[:, i] = _impulses([1.0], [1.0], len(one), ACCENT_PUSH)
            alone = _hops(one, np.zeros_like(one))[:, i]
            top = int(np.argmax(alone))
            push[:, i] += radius[i] / alone[top] * _impulses(np.asarray(ft) - (top / RATE - 1.0), fa, n, ACCENT_PUSH)
    hop = _hops(push, high)
    if swayed and orbit_speed is not None:
        # it slows and it surges, and never goes back: where sway would take back more than
        # AHEAD of a planet's own speed along its orbit, the whole of its sway is made smaller
        back = np.maximum(-np.gradient(ahead, axis=0) * RATE, 1e-12)
        ahead *= np.minimum(AHEAD * orbit_speed / back, 1.0).min(axis=0)

    # ---- what follows the notes directly, eased ---------------------------------------------------
    out: dict = {}
    for i, (t, a) in enumerate(notes):
        amp = np.clip(a, 0, 1.2)
        glow = ease.envelope(t, amp, n, 0.12, 0.60, soften=0.06)
        swell = ease.envelope(t, amp, n, max(float(tp[i]), 0.14), 0.70, rise=ease.EASE_SLOW, soften=0.07)
        if accents:                                  # the accent lights it, and swells it with its hop
            ta, aa = stand_out[i]
            aa = np.clip(aa, 0, 1.2)
            glow = (1.0 - accents) * glow + accents * ease.envelope(ta, aa, n, 0.12, 0.60, soften=0.06)
            swell = (1.0 - accents) * swell + accents * ease.envelope(ta, aa, n, max(float(tpa[i]), 0.14), 0.70, rise=ease.EASE_SLOW, soften=0.07)
        # the moons are on strings: they follow the swell late, and overshoot a little
        s, vs, swing = 0.0, 0.0, np.zeros(n)
        ws = 0.6 * w[i]
        for k in range(n):
            vs += dt * (-2 * 0.45 * ws * vs - ws ** 2 * (s - swell[k]))
            s += dt * vs
            swing[k] = s
        spin = np.cumsum(ease.envelope(t, amp, n, 0.10, 1.6)) * dt * 0.9
        out[f"uLean{i}"], out[f"uHop{i}"], out[f"uSway{i}"] = lean[:, i], hop[:, i], ahead[:, i]
        out[f"uGlow{i}"], out[f"uBig{i}"], out[f"uSwing{i}"], out[f"uSpin{i}"] = glow, swell, swing, spin
    out["rings"], out["restless"] = rings, restless
    return out
