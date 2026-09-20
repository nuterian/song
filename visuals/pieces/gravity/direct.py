"""From what was heard to what the shader is handed: every uniform, baked at 120 Hz.

One instrument, one visual role, and nothing sharing:

    kick            the body's punch                      uKickT  uKickA
    sub floor       the body's mass; how hard it holds    uMass   uSpread  uOrbit
    bass            the body's glow                       uBass
    clap / snare    a ring thrown outward                 uRingT0..5  uRingA0..5
    hats            the orbit lines tick                  uHatT   uHatA
    synth notes     a satellite lights; which, by pitch   uNoteT0..7  uNoteA0..7
    voice           the core's light, the corona's reach  uVoice  uPitch  uSyllT  uSyllA
    pad brightness  how far the field glows               uField
    harmony, arc    hue                                   uHue    uWarm
    loudness        exposure                              uExposure
    re-entries      the shock                             uDropT  uDropA

Anything that happens at an instant is handed over as the *time* it happened, in a
held channel, and the shader works out how long ago that was. So an attack is as
sharp as the frame rate, a ring's radius is exact, and the picture is a pure
function of the clock - no feedback buffer, so a preview from the middle of the
song is the same picture the full render has there.

Anything with inertia - the orbits widening as the floor goes, snapping back when
it returns - is a spring integrated here, once, over the whole song.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .listen import RATE, smooth

N_RINGS = 6
N_SATS = 8

LERP, HOLD = "lerp", "hold"


@dataclass
class Channels:
    names: list[str]
    kinds: list[str]
    data: np.ndarray          # (frames, channels) float32
    drops: list[dict]
    duration: float

    def index(self, name: str) -> int:
        return self.names.index(name)

    def at(self, t: float) -> dict[str, float]:
        x = min(max(t * RATE, 0.0), len(self.data) - 1.0)
        i = int(np.floor(x + 1e-6))
        j = min(i + 1, len(self.data) - 1)
        f = x - i
        row = {}
        for c, (name, kind) in enumerate(zip(self.names, self.kinds)):
            a = self.data[i, c]
            row[name] = float(a + (self.data[j, c] - a) * f) if kind == LERP else float(a)
        return row

    def rows(self, times: np.ndarray) -> np.ndarray:
        """`at`, for many times at once: (len(times), channels)."""
        x = np.clip(times * RATE, 0.0, len(self.data) - 1.0)
        i = np.floor(x + 1e-6).astype(int)
        j = np.minimum(i + 1, len(self.data) - 1)
        f = (x - i)[:, None].astype(np.float32)
        held = self.data[i]
        lerp = np.array([k == LERP for k in self.kinds])
        return np.where(lerp[None, :], held + (self.data[j] - held) * f, held)

    def header(self) -> dict:
        return {"rate": RATE, "frames": int(len(self.data)),
                "features": [{"name": n, "kind": k} for n, k in zip(self.names, self.kinds)]}


# --------------------------------------------------------------------- helpers


def held_events(times: np.ndarray, amps: np.ndarray, n: int, slots: int = 1,
                slot_of: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(n, slots) arrays: the time and size of the latest event in each slot.

    Row i holds the latest event at or before i / RATE. Before a slot's first event
    its time is far in the past, so its age is large and it draws nothing.
    """
    T = np.full((n, slots), -1000.0, dtype=np.float32)
    A = np.zeros((n, slots), dtype=np.float32)
    if slot_of is None:
        slot_of = np.arange(len(times)) % slots
    first = np.ceil(times * RATE - 1e-6).astype(int)
    for t, a, s, i in zip(times, amps, slot_of, first):
        if 0 <= i < n:
            T[i:, s] = t
            A[i:, s] = a
    return T, A


def follow(x: np.ndarray, attack: float, release: float) -> np.ndarray:
    """One-pole follower with separate rise and fall times, in seconds."""
    ka = 1.0 - np.exp(-1.0 / max(attack * RATE, 1e-6))
    kr = 1.0 - np.exp(-1.0 / max(release * RATE, 1e-6))
    y = np.empty_like(x)
    s = x[0]
    for i, v in enumerate(x):
        s += (ka if v > s else kr) * (v - s)
        y[i] = s
    return y


