"""project.json -> an ASS subtitle file with per-word karaoke timing.

There is no frame renderer here, and none anywhere else either. ASS has carried
karaoke tags since the VirtualDub era: `\\kf` sweeps a fill across a run of text
over a given duration, which is exactly the classic per-syllable wipe, and
libass draws it with real shaping, and with per-word transforms that grow the
word being sung and hand it back to ink afterwards. This project already knows
where every word starts and ends, so the karaoke layer is a format conversion
plus a burn-in - not a text renderer that would have to reimplement kerning,
wrapping and antialiasing to arrive somewhere worse.

Stdlib only, so it is unit-testable with nothing installed. `song.project` is
pure too, which is what keeps that true.
"""

from __future__ import annotations

from pathlib import Path

from ..project import Project

# The frame every coordinate below is expressed in. ffmpeg scales the picture up
# to this before libass touches it, so the text is drawn at output resolution and
# stays sharp however soft the generated visuals underneath are.
PLAY_W, PLAY_H = 1280, 720

# libass resolves this through fontconfig and falls back to the system sans when
# it is missing, so a render elsewhere degrades to a different face rather than
# to no text. The weight is in the family name and Bold stays off, because
# asking libass for "Avenir Next" *bold* picks the Bold **Italic** face out of
# the macOS .ttc collection and the whole song renders oblique with nothing
# anywhere saying italic.
FONT = "Avenir Next Demi Bold"
FONT_SIZE = 39

# Nothing at all around the letterforms: no border, no blur, no shadow. Every
# one of those is a second shape drawn from the text, and at this size they read
# as an outline rather than as separation. The contrast the words need comes
# from the picture instead - scene.py lifts a wide, soft patch of light under
# the corner they sit in, which is a gradient nobody can see the edge of.
BORDER = 0
EDGE = (0xFFFFFF, 0xFF)

# Dark type, because the picture is light. Three states: a word not yet sung is
# the same ink at low opacity, the word being sung fills in the accent, and a
# word already sung settles to full ink. \kf gives the first two - it sweeps the
# fill from Secondary to Primary - and the third is one transform per word.
INK = 0x100B14
UNSUNG = (INK, 0xA6)
ACCENT = 0xC4490A
# 450 ms of tail all told, which is what it was before this was eased and is
# not a number to grow. The median word here is 582 ms, so a longer drain than
# this leaves the word before still visibly lit under the word being sung, and
# two lit words is no lit word.
SETTLE_HOLD = 120            # ms the accent holds after the word ends
SETTLE = 330                 # ...then this long to drain back to ink
SETTLE_STEPS = 3             # eased, like everything else that moves

# The word being sung is larger than the rest of its line, and eases in and back
# out again. Size and colour carry it and nothing else does: weight was an
# animated border in the fill's own colour, which is a real way to thicken a
# glyph smoothly, but a border is a border and at this size it reads as an
# outline drawn round the word rather than as weight in it.
#
# The line is anchored at its left edge, so a word growing pushes the words
# after it to the right and leaves the ones before it alone. Centred, the whole
# sentence would shuffle under the reader on every syllable.
# The word is sung for a while - 582 ms at the median on this track, and 883 at
# the third quartile - and the first version of this spent 150 ms of that
# arriving and the rest of it sitting perfectly still at full size. A word that
# pops up, holds and pops down is three events; a word that is being sung is one
# long one. So the lift arrives over a share of the word rather than over a
# fixed 150 ms, and then keeps going: it is still 14% short of its full size
# when it gets there, and spends the whole rest of the word creeping up to it.
# That last stretch is under a third of a pixel of growth and nobody will ever
# see it happening - which is the point. What you see is that it never stops.
LIFT = 26.0            # percent larger, for a word long enough to show it
LIFT_FULL = 240        # ms of word length that earns the whole lift
LIFT_LEAD = 90         # ms early, so the word is already moving when it is sung
LIFT_ATTACK = 0.38     # the share of the word spent arriving...
LIFT_ATTACK_MIN = 120  # ...between these, so neither a snapped syllable
LIFT_ATTACK_MAX = 300  #    nor a held note gets an attack that suits the other
LIFT_SWELL = 0.86      # how much of the lift the attack delivers; the rest creeps
LIFT_OUT = 340         # ms to release, once the word is over
LIFT_STEPS = 4         # segments per eased stage

