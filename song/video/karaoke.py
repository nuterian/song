"""project.json -> an ASS subtitle file with per-word karaoke timing.

There is no frame renderer here, and none anywhere else either. ASS has carried
karaoke tags since the VirtualDub era: `\\kf` sweeps a fill across a run of text
over a given duration, which is exactly the classic per-syllable wipe, and
libass draws it with real shaping, a blurred halo, and per-word transforms that
grow the word being sung. This project already knows where every word starts and
ends, so the karaoke layer is a format conversion plus a burn-in - not a text
renderer that would have to reimplement kerning, wrapping and antialiasing to
arrive somewhere worse.

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

# A blurred border and no drop shadow. The hard black stroke plus offset shadow
# that came first is the look of a 2005 fansub: it puts a stair-stepped edge on
# every glyph, which is most of what reads as aliasing, and it fights the soft
# picture underneath instead of sitting in it. Blurring the border turns it into
# a halo that lifts the word off any background without drawing an edge.
BLUR = 2.8
BORDER = 3.0
HALO = (0x05030A, 0x24)      # the resting halo: colour, transparency

SUNG = (0xFFFFFF, 0x00)      # a word already sung
UNSUNG = (0xFFFFFF, 0x80)    # ...and one still coming

# While a word is being sung its halo warms and opens, so the word carries a
# light of its own rather than only being larger than its neighbours.
GLOW = (0xFFD9A8, 0x60)
GLOW_BLUR = 4.0
GLOW_BORDER = 3.4

# The word being sung swells. Capped by how long the word lasts: at full size on
# a 90 ms syllable it is a flicker rather than an emphasis, so short words grow
# proportionally less and a fast run reads as a ripple instead of a strobe.
GROW = 14.0        # percent, for a word long enough to see it
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


def karaoke_text(line, start_cs: int) -> str:
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
        if i:
            out.append("{\\k0} ")
        if w_start > at:
            out.append(f"{{\\k{w_start - at}}}")  # unsung wait: the lead-in, or a rest
        out.append(
            f"{{\\r\\blur{BLUR}\\kf{w_end - w_start}"
            f"{swell(w_start - start_cs, w_end - start_cs)}}}{escape(token)}"
        )
        at = w_end

    return "".join(out)


def swell(start_cs: int, end_cs: int) -> str:
    """`\\t` pair that grows one word as it is sung and lets it back down.

    Every word's block opens with `\\r` because of this. An override applies to
    all the text after it, and a `\\t` that has not started yet does not cancel
    one that has: without the reset, word one's swell is still in force when
    word two is drawn, and the whole line inflates instead of one word in it.
    That looked like it worked until a frame was pulled at the moment word one
    was up, where the entire line was 40% larger.

    `\\r` clears the blur too, so each block re-applies it. It does not disturb
    the karaoke clock, which keeps accumulating across the resets - checked, not
    assumed, since the whole sweep would be wrong if it did.

    The line re-centres as a word grows, which is the effect rather than a flaw
    in it: the row breathes around the word being sung.
    """
    length = (end_cs - start_cs) * 10
    grow = GROW * min(1.0, length / GROW_FULL)
    if grow < 1.0:
        return ""       # below a percent it is invisible, and two tags cost more

    rise = max(0, start_cs * 10 - GROW_LEAD)
    # A word shorter than the swell itself gets a shorter swell, not one that
    # overruns into its own settling.
    peak = min(rise + GROW_IN, max(rise + 40, end_cs * 10))
    scale = round(100 + grow, 1)
    fall = end_cs * 10
    return (
        f"\\t({rise},{peak},\\fscx{scale}\\fscy{scale}"
        f"\\3c{tag_colour(GLOW[0])}\\3a&H{GLOW[1]:02X}&"
        f"\\bord{GLOW_BORDER}\\blur{GLOW_BLUR})"
        f"\\t({fall},{fall + GROW_OUT},\\fscx100\\fscy100"
        f"\\3c{tag_colour(HALO[0])}\\3a&H{HALO[1]:02X}&"
        f"\\bord{BORDER}\\blur{BLUR})"
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
        # Primary is the sung colour, Secondary the unsung one - \kf sweeps from
        # the second to the first. Both are white and the dimming does the work,
        # which leaves the background free to change hue by section without ever
        # fighting the words. Alignment 2 anchors the block by its bottom edge,
        # so a line that wraps to two rows grows upward and the row being sung
        # never moves under you.
        f"Style: Lyric,{font},{size},"
        f"{colour(*SUNG)},{colour(*UNSUNG)},{colour(*HALO)},{colour(0x000000, 0xFF)},"
        f"0,0,0,0,100,100,0,0,1,{BORDER},0,2,86,86,180,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV,"
        " Effect, Text",
    ]

    for line, (appear, vanish) in zip(lines, windows(project)):
        start_cs = centis(appear)
        end_cs = max(start_cs + 1, centis(vanish))
        out.append(
            f"Dialogue: 0,{ass_time(start_cs)},{ass_time(end_cs)},Lyric,,0,0,0,,"
            f"{karaoke_text(line, start_cs)}"
        )

    return "\n".join(out) + "\n"


def write(project: Project, path: Path | str, **kwargs) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(project, **kwargs), encoding="utf-8")
    return path