def spring(target: np.ndarray, hz: float, damping: float) -> np.ndarray:
    """A damped spring chasing `target`. Under 1.0 damping it overshoots, once."""
    w = 2 * np.pi * hz
    dt = 1.0 / RATE
    x, v = float(target[0]), 0.0
    out = np.empty_like(target)
    for i, g in enumerate(target):
        acc = w * w * (g - x) - 2 * damping * w * v
        v += acc * dt
        x += v * dt
        out[i] = x
    return out


def trailing_max(x: np.ndarray, width: int) -> np.ndarray:
    from scipy import ndimage
    width = max(1, int(width))
    c = ndimage.maximum_filter1d(x, size=width, mode="nearest")
    s = width // 2
    out = x.copy()
    out[s:] = c[: len(x) - s]
    return out


# ------------------------------------------------------------------ structure


def find_drops(a: dict, period: float, duration: float) -> list[dict]:
    """Downbeats where the floor comes back.

    At each downbeat: how much louder is the beat after it than the bar before it,
    and how much floor arrived. A re-entry is both at once. Strength is the two
    added, scaled so the biggest in the song is 1.
    """
    loud, floor = a["loud_db"], a["sub"]
    bar = 4 * period
    found = []
    for d in a["downbeats"]:
        if d < bar or d > duration - bar:
            continue
        pre = slice(int((d - bar) * RATE), int((d - 0.02) * RATE))
        post = slice(int((d + 0.02) * RATE), int((d + period) * RATE))
        jump = float(loud[post].mean() - loud[pre].mean())
        arrive = float(floor[post].max() - floor[pre].max())
        if jump > 1.5 and arrive > 0.12:
            found.append({"t": float(d), "jump_db": jump, "floor": arrive,
                          "bar": int(round((d - a["downbeats"][0]) / bar))})
    if found:
        # A rise out of silence is forty decibels and means nothing; past eight, a
        # jump is as big as a jump gets.
        raw = np.array([min(f["jump_db"], 8.0) / 8.0 + f["floor"] for f in found])
        for f, r in zip(found, raw / raw.max()):
            f["strength"] = float(r)
    return found


# ------------------------------------------------------------------- the score