# Bottom left, three lines deep, and they move. A line rises from the next slot
# to the sung slot to the previous slot as the song goes through it, growing and
# then shrinking again - so the progression is something you watch rather than
# something you infer from which line happens to be brightest.
MARGIN_L = 92
MARGIN_R = 500
# Five stops, of which two are never seen. A line rises through all of them, so
# every line on screen moves at every change and the spacing between them never
# alters. Moving only the ones that change slot was the first attempt, and for
# the length of the move two of them sit almost on top of each other.
SLOT_IN = 14                 # distance from the bottom of the frame
SLOT_NEXT = 76
SLOT_NOW = 140
SLOT_PREV = 206
SLOT_OUT = 268
MOVE = 470                   # ms to travel between stops
# \move is linear and has no easing of its own, so the travel is cut into this
# many segments whose lengths follow a smoothstep. Three is enough: the fastest
# segment is only twice the slowest, which is a curve rather than a staircase,
# and each one is its own event carrying its own share of the fade and the
# scale, so everything about a line eases on the same curve.
MOVE_STEPS = 3
NEAR_SCALE = 82              # percent, for the lines either side
NEAR = (0xB2, 0xB2, 0xC2)    # their transparency: fill, unsung fill, edge
GONE = (0xFF, 0xFF, 0xFF)    # ...and the two stops nobody sees

# How long the block takes to leave when it has somewhere to leave from - the
# ends of the song, and every instrumental long enough to empty the screen.
# Between lines nothing fades: a block that faded in and out on every change
# would blink thirty-three times.
FADE = 700
# Two windows this close are touching; anything more is an instrumental, and the
# words go away and come back over it.
SEAM = 0.02

# Seconds a line sits on screen unsung before its first word. A karaoke line
# that appears on the beat it is sung on is unsingable - the point is reading
# ahead.
LEAD_IN = 1.6
# ...and seconds it stays fully filled afterwards, so the last word does not
# blink out the instant it lands.
HOLD = 0.6


# ---------------------------------------------------------------- formatting


def centis(t: float) -> int:
    """Seconds -> centiseconds, the only time unit ASS has."""
    return max(0, int(round(t * 100)))


def ass_time(cs: int) -> str:
    """Centiseconds -> `H:MM:SS.cc`.

    Takes centiseconds rather than seconds so callers quantize once, up front,
    and every duration downstream is a difference between two positions that
    already exist on the timeline. Round each word on its own instead and the
    error accumulates - half a centisecond per word is most of a second across a
    177-word song, all of it arriving at the end, which is the half nobody
    checks.
    """
    cs = max(0, int(cs))
    hours, cs = divmod(cs, 360000)
    minutes, cs = divmod(cs, 6000)
    seconds, cs = divmod(cs, 100)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def colour(rgb: int, alpha: int = 0) -> str:
    """`&HAABBGGRR` - ASS stores colour backwards, and alpha as transparency."""
    r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def tag_colour(rgb: int) -> str:
    """`&HBBGGRR&` - what an override tag wants, which is not what a style wants.

    Style fields carry the alpha in the same number; an inline `\\3c` does not,
    and takes a trailing `&`. Feeding one format to the other is silently
    accepted and renders the wrong colour.
    """
    r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
    return f"&H{b:02X}{g:02X}{r:02X}&"


def escape(text: str) -> str:
    """Make a lyric safe as ASS dialogue text.

    A brace opens an override block, so a lyric containing one would silently
    swallow itself and everything after it up to the next closing brace.
    """
    return (
        text.replace("\\", "/")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )


# ---------------------------------------------------------------- the events


def windows(project: Project) -> list[tuple[float, float]]:
    """When each timed line appears and disappears, lead-in and hold-out included.

    Every line gets its ideal window first and the collisions are resolved
    pairwise afterwards, because a clamp applied line by line cannot see the
    overlap it is about to cause with the line after it.

    Two lines on screen at once would make the sweep ambiguous - which one is it
    in? - so a collision is settled at the midpoint of the silence between the
    two sung spans, with one line leaving on the exact frame the next arrives.
    Leaving a gap there instead reads as a blink: back-to-back lines in this
    track are 80 ms apart, which is two frames of nothing.
    """
    lines = [ln for ln in project.lines if ln.end > ln.start]
    spans = [(max(0.0, ln.start - LEAD_IN), ln.end + HOLD) for ln in lines]

    for i, (this, following) in enumerate(zip(lines, lines[1:])):
        (appear, vanish), (next_appear, next_vanish) = spans[i], spans[i + 1]
        if next_appear >= vanish:
            continue
        edge = max(this.end, min((this.end + following.start) / 2, following.start))
        spans[i] = (appear, min(vanish, edge))
        spans[i + 1] = (max(next_appear, edge), next_vanish)

    return spans


