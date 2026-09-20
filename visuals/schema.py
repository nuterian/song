"""The score: a typed, quantised description of what the visuals do.

A score is data, not code, and it is not free text either. It is a fixed set of
*slots*, each one a categorical choice over an enumerated set of legal values.
That shape is the whole point. It means the decision model of milestone 4 never
emits a token of GLSL: it fills slots, illegal values are masked out of its
logits, and so every score it produces is valid by construction rather than by
good behaviour.

Three tiers, coarse to fine:

    song      one of each slot, for the whole track - palette, block set, motif,
              how the motion feels, how symmetric the frame is
    section   one of each slot per section of the song - the scene, the warp,
              the post chain, how dense and how bright, how it arrives
    bar       one of each slot per bar - a routing event, which is to say: take
              this audio feature, drive that uniform with it, this hard, with
              this attack and release

Continuous quantities are quantised to 32 bins, so that every slot is a
categorical and a single masking rule covers all of them. `BINS` is that count.

Partially filled scores are first class: any slot may hold `MASK`, which is what
makes both masked decoding and "lock the palette, re-roll the bridge" the same
operation. `to_slots` flattens a score to a fixed integer layout - song slots,
then section slots section by section, then bar slots bar by bar - and
`from_slots` brings it back, exactly.

`legal_values` is the grammar's half of the contract: given the slots filled so
far, which values does slot i still allow. Where a rule depends on a slot that
is itself still masked, the rule is evaluated over every value that slot could
take and the results are unioned, so a decode can commit slots in any order and
never paint itself into a corner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

import numpy as np

VERSION = 1

# Every slot value is an index into its own value list. MASK is outside every
# such list, so it can never be confused with a decision.
MASK = -1

# Resolution of a quantised continuous slot. 32 is enough that a bin boundary is
# not visible on screen and small enough that a softmax over it stays sharp.
BINS = 32


@dataclass(frozen=True)
class Slot:
    """One decision. `values` is the complete enumeration of what it may say."""

    name: str
    tier: str  # "song" | "section" | "bar"
    kind: str  # "enum" | "bin"
    values: tuple[str, ...]
    doc: str

    @property
    def card(self) -> int:
        return len(self.values)

    def index_of(self, value: str | int) -> int:
        if self.kind == "bin":
            i = int(value)
            if not 0 <= i < BINS:
                raise ValueError(f"{self.name}: bin {i} outside 0..{BINS - 1}")
            return i
        try:
            return self.values.index(str(value))
        except ValueError:
            raise ValueError(
                f"{self.name}: {value!r} is not one of {', '.join(self.values)}"
            ) from None

    def value_of(self, index: int) -> str | int:
        """The JSON form of a slot index: a name for an enum, a number for a bin."""
        return index if self.kind == "bin" else self.values[index]

    def unit(self, index: int) -> float:
        """A bin index as a number in 0..1. Bin centres, so 0 is not dead zero."""
        return (index + 0.5) / BINS


def _bin_slot(name: str, tier: str, doc: str) -> Slot:
    return Slot(name, tier, "bin", tuple(f"{i}" for i in range(BINS)), doc)


def _enum_slot(name: str, tier: str, values: Sequence[str], doc: str) -> Slot:
    return Slot(name, tier, "enum", tuple(values), doc)


# --------------------------------------------------------------------------- #
# Song tier
# --------------------------------------------------------------------------- #

PALETTE_FAMILIES = ("ember", "ice", "neon", "mono", "verdant", "dusk", "rust", "coral")
MOTIFS = ("circle", "hex", "triangle", "star", "slot", "bar")
# The first four fold around a centre; the last two point somewhere, and a
# kaleidoscope only makes a mess of those.
RADIAL_MOTIFS = ("circle", "hex", "triangle", "star")

# A block set is a promise about which moods belong to one song. It is what keeps
# a song recognisable as itself: every layer is compiled in, but a song only moves
# among the scenes its set admits.
BLOCK_SET_SCENES: dict[str, tuple[str, ...]] = {
    "orbital": ("wash", "drift", "orbits", "bloom"),
    "linear": ("wash", "sweep", "bands", "weave"),
    "radial": ("wash", "halo", "eclipse", "bloom"),
    "woven": ("drift", "weave", "bands", "orbits"),
    "wide": ("wash", "sweep", "eclipse", "halo"),
}
BLOCK_SETS = tuple(BLOCK_SET_SCENES)
MOTION_CHARACTERS = ("drift", "pulse", "sweep", "churn", "still")
SYMMETRIES = ("none", "mirror_x", "kaleido_3", "kaleido_5", "kaleido_6", "kaleido_8")

SONG_SLOTS: tuple[Slot, ...] = (
    _enum_slot("palette_family", "song", PALETTE_FAMILIES,
               "Which cosine-palette family colours the whole track."),
    _bin_slot("palette_shift", "song",
              "Phase offset into that palette, so two songs on the same family "
              "do not open on the same colour."),
    _enum_slot("block_set", "song", BLOCK_SETS,
               "The family of grammar blocks this song is built from. Constrains "
               "which scenes a section may choose."),
    _enum_slot("motif", "song", MOTIFS,
               "The shape that recurs. Radial motifs admit kaleidoscopes; "
               "grid and line motifs do not."),
    _enum_slot("motion_character", "song", MOTION_CHARACTERS,
               "How motion feels across the whole track, independently of how "
               "fast the song is."),
    _enum_slot("symmetry", "song", SYMMETRIES,
               "Frame symmetry. Applied once, before anything is drawn."),
    _bin_slot("grain", "song", "How much noise sits on top of the final frame."),
)

# --------------------------------------------------------------------------- #
# Section tier
#
# Nothing here is a switch. Every section-level choice resolves to a vector of
# numbers - layer weights, warp weights, post weights, levels - and the renderer
# ramps from one section's vector to the next's over a window the section itself
# chooses. That is the whole reason there are no cuts: a section boundary is a
# place where numbers start moving, not a place where one thing is replaced by
# another. One shader draws the entire song.
# --------------------------------------------------------------------------- #

# The four layers every frame is built from. They are always all compiled in and
# always all evaluated; a scene is a set of weights over them, so any two scenes
# have a straight line between them.
LAYERS = ("wash", "orbits", "bands", "halo")

# A scene is a named point in weight space. Naming them keeps the slot categorical -
# which is what the decision model wants - while the thing it denotes stays a
# vector, which is what a seamless transition needs.
SCENE_LAYERS: dict[str, tuple[float, float, float, float]] = {
    #              wash  orbits bands  halo
    "wash":       (1.00, 0.00, 0.00, 0.00),
    "drift":      (0.70, 0.55, 0.00, 0.00),
    "orbits":     (0.25, 1.00, 0.00, 0.00),
    "sweep":      (0.55, 0.00, 0.80, 0.00),
    "bands":      (0.20, 0.00, 1.00, 0.00),
    "halo":       (0.35, 0.00, 0.00, 1.00),
    "bloom":      (0.45, 0.45, 0.00, 0.70),
    "weave":      (0.30, 0.30, 0.65, 0.00),
    "eclipse":    (0.60, 0.00, 0.30, 0.85),
}
SCENES = tuple(SCENE_LAYERS)

# Warps are weights too, so a section can be half way between two of them.
WARP_WEIGHTS: dict[str, tuple[float, float, float]] = {
    #             swirl ripple stretch
    "none":      (0.00, 0.00, 0.00),
    "swirl":     (1.00, 0.00, 0.00),
    "ripple":    (0.00, 1.00, 0.00),
    "stretch":   (0.00, 0.00, 1.00),
    "breathe":   (0.25, 0.70, 0.00),
    "draw":      (0.45, 0.00, 0.55),
}
WARPS = tuple(WARP_WEIGHTS)

POST_STAGES = ("bloom", "trails", "split", "vignette")
POST_WEIGHTS: dict[str, tuple[float, float, float, float]] = {
    #             bloom trails split vignette
    "clean":     (0.00, 0.00, 0.00, 0.35),
    "soft":      (0.65, 0.00, 0.00, 0.45),
    "trails":    (0.20, 0.75, 0.00, 0.40),
    "smear":     (0.45, 0.90, 0.20, 0.30),
    "split":     (0.25, 0.00, 0.80, 0.45),
    "deep":      (0.70, 0.45, 0.35, 0.60),
}
POSTS = tuple(POST_WEIGHTS)

# How long a transition takes, in bars, and the shape of the ramp. Both are part
# of the score because how a mood arrives is a decision, not a constant.
TRANSITION_BARS = ("1", "2", "4", "8")
TRANSITION_CURVES = ("linear", "ease", "early", "late", "sigmoid")

# What "still" permits. A still song may breathe; it may not churn.
STILL_WARPS = ("none", "ripple", "breathe")
# Trails on a still song are a smear that never clears.
STILL_POSTS = tuple(p for p, w in POST_WEIGHTS.items() if w[POST_STAGES.index("trails")] == 0.0)

SECTION_SLOTS: tuple[Slot, ...] = (
    _enum_slot("scene", "section", SCENES,
               "Which layers this section is made of, and how much of each. Must "
               "be one the song's block set admits."),
    _enum_slot("warp", "section", WARPS,
               "How space is bent under the layers."),
    _enum_slot("post", "section", POSTS,
               "The post chain, as weights over bloom, trails, split and vignette."),
    _bin_slot("density", "section",
              "How much there is of whatever the layers draw - how many discs, "
              "how many bands, how wide the gradient."),
    _bin_slot("energy", "section",
              "Overall brightness and contrast of the section."),
    _bin_slot("softness", "section",
              "Hard edge to pure gradient. The single most useful dial for making "
              "one mood feel unlike another without changing what is drawn."),
    _bin_slot("palette_rotate", "section",
              "Where in the palette this section sits, which is how the colour "
              "arc over the song is written."),
    _enum_slot("transition_bars", "section", TRANSITION_BARS,
               "How many bars the morph into this section takes. Always begins on "
               "the downbeat the section begins on."),
    _enum_slot("transition_curve", "section", TRANSITION_CURVES,
               "The shape of that morph."),
)

# --------------------------------------------------------------------------- #
# Bar tier
# --------------------------------------------------------------------------- #

# `flux` is the half-wave-rectified rise of the mix envelope: the small changes,
# the ones a level does not show. It is here because "the picture notices what the
# music just did" is mostly a question of having a feature that notices it.
ROUTE_SOURCES = ("none", "mix", "vocal", "low", "high", "flux", "onset", "beat", "bar")

# Every target modulates something a simple shape has: how big it is, how far out
# it sits, how soft its edge is, what colour it is, how bright, how bent, how
# turned, how split, how shaken. Nothing here adds an element to the frame - the
# frame's elements are the section's business, and these are how the music moves
# what is already there.
ROUTE_TARGETS = ("none", "scale", "radius", "blur", "hue", "bright", "warp",
                 "spin", "split", "shake")
# Attack and release, in seconds, as a small set of felt shapes rather than two
# more continuous slots. The renderer and the player both read this table.
ROUTE_ENVELOPES: dict[str, tuple[float, float]] = {
    "snap": (0.001, 0.060),
    "tight": (0.005, 0.120),
    "soft": (0.020, 0.250),
    "slow": (0.080, 0.600),
    "hold": (0.010, 1.500),
    "glide": (0.200, 0.900),
}
ROUTE_ENVS = tuple(ROUTE_ENVELOPES)

# A bar carries up to three routing events at once, in three fixed lanes. One
# would be tidier, and was what this started as, but a single event per bar means
# every uniform the song is not currently pointing at has decayed to its neutral,
# and a chorus that wants the kick on the scale and the voice on the hue and the
# onsets on the shake cannot say so. Three is enough for that and still leaves the
# bar tier aligned one-to-one with bars: bar j owns lanes a, b and c of bar j.
ROUTE_LANES = ("a", "b", "c")


def _bar_slots() -> tuple[Slot, ...]:
    out: list[Slot] = []
    for lane in ROUTE_LANES:
        out += [
            _enum_slot(f"route_source_{lane}", "bar", ROUTE_SOURCES,
                       f"Lane {lane}: the audio feature this bar listens to."),
            _enum_slot(f"route_target_{lane}", "bar", ROUTE_TARGETS,
                       f"Lane {lane}: the uniform it drives."),
            _bin_slot(f"route_gain_{lane}", "bar", f"Lane {lane}: how hard."),
            _enum_slot(f"route_env_{lane}", "bar", ROUTE_ENVS,
                       f"Lane {lane}: the attack and release it is followed with."),
        ]
    return tuple(out)


BAR_SLOTS: tuple[Slot, ...] = _bar_slots()

TIERS: dict[str, tuple[Slot, ...]] = {
    "song": SONG_SLOTS,
    "section": SECTION_SLOTS,
    "bar": BAR_SLOTS,
}


def slot(tier: str, name: str) -> Slot:
    for s in TIERS[tier]:
        if s.name == name:
            return s
    raise KeyError(f"no {tier} slot named {name!r}")


# --------------------------------------------------------------------------- #
# The flat integer layout
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Shape:
    """How many of each repeated tier this song has.

    `n_bars` is the number of bars the beat tracker found, so bar slot j lines up
    one-to-one with bar j of the audio token sequence the model will read.
    """

    n_sections: int
    n_bars: int

    def __post_init__(self) -> None:
        if self.n_sections < 1 or self.n_bars < 1:
            raise ValueError(f"degenerate shape: {self}")

    @property
    def n_slots(self) -> int:
        return (
            len(SONG_SLOTS)
            + len(SECTION_SLOTS) * self.n_sections
            + len(BAR_SLOTS) * self.n_bars
        )

    @property
    def section_offset(self) -> int:
        return len(SONG_SLOTS)

    @property
    def bar_offset(self) -> int:
        return self.section_offset + len(SECTION_SLOTS) * self.n_sections

    def index(self, tier: str, name: str, group: int = 0) -> int:
        """Where one slot lives in the flat layout."""
        slots = TIERS[tier]
        within = [s.name for s in slots].index(name)
        if tier == "song":
            return within
        if tier == "section":
            if not 0 <= group < self.n_sections:
                raise IndexError(f"section {group} outside 0..{self.n_sections - 1}")
            return self.section_offset + group * len(slots) + within
        if not 0 <= group < self.n_bars:
            raise IndexError(f"bar {group} outside 0..{self.n_bars - 1}")
        return self.bar_offset + group * len(slots) + within

    def describe(self, i: int) -> tuple[str, Slot, int]:
        """The inverse of `index`: which tier, which slot, which group."""
        if not 0 <= i < self.n_slots:
            raise IndexError(f"slot {i} outside 0..{self.n_slots - 1}")
        if i < self.section_offset:
            return "song", SONG_SLOTS[i], 0
        if i < self.bar_offset:
            j = i - self.section_offset
            n = len(SECTION_SLOTS)
            return "section", SECTION_SLOTS[j % n], j // n
        j = i - self.bar_offset
        n = len(BAR_SLOTS)
        return "bar", BAR_SLOTS[j % n], j // n


def layout(shape: Shape) -> list[tuple[str, Slot, int]]:
    """The whole layout, in order. Useful for building a model's slot tokens."""
    return [shape.describe(i) for i in range(shape.n_slots)]