def direct(got: dict) -> Channels:
    a, meta = got["arrays"], got["meta"]
    n, period, duration = int(meta["n"]), float(meta["period"]), float(meta["duration"])
    t = np.arange(n) / RATE
    beat_w = int(round(period * RATE))
    cols: dict[str, tuple[str, np.ndarray]] = {}

    # --- the floor -------------------------------------------------------------
    # The sub, held up across one beat so a kick a beat keeps it there. Three
    # levels fall out of this track: about 1 with the kick in, about a half when
    # only the bass is pulsing, nothing in the bars before each re-entry.
    floor = np.clip(trailing_max(a["sub"].astype(np.float64), int(beat_w * 1.1)) / 0.55, 0, 1)
    floor = follow(floor, 0.01, 0.35)

    kt, ka = a["ev_kick_t"], a["ev_kick_amp"]
    strong = ka > 0.5
    KT, KA = held_events(kt[strong], np.clip(ka[strong], 0, 1.2), n)
    since_kick = t - KT[:, 0]
    drive = np.clip(1.0 - (since_kick - 1.15 * period) / (0.5 * period), 0, 1)

    # Mass is how big the body stands. It arrives at once and leaves slowly.
    mass = follow(0.30 + 0.40 * floor + 0.30 * drive, 0.015, 0.45)
    cols["uMass"] = (LERP, mass)
    cols["uKickT"] = (HOLD, KT[:, 0])
    cols["uKickA"] = (HOLD, KA[:, 0])
    cols["uBass"] = (LERP, follow(a["bass"].astype(np.float64), 0.008, 0.10))

    # The orbits: tight and quick under a full floor, wide and slow without one.
    # A spring, so that when the floor returns the satellites fall in and overshoot.
    hold = 0.55 * floor + 0.45 * drive
    spread = spring(1.0 + 0.85 * (1.0 - hold), hz=1.6, damping=0.42)
    cols["uSpread"] = (LERP, np.clip(spread, 0.6, 2.2))
    # Orbital phase runs on beats, faster the harder the body holds: integrate.
    beats_per_s = 1.0 / period
    rate = (0.05 + 0.20 * hold) * beats_per_s          # turns per second
    cols["uOrbit"] = (LERP, np.cumsum(rate) / RATE)

    # --- thrown rings, ticking lines, lit satellites ----------------------------
    st, sa = a["ev_snare_t"], a["ev_snare_amp"]
    keep = sa > 0.30
    RT, RA = held_events(st[keep], np.clip(sa[keep], 0, 1.3), n, N_RINGS)
    for k in range(N_RINGS):
        cols[f"uRingT{k}"] = (HOLD, RT[:, k])
        cols[f"uRingA{k}"] = (HOLD, RA[:, k])

    ht, ha = a["ev_hat_t"], a["ev_hat_amp"]
    keep = ha > 0.25
    HT, HA = held_events(ht[keep], np.clip(ha[keep], 0, 1.3), n)
    cols["uHatT"] = (HOLD, HT[:, 0])
    cols["uHatA"] = (HOLD, HA[:, 0])

    nt, na = a["ev_note_t"], a["ev_note_amp"]
    keep = na > 0.25
    # Which satellite a note lights is its pitch: low notes close in, high notes far
    # out, ranked within the song so all eight orbits get used.
    pitch = a["ev_note_pitch"][keep]
    ranks = np.searchsorted(np.sort(pitch), pitch, side="left") / max(len(pitch), 1)
    ties = np.searchsorted(np.sort(pitch), pitch, side="right") / max(len(pitch), 1)
    slot = np.clip(((ranks + ties) / 2 * N_SATS).astype(int), 0, N_SATS - 1)
    NT, NA = held_events(nt[keep], np.clip(na[keep], 0, 1.3), n, N_SATS, slot_of=slot)
    for k in range(N_SATS):
        cols[f"uNoteT{k}"] = (HOLD, NT[:, k])
        cols[f"uNoteA{k}"] = (HOLD, NA[:, k])
    cols["uSynth"] = (LERP, follow(a["other"].astype(np.float64), 0.03, 0.5))

    # --- the voice --------------------------------------------------------------
    cols["uVoice"] = (LERP, follow(a["voice"].astype(np.float64), 0.010, 0.09))
    cols["uPresence"] = (LERP, a["voice_presence"].astype(np.float64))
    cols["uPitch"] = (LERP, a["voice_pitch"].astype(np.float64))
    yt, ya = a["ev_syllable_t"], a["ev_syllable_amp"]
    keep = ya > 0.30
    YT, YA = held_events(yt[keep], np.clip(ya[keep], 0, 1.3), n)
    cols["uSyllT"] = (HOLD, YT[:, 0])
    cols["uSyllA"] = (HOLD, YA[:, 0])

    # --- the field, the colour, the light ---------------------------------------
    cols["uField"] = (LERP, smooth(a["bright"].astype(np.float64), RATE, 0.25))
    cols["uAir"] = (LERP, a["air"].astype(np.float64))

    # Hue travels with the song's spent energy - cool before dawn, warm by the last
    # chorus - and leans with the harmony inside that.
    energy = a["energy"].astype(np.float64)
    arc = np.cumsum(energy) / max(energy.sum(), 1e-9)
    harm = a["harmony"].astype(np.float64)
    harm = harm - smooth(harm, RATE, 16 * period)       # chord-scale motion only
    cols["uHue"] = (LERP, 0.60 + 0.42 * arc + 0.035 * np.clip(harm, -1.5, 1.5))
    cols["uWarm"] = (LERP, smooth(energy, RATE, 4 * period))

    loud = a["loud"].astype(np.float64)
    exposure = np.clip((loud - 0.50) / 0.40, 0.0, 1.0) ** 1.3
    cols["uExposure"] = (LERP, follow(exposure, 0.02, 0.18))

    # --- the shock --------------------------------------------------------------
    drops = find_drops(a, period, duration)
    DT, DA = held_events(np.array([d["t"] for d in drops]),
                         np.array([d["strength"] for d in drops]), n)
    cols["uDropT"] = (HOLD, DT[:, 0])
    cols["uDropA"] = (HOLD, DA[:, 0])

    cols["uBeats"] = (LERP, a["beats_elapsed"].astype(np.float64))

    names = list(cols)
    kinds = [cols[k][0] for k in names]
    data = np.stack([cols[k][1] for k in names], axis=1).astype(np.float32)
    return Channels(names, kinds, data, drops, duration)