def karaoke_text(line, start_cs: int, state: str = "") -> str:
    """One dialogue line's text, with a `\\kf` run per word.

    Every duration is a difference of absolute centisecond positions on the
    project timeline, so the sweep cannot walk away from the audio however many
    words the line holds.

    The space between two words is its own zero-length `\\k` segment rather than
    a passenger on either neighbour. Hang it on the word before and the sweep
    spends the tail of that word's duration crossing whitespace, so the word
    finishes early; hang it on the word after and the word starts late. Both
    show on a fast syllable run, and late is the one that reads as broken.

    `state` is the slot the line is in - its size and how far it is faded, and
    the transform that carries it to the next slot. It has to be repeated in
    every word's block because every block opens with `\\r`, which is itself
    unavoidable: see settle().
    """
    if not line.words:
        return f"{{\\r{state}}}{escape(line.text)}"

    # The words carry the timing; line.text carries the lyric. They are the same
    # tokens in the same order, but the aligner strips trailing punctuation off
    # some of them - four commas and a full stop go missing on the sample track
    # alone - and what gets burned into a video has to be what was typed. So the
    # timing comes from the word and the glyphs come from the text, paired by
    # position; only a project where the two disagree in length falls back to
    # the word list, where at least the timing is still right.
    tokens = line.text.split()
    if len(tokens) != len(line.words):
        tokens = [w.text for w in line.words]

    end_cs = centis(line.end)
    at = start_cs
    out: list[str] = []

    for i, (word, token) in enumerate(zip(line.words, tokens)):
        # Clamp forward only. A project whose word starts ran backwards would
        # otherwise emit a negative \k, which libass reads as an enormous one.
        w_start = min(max(centis(word.start), at), end_cs)
        w_end = min(max(centis(word.end), w_start), end_cs)
        if i:
            out.append("{\\k0} ")
        if w_start > at:
            out.append(f"{{\\k{w_start - at}}}")   # the lead-in, or a held rest
        out.append(
            f"{{\\r{state}\\kf{w_end - w_start}"
            f"{lift(w_start - start_cs, w_end - start_cs)}"
            f"{settle(w_end - start_cs)}}}{escape(token)}"
        )
        at = w_end

    return "".join(out)


def eased(begin: int, until: int, steps: int, stop) -> str:
    """A `\\t` chain across one span whose stops follow a smoothstep.

    `\\t` interpolates linearly. Its optional acceleration is a power curve,
    `p**a`, and a power curve is slow at one end or the other but never at both:
    at a<1 it leaves at infinite speed, at a>1 it arrives at full speed. Two of
    them back to back is worse than either, because the join lands where one is
    at full speed and the next is at infinite - a snap in the middle of the
    move, which is exactly where nobody is expecting one.

    An ease that is slow at both ends is the one that reads as natural, and the
    way to get one out of `\\t` is the way `\\move` already gets one here: cut
    the span into equal slices and put the curve into where they stop. Four
    slices make the fastest one 2.2x the slowest, which is a curve; the two in
    the middle are the same speed as each other, so there is no corner between
    them at all.
    """
    out, at = [], begin
    for k in range(1, steps + 1):
        to = round(begin + (until - begin) * k / steps)
        if to > at:
            out.append(f"{{\\t({at},{to},{stop(smoothstep(k / steps))})}}"[1:-1])
            at = to
    return "".join(out)


def blend(here: int, there: int, how_far: float) -> int:
    """One point on the way from one packed RGB to another."""
    out = 0
    for shift in (16, 8, 0):
        a, b = (here >> shift) & 0xFF, (there >> shift) & 0xFF
        out |= round(a + (b - a) * how_far) << shift
    return out


