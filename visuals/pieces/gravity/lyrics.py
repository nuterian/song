"""Lyrics in the picture: timed to the word, placed where nothing is, and quiet.

Where the words come from: the song tool's word timings - hand-timed gold when the song
has it, else its own alignment (`source`).

How they look (agreed with Jugal, 2026-09-20): one line at a time, small, a light face in
warm off-white ink at low strength. The word being sung lifts - it eases up to full ink
just before it is sung and peaks on it, as everything in the picture does - and a sung
word settles a little brighter than the words still to come. No karaoke bar, no colour:
the solar system does not change colour, and neither do its words. A line fades in over
INTRO, ending on its first word, and out after its last; instrumental stretches are clean.

Where they go: for each line and each camera, the region of the frame nothing crosses
while the line is up - the Sun and its corona, each planet and the reach of its rings -
from a handful of candidates, preferring the one the last line used. A line never moves
while it is up; a new place is taken between lines, by fading out and in.

`ink` is the one definition of how bright a word is at a moment; the player's copy
(player.js, `lyricInk`) is held to it by a test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import ROOT, cosmos, direct, follow
from .track import Track

INTRO = 0.35                 # s: a line fades in over this, arriving on its first word
OUTRO = 0.50                 # s: and stays this long after its last, then fades
FADE_OUT = 0.40              # s
LEAD = 0.09                  # s: a word starts to lift this long before it is sung
UNSUNG, PEAK, SUNG = 0.42, 1.0, 0.64
SIZE = 0.030                 # font size, in frame heights (32 px at 1080p)
CHAR_W = 0.53                # average advance of a character, in font sizes: Inter Light letter-spaced
                             # 0.06 em measures 0.52 on Gravity's lines (0.47-0.59); a little over, so a
                             # line's box errs wide (it was 0.56; Helvetica Neue Light, the face before, measures 0.49)
MARGIN = 0.035               # frame heights kept clear round the text
ASPECT = 16 / 9
CORONA = 3.0                 # the Sun's clear zone, in its radii: the corona can stand out that far
RING_REACH = 2.5             # a planet's, in its radii: its rings and moons (4.0 left too few places:
                             # on Gravity, text touched a body in 5-15 % of lyric frames against 0-3 %)

# Candidate places: centre (x, y) in frame heights from the middle, y up; and alignment.
# Six were too few - the tilted orbits sweep the lower third - so there are the edges too,
# and a place at each side, beside the system, for the close shots.
REGIONS = {
    "low": (0.0, -0.36, "center"),
    "low-left": (-0.80, -0.36, "left"),
    "low-right": (0.80, -0.36, "right"),
    "high": (0.0, 0.37, "center"),
    "high-left": (-0.80, 0.37, "left"),
    "high-right": (0.80, 0.37, "right"),
    "bottom": (0.0, -0.43, "center"),
    "bottom-left": (-0.82, -0.43, "left"),
    "bottom-right": (0.82, -0.43, "right"),
    "top": (0.0, 0.43, "center"),
    "top-left": (-0.82, 0.43, "left"),
    "top-right": (0.82, 0.43, "right"),
    "side-left": (-0.82, -0.18, "left"),
    "side-right": (0.82, -0.18, "right"),
}
PREFER = list(REGIONS)       # in this order, other things equal: low and centred first


@dataclass
class Line:
    words: list[tuple[str, float, float]]
    in0: float = 0.0         # starts to appear
    in1: float = 0.0         # fully in
    out0: float = 0.0        # starts to fade
    out1: float = 0.0        # gone
    place: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(w for w, _, _ in self.words)

    @property
    def first(self) -> float:
        return self.words[0][1]

    @property
    def last(self) -> float:
        return self.words[-1][2]


# ------------------------------------------------------------------------ words


def source(track: Track) -> Path | None:
    """The best word timings there are for this track, in this order: a hand-timed gold
    workdir (workdir/<slug>-gold/), the committed gold file (examples/gold/), the song
    tool's own alignment. For Gravity the first is the newest and the most complete - it
    has a sung chorus line the lyric sheet left out (34 lines, 182 words, against 33 and 177)."""
    for p in (ROOT / "workdir" / f"{track.slug}-gold" / "project.json",
              ROOT / "examples" / "gold" / f"{track.slug}.project.json"):
        if p.exists():
            return p
    return track.project


def read(path: Path) -> list[Line]:
    project = json.loads(Path(path).read_text())
    lines = []
    for ln in project.get("lines", []):
        ws = [(w["text"].strip(), float(w["start"]), float(w["end"])) for w in ln.get("words", [])
              if w.get("start") is not None and w.get("end") is not None and w["text"].strip()]
        if ws:
            lines.append(Line(ws))
    lines.sort(key=lambda l: l.first)
    return timed(lines)


DISSOLVE = 0.08             # s: half the shortest changeover, when lines come back to back


def timed(lines: list[Line]) -> list[Line]:
    """When each line is up. One at a time: in over INTRO ending on its first word, out
    OUTRO after its last over FADE_OUT - unless the next comes too soon, and then the two
    dissolve into each other in the middle of the gap, never quicker than 2 x DISSOLVE."""
    for ln in lines:
        ln.in0, ln.in1 = ln.first - INTRO, ln.first
        ln.out0 = ln.last + OUTRO
        ln.out1 = ln.out0 + FADE_OUT
    for ln, nxt in zip(lines[:-1], lines[1:]):
        if nxt.in0 < ln.out1:
            mid = 0.5 * (ln.last + nxt.first)
            d = max(min(0.20, 0.5 * (nxt.first - ln.last)), DISSOLVE)
            ln.out0, ln.out1 = mid - d, mid + d
            nxt.in0, nxt.in1 = mid - d, max(nxt.first, mid + d)
    return lines


def opacity(line: Line, t: float) -> float:
    """The line as a whole, eased in and out on its four moments."""
    if t <= line.in0 or t >= line.out1:
        return 0.0
    up = _ease((t - line.in0) / max(line.in1 - line.in0, 1e-3))
    down = _ease((line.out1 - t) / max(line.out1 - line.out0, 1e-3))
    return float(min(up, down))


def ink(t: float, start: float, end: float, unsung: float = UNSUNG, peak: float = PEAK, sung: float = SUNG) -> float:
    """How much ink a word has at `t`: `unsung` until LEAD before it, eased up to `peak` on
    it, eased down to `sung` over its length (at least a quarter second) after. The three
    inks are the sheet's to change (`layout` gives them in its style); these are the defaults."""
    if t < start - LEAD:
        return unsung
    if t < start:
        return unsung + (peak - unsung) * _ease((t - (start - LEAD)) / LEAD)
    settle = max(end - start, 0.25)
    if t < start + settle:
        return peak + (sung - peak) * _ease((t - start) / settle)
    return sung


