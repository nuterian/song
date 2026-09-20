"""Scores written by hand, and the seeded sampler that stands in for a director.

Two ways to get a score in milestone 1. `handwritten` builds one deliberately, by
naming what each section should look like and what each bar should listen to -
which is the thing milestone 4's model will be trained to do, so writing one by
hand first is how the schema gets tested against an actual intention. `sampled`
draws a legal score from a seed, which is what `--seed` uses and what milestone 3
will replace with a sampler that has priors worth the name.

Both go through the same slots and the same legality rules. A hand-written score
that breaks a rule is rejected exactly as a model's would be.
"""

from __future__ import annotations

import numpy as np

from . import schema
from .listen import Track


def shape_of(track: Track) -> schema.Shape:
    return schema.Shape(len(track.sections), track.n_bars)


def sampled(track: Track, seed: int) -> schema.Score:
    """A legal score drawn from `seed`. Same seed, same score, byte for byte."""
    shape = shape_of(track)
    return schema.Score.from_slots(
        shape, schema.random_fill(shape, seed), track=track.name, seed=seed
    )


# --------------------------------------------------------------------------- #
# The hand-written score
# --------------------------------------------------------------------------- #

# One entry per kind of section, keyed on the name the lyrics file gave it. The
# song has two verses, two pre-choruses, three choruses and a bridge, and the
# point of keying on the name is that the two choruses come out looking like each
# other - which is the long-range agreement milestone 4 has to learn rather than
# be told.
#
# Every value here is a number or a name that stands for numbers, and the renderer
# ramps between consecutive sections, so what is written below is not a sequence
# of looks but a sequence of destinations. The transition fields say how long the
# song takes to get to each one and how it moves on the way.
LOOK: dict[str, dict] = {
    "verse": dict(scene="wash", warp="breathe", post="soft",
                  density=9, energy=13, softness=25,
                  transition_bars="4", transition_curve="sigmoid"),
    # Wider, harder-edged, and arriving over two bars - a lift rather than a change.
    "pre-chorus": dict(scene="drift", warp="breathe", post="soft",
                       density=15, energy=19, softness=17,
                       transition_bars="2", transition_curve="early"),
    # The chorus is the only place the edges get crisp, which is most of why it
    # reads as the chorus at all.
    "chorus": dict(scene="bloom", warp="swirl", post="trails",
                   density=22, energy=27, softness=8,
                   transition_bars="2", transition_curve="ease"),
    # The bridge goes the other way: everything softens, and the discs come out
    # from behind the wash over eight bars, which is long enough that no single
    # moment of it is the moment the bridge began.
    "bridge": dict(scene="orbits", warp="ripple", post="smear",
                   density=12, energy=15, softness=27,
                   transition_bars="8", transition_curve="sigmoid"),
    "outro": dict(scene="wash", warp="none", post="soft",
                  density=5, energy=8, softness=29,
                  transition_bars="8", transition_curve="linear"),
}

# The colour arc: where each kind of section sits in the palette. Verses low,
# choruses high, the bridge off on its own side, the outro walking away. Because
# palette_rotate is ramped like everything else, this is a drift through the
# palette over four and a half minutes, not nine changes of colour.
ROTATE: dict[str, int] = {
    "verse": 3, "pre-chorus": 7, "chorus": 13, "bridge": 21, "outro": 26,
}

# What each kind of section listens to. A bar has three lanes, and a section names
# a cycle of bar patterns that its bars step through - so a chorus holds the kick
# on the scale the whole way while the third lane alternates between the onsets and
# the voice, which is the kind of thing a person would actually ask for.
#
# Each tuple is (source, target, gain bin, envelope), and each inner tuple is one
# bar's three lanes. `None` leaves a lane silent.
Lane = tuple[str, str, int, str]
SILENT: Lane = ("none", "none", 0, "snap")

BARS: dict[str, tuple[tuple[Lane, ...], ...]] = {
    # A verse listens quietly, but it does listen on every bar: the kick on the
    # size of things, the voice on the colour, and `flux` - the rise of the mix
    # rather than its level - on the blur, which is what makes a small change in
    # the arrangement visible without anything having to get louder.
    "verse": (
        (("low", "scale", 13, "tight"), ("vocal", "hue", 15, "glide"),
         ("flux", "blur", 18, "tight")),
        (("low", "radius", 15, "tight"), ("vocal", "bright", 16, "soft"),
         ("flux", "blur", 18, "tight")),
    ),
    "pre-chorus": (
        (("low", "scale", 17, "tight"), ("high", "warp", 19, "soft"),
         ("flux", "blur", 21, "tight")),
        (("low", "radius", 19, "tight"), ("vocal", "bright", 20, "soft"),
         ("flux", "blur", 20, "tight")),
    ),
    # The chorus pumps. `beat` on the scale with a snap envelope is the single
    # most legible thing the whole vocabulary can do, so the chorus is where it
    # goes, and the other two lanes keep working underneath it.
    "chorus": (
        (("beat", "scale", 20, "snap"), ("vocal", "hue", 20, "glide"),
         ("low", "radius", 22, "tight")),
        (("beat", "scale", 20, "snap"), ("flux", "bright", 22, "tight"),
         ("low", "radius", 22, "tight")),
        (("beat", "scale", 22, "snap"), ("high", "warp", 18, "soft"),
         ("flux", "radius", 21, "tight")),
        (("onset", "shake", 10, "snap"), ("vocal", "hue", 21, "glide"),
         ("low", "scale", 24, "tight")),
    ),
    "bridge": (
        (("vocal", "hue", 21, "glide"), ("mix", "warp", 16, "slow"),
         ("bar", "spin", 7, "hold")),
        (("flux", "blur", 19, "tight"), ("low", "radius", 14, "soft"),
         ("vocal", "bright", 15, "glide")),
    ),
    "outro": (
        (("mix", "bright", 11, "slow"), ("vocal", "hue", 9, "glide"),
         ("flux", "blur", 12, "soft")),
        (("mix", "bright", 10, "slow"), ("low", "radius", 8, "soft"), SILENT),
    ),
}

