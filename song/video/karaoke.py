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
FONT = "Avenir Next Heavy"
FONT_SIZE = 60

# No blur on the words themselves, at all. libass's \blur is described as
# softening the border, but with a border thick enough to read it bleeds into
# the fill: at bord 3.0 / blur 2.8 the letterforms visibly lose their edges, and
# every word came *into focus* as it was sung, which is not an effect anybody
# asked for. So the lyric layer is a hairline edge and nothing else.
BORDER = 1.2
EDGE = (0x000000, 0x50)

# The shadow is a second event underneath, carrying the same words with no fill
# and a thick blurred border, sitting a few pixels lower. That is the only way
# to get a soft shadow without blurring the text: ASS's own \shad is a hard
# offset copy, which is the 1990s word-processor look, and \blur on the lyric
# layer would take the letterforms with it. Nothing is drawn on this layer that
# a blur could soften except the shadow itself.
SHADE = (0x000000, 0x60)
SHADE_BORDER = 6.5
SHADE_BLUR = 8.0
SHADE_DROP = 3               # pixels lower than the words

# Where the block sits, in the 1280x720 frame the coordinates above assume.
MARGIN = 86
BASELINE = 180

# Three states, and the middle one is the point. A word not yet sung is dim
# white; the word being sung fills in the accent; a word already sung settles to
# plain white. \kf gives the first two - it sweeps the fill from Secondary to
# Primary - and the third is one transform per word, turning that word's primary
# white a beat after it is done.
UNSUNG = (0xFFFFFF, 0x68)
ACCENT = 0xFFC64D
SUNG = 0xFFFFFF
SETTLE_HOLD = 130            # ms the accent holds after the word ends
SETTLE = 320                 # ...then this long to fade to white

# The word being sung swells. Capped by how long the word lasts: at full size on
# a 90 ms syllable it is a flicker rather than an emphasis, so short words grow
# proportionally less and a fast run reads as a ripple instead of a strobe.
GROW = 12.0        # percent, for a word long enough to see it
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
        # final colour - each word turns itself white afterwards. Alignment 2
        # anchors the block by its bottom edge, so a line that wraps to two rows
        # grows upward and the row being sung never moves under you.
        f"Style: Lyric,{font},{size},"
        f"{colour(ACCENT)},{colour(*UNSUNG)},{colour(*EDGE)},{colour(0x000000, 0xFF)},"
        f"0,0,0,0,100,100,0,0,1,{BORDER},0,2,{MARGIN},{MARGIN},{BASELINE},1",
        # The shadow layer. Same face, same size, same margins, so it wraps
        # identically - a shadow that breaks a line somewhere else than the
        # words above it is worse than no shadow. Only the baseline differs.
        f"Style: Shade,{font},{size},"
        f"{colour(0x000000)},{colour(0x000000)},{colour(*SHADE)},{colour(0x000000, 0xFF)},"
        f"0,0,0,0,100,100,0,0,1,{SHADE_BORDER},0,2,{MARGIN},{MARGIN},"
        f"{BASELINE - SHADE_DROP},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV,"
        " Effect, Text",
    ]

    for line, (appear, vanish) in zip(lines, windows(project)):
        start_cs = centis(appear)
        end_cs = max(start_cs + 1, centis(vanish))
        stamps = f"{ass_time(start_cs)},{ass_time(end_cs)}"
        out.append(
            f"Dialogue: 0,{stamps},Shade,,0,0,0,,"
            f"{karaoke_text(line, start_cs, shade=True)}"
        )
        out.append(
            f"Dialogue: 1,{stamps},Lyric,,0,0,0,,{karaoke_text(line, start_cs)}"
        )

    return "\n".join(out) + "\n"


def write(project: Project, path: Path | str, **kwargs) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(project, **kwargs), encoding="utf-8")
    return path