def _ease(x: float) -> float:
    """Cubic in-out on 0..1, flat at both ends."""
    x = min(max(x, 0.0), 1.0)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def sung_sections(track: Track, bar_t) -> list[tuple[str, int, int]]:
    """The song's sections as its lyric sheet names them, in bars: from the bar its first
    line starts in to the bar after its last line ends. Repeated names are numbered."""
    src = source(track)
    if src is None:
        return []
    project = json.loads(src.read_text())
    lines = project.get("lines", [])
    names = [s.get("name", "") for s in project.get("sections", [])]
    count = {n: names.count(n) for n in names}
    seen: dict[str, int] = {}
    out = []
    for s in project.get("sections", []):
        idx = [i for i in s.get("line_indices", []) if i < len(lines) and lines[i].get("start") is not None]
        if not idx:
            continue
        name = s.get("name", "section")
        seen[name] = seen.get(name, 0) + 1
        if count[name] > 1:
            name = f"{name} {seen[name]}"
        t0, t1 = float(lines[idx[0]]["start"]), float(lines[idx[-1]]["end"])
        b0 = max(0, int((bar_t <= t0).sum()) - 1)
        b1 = min(len(bar_t), int((bar_t < t1).sum()))
        out.append((name, b0, max(b1, b0 + 1)))
    return out


# ------------------------------------------------------------------------ places


