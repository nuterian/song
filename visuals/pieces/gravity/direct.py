"""From what was heard to what the shader is handed: every uniform, baked at 120 Hz.

One instrument, one visual role, and nothing sharing:

    kick            the body's punch, a tug on every orbit   uKickT  uKickA
    sub floor       the body's mass; how hard it holds       uMass   uSpread  uOrbit  uHold
    bass            the body's glow; its note leans the hue   uBass   (palette)
    clap / snare    a ring thrown outward, coloured by tone   uRingT/A/M 0..5
    hats            orbit lines tick; a third of the stars    uHatT   uHatA   uHatK
    crash           the stars ring on; a shooting star          uCrashT uCrashA  uMetT/A/S 0..2
    synth notes     a satellite lights: which by pitch,       uNoteT/A/M 0..7
                    what colour by its place in the key
    pad             field reach; and its pumping              uField  uPump
    voice           the core's light, the aura's reach,       uVoice  uPitch  uSyllT/A
                    its swell on a held note                  uSustain
    lyric           what the line is about tints the voice    uTint   uTintR/G/B
    chord           leans the field's hue                     (palette)
    section         palette, rays, bands, stars, tilt         uC*     uRays uBands uStars uTilt uIncl
    riser           the stars drawn outward                   uDrift
    re-entry        the shock                                 uDropT  uDropA

Anything that happens at an instant is handed over as the *time* it happened, in a
held channel, and the shader works out how long ago that was. So an attack is as
sharp as the frame rate, a ring's radius is exact, and the picture is a pure
function of the clock - no feedback buffer, so a preview from the middle of the
song is the same picture the full render has there.

Anything decided once per passage - a palette, a layer's weight, the tilt of the
plane - is held per section and then low-passed into a ramp that starts before the
bar line and ends after it (`colour.hold_then_ramp`). A decision can be as abrupt
as it likes; the track it becomes has no steps in it, and hue goes the short way
round. Anything with inertia is a spring integrated here, once, over the song.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import colour, decide
from .listen import RATE, smooth

N_RINGS = 6
N_SATS = 8
N_METEORS = 3
PALETTE_ROLES = ("Field", "Far", "Body", "Accent", "Accent2")

LERP, HOLD = "lerp", "hold"


@dataclass
class Channels:
    names: list[str]
    kinds: list[str]
    data: np.ndarray          # (frames, channels) float32
    drops: list[dict]
    duration: float
    sections: list = None        # decide.Section, when made by direct()
    info: dict = None

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


def find_drops(a: dict, period: float, duration: float, meter: int = 4) -> list[dict]:
    """Downbeats where the floor comes back.

    At each downbeat: how much louder is the beat after it than the bar before it,
    and how much floor arrived. A re-entry is both at once. Strength is the two
    added, scaled so the biggest in the song is 1.
    """
    loud, floor = a["loud_db"], a["sub"]
    bar = meter * period
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

SECTION_RAMP_BARS = 4.0        # a palette or a mode arrives over this many bars
CHORD_RAMP_BEATS = 2.0


def avoid_murk(h: np.ndarray) -> np.ndarray:
    """Two arcs of the wheel turn to mud on a dark screen: yellow-green, and orange,
    which at low lightness is simply brown. Hues that land in the first are eased
    round to emerald and teal, in the second to rose and wine. Smooth and monotone,
    so two hues that were neighbours still are."""
    h = np.asarray(h, dtype=np.float64)
    green = ((h - 0.32 + 0.5) % 1.0) - 0.5
    brown = ((h - 0.10 + 0.5) % 1.0) - 0.5
    return h + 0.10 * np.exp(-(green / 0.11) ** 2) - 0.085 * np.exp(-(brown / 0.085) ** 2)


def fifths_from(tonic: int, pc: np.ndarray) -> np.ndarray:
    """Signed distance round the circle of fifths, -6..+6."""
    f = (7 * (np.asarray(pc) - tonic)) % 12
    return np.where(f > 6, f - 12, f)


CHORD_ROOTS = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6,
               "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def direct(got: dict, mod: tuple[dict, dict] | None = None) -> Channels:
    a, meta = got["arrays"], got["meta"]
    n, period, duration = int(meta["n"]), float(meta["period"]), float(meta["duration"])
    t = np.arange(n) / RATE
    beat_w = int(round(period * RATE))
    bar = int(meta.get("meter", 4)) * period
    cols: dict[str, tuple[str, np.ndarray]] = {}
    m_arr, m_meta = mod if mod is not None else ({}, {})
    tonic = int(m_meta.get("key", {}).get("tonic", 9))

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
    cols["uHold"] = (LERP, follow(hold, 0.10, 0.60))
    # Orbital phase runs on beats, faster the harder the body holds: integrate.
    rate = (0.05 + 0.20 * hold) / period                 # turns per second
    cols["uOrbit"] = (LERP, np.cumsum(rate) / RATE)
    # The same clock at a pace a real system could keep: the innermost planet goes
    # round once in sixteen bars under a full floor, and slower without one. (The glow
    # style's satellites are abstract and keep the quick one; the cel-shaded style's
    # planets are meant to be believed.)
    cols["uOrbitSlow"] = (LERP, np.cumsum((0.40 + 0.60 * hold) / (16.0 * bar)) / RATE)

    # --- thrown rings ------------------------------------------------------------
    st, sa = a["ev_snare_t"], a["ev_snare_amp"]
    keep = sa > 0.30
    tone = a["ev_snare_bright"][keep].astype(np.float64)
    tone = np.searchsorted(np.sort(tone), tone) / max(len(tone) - 1, 1)      # rank, 0..1
    RT, RA = held_events(st[keep], np.clip(sa[keep], 0, 1.3), n, N_RINGS)
    _, RM = held_events(st[keep], tone, n, N_RINGS)
    for k in range(N_RINGS):
        cols[f"uRingT{k}"] = (HOLD, RT[:, k])
        cols[f"uRingA{k}"] = (HOLD, RA[:, k])
        cols[f"uRingM{k}"] = (HOLD, RM[:, k])

    # --- hats and crashes ----------------------------------------------------------
    ht, ha = a["ev_hat_t"], a["ev_hat_amp"]
    keep = ha > 0.25
    HT, HA = held_events(ht[keep], np.clip(ha[keep], 0, 1.3), n)
    _, HK = held_events(ht[keep], (np.arange(keep.sum()) % 3).astype(np.float64), n)
    cols["uHatT"] = (HOLD, HT[:, 0])
    cols["uHatA"] = (HOLD, HA[:, 0])
    cols["uHatK"] = (HOLD, HK[:, 0])
    ct, ca = a["ev_crash_t"], a["ev_crash_amp"]
    keep_crash = ca > 0.9
    CT, CA = held_events(ct[keep_crash], np.clip(ca[keep_crash] / 1.6, 0, 1.0), n)
    cols["uCrashT"] = (HOLD, CT[:, 0])
    cols["uCrashA"] = (HOLD, CA[:, 0])

    # --- notes: the model says which, the stem says when -----------------------------
    nt, na, npitch = a["ev_note_t"], a["ev_note_amp"], a["ev_note_pitch"].astype(np.float64)
    keep = na > 0.25
    nt, na, npitch = nt[keep], na[keep], npitch[keep]
    if "other_t" in m_arr:
        mt, mm, ma = m_arr["other_t"], m_arr["other_midi"].astype(np.float64), m_arr["other_amp"]
        # every measured attack takes the pitch of the model note that snapped to it
        # (the loudest, if a chord did); attacks the model did not name keep the
        # constant-Q guess. Model notes on top of an attack, other than the loudest,
        # light their own satellites too - a chord is several satellites at once.
        order = np.argsort(-ma)
        seen: dict[float, int] = {}
        extra_t, extra_a, extra_p = [], [], []
        idx = {float(x): i for i, x in enumerate(nt)}
        for j in order:
            key = float(mt[j])
            if key in idx:
                if key not in seen:
                    seen[key] = j
                    npitch[idx[key]] = mm[j]
                elif ma[j] > 0.45:
                    extra_t.append(key); extra_a.append(0.7 * na[idx[key]]); extra_p.append(mm[j])
        nt = np.concatenate([nt, extra_t]); na = np.concatenate([na, extra_a])
        npitch = np.concatenate([npitch, extra_p])
        o = np.argsort(nt, kind="stable")
        nt, na, npitch = nt[o], na[o], npitch[o]
    # which satellite: its pitch, ranked within the song so all eight get used
    srt = np.sort(npitch)
    rank = (np.searchsorted(srt, npitch, "left") + np.searchsorted(srt, npitch, "right")) / (2 * max(len(srt), 1))
    slot = np.clip((rank * N_SATS).astype(int), 0, N_SATS - 1)
    # what colour: how far from home it is round the circle of fifths. The tonic and
    # its fifth are the first accent; the far side of the key is the second.
    far = np.abs(fifths_from(tonic, np.round(npitch).astype(int) % 12)) / 6.0
    NT, NA = held_events(nt, np.clip(na, 0, 1.3), n, N_SATS, slot_of=slot)
    _, NM = held_events(nt, far, n, N_SATS, slot_of=slot)
    for k in range(N_SATS):
        cols[f"uNoteT{k}"] = (HOLD, NT[:, k])
        cols[f"uNoteA{k}"] = (HOLD, NA[:, k])
        cols[f"uNoteM{k}"] = (HOLD, NM[:, k])
    cols["uSynth"] = (LERP, follow(a["other"].astype(np.float64), 0.03, 0.5))
    # the pad ducking under the kick, fast enough to see
    other = a["other"].astype(np.float64)
    cols["uPump"] = (LERP, follow(np.clip(other / max(np.percentile(other, 95), 1e-9), 0, 1), 0.012, 0.09))

    # --- the voice --------------------------------------------------------------
    cols["uVoice"] = (LERP, follow(a["voice"].astype(np.float64), 0.010, 0.09))
    if "f0_t" in m_arr:
        ft, hz, conf = m_arr["f0_t"], m_arr["f0_hz"].astype(np.float64), m_arr["f0_conf"]
        sure = conf > 0.6
        semis = 12 * np.log2(np.maximum(hz, 1.0) / 220.0)
        centre = np.median(semis[sure])
        last = np.where(sure, np.arange(len(semis)), 0)
        np.maximum.accumulate(last, out=last)
        held = np.where(last > 0, semis[last], centre)
        f_rate = 1.0 / float(np.median(np.diff(ft)))
        pitch = np.interp(t, ft, smooth(held - centre, f_rate, 0.07))
        # a held note: sure of the pitch, and the pitch not going anywhere
        moving = np.abs(np.gradient(smooth(held, f_rate, 0.05))) * f_rate      # st per second
        steady = np.interp(t, ft, (sure & (moving < 4.0)).astype(np.float64))
        cols["uPitch"] = (LERP, smooth(np.clip(pitch / 12.0, -1, 1), RATE, 0.10))
        cols["uSustain"] = (LERP, follow(steady * np.clip(a["voice"] / 0.3, 0, 1), 0.45, 0.14))
    else:
        cols["uPitch"] = (LERP, a["voice_pitch"].astype(np.float64))
        cols["uSustain"] = (LERP, np.zeros(n))
    yt, ya = a["ev_syllable_t"], a["ev_syllable_amp"]
    keep = ya > 0.30
    YT, YA = held_events(yt[keep], np.clip(ya[keep], 0, 1.3), n)
    cols["uSyllT"] = (HOLD, YT[:, 0])
    cols["uSyllA"] = (HOLD, YA[:, 0])

    # what the line is about tints the voice; a word that *is* the image, fully
    tint_w = np.zeros(n)
    tint_lch = np.tile(np.array([0.9, 0.0, 0.0]), (n, 1))
    images = list(decide.IMAGES.values())
    if "line_similarity" in m_arr:
        spans = []
        for (t0, t1), row in zip(m_arr["line_t"], m_arr["line_similarity"]):
            k = int(np.argmax(row))
            if row[k] >= 0.35:
                spans.append((t0, t1 + 0.4, 0.30 + 0.55 * min((row[k] - 0.35) / 0.25, 1.0), k))
        for (t0, t1), row in zip(m_arr["word_t"], m_arr["word_similarity"]):
            k = int(np.argmax(row))
            if row[k] >= 0.50:
                spans.append((t0, max(t1, t0 + 0.35) + 0.5, 1.0, k))
        target = np.zeros(n)
        which = np.full(n, -1)
        for t0, t1, wgt, k in sorted(spans, key=lambda s_: s_[2]):      # strongest written last
            i0, i1 = int(t0 * RATE), min(int(t1 * RATE), n)
            target[i0:i1] = wgt
            which[i0:i1] = k
        # the colour is held from one tinted span to the next and ramped between, so
        # when the weight comes up the colour is already there
        marks = np.where(which >= 0)[0]
        if len(marks):
            nearest = marks[np.clip(np.searchsorted(marks, np.arange(n)), 0, len(marks) - 1)]
            lch = np.array([images[k][1] for k in which[nearest]])
            lch[:, 2] = colour.unwrap_turns(lch[:, 2])
            for c in range(3):
                tint_lch[:, c] = smooth(lch[:, c], RATE, 0.5)
        tint_w = follow(target, 0.10, 0.9)
    rgb = colour.oklch_to_linear_rgb(tint_lch[:, 0], tint_lch[:, 1], tint_lch[:, 2] % 1.0)
    cols["uTint"] = (LERP, tint_w)
    for c, name in enumerate("RGB"):
        cols[f"uTint{name}"] = (LERP, rgb[:, c])

    # --- the field and the light --------------------------------------------------
    cols["uField"] = (LERP, smooth(a["bright"].astype(np.float64), RATE, 0.25))
    cols["uAir"] = (LERP, a["air"].astype(np.float64))
    loud = a["loud"].astype(np.float64)
    exposure = np.clip((loud - 0.50) / 0.40, 0.0, 1.0) ** 1.3
    cols["uExposure"] = (LERP, follow(exposure, 0.02, 0.18))

    # --- per section: palette, layers, the plane ------------------------------------
    drops = find_drops(a, period, duration, int(meta.get("meter", 4)))
    sections, info = decide.plan(a, drops, duration, mod)
    starts = np.array([s.start for s in sections])
    ramp = SECTION_RAMP_BARS * bar

    def track(values, circular=False, seconds=ramp):
        return colour.hold_then_ramp(np.asarray(values, dtype=np.float64), starts, n, RATE,
                                     seconds, circular=circular)

    # the song's own arc rides on top of the form: everything turns a tenth of the
    # wheel warmer between the first bar and the last
    energy = a["energy"].astype(np.float64)
    arc = np.cumsum(energy) / max(energy.sum(), 1e-9)
    # chords lean the field; the bass note leans the body
    chord_lean, chord_light = np.zeros(n), np.zeros(n)
    for c in m_meta.get("chords", []):
        name = c["chord"]
        if name in ("N", "X") or ":" not in name:
            continue
        root, quality = name.split(":", 1)
        if root not in CHORD_ROOTS:
            continue
        i0, i1 = int(c["start"] * RATE), min(int(c["end"] * RATE), n)
        chord_lean[i0:i1] = float(fifths_from(tonic, np.array([CHORD_ROOTS[root]]))[0]) / 6.0
        chord_light[i0:i1] = 1.0 if quality.startswith("maj") else -1.0
    chord_lean = smooth(chord_lean, RATE, CHORD_RAMP_BEATS * period)
    chord_light = smooth(chord_light, RATE, CHORD_RAMP_BEATS * period)
    bass_lean = np.zeros(n)
    if "bass_t" in m_arr:
        bt, bm = m_arr["bass_t"], m_arr["bass_midi"]
        i = np.clip(np.searchsorted(bt, t, side="right") - 1, 0, len(bt) - 1)
        bass_lean = smooth(fifths_from(tonic, bm[i] % 12) / 6.0, RATE, 0.20)

    palettes = [decide.palette_for(s) for s in sections]
    # with no floor the colour drains a little: the void is paler than the drive
    drain = 1.0 - 0.30 * smooth(1.0 - floor, RATE, 0.6)
    for role in PALETTE_ROLES:
        L = track([p[role][0] for p in palettes])
        C = track([p[role][1] for p in palettes]) * drain
        h = track([p[role][2] for p in palettes], circular=True) + 0.10 * arc
        if role in ("Field", "Far"):
            h = h + 0.045 * chord_lean
            L = L + 0.035 * chord_light
        if role == "Body":
            h = h + 0.035 * bass_lean
        rgb = colour.oklch_to_linear_rgb(np.clip(L, 0, 1), np.clip(C, 0, 0.4), avoid_murk(h) % 1.0)
        for c, name in enumerate("RGB"):
            cols[f"uC{role}{name}"] = (LERP, rgb[:, c])

    modes = [decide.modes_for(s) for s in sections]
    cols["uRays"] = (LERP, track([m["rays"] for m in modes]) * (0.35 + 0.65 * follow(hold, 0.15, 0.8)))
    cols["uBands"] = (LERP, track([m["bands"] for m in modes]))
    cols["uStars"] = (LERP, track([m["stars"] for m in modes]))
    cols["uTilt"] = (LERP, track([m["tilt"] for m in modes], seconds=2 * ramp))
    cols["uIncl"] = (LERP, track([m["incl"] for m in modes], seconds=2 * ramp))

    # a riser draws the stars outward: no floor, and the air rising
    tension = smooth((1.0 - floor) * (0.35 + 0.65 * a["air"].astype(np.float64)), RATE, 1.0)
    cols["uDrift"] = (LERP, np.cumsum(0.004 + 0.085 * tension) / RATE)      # octaves

    # --- the shock --------------------------------------------------------------
    DT, DA = held_events(np.array([d["t"] for d in drops]),
                         np.array([d["strength"] for d in drops]), n)
    cols["uDropT"] = (HOLD, DT[:, 0])
    cols["uDropA"] = (HOLD, DA[:, 0])

    # --- shooting stars: every crash throws one, every re-entry a bigger one,
    # (only the printed style draws them; a channel no shader declares is never set)
    # and the bar line a small one, every second bar, wherever the song has some air in
    # it - so there is always something crossing the sky, and it is always on the grid
    big_t = np.concatenate([ct[keep_crash], np.array([d["t"] for d in drops])])
    big_a = np.concatenate([np.clip(ca[keep_crash] / 1.6, 0.45, 0.8),
                            np.array([0.7 + 0.3 * d["strength"] for d in drops])])
    bars_t = a["downbeats"][(a["downbeats"] > 2 * bar) & (a["downbeats"] < duration - bar)][::2]
    loud_at = a["loud"][np.clip((bars_t * RATE).astype(int), 0, n - 1)]
    bars_t = bars_t[loud_at > 0.55]
    clear = np.array([np.abs(big_t - x).min() > 1.0 for x in bars_t]) if len(big_t) else np.ones(len(bars_t), bool)
    bars_t = bars_t[clear]
    mt = np.concatenate([big_t, bars_t])
    ma = np.concatenate([big_a, np.full(len(bars_t), 0.22)])
    o = np.argsort(mt)
    mt, ma = mt[o], ma[o]
    far_enough = np.concatenate([[True], np.diff(mt) > 0.30])          # a crash *on* a re-entry is one event
    mt, ma = mt[far_enough], ma[far_enough]
    MT, MA = held_events(mt, ma, n, N_METEORS)
    _, MS = held_events(mt, 1.0 + np.arange(len(mt), dtype=np.float64), n, N_METEORS)
    for k in range(N_METEORS):
        cols[f"uMetT{k}"] = (HOLD, MT[:, k])
        cols[f"uMetA{k}"] = (HOLD, MA[:, k])
        cols[f"uMetS{k}"] = (HOLD, MS[:, k])

    cols["uBeats"] = (LERP, a["beats_elapsed"].astype(np.float64))

    names = list(cols)
    kinds = [cols[k][0] for k in names]
    data = np.stack([cols[k][1] for k in names], axis=1).astype(np.float32)
    ch = Channels(names, kinds, data, drops, duration)
    ch.sections = sections
    ch.info = info
    return ch