# --------------------------------------------------------------------------- #
# Legality
# --------------------------------------------------------------------------- #


def _candidates(slots: np.ndarray, i: int, card: int) -> Iterable[int]:
    """What slot i could be: its value if decided, every value if not.

    Unioning a rule over these is what lets a decode commit slots in any order.
    """
    v = int(slots[i])
    return (v,) if v != MASK else range(card)


def _allow(card: int, keep: Iterable[str] | Iterable[int], values: tuple[str, ...]) -> np.ndarray:
    m = np.zeros(card, dtype=bool)
    for k in keep:
        m[values.index(k) if isinstance(k, str) else int(k)] = True
    return m


def legal_values(shape: Shape, slots: np.ndarray, i: int) -> np.ndarray:
    """A boolean mask over slot i's values: which ones the grammar still allows.

    Depends only on other slots' *decided* values. A rule whose dependency is
    still masked is evaluated over every value that dependency could take and the
    masks are unioned, so this is monotone: committing a slot can only narrow
    what is legal elsewhere, never widen it.
    """
    tier, s, group = shape.describe(i)
    card = s.card
    allow = np.ones(card, dtype=bool)

    if tier == "song":
        if s.name == "symmetry":
            # A kaleidoscope folds space around a centre. On a motif that points
            # somewhere it only makes a mess, so those keep the flat symmetries.
            out = np.zeros(card, dtype=bool)
            mi = shape.index("song", "motif")
            for m in _candidates(slots, mi, len(MOTIFS)):
                keep = SYMMETRIES if MOTIFS[m] in RADIAL_MOTIFS else ("none", "mirror_x")
                out |= _allow(card, keep, SYMMETRIES)
            allow &= out

    elif tier == "section":
        if s.name == "scene":
            out = np.zeros(card, dtype=bool)
            bi = shape.index("song", "block_set")
            for b in _candidates(slots, bi, len(BLOCK_SETS)):
                out |= _allow(card, BLOCK_SET_SCENES[BLOCK_SETS[b]], SCENES)
            allow &= out

        elif s.name == "warp":
            out = np.zeros(card, dtype=bool)
            ci = shape.index("song", "motion_character")
            for c in _candidates(slots, ci, len(MOTION_CHARACTERS)):
                keep = STILL_WARPS if MOTION_CHARACTERS[c] == "still" else WARPS
                out |= _allow(card, keep, WARPS)
            allow &= out

        elif s.name == "post":
            # Trails with nothing moving underneath them are a smear that then
            # never clears, so a still song gets the chains that do not trail.
            out = np.zeros(card, dtype=bool)
            ci = shape.index("song", "motion_character")
            for c in _candidates(slots, ci, len(MOTION_CHARACTERS)):
                keep = STILL_POSTS if MOTION_CHARACTERS[c] == "still" else POSTS
                out |= _allow(card, keep, POSTS)
            allow &= out

        elif s.name == "palette_rotate":
            # Rotating a one-colour palette does nothing, so there is exactly one
            # honest answer and the model is not asked to guess among 32.
            out = np.zeros(card, dtype=bool)
            pi = shape.index("song", "palette_family")
            for p in _candidates(slots, pi, len(PALETTE_FAMILIES)):
                out |= _allow(card, (0,), s.values) if PALETTE_FAMILIES[p] == "mono" \
                    else np.ones(card, dtype=bool)
            allow &= out

        elif s.name == "transition_bars" and group == 0:
            # The song opens out of darkness, and a one-bar ramp out of darkness
            # is a cut with extra steps. The first section takes its time.
            allow &= _allow(card, [b for b in TRANSITION_BARS if int(b) >= 2],
                            TRANSITION_BARS)

    else:  # bar
        kind, lane = s.name.rsplit("_", 1)

        # A lane either carries a routing event or it does not, and its four slots
        # have to agree about which. Both directions of the implication are
        # enforced, so a decode can start from either end.
        si = shape.index("bar", f"route_source_{lane}", group)
        ti = shape.index("bar", f"route_target_{lane}", group)
        src = [ROUTE_SOURCES[v] for v in _candidates(slots, si, len(ROUTE_SOURCES))]
        tgt = [ROUTE_TARGETS[v] for v in _candidates(slots, ti, len(ROUTE_TARGETS))]
        src_off, src_on = "none" in src, any(v != "none" for v in src)
        tgt_off, tgt_on = "none" in tgt, any(v != "none" for v in tgt)

        if kind == "route_source":
            out = np.zeros(card, dtype=bool)
            if tgt_off:
                out |= _allow(card, ("none",), ROUTE_SOURCES)
            if tgt_on:
                out |= _allow(card, [v for v in ROUTE_SOURCES if v != "none"], ROUTE_SOURCES)
            allow &= out

        elif kind == "route_target":
            out = np.zeros(card, dtype=bool)
            if src_off:
                out |= _allow(card, ("none",), ROUTE_TARGETS)
            if src_on:
                out |= _allow(card, [v for v in ROUTE_TARGETS if v != "none"], ROUTE_TARGETS)
            allow &= out
            # Two lanes of the same bar fighting over one uniform is not a choice
            # anybody meant to make - the second would simply overwrite the first -
            # so a target another lane has already claimed is struck out.
            for other in ROUTE_LANES:
                if other == lane:
                    continue
                oi = shape.index("bar", f"route_target_{other}", group)
                v = int(slots[oi])
                if v != MASK and ROUTE_TARGETS[v] != "none":
                    allow[v] = False

        elif kind == "route_gain":
            # A silent lane has no gain to choose; bin 0 is its canonical value.
            out = np.zeros(card, dtype=bool)
            if src_off or tgt_off:
                out |= _allow(card, (0,), s.values)
            if src_on and tgt_on:
                out |= np.ones(card, dtype=bool)
            allow &= out

        elif kind == "route_env":
            out = np.zeros(card, dtype=bool)
            if src_off or tgt_off:
                out |= _allow(card, (ROUTE_ENVS[0],), ROUTE_ENVS)
            if src_on and tgt_on:
                out |= np.ones(card, dtype=bool)
            allow &= out

    if not allow.any():  # pragma: no cover - would mean the rules contradict
        raise RuntimeError(f"no legal value left for slot {i} ({tier}.{s.name})")
    return allow