def box(region: str, text: str, size: float = SIZE) -> tuple[float, float, float, float]:
    """The text's extent in frame heights (x0, y0, x1, y1), margin not included."""
    x, y, align = REGIONS[region]
    w = len(text) * CHAR_W * size
    h = 1.3 * size
    x0 = {"center": x - w / 2, "left": x, "right": x - w}[align]
    return x0, y - h / 2, x0 + w, y + h / 2


def obstacles(ch: direct.Channels, times: np.ndarray, camera: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Discs nothing may cross, at each time: (x, y, r) each (times, bodies), frame heights."""
    rows = np.minimum(np.round(times * direct.RATE).astype(int), len(ch.data) - 1)
    g = follow.geometry(ch, rows, camera)
    x = np.column_stack([g["sun_x"], g["planet_x"]])
    y = np.column_stack([g["sun_y"], g["planet_y"]])
    r = np.column_stack([CORONA * g["sun_r"], RING_REACH * g["planet_r"]])
    return x, y, r


def crosses(b: tuple[float, float, float, float], x: np.ndarray, y: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Per time: does any disc come within MARGIN of the box."""
    x0, y0, x1, y1 = b[0] - MARGIN, b[1] - MARGIN, b[2] + MARGIN, b[3] + MARGIN
    dx = np.maximum(np.maximum(x0 - x, 0.0), x - x1)
    dy = np.maximum(np.maximum(y0 - y, 0.0), y - y1)
    return (np.hypot(dx, dy) < r).any(axis=1)


def place(lines: list[Line], ch: direct.Channels, camera: str, step: float = 0.1, size: float = SIZE) -> dict:
    """Each line's region for this camera: the fewest moments crossed, then the region the
    last line used, then the preferred order. Returns what that cost, for the scorecard."""
    prev, crossed, shown, moves = None, 0, 0, 0
    for ln in lines:
        times = np.arange(ln.in0, ln.out1, step)
        x, y, r = obstacles(ch, times, camera)
        best, best_cost = None, None
        for k, region in enumerate(PREFER):
            b = box(region, ln.text, size)
            if b[0] < -ASPECT / 2 + 0.02 or b[2] > ASPECT / 2 - 0.02:
                continue                                   # it would not fit across the frame here
            hits = crosses(b, x, y, r)
            cost = (hits.mean(), 0 if region == prev else 1, k)
            if best_cost is None or cost < best_cost:
                best, best_cost = region, cost
        if best is None:                                   # longer than any place: centred, low
            best = "low"
        hits = crosses(box(best, ln.text, size), x, y, r)
        crossed += int(hits.sum()); shown += len(times)
        moves += int(prev is not None and best != prev)
        ln.place[camera] = best
        prev = best
    return {"camera": camera, "crossed": crossed / max(shown, 1), "moves": moves}


def layout(track: Track, ch: direct.Channels, style: dict | None = None) -> dict | None:
    """Everything the player needs to set the words, and what placing them cost. `style` is
    the direction sheet's `lyrics`: whether they show, their size and their inks."""
    st = {"show": True, "size": SIZE, "unsung": UNSUNG, "peak": PEAK, "sung": SUNG} | (style or {})
    src = source(track)
    if src is None or not st["show"]:
        return None
    lines = read(src)
    if not lines:
        return None
    size = st["size"]
    cost = [place(lines, ch, mode, size=size) for mode in cosmos.MODES]
    covered = max(box(ln.place["static"], ln.text, size)[2] - box(ln.place["static"], ln.text, size)[0] for ln in lines) * 1.3 * size / ASPECT
    return {
        "source": str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else str(src),
        "style": {"size": size, "intro": INTRO, "outro": OUTRO, "fade_out": FADE_OUT, "lead": LEAD,
                  "unsung": st["unsung"], "peak": st["peak"], "sung": st["sung"]},
        "regions": {k: {"x": x, "y": y, "align": a} for k, (x, y, a) in REGIONS.items()},
        "lines": [{"in": [round(ln.in0, 4), round(ln.in1, 4)], "out": [round(ln.out0, 4), round(ln.out1, 4)], "place": ln.place,
                   "words": [[w, round(s, 4), round(e, 4)] for w, s, e in ln.words]} for ln in lines],
        "cost": cost,
        "largest_share_of_frame": covered,
    }
