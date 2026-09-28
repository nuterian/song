"""A loop: a few bars of the song's picture, made to run round without a seam.

For Spotify's Canvas, which plays a loop of three to eight seconds, tall, over a song in its
telephone app, in place of the cover (support.spotify.com/us/artists/article/canvas-guidelines,
read 2026-09-27: "3-8 seconds long, Vertical 9:16 ratio, Between 720px - 1080px tall, An MP4
or JPG file"; "avoid rapid video cuts or intense flashing graphics"; "consider excluding your
song and artist name"). It has no sound of its own and it is not in step with the song: the
app starts it when it likes. So it is the picture at its liveliest, for its own sake.

Which bars: whole bars, as many as fit in eight seconds, where the most is played (the
kicks, the bass line's notes and the planets' notes, by their sizes), and no re-entry
falls: a re-entry is a flash, and once a loop is a flash every few seconds.

How it is made to run round. The picture is drawn from channels and from the time, and the
time is only ever asked how long ago a hit was. So the channels are made to come back to
where they began, and the picture does:

  a level or a clock   is eased back by as much as it got ahead: over the loop it loses, a
                       little each frame, what it gained. A level that follows the music is
                       at a bar line at both ends and had gained next to nothing. A clock
                       (the orbits, the weather, the turn of a camera) had gained its whole
                       run, and so it stands: for these few seconds the planets keep their
                       places on their orbits, and dance there.
  a hit                is the loop's own. Until a slot's first hit in the loop, what it
                       holds is its last hit of the loop, a loop's length ago: so a ring
                       thrown in the last bar is still going out in the first. A slot with
                       no hit in the loop holds none: what was thrown before the loop's
                       bars is not in it.

The loop is a whole number of frames, the nearest to its bars' length (461 for Gravity's
7.68 s, so its beats are 0.04 % slow): a loop that is not, stutters where it joins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from . import cosmos, direct

LONGEST, SHORTEST = 8.0, 3.0           # seconds: Spotify's
_HIT = re.compile(r"^(u[A-Z][a-z]+)([A-Z])(\d*)$")


@dataclass(frozen=True)
class Window:
    start: float             # seconds into the song
    length: float            # seconds: whole bars (whole beats, of a song whose bar is longer than the longest loop)
    bars: float
    bar: int                 # the bar it starts on
    played: float            # how much is played in it, against the most in any window of the song (1 = the most)


def lengths(bar: float, meter: int, longest: float = LONGEST, shortest: float = SHORTEST) -> tuple[float, float]:
    """(seconds, bars): as many whole bars as fit in `longest`; of a bar longer than that,
    as many of its beats."""
    n = int(np.floor(longest / bar + 1e-9))
    if n >= 1:
        while n * bar < shortest:                          # a bar under three seconds, and one of them: two, three...
            n += 1
        return n * bar, float(n)
    beats = int(np.floor(longest / (bar / meter) + 1e-9))
    return beats * bar / meter, beats / meter


def window(ch: direct.Channels, got: dict, camera: str = "static", longest: float = LONGEST) -> Window:
    """The bars to loop: see the module's docstring."""
    from . import render

    meta = got["meta"]
    meter = int(meta.get("meter", 4))
    bar = meter * float(meta["period"])
    bar_t = np.asarray(got["arrays"]["bar_t"], dtype=np.float64)
    length, bars = lengths(bar, meter, longest)
    heard = render.heard(ch)
    t = np.concatenate([np.asarray(heard[k]["t"], dtype=np.float64) for k in ("kick", "bass", "notes")])
    a = np.concatenate([np.asarray(heard[k]["a"], dtype=np.float64) for k in ("kick", "bass", "notes")])
    order = np.argsort(t)
    t, run = t[order], np.concatenate([[0.0], np.cumsum(a[order])])
    played = lambda t0: run[np.searchsorted(t, t0 + length)] - run[np.searchsorted(t, t0)]
    drops = np.array([d["t"] for d in ch.drops], dtype=np.float64)
    span = ch.data[:, ch.index(f"uCamSpan.{camera}")].astype(np.float64)
    at = lambda s: span[min(int(round(s * direct.RATE)), len(span) - 1)]
    best, most = None, 0.0
    for k, t0 in enumerate(bar_t):
        if t0 + length > ch.duration - 0.5:
            break
        p = played(t0)
        most = max(most, p)
        if ((drops > t0 - 0.5 * bar) & (drops < t0 + length + 0.25 * bar)).any():
            continue                                       # a re-entry in it, or its flash still on
        if abs(np.log(at(t0 + length) / at(t0))) > 0.05:
            continue                                       # the camera is on its way somewhere
        if best is None or p > best[0]:
            best = (p, k, float(t0))
    if best is None:                                       # every window has one or the other: the liveliest, then
        best = max((played(t0), k, float(t0)) for k, t0 in enumerate(bar_t) if t0 + length <= ch.duration - 0.5)
    return Window(best[2], length, bars, best[1], float(best[0] / max(most, 1e-9)))


def frames(length: float, fps: int) -> int:
    return max(1, int(round(length * fps)))


def rows(ch: direct.Channels, w: Window, fps: int = 60) -> tuple[np.ndarray, np.ndarray]:
    """(times, rows) for the loop's frames: the time each is drawn for, and the channels it
    is drawn from, which come back at the last frame to what they were before the first."""
    n = frames(w.length, fps)
    inside = (np.arange(n, dtype=np.float64) + 1.0) * w.length / n            # a frame shows the end of its span
    out = ch.rows(w.start + inside).astype(np.float64)
    before, after = ch.rows(np.array([w.start]))[0].astype(np.float64), out[-1].copy()
    lerp = np.array([k == direct.LERP for k in ch.kinds])
    out[:, lerp] -= np.outer(inside / w.length, (after - before))[:, lerp]

    # the hits: each slot's time, and what is held with it (its size, its tone, its place)
    groups: dict[tuple[str, str], dict[str, int]] = {}
    for c, (name, kind) in enumerate(zip(ch.names, ch.kinds)):
        m = _HIT.match(name.split(".")[0])
        if kind == direct.HOLD and m:
            groups.setdefault((m.group(1), m.group(3)), {})[m.group(2)] = c
    for members in groups.values():
        lead = members.get("T", next(iter(members.values())))
        changed = np.flatnonzero(out[:, lead] != before[lead])
        first = int(changed[0]) if len(changed) else n
        if first == n:                                                         # no hit in the loop: none held
            if "T" in members:
                out[:, members["T"]] = -1000.0
            continue
        for letter, c in members.items():
            out[:first, c] = after[c] - (w.length if letter == "T" else 0.0)
    grouped = {c for members in groups.values() for c in members.values()}
    for c, kind in enumerate(ch.kinds):                                        # and what is held by itself
        if kind == direct.HOLD and c not in grouped:
            changed = np.flatnonzero(out[:, c] != before[c])
            if len(changed):
                out[:int(changed[0]), c] = after[c]
    return w.start + inside, out