# Before the first sung line there are twenty-one bars of introduction. They get
# the verse's destination and a slow swell, so the picture arrives with the song
# rather than waiting for a voice.
INTRO_BARS: tuple[tuple[Lane, ...], ...] = (
    (("mix", "bright", 9, "slow"), ("low", "radius", 8, "soft"),
     ("bar", "spin", 5, "hold")),
    (("mix", "bright", 10, "slow"), ("flux", "blur", 8, "glide"), SILENT),
)


def _kind(name: str) -> str:
    """Which entry in the tables a section name falls under."""
    n = name.strip().lower()
    for key in ("pre-chorus", "chorus", "verse", "bridge", "outro", "intro"):
        if key in n:
            return "verse" if key == "intro" else key
    return "verse"


def handwritten(track: Track, seed: int = 0) -> schema.Score:
    """A score for this track, written rather than sampled.

    Song-level choices are fixed. Section-level ones come from the section's kind,
    so repeats look alike. Bar-level routing cycles through the kind's list, and
    the bars before the first sung line get their own swell.
    """
    shape = shape_of(track)
    song = dict(
        palette_family="dusk",
        palette_shift=5,
        # Admits wash, drift, orbits and bloom - the four this score moves among.
        block_set="orbital",
        motif="circle",
        motion_character="drift",
        symmetry="none",
        grain=4,
    )

    sections = []
    previous = None
    for s in track.sections:
        kind = _kind(s.name)
        look = dict(LOOK[kind])
        look["palette_rotate"] = ROTATE[kind]
        # How long an arrival should take depends on where it is arriving *from*,
        # which the table above cannot say. Coming out of the bridge - the softest
        # the song ever gets - into the crispest thing in it, two bars is a lurch
        # even though nothing cuts. Four is the same arrival, unhurried.
        if previous == "bridge" and kind == "chorus":
            look["transition_bars"] = "4"
            look["transition_curve"] = "sigmoid"
        sections.append(look)
        previous = kind

    first_line = min((ln.start for ln in track.lines), default=0.0)
    spans = track.bar_spans()
    bars = []
    counter: dict[int, int] = {}
    for b in range(shape.n_bars):
        start = float(spans[b, 0])
        if start < first_line:
            lanes = INTRO_BARS[b % len(INTRO_BARS)]
        else:
            si = track.section_of(start)
            table = BARS[_kind(track.sections[si].name)]
            # Counted within the section, so every verse starts its cycle at the
            # same place in the pattern and the two of them rhyme.
            i = counter.get(si, 0)
            counter[si] = i + 1
            lanes = table[i % len(table)]
        bar: dict = {}
        for lane, (src, tgt, gain, env) in zip(schema.ROUTE_LANES, lanes):
            bar[f"route_source_{lane}"] = src
            bar[f"route_target_{lane}"] = tgt
            bar[f"route_gain_{lane}"] = gain
            bar[f"route_env_{lane}"] = env
        for lane in schema.ROUTE_LANES[len(lanes):]:
            bar[f"route_source_{lane}"] = "none"
            bar[f"route_target_{lane}"] = "none"
            bar[f"route_gain_{lane}"] = 0
            bar[f"route_env_{lane}"] = schema.ROUTE_ENVS[0]
        bars.append(bar)

    score = schema.Score(shape, song, sections, bars, track=track.name, seed=seed)
    bad = score.violations()
    if bad:
        raise ValueError("the hand-written score breaks the grammar: " + "; ".join(bad))
    return score


def for_track(track: Track, seed: int | None = None) -> schema.Score:
    """The score to render: hand-written by default, sampled when a seed is given."""
    return handwritten(track) if seed is None else sampled(track, seed)


def prior_free_fill(shape: schema.Shape, seed: int) -> np.ndarray:
    """A uniform draw over the legal values. Exposed for the tests."""
    return schema.random_fill(shape, seed)
