"""The decisions that are made once per passage rather than once per hit.

Where the sections are; what colours each one wears; which of the background
layers it leans on; how far the orbit plane is tipped. Every decision here is a
value per section, and `direct` turns each into a track with no steps in it - so
however abrupt a decision is, the picture ramps.

Three kinds of evidence go in:

    measured     floor state, voice, percussion, loudness, brightness, per bar
    heard        CLAP's reading of each section against pairs of opposite words
    read         what each lyric line is about, against colour-bearing images

and the rule that turns them into hue is the song's own form: **sections that sound
alike are given hues that sit together, sections that contrast are sent apart.** The
second chorus looks like the first because it sounds like the first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .listen import RATE

# Opposites, for CLAP. Each pair is one axis; a section's place on it is the
# difference of its similarities, standardised across the song - so an axis says
# how this passage differs from the rest of *this* track, which is what variety is.
AXES: dict[str, tuple[str, str]] = {
    # kept for the record, not used: it does not follow loudness on this track
    "energy": ("calm, quiet, sparse, gentle music", "loud, energetic, driving dance music with a heavy beat"),
    "bright": ("dark, moody, brooding, ominous music", "bright, uplifting, euphoric, joyful music"),
    "warm": ("cold, icy, metallic, synthetic electronic music", "warm, lush, emotional, soulful music"),
    "space": ("intimate, close, dry, minimal music", "huge, spacious, atmospheric music with long reverb"),
    "tension": ("relaxed, resolved, flowing, steady groove", "tense, suspenseful build-up rising toward a drop"),
    "dream": ("punchy, hard-hitting, percussive, aggressive music", "dreamy, ethereal, floating, weightless music"),
}

# Images a lyric can be about, and the colour each one is. Hue in turns of OKLCH
# (0.08 orange, 0.30 green, 0.55 cyan-blue, 0.75 violet, 0.95 pink-red).
IMAGES: dict[str, tuple[str, tuple[float, float, float]]] = {
    "gold": ("sunlight, golden light, dawn, daybreak, morning", (0.88, 0.13, 0.22)),
    "silver": ("silver, moonlight, chrome, mirror, glass", (0.90, 0.035, 0.66)),
    "fire": ("fire, flames, heat, burning, explosion", (0.74, 0.19, 0.11)),
    "shadow": ("shadow, darkness, night, hidden, silence", (0.55, 0.12, 0.80)),
    "electric": ("electric, lightning, neon, spark, raw voltage", (0.88, 0.14, 0.54)),
    "velvet": ("velvet, haze, smoke, soft, deep", (0.68, 0.15, 0.90)),
    "sky": ("sky, air, floating, weightless, orbit, space, gravity", (0.82, 0.11, 0.62)),
    "heart": ("heart, love, pulse, devotion, emotion, desire", (0.72, 0.19, 0.01)),
}


@dataclass
class Section:
    index: int
    bar0: int
    bar1: int                       # exclusive
    start: float
    end: float
    state: str                      # drive / float / void / silent
    voiced: float                   # share of bars with the voice in
    drive: float
    void: float
    loud: float
    bright: float
    hats: float                     # per bar
    snares: float                   # per bar
    notes: float                    # per bar
    axes: dict[str, float] = field(default_factory=dict)
    family: int = 0                 # which sections it sounds like
    hue: float = 0.0

    @property
    def bars(self) -> int:
        return self.bar1 - self.bar0


def drive_at(pulses: np.ndarray) -> int:
    """How many strong pulses make a bar drive, for this song: three quarters of what a bar
    has when the pulse is playing, rounded. Four on the floor gives 3, as it always was; a
    half-time kick, two to a bar, gives 2 (at a fixed 3, Shattered Voices had no bar that
    drove though its kick played in 97 % of them)."""
    playing = pulses[pulses > 0]
    return max(1, int(np.floor(0.75 * np.median(playing) + 0.5))) if len(playing) else 3


def bar_table(a: dict, duration: float) -> dict[str, np.ndarray]:
    """Per bar: what is playing. Bar 0 starts at the first downbeat at or before 0."""
    t = a["bar_t"]
    edges = np.append(t, duration)

    def count(name: str, floor: float) -> np.ndarray:
        ev = a[f"ev_{name}_t"][a[f"ev_{name}_amp"] > floor]
        return np.histogram(ev, bins=edges)[0].astype(float)

    def mean(name: str) -> np.ndarray:
        return np.array([a[name][int(max(b0, 0) * RATE): max(int(b1 * RATE), int(max(b0, 0) * RATE) + 1)].mean()
                         for b0, b1 in zip(edges[:-1], edges[1:])])

    kicks = count("kick", 0.5)
    sub, loud = mean("sub"), mean("loud")
    state = np.where(loud < 0.30, 3, np.where(kicks >= drive_at(kicks), 0, np.where(sub < 0.06, 2, 1)))
    return {"t": t, "kicks": kicks, "hats": count("hat", 0.25), "snares": count("snare", 0.30),
            "notes": count("note", 0.25), "voice": mean("voice"), "sub": sub, "loud": loud,
            "bright": mean("bright"), "state": state}


STATE_NAMES = ("drive", "float", "void", "silent")


def find_sections(a: dict, drops: list[dict], duration: float, min_bars: int = 4) -> list[Section]:
    """Runs of bars in one state, cut also at every re-entry, short runs absorbed.

    A void is the held breath before a re-entry: it belongs to the passage it ends,
    so it never starts a section of its own. What is left agrees with the song's
    eight-bar phrasing without having been told about it.
    """
    tb = bar_table(a, duration)
    n = len(tb["t"])
    state = tb["state"].copy()
    voiced = tb["voice"] > 0.25
    # a void continues whatever came before it
    for i in range(1, n):
        if state[i] == 2:
            state[i] = state[i - 1]
    key = state * 2 + voiced.astype(int)
    # majority over a four-bar window, so one odd bar does not make a section
    smooth_key = key.copy()
    for i in range(n):
        lo, hi = max(0, i - 1), min(n, i + 3)
        vals, counts = np.unique(key[lo:hi], return_counts=True)
        smooth_key[i] = vals[np.argmax(counts)]
    cuts = {0} | {i for i in range(1, n) if smooth_key[i] != smooth_key[i - 1]}
    bar_len = float(np.median(np.diff(tb["t"])))
    cuts |= {int(round((d["t"] - tb["t"][0]) / bar_len)) for d in drops}
    cuts = sorted(c for c in cuts if 0 <= c < n)
    # absorb anything shorter than min_bars into the section before it, unless it
    # begins at a re-entry - a re-entry always begins something
    drop_bars = {int(round((d["t"] - tb["t"][0]) / bar_len)) for d in drops}
    kept = [cuts[0]]
    for c, nxt in zip(cuts[1:], cuts[2:] + [n]):
        if nxt - c < min_bars and c not in drop_bars:
            continue
        if c - kept[-1] < min_bars and c not in drop_bars and kept[-1] not in drop_bars and len(kept) > 1:
            kept[-1] = c
            continue
        kept.append(c)
    bounds = kept + [n]

    out = []
    for k, (b0, b1) in enumerate(zip(bounds[:-1], bounds[1:])):
        sl = slice(b0, b1)
        raw = tb["state"][sl]
        shares = [float((raw == s).mean()) for s in range(4)]
        out.append(Section(
            index=k, bar0=b0, bar1=b1, start=float(max(tb["t"][b0], 0.0)),
            end=float(tb["t"][b1]) if b1 < n else duration,
            state=STATE_NAMES[int(np.argmax(shares))], voiced=float(voiced[sl].mean()),
            drive=shares[0], void=shares[2], loud=float(tb["loud"][sl].mean()),
            bright=float(tb["bright"][sl].mean()), hats=float(tb["hats"][sl].mean()),
            snares=float(tb["snares"][sl].mean()), notes=float(tb["notes"][sl].mean())))
    return out


# ------------------------------------------------------------------ form -> hue


def place_hues(sections: list[Section], embedding: np.ndarray, warm: np.ndarray,
               anchor_hue: float = 0.72) -> dict:
    """Give each section a hue so that likeness in sound is nearness in hue.

    The sections' embeddings, with what the whole song has in common taken out, are
    reduced to the plane in which they differ most, and a section's hue is its
    *direction* in that plane. Sections that sound alike point the same way and wear
    the same hue; families of sections end up in different parts of the wheel. The
    plane is turned so the first long section sits at `anchor_hue` (blue), and
    flipped, if need be, so that the sections CLAP hears as warm land on the warm
    side - the two freedoms a projection leaves open, both settled by the data.
    """
    live = np.array([s.state != "silent" for s in sections])
    x = embedding - embedding[live].mean(axis=0, keepdims=True)
    w = np.sqrt(np.array([s.bars for s in sections], dtype=np.float64)) * live
    _, sv, vt = np.linalg.svd(x * w[:, None], full_matrices=False)
    xy = x @ vt[:2].T
    ang = np.arctan2(xy[:, 1], xy[:, 0]) / (2 * np.pi)
    first = next(i for i, s in enumerate(sections) if s.bars >= 8)

    def hues(sign: float) -> np.ndarray:
        return (anchor_hue + sign * (ang - ang[first])) % 1.0

    def warmth_fit(h: np.ndarray) -> float:
        warm_side = np.cos(2 * np.pi * (h - 0.10))          # 1 at orange, -1 at blue
        return float(np.corrcoef(warm_side[live], warm[live])[0, 1])

    sign = 1.0 if warmth_fit(hues(1.0)) >= warmth_fit(hues(-1.0)) else -1.0
    h = hues(sign)
    # how far from the centre a section is says how sure its direction is; one that
    # sounds like the average of the song is pulled toward its neighbour's hue
    radius = np.hypot(xy[:, 0], xy[:, 1])
    sure = np.clip(radius / max(np.median(radius[live]), 1e-9), 0.0, 1.0)
    for i, s in enumerate(sections):
        if not live[i] or sure[i] < 0.35:
            j = i - 1 if i > 0 else i + 1
            d = ((h[j] - h[i] + 0.5) % 1.0) - 0.5
            h[i] = (h[i] + (1.0 - sure[i] / 0.35 if live[i] else 1.0) * d) % 1.0
        s.hue = float(h[i])
    return {"variance_in_plane": float((sv[:2] ** 2).sum() / max((sv ** 2).sum(), 1e-12)),
            "flipped": sign < 0, "warmth_fit": warmth_fit(h)}


def z(values: list[float]) -> np.ndarray:
    v = np.asarray(values, dtype=np.float64)
    return (v - v.mean()) / max(v.std(), 1e-9)


def energy_of(s: Section) -> float:
    """Measured, not heard: CLAP's energy axis has no correlation with loudness on
    this track (r = -0.05), so loudness and the kick are asked instead."""
    return float(np.clip(0.55 * (s.loud - 0.60) / 0.30 + 0.45 * s.drive, 0.0, 1.0))


def dream_of(s: Section) -> float:
    """Likewise measured: CLAP's dreamy axis mostly counts hi-hats (r = +0.78). A
    passage floats when nothing is driving it and someone is singing."""
    return float(np.clip((1.0 - s.drive) * (0.55 + 0.45 * s.voiced), 0.0, 1.0))


def palette_for(s: Section) -> dict[str, tuple[float, float, float]]:
    """Five roles in OKLCH (lightness, chroma, hue in turns) for one section.

    The field wears the section's hue. The body sits a little round from it and
    lighter. The two accents are thrown well away from the field, on either side, so
    that a melody moving between them is two colours against a third: that is where
    most of the colour on screen at once comes from. Energy buys chroma; brightness
    buys lightness; warmth pulls the accents toward the warm side of the wheel.
    """
    ax = s.axes
    e = energy_of(s)
    b = float(np.clip(0.5 + 0.22 * ax.get("bright", 0.0), 0.0, 1.0))
    wm = float(np.clip(0.18 * ax.get("warm", 0.0), -0.3, 0.3))
    dream = dream_of(s)
    h = s.hue
    wide = 0.30 + 0.08 * e                       # how far the accents are thrown
    return {
        "Field": (0.56 + 0.10 * b, 0.17 + 0.07 * e, h),
        "Far": (0.40 + 0.06 * b, 0.13 + 0.05 * dream, h - 0.13 - 0.05 * dream),
        "Body": (0.80 + 0.06 * b, 0.12 + 0.05 * e, h + 0.07 + 0.3 * wm),
        "Accent": (0.80, 0.19 + 0.05 * e, h + wide + 0.5 * wm),
        "Accent2": (0.76, 0.19 + 0.05 * e, h - wide + 0.5 * wm),
    }


def modes_for(s: Section) -> dict[str, float]:
    """Which background layers a section leans on, and how the orbits are seen.

    Rays belong to a body that is driving; bands to a passage that is floating;
    stars to anything with air in it. The plane tips toward face-on when the music
    opens out and lies flatter when it drives. All weights, all ramped: a section
    never switches a layer on, it leans toward it.
    """
    ax = s.axes
    dream = dream_of(s)
    space = float(np.clip(0.5 + 0.25 * ax.get("space", 0.0), 0, 1))
    energy = energy_of(s)
    return {
        "rays": float(np.clip(0.15 + 0.95 * s.drive * (0.5 + 0.5 * energy) - 0.3 * dream * (1 - s.drive), 0, 1)),
        "bands": float(np.clip(0.10 + 0.85 * (1 - s.drive) * (0.4 + 0.6 * dream) + 0.2 * s.voiced * (1 - s.drive), 0, 1)),
        "stars": float(np.clip(0.30 + 0.35 * space + 0.35 * min(s.hats / 12.0, 1.0), 0, 1)),
        "tilt": float(np.clip(0.44 + 0.30 * (1 - s.drive) * (0.4 + 0.6 * space) + 0.08 * dream, 0.40, 0.82)),
        # the plane swings with the hue, so a family of sections shares a way of
        # being looked at as well as a colour
        "incl": float(0.42 * np.sin(2 * np.pi * (s.hue - 0.72)) - 0.12),
    }


def plan(a: dict, drops: list[dict], duration: float, mod: tuple[dict, dict] | None) -> tuple[list[Section], dict]:
    """Sections, each with its axes, its hue, and so its palette and its modes."""
    sections = find_sections(a, drops, duration)
    live = np.array([s.state != "silent" for s in sections])

    def unit_rows(x: np.ndarray) -> np.ndarray:
        x = x - x[live].mean(axis=0, keepdims=True)
        return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)

    feat = a["bar_feat"].astype(np.float64)
    feat = (feat - feat.mean(axis=0)) / np.maximum(feat.std(axis=0), 1e-9)
    embedding = unit_rows(np.stack([feat[s.bar0:s.bar1].mean(axis=0) for s in sections]))
    warm = np.array([s.bright for s in sections])          # a stand-in, without CLAP
    if mod is not None and len(mod[0]["clap_similarity"]) == len(sections):
        sim = mod[0]["clap_similarity"].astype(np.float64)
        for k, name in enumerate(AXES):
            d = sim[:, 2 * k + 1] - sim[:, 2 * k]
            zed = (d - d[live].mean()) / max(d[live].std(), 1e-9)
            for s, v in zip(sections, zed):
                s.axes[name] = float(np.clip(v, -2.5, 2.5)) if s.state != "silent" else 0.0
        embedding = np.concatenate([embedding, unit_rows(mod[0]["clap_embedding"].astype(np.float64))], axis=1)
        warm = np.array([s.axes["warm"] for s in sections])
    info = place_hues(sections, embedding, warm)
    return sections, info