def lift(start_cs: int, end_cs: int, size: int = FONT_SIZE) -> str:
    """The `\\t` chain that swells one word as it is sung, then lets it go.

    Three stages, and the middle one is the reason the other two are shaped the
    way they are. The word arrives over a share of its own length rather than
    over a fixed time, so a snapped syllable and a held note are not given the
    same attack. It arrives 14% short. Then it spends every remaining
    millisecond of the word closing that gap, which at this size is a third of a
    pixel spread over half a second - far too slow to watch, and the whole
    difference between a word that is being held and a word that is merely large.
    Then it releases, eased at both ends so it neither jumps off the top nor
    lands hard at the bottom.

    Every word's block opens with `\\r` because of this. An override applies to
    all the text after it, and a `\\t` that has not started yet does not cancel
    one that has: without the reset, word one's lift is still in force when word
    two is drawn and the whole line inflates instead of one word in it. That
    looked like it worked until a frame was pulled at the moment word one was up.
    """
    length = (end_cs - start_cs) * 10
    amount = LIFT * min(1.0, length / LIFT_FULL)
    # Below half a pixel of growth nobody can see it, and a chain of transforms
    # costs more than nothing. Expressed against the size rather than as a flat
    # percentage, so it stays true when either the size or the lift changes.
    if amount * size < 50.0:
        return ""

    rise = max(0, start_cs * 10 - LIFT_LEAD)
    fall = end_cs * 10
    attack = min(max(length * LIFT_ATTACK, LIFT_ATTACK_MIN), LIFT_ATTACK_MAX)
    # A word shorter than its own attack gets a shorter one, not an attack that
    # overruns into its own release.
    peak = min(rise + round(attack), max(rise + 40, fall))
    top, held = 100.0 + amount, 100.0 + amount * LIFT_SWELL

    def scale(at: float) -> str:
        return f"\\fscx{at:.1f}\\fscy{at:.1f}"

    out = [eased(rise, peak, LIFT_STEPS,
                 lambda u: scale(100.0 + (held - 100.0) * u))]
    if fall > peak:
        # The creep. One linear transform, because it is a third of a pixel and
        # a curve on it would be a curve nobody could measure, let alone see.
        out.append(f"\\t({peak},{fall},{scale(top)})")
    from_ = top if fall > peak else held
    out.append(eased(fall, fall + LIFT_OUT, LIFT_STEPS,
                     lambda u: scale(from_ + (100.0 - from_) * u)))
    return "".join(out)


def settle(end_cs: int) -> str:
    """`\\t` that turns a word white once it has been sung.

    `\\kf` gives two states, and the useful one is a third. The style's primary
    is the accent, so the sweep fills the word being sung in colour; this hands
    that word back to ink a moment later, leaving exactly one word lit at a time
    with a short trail behind it.
    """
    # Clamped, because a line is also drawn in the slot above while the next
    # one is sung, and there its words all ended before the event began.
    leave = max(0, end_cs * 10 + SETTLE_HOLD)
    # Eased, for the same reason the size is. A linear colour fade has no
    # velocity to watch, but it does have two corners - the moment it starts and
    # the moment it stops - and on a word you are looking straight at, those are
    # the two moments you see.
    return eased(leave, leave + SETTLE, SETTLE_STEPS,
                 lambda u: f"\\1c{tag_colour(blend(ACCENT, INK, u))}")


Look = tuple      # (fill alpha, unsung alpha, edge alpha, scale percent)

AT_REST: Look = (0x00, UNSUNG[1], 0x00, 100)


def look_at(slot_alpha: tuple[int, int, int], scale: int) -> Look:
    return (*slot_alpha, scale)


def between(here: Look, there: Look, how_far: float) -> Look:
    """One point on the way from one slot's look to the next."""
    return tuple(round(a + (b - a) * how_far) for a, b in zip(here, there))


def state(look: Look) -> str:
    """How a line looks right now: how faded, and how large.

    The three alpha channels move separately because `\\alpha` sets all of them
    at once - including the unsung one, which is the whole difference between a
    word that has been sung and a word that has not.
    """
    fill, unsung, edge, scale = look
    return (
        f"\\1a&H{fill:02X}&\\2a&H{unsung:02X}&\\3a&H{edge:02X}&"
        f"\\fscx{scale}\\fscy{scale}"
    )


def travel(here: Look, there: Look, over: int) -> str:
    """The look now, and the transform that carries it to the next look."""
    return f"{state(here)}\\t(0,{over},{state(there)})"


def smoothstep(u: float) -> float:
    """Slow at both ends, quick through the middle."""
    return u * u * (3.0 - 2.0 * u)