def is_legal(shape: Shape, slots: np.ndarray) -> bool:
    """Whether every decided slot in `slots` is legal given the others."""
    return not violations(shape, slots)


def violations(shape: Shape, slots: np.ndarray) -> list[str]:
    """Every decided slot whose value the grammar does not allow, named."""
    out = []
    for i in range(shape.n_slots):
        v = int(slots[i])
        if v == MASK:
            continue
        if not legal_values(shape, slots, i)[v]:
            tier, s, group = shape.describe(i)
            where = tier if tier == "song" else f"{tier} {group}"
            out.append(f"{where}.{s.name} = {s.value_of(v)!r}")
    return out


def random_fill(
    shape: Shape,
    seed: int,
    slots: np.ndarray | None = None,
    prior: Callable[[str, Slot, int], np.ndarray] | None = None,
) -> np.ndarray:
    """Fill every masked slot with a legal value, deterministically from `seed`.

    Slots are visited in layout order - song, then sections, then bars - so a
    decision is always made after the coarser decisions it depends on, and the
    result is legal without any rejection. This is the seeded sampler the `--seed`
    flag draws from, and the stand-in for milestone 3's sampler with priors.
    """
    rng = np.random.default_rng(seed)
    out = np.full(shape.n_slots, MASK, dtype=np.int16) if slots is None else slots.copy()
    for i in range(shape.n_slots):
        if int(out[i]) != MASK:
            continue
        tier, s, group = shape.describe(i)
        allow = legal_values(shape, out, i)
        w = allow.astype(np.float64)
        if prior is not None:
            w *= np.clip(prior(tier, s, group), 1e-9, None)
            if not w.any():  # a prior that rules everything out defers to legality
                w = allow.astype(np.float64)
        out[i] = int(rng.choice(s.card, p=w / w.sum()))
    return out


