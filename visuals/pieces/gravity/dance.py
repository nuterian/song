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


def _impulses(times, amps, n: int) -> np.ndarray:
    """Pushes, as velocity per sample: each spread over PUSH_TIME (a raised cosine, centred
    on its moment), so that not even the *velocity* of a body has a corner in it."""
    out = np.zeros(n)
    i = np.round(np.asarray(times) * RATE).astype(int)
    ok = (i >= 0) & (i < n)
    np.add.at(out, i[ok], np.asarray(amps)[ok])
    k = max(int(PUSH_TIME * RATE), 3)
    bell = 1.0 - np.cos(2 * np.pi * (np.arange(k) + 0.5) / k)
    return np.convolve(out, bell / bell.sum(), mode="same")


def simulate(notes: list[tuple[np.ndarray, np.ndarray]], kicks: tuple[np.ndarray, np.ndarray],
             strikes: list[tuple[float, int, float]], downbeats: np.ndarray, grid: np.ndarray,
             n: int, bar: float, find_threshold) -> dict:
    """Run the eight bodies through the song. `notes[i]` are planet i's (times, sizes);
    `strikes` are (arrival time, planet, size) of flares; `grid` is the lattice a ring may
    be thrown on. Returns the channels, and what was decided (rings, restless moments)."""
    dt = 1.0 / RATE
    w = 2 * np.pi * FREQ
    r_mean = 0.255 + orrery.MEAN_STEP
    radius = orrery.SIZE

    # ---- what each planet decides to do: its rings, and its restless moments -----------------
    rings, restless = [], []
    for i, (t, a) in enumerate(notes):
        if len(t) == 0:
            rings.append((np.zeros(0), np.zeros(0)))
        else:
            rt, ra, _, _ = find_threshold(t, a, np.zeros(len(t)), grid, n, bar, every_bars=1.5, leak_bars=2.0, rest_bars=1.0)
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
    push = np.zeros((n, N))                     # upward pushes: notes (advanced, so the top is on the note) and restlessness
    for i, (t, a) in enumerate(notes):
        unit = HOP * radius[i] / peak_of_unit_push(FREQ[i], DAMP[i])
        push[:, i] += unit * _impulses(t - tp[i], np.clip(a, 0, 1.2), n)
        push[:, i] += unit * 0.55 * _impulses(restless[i] - tp[i], np.ones(len(restless[i])), n)
    kt, ka = kicks
    pull = np.zeros((n, N))                     # the Sun's pull: a smooth bump, arriving later the further out
    bump = ease.envelope(kt, np.clip(ka, 0, 1.2), n, 0.06, 0.24)
    for i in range(N):
        late = int(round((r_mean[i] - r_mean[0]) / orrery.PULL_SPEED * RATE))
        pull[late:, i] = -orrery.pull_depth(r_mean[i], r_mean[0]) * bump[:n - late] if late else -orrery.pull_depth(r_mean[i], r_mean[0]) * bump
    throw = np.zeros((n, N))                    # struck by a flare: thrown outward
    for at, planet, size in strikes:
        throw[:, planet] += 1.1 * radius[planet] * size / peak_of_unit_push(FREQ[planet], DAMP[planet]) * _impulses([at - tp[planet]], [1.0], n)

    # ---- the bodies: two damped springs each, coupled along the chain (semi-implicit Euler) --------
    lean, hop = np.zeros((n, N)), np.zeros((n, N))
    x, vx, y, vy = np.zeros(N), np.zeros(N), np.zeros(N), np.zeros(N)
    for k in range(n):
        nx = np.concatenate([[x[0]], x, [x[-1]]]); ny = np.concatenate([[y[0]], y, [y[-1]]])
        cx = COUPLING * w ** 2 * (nx[:-2] + nx[2:] - 2 * x)
        cy = COUPLING * w ** 2 * (ny[:-2] + ny[2:] - 2 * y)
        vx += dt * (-2 * DAMP * w * vx - w ** 2 * (x - pull[k]) + cx) + throw[k]
        vy += dt * (-2 * DAMP * w * vy - w ** 2 * y + cy) + push[k]
        x += dt * vx; y += dt * vy
        lean[k], hop[k] = x, y

    # ---- what follows the notes directly, eased ---------------------------------------------------
    out: dict = {}
    for i, (t, a) in enumerate(notes):
        amp = np.clip(a, 0, 1.2)
        glow = ease.envelope(t, amp, n, 0.12, 0.60, soften=0.06)
        swell = ease.envelope(t, amp, n, max(float(tp[i]), 0.14), 0.70, rise=ease.EASE_SLOW, soften=0.07)
        # the moons are on strings: they follow the swell late, and overshoot a little
        s, vs, swing = 0.0, 0.0, np.zeros(n)
        ws = 0.6 * w[i]
        for k in range(n):
            vs += dt * (-2 * 0.45 * ws * vs - ws ** 2 * (s - swell[k]))
            s += dt * vs
            swing[k] = s
        spin = np.cumsum(ease.envelope(t, amp, n, 0.10, 1.6)) * dt * 0.9
        out[f"uLean{i}"], out[f"uHop{i}"] = lean[:, i], hop[:, i]
        out[f"uGlow{i}"], out[f"uBig{i}"], out[f"uSwing{i}"], out[f"uSpin{i}"] = glow, swell, swing, spin
    out["rings"], out["restless"] = rings, restless
    return out
