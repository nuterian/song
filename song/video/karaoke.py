"""project.json -> an ASS subtitle file with per-word karaoke timing.

There is no frame renderer here, and none anywhere else either. ASS has carried
karaoke tags since the VirtualDub era: `\\kf` sweeps a fill across a run of text
over a given duration, which is exactly the classic per-syllable wipe, and
libass draws it with real shaping, and with per-word transforms that grow the
word being sung and hand it back to white afterwards. This project already knows
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
FONT = "Avenir Next"
FONT_SIZE = 34

# No blur on the words, and no shadow under them. libass's \blur is described as
# softening the border, but with a border thick enough to read it bleeds into
# the fill, and every word came *into focus* as it was sung. A drop shadow, hard
# or soft, is a second copy of the text lying underneath the first, which is
# exactly the thing this is trying not to look like. What is left is a hairline
# edge at low opacity - enough to hold the letterform against a light frame,
# not enough to read as an outline.
BORDER = 0.9
EDGE = (0x14060E, 0x84)

# Bottom left, three lines deep: the one being sung, with the one before and the
# one after faded either side of it. Margins are from the frame edge, and the
# right one keeps the block clear of the trace in the opposite corner.
MARGIN_L = 86
MARGIN_R = 540
# Spaced so that a line long enough to wrap - none on the sample track, but
# somebody's will - grows upward into its own slot without reaching the one
# above it.
SLOT_NEXT = 70               # distance from the bottom of the frame
SLOT_NOW = 128
SLOT_PREV = 186

# Lines arrive and leave rather than cutting. \fad measures its out-fade from
# the *end* of the event, and consecutive lines here touch rather than overlap,
# so one line has finished fading out on the exact frame the next starts fading
# in - no dissolve between two different sentences, and no gap either.
FADE_IN = 260
FADE_OUT = 300


# Three states, and the middle one is the point. A word not yet sung is dim
# white; the word being sung fills in the accent; a word already sung settles to
# plain white. \kf gives the first two - it sweeps the fill from Secondary to
# Primary - and the third is one transform per word, turning that word's primary
# white a beat after it is done.
UNSUNG = (0xFFFFFF, 0x76)
NEAR = (0xFFFFFF, 0x96)      # the line before and the line after
ACCENT = 0xFFC64D
SUNG = 0xFFFFFF
SETTLE_HOLD = 130            # ms the accent holds after the word ends
SETTLE = 320                 # ...then this long to fade to white

# The word being sung swells. Capped by how long the word lasts: at full size on
# a 90 ms syllable it is a flicker rather than an emphasis, so short words grow
# proportionally less and a fast run reads as a ripple instead of a strobe.
GROW = 5.0         # percent, for a word long enough to see it
GROW_FULL = 220    # ms of word length that earns the full swell
GROW_LEAD = 90     # ms early, so the word is already up when it is sung
GROW_IN = 130      # ms to swell
GROW_OUT = 260     # ms to settle back

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


def karaoke_text(line, start_cs: int, shade: bool = False) -> str:
    """One dialogue line's text, with a `\\kf` run per word.

    Every duration is a difference of absolute centisecond positions on the
    project timeline, so the sweep cannot walk away from the audio however many
    words the line holds.

    The space between two words is its own zero-length `\\k` segment rather than
    a passenger on either neighbour. Hang it on the word before and the sweep
    spends the tail of that word's duration crossing whitespace, so the word
    finishes early; hang it on the word after and the word starts late. Both
    show on a fast syllable run, and late is the one that reads as broken.
    """
    if not line.words:
        return escape(line.text)

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
        rise, fall = w_start - start_cs, w_end - start_cs
        if shade:
            # Nothing sweeps here - the fill is off and only the blurred border
            # is drawn - so the karaoke tags are left out entirely. The swell is
            # not: without it the shadow keeps the width of a word the layer
            # above has already grown, and slides out from under it.
            out.append(
                f"{' ' if i else ''}"
                f"{{\\r\\1a&HFF&\\blur{SHADE_BLUR}{grow(rise, fall)}}}{escape(token)}"
            )
        else:
            if i:
                out.append("{\\k0} ")
            if w_start > at:
                out.append(f"{{\\k{w_start - at}}}")   # the lead-in, or a held rest
            out.append(
                f"{{\\r\\kf{w_end - w_start}{grow(rise, fall)}{settle(fall)}}}"
                f"{escape(token)}"
            )
        at = w_end

    return "".join(out)


def settle(end_cs: int) -> str:
    """`\\t` that turns a word white once it has been sung.

    `\\kf` gives two states, and the useful one is a third. The style's primary
    is the accent, so the sweep fills the word being sung in colour; this hands
    that word back to white a moment later, leaving exactly one word lit at a
    time with a short trail behind it.
    """
    leave = end_cs * 10 + SETTLE_HOLD
    return f"\\t({leave},{leave + SETTLE},\\1c{tag_colour(SUNG)})"


def grow(start_cs: int, end_cs: int) -> str:
    """`\\t` pair that swells one word as it is sung and lets it back down.

    Every word's block opens with `\\r` because of this. An override applies to
    all the text after it, and a `\\t` that has not started yet does not cancel
    one that has: without the reset, word one's swell is still in force when
    word two is drawn, and the whole line inflates instead of one word in it.
    That looked like it worked until a frame was pulled at the moment word one
    was up, where the entire line was 40% larger.

    `\\r` does not disturb the karaoke clock, which keeps accumulating across
    the resets - checked, not assumed, since the whole sweep would be wrong if
    it did.

    The line re-centres as a word grows, which is the effect rather than a flaw
    in it: the row breathes around the word being sung.
    """
    length = (end_cs - start_cs) * 10
    amount = GROW * min(1.0, length / GROW_FULL)
    if amount < 1.0:
        return ""       # below a percent it is invisible, and two tags cost more

    rise = max(0, start_cs * 10 - GROW_LEAD)
    fall = end_cs * 10
    # A word shorter than the swell itself gets a shorter swell, not one that
    # overruns into its own settling.
    peak = min(rise + GROW_IN, max(rise + 40, fall))
    scale = round(100 + amount, 1)
    return (
        f"\\t({rise},{peak},\\fscx{scale}\\fscy{scale})"
        f"\\t({fall},{fall + GROW_OUT},\\fscx100\\fscy100)"
    )


def build(project: Project, font: str = FONT, size: int = FONT_SIZE) -> str:
    """The whole .ass file, as text."""
    lines = [ln for ln in project.lines if ln.end > ln.start]
    spans = windows(project)
    fade = f"{{\\fad({FADE_IN},{FADE_OUT})}}"

    def style(name: str, primary: str, secondary: str) -> str:
        # Alignment 1 anchors each slot to its own bottom-left corner, so a line
        # that wraps grows upward inside its slot instead of pushing the others.
        return (
            f"Style: {name},{font},{size},{primary},{secondary},"
            f"{colour(*EDGE)},{colour(0x000000, 0xFF)},"
            f"0,0,0,0,100,100,0,0,1,{BORDER},0,1,{MARGIN_L},{MARGIN_R},{SLOT_NOW},1"
        )

    out = [
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
        # final colour - each word turns itself white afterwards.
        style("Lyric", colour(ACCENT), colour(*UNSUNG)),
        # The line before and the line after. One flat colour, no sweep: they
        # are there to be read ahead and remembered, not followed.
        style("Near", colour(*NEAR), colour(*NEAR)),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV,"
        " Effect, Text",
    ]

    def event(style_name: str, span: tuple[float, float], slot: int, body: str) -> str:
        start_cs = centis(max(0.0, span[0]))
        end_cs = max(start_cs + 1, centis(span[1]))
        return (
            f"Dialogue: 0,{ass_time(start_cs)},{ass_time(end_cs)},{style_name},,"
            f"0,0,{slot},,{fade}{body}"
        )

    for i, (line, span) in enumerate(zip(lines, spans)):
        out.append(event("Lyric", span, SLOT_NOW, karaoke_text(line, centis(span[0]))))
        # The neighbours share the window exactly, so no line is ever on screen
        # in two slots at once. Overlapping them by a few hundred milliseconds
        # to cross-dissolve between slots was the obvious idea and it looks like
        # a duplicate: for the length of the overlap the same sentence is
        # legible twice, and the eye reads that as a fault rather than a move.
        if i + 1 < len(lines):
            out.append(event("Near", span, SLOT_NEXT, escape(lines[i + 1].text)))
        if i:
            out.append(event("Near", span, SLOT_PREV, escape(lines[i - 1].text)))

    return "\n".join(out) + "\n"


def write(project: Project, path: Path | str, **kwargs) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(project, **kwargs), encoding="utf-8")
    return path