# --------------------------------------------------------------------------- #
# Score
# --------------------------------------------------------------------------- #


class Score:
    """A score as names and numbers, with the flat layout one call away."""

    def __init__(
        self,
        shape: Shape,
        song: dict | None = None,
        sections: list[dict] | None = None,
        bars: list[dict] | None = None,
        track: str = "",
        seed: int | None = None,
    ) -> None:
        self.shape = shape
        self.track = track
        self.seed = seed
        self.song = dict(song or {})
        self.sections = [dict(d) for d in (sections or [{} for _ in range(shape.n_sections)])]
        self.bars = [dict(d) for d in (bars or [{} for _ in range(shape.n_bars)])]
        if len(self.sections) != shape.n_sections:
            raise ValueError(f"{len(self.sections)} sections, shape says {shape.n_sections}")
        if len(self.bars) != shape.n_bars:
            raise ValueError(f"{len(self.bars)} bars, shape says {shape.n_bars}")

    # -- the flat layout -------------------------------------------------- #

    def to_slots(self) -> np.ndarray:
        """Flatten to the fixed integer layout. Anything absent or null is MASK."""
        out = np.full(self.shape.n_slots, MASK, dtype=np.int16)
        groups = [("song", SONG_SLOTS, [self.song]),
                  ("section", SECTION_SLOTS, self.sections),
                  ("bar", BAR_SLOTS, self.bars)]
        for tier, slots, dicts in groups:
            for g, d in enumerate(dicts):
                unknown = set(d) - {s.name for s in slots}
                if unknown:
                    raise ValueError(f"unknown {tier} slot(s): {', '.join(sorted(unknown))}")
                for s in slots:
                    v = d.get(s.name)
                    if v is None:
                        continue
                    out[self.shape.index(tier, s.name, g)] = s.index_of(v)
        return out

    @classmethod
    def from_slots(
        cls, shape: Shape, slots: np.ndarray, track: str = "", seed: int | None = None
    ) -> "Score":
        """The inverse of `to_slots`. MASK comes back as an absent key."""
        if len(slots) != shape.n_slots:
            raise ValueError(f"{len(slots)} values, shape wants {shape.n_slots}")
        song: dict = {}
        sections: list[dict] = [{} for _ in range(shape.n_sections)]
        bars: list[dict] = [{} for _ in range(shape.n_bars)]
        sink = {"song": [song], "section": sections, "bar": bars}
        for i in range(shape.n_slots):
            v = int(slots[i])
            if v == MASK:
                continue
            tier, s, group = shape.describe(i)
            sink[tier][group][s.name] = s.value_of(v)
        return cls(shape, song, sections, bars, track=track, seed=seed)

    # -- reading it ------------------------------------------------------- #

    def value(self, tier: str, name: str, group: int = 0) -> str | int | None:
        d = {"song": self.song, "section": self.sections, "bar": self.bars}[tier]
        return (d if tier == "song" else d[group]).get(name)

    def unit(self, tier: str, name: str, group: int = 0, default: float = 0.5) -> float:
        """A bin slot as a number in 0..1, or `default` if it is masked."""
        v = self.value(tier, name, group)
        return default if v is None else slot(tier, name).unit(int(v))

    def is_complete(self) -> bool:
        return bool((self.to_slots() != MASK).all())

    def violations(self) -> list[str]:
        return violations(self.shape, self.to_slots())

    def filled(self, seed: int) -> "Score":
        """This score with every masked slot legally filled from `seed`."""
        return Score.from_slots(
            self.shape,
            random_fill(self.shape, seed, self.to_slots()),
            track=self.track,
            seed=seed,
        )

    # -- on disk ---------------------------------------------------------- #

    def to_dict(self) -> dict:
        def dense(d: dict, slots: tuple[Slot, ...]) -> dict:
            return {s.name: d.get(s.name) for s in slots}

        return {
            "version": VERSION,
            "track": self.track,
            "seed": self.seed,
            "shape": {"n_sections": self.shape.n_sections, "n_bars": self.shape.n_bars},
            "song": dense(self.song, SONG_SLOTS),
            "sections": [dense(d, SECTION_SLOTS) for d in self.sections],
            "bars": [dense(d, BAR_SLOTS) for d in self.bars],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Score":
        if d.get("version") != VERSION:
            raise ValueError(f"score version {d.get('version')!r}, this is {VERSION}")
        shape = Shape(int(d["shape"]["n_sections"]), int(d["shape"]["n_bars"]))
        drop = lambda g: {k: v for k, v in g.items() if v is not None}  # noqa: E731
        return cls(
            shape,
            drop(d["song"]),
            [drop(g) for g in d["sections"]],
            [drop(g) for g in d["bars"]],
            track=d.get("track", ""),
            seed=d.get("seed"),
        )

    def write(self, path) -> None:
        # One bar per line: the file is read by eye as often as by the loader, and
        # a bar is the unit a person edits.
        text = json.dumps(self.to_dict(), indent=1)
        with open(path, "w") as fh:
            fh.write(text + "\n")

    @classmethod
    def read(cls, path) -> "Score":
        with open(path) as fh:
            return cls.from_dict(json.load(fh))

    def __repr__(self) -> str:
        n = int((self.to_slots() != MASK).sum())
        return (f"<Score {self.track or '?'} {self.shape.n_sections}sec "
                f"{self.shape.n_bars}bar {n}/{self.shape.n_slots} filled>")