def build(project: Project, font: str = FONT, size: int = FONT_SIZE) -> str:
    """The whole .ass file, as text."""
    lines = [ln for ln in project.lines if ln.end > ln.start]
    spans = windows(project)
    out = [_header(font, size)]
    if not lines:
        return "\n".join(out) + "\n"

    gone = look_at(GONE, NEAR_SCALE)
    near = look_at(NEAR, NEAR_SCALE)
    # The border alpha is opaque in the sung slot and only there. Nothing has a
    # border at rest - it is the weight of the word being lifted - and if it
    # were transparent the lift would change size without changing weight.
    now = AT_REST
    # Which stop a line is at while the window `offset` windows away is sung,
    # and how it looks there. -1 is the window before its own.
    stops = {
        -1: (SLOT_IN, SLOT_NEXT, gone, near),
        0: (SLOT_NEXT, SLOT_NOW, near, now),
        1: (SLOT_NOW, SLOT_PREV, now, near),
        2: (SLOT_PREV, SLOT_OUT, near, gone),
    }

    for i, line in enumerate(lines):
        for offset, (leaving, arriving, before, after) in stops.items():
            window = i + offset
            if not 0 <= window < len(lines):
                continue
            opens, closes = spans[window]
            # Windows normally touch, and while they do the block never leaves
            # the screen: every line arrives from the invisible stop below and
            # departs by the invisible one above. Where they do not touch - the
            # two ends of the song, and every instrumental, of which this track
            # has ten - the whole block does leave, and it has to do that
            # gently. It comes back from nothing rather than on a fade, because
            # a \fad spread across the segments of a move restarts on each one.
            starts_alone = window == 0 or spans[window][0] - spans[window - 1][1] > SEAM
            ends_alone = (window == len(lines) - 1
                          or spans[window + 1][0] - spans[window][1] > SEAM)
            if starts_alone:
                before = gone

            for step in range(MOVE_STEPS):
                first, last = step / MOVE_STEPS, (step + 1) / MOVE_STEPS
                from_, to = smoothstep(first), smoothstep(last)
                over = round(MOVE * (last - first))
                start = opens + MOVE * first / 1000.0
                # The last segment runs to the end of the window and holds
                # there: \move stays put once its time is up.
                end = closes if step == MOVE_STEPS - 1 else opens + MOVE * last / 1000.0
                # ...and going out is a fade, on the one segment that reaches
                # the end of the window. The others are minding its beginning,
                # and a fade measured from the end of a 157 ms segment is over
                # before it starts.
                fade = f"\\fad(0,{FADE})" if ends_alone and step == MOVE_STEPS - 1 else ""
                start_cs = centis(max(0.0, start))
                end_cs = max(start_cs + 1, centis(end))
                y_from = PLAY_H - (leaving + (arriving - leaving) * from_)
                y_to = PLAY_H - (leaving + (arriving - leaving) * to)
                carry = travel(between(before, after, from_),
                               between(before, after, to), over)
                # Only the line being sung is swept. A neighbour drawn with
                # karaoke tags has every word already over or not yet begun, so
                # `\kf0` fills the whole line to the accent and the settle then
                # walks it back to ink - a line that has finished being sung
                # relights in colour as it leaves, which reads as a fault.
                body = (karaoke_text(line, start_cs, carry) if offset == 0 else
                        f"{{\\r{carry}\\1c{tag_colour(INK)}}}{escape(line.text)}")
                out.append(
                    f"Dialogue: 0,{ass_time(start_cs)},{ass_time(end_cs)},Lyric,,"
                    f"0,0,0,,{{\\move({MARGIN_L},{y_from:.0f},{MARGIN_L},"
                    f"{y_to:.0f},0,{over}){fade}}}{body}"
                )

    return "\n".join(out) + "\n"


def _header(font: str, size: int) -> str:
    return "\n".join([
        "[Script Info]",
        "; Generated by song - https://github.com/nuterian/song",
        "ScriptType: v4.00+",
        f"PlayResX: {PLAY_W}",
        f"PlayResY: {PLAY_H}",
        # Wrap a long line evenly rather than filling the first row and
        # orphaning one word underneath it.
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding",
        # Primary is what \kf sweeps *to*, so it is the accent rather than the
        # final colour - each word settles to ink on its own afterwards.
        # Alignment 1 anchors to the bottom left, which is where \move's
        # coordinates are measured from too.
        f"Style: Lyric,{font},{size},{colour(ACCENT)},{colour(*UNSUNG)},"
        f"{colour(*EDGE)},{colour(0x000000, 0xFF)},"
        f"0,0,0,0,100,100,0,0,1,{BORDER},0,1,{MARGIN_L},{MARGIN_R},{SLOT_NOW},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV,"
        " Effect, Text",
    ])


def write(project: Project, path: Path | str, **kwargs) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(project, **kwargs), encoding="utf-8")
    return path
