"""The direction sheet: every decision the director makes for a song, in words a person -
or a small local model, prompted - can read and change.

What was heard is not in it - where the beats fall, what each instrument played, how
loud; that is the song. The sheet is what was made of it:

    cast        who plays each part of the theme
    reentries   the bars where the floor comes back, and how hard
    acts        the song cut into acts: bars, a shot, and for some shots a planet. The act
                whose shot is `alignment` is the climax: the planets stand in a row in it.
    feel        a few dials, each a number with a range and a meaning
    lyrics      whether the words show, and how quietly

Bars are counted from 0, as the song's own bar lines fall (`bar_t` in the listening);
`[14, 50]` is bar 14 up to, not including, bar 50.

`default` writes the sheet the director would make; `render.bake` reads one. The default
sheet bakes the very same channels as a bake with no sheet at all (a test holds it, byte
for byte), so everything the video does is in the sheet, and an edit to the sheet is an
edit to the video. `validate` refuses anything outside the vocabulary below, so an edit
either means something or is turned away with the reason.

Curated sheets - the ones a person, or a model, has edited - live in visuals/sheets/ and
are kept; any other song's is written beside its bundle, as derived as the bundle is.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import ROOT
from .cast import CHOICES
from .track import Track

VERSION = 1
CURATED = ROOT / "visuals" / "sheets"

SHOTS = {
    "approach": "from far out and low, coming in to the home view",
    "wide": "home, turning slowly, coming down low over the plane mid-act",
    "intimate": "a two-shot: the Sun and one planet (subject), framed to fit both",
    "eclipse": "close on one planet (subject) while the ripples sweep past it",
    "alignment": "the climax: the planets stand in a row, filling the frame",
    "pullback": "up over the plane and away, until the system is a mark on the galaxy",
}
NEEDS_SUBJECT = ("intimate", "eclipse")
PLANETS = ("mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune")

# name: (default, low, high, what it means)
FEEL = {
    "flares_every_bars": (2.0, 0.5, 16.0, "a solar flare about once every this many bars of the bass line"),
    "planet_rings_every_bars": (1.5, 0.5, 16.0, "a planet throws a ring about once every this many bars of its notes"),
    "camera_move_bars": (8.0, 1.0, 32.0, "cinematic camera: how many bars a move from one shot to the next takes"),
    "hybrid_turn_bars": (96.0, 16.0, 1024.0, "hybrid camera: bars for one slow turn all the way round"),
    "orbits_breathe": (0.55, 0.0, 1.5, "how far the orbits widen when the floor goes (0 = not at all)"),
}
LYRICS = {
    "show": (True, None, None, "whether the words are shown"),
    "size": (0.030, 0.015, 0.060, "type size, in frame heights"),
    "unsung": (0.42, 0.0, 1.0, "ink of a word not yet sung"),
    "peak": (1.0, 0.0, 1.0, "ink of a word as it is sung"),
    "sung": (0.64, 0.0, 1.0, "ink a sung word settles to"),
}


# ------------------------------------------------------------------------ making


def default(track: Track, got: dict, ch) -> dict:
    """The sheet the director makes: read off a bake with no sheet (`ch`)."""
    a, m = got["arrays"], got["meta"]
    bar_t = a["bar_t"]
    cast = (ch.info or {}).get("cast", {})
    acts = []
    for act in ch.acts:
        entry = {"bars": [int(act.sections[0].bar0), int(act.sections[-1].bar1)], "shot": act.function}
        if act.function in NEEDS_SUBJECT and act.subject >= 0:
            entry["subject"] = PLANETS[act.subject]
        acts.append(entry)
    return {
        "sheet": VERSION,
        "song": {"slug": track.slug, "tempo": round(float(m["tempo"]), 4), "meter": int(m.get("meter", 4)),
                 "bars": int(len(bar_t)), "seconds": round(float(m["duration"]), 2)},
        "cast": {part: cast[part]["choice"] for part in CHOICES},
        "reentries": [{"bar": bar_of(bar_t, d["t"]), "strength": float(d["strength"])} for d in ch.drops],
        "acts": acts,
        "feel": {k: v[0] for k, v in FEEL.items()},
        "lyrics": {k: v[0] for k, v in LYRICS.items()},
    }


def bar_of(bar_t: np.ndarray, t: float) -> int:
    """The bar a bar line at `t` begins."""
    return int(np.argmin(np.abs(bar_t - t)))


def span(bar_t: np.ndarray, duration: float, bars: list[int]) -> tuple[float, float]:
    """The seconds bars [first, after-last] cover - reckoned exactly as a section reckons its
    own (decide.find_sections), so an act the sheet gives is the act the director made."""
    b0, b1 = bars
    return float(max(bar_t[b0], 0.0)), (float(bar_t[b1]) if b1 < len(bar_t) else float(duration))


# ------------------------------------------------------------------------ checking


def validate(sheet: dict, got: dict | None = None) -> list[str]:
    """Everything wrong with a sheet, in words; empty if it can be baked."""
    bad = []
    if sheet.get("sheet") != VERSION:
        bad.append(f"sheet: version {sheet.get('sheet')!r}, this reads {VERSION}")
    n_bars = int(sheet.get("song", {}).get("bars", 0))
    if got is not None:
        n_bars = len(got["arrays"]["bar_t"])
        if sheet.get("song", {}).get("bars") != n_bars:
            bad.append(f"song: the sheet has {sheet.get('song', {}).get('bars')} bars and the song {n_bars} - "
                       f"made for another listening; write a fresh one")
    for part, choice in sheet.get("cast", {}).items():
        if part not in CHOICES:
            bad.append(f"cast: no part called {part!r} (there are {', '.join(CHOICES)})")
        elif choice not in CHOICES[part]:
            bad.append(f"cast: {part} cannot be {choice!r}; it can be {', '.join(CHOICES[part])}")
    for r in sheet.get("reentries", []):
        if not isinstance(r.get("bar"), int) or not 1 <= r["bar"] < n_bars:
            bad.append(f"reentries: bar {r.get('bar')!r} is not a bar of this song (1-{n_bars - 1})")
        if not isinstance(r.get("strength"), (int, float)) or not 0.0 < r["strength"] <= 1.0:
            bad.append(f"reentries: strength {r.get('strength')!r} at bar {r.get('bar')} must be in (0, 1]")
    acts = sheet.get("acts", [])
    if not acts:
        bad.append("acts: there must be at least one")
    at = 0
    for i, act in enumerate(acts):
        b = act.get("bars")
        if not (isinstance(b, list) and len(b) == 2 and all(isinstance(x, int) for x in b)):
            bad.append(f"acts[{i}]: bars must be [first, after-last], two whole numbers")
            continue
        if b[0] != at:
            bad.append(f"acts[{i}]: starts at bar {b[0]}, but the act before ends at {at} - acts must follow on, no gaps or overlaps")
        if b[1] <= b[0]:
            bad.append(f"acts[{i}]: bars {b} are empty or backwards")
        at = b[1]
        if act.get("shot") not in SHOTS:
            bad.append(f"acts[{i}]: shot {act.get('shot')!r} is not one of {', '.join(SHOTS)}")
        if act.get("shot") in NEEDS_SUBJECT and act.get("subject") not in PLANETS:
            bad.append(f"acts[{i}]: a {act.get('shot')} shot needs a subject: one of {', '.join(PLANETS)}")
    if acts and at != n_bars:
        bad.append(f"acts: they end at bar {at}, the song has {n_bars}")
    for group, spec in (("feel", FEEL), ("lyrics", LYRICS)):
        for k, v in sheet.get(group, {}).items():
            if k not in spec:
                bad.append(f"{group}: no dial called {k!r} (there are {', '.join(spec)})")
                continue
            dflt, lo, hi, _ = spec[k]
            if isinstance(dflt, bool):
                if not isinstance(v, bool):
                    bad.append(f"{group}.{k}: must be true or false")
            elif not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                bad.append(f"{group}.{k}: {v!r} is outside {lo}-{hi}")
    return bad


# ------------------------------------------------------------------------ keeping


def path_for(track: Track) -> Path:
    """Where this song's sheet is read from: a curated one if there is one."""
    curated = CURATED / f"{track.slug}.json"
    return curated if curated.exists() else track.out("cosmos") / "sheet.json"


def write(sheet: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(sheet) + "\n")
    return path


def dumps(sheet: dict) -> str:
    """JSON, one act or re-entry to a line and one dial to a line, so a sheet reads - and
    diffs - like a list. Numbers are written exactly (a re-entry's strength round-trips)."""
    parts = []
    for k, v in sheet.items():
        if isinstance(v, list) and v:
            body = ",\n".join("    " + json.dumps(x) for x in v)
            parts.append(f"  {json.dumps(k)}: [\n{body}\n  ]")
        elif isinstance(v, dict):
            body = ",\n".join(f"    {json.dumps(kk)}: {json.dumps(vv)}" for kk, vv in v.items())
            parts.append(f"  {json.dumps(k)}: {{\n{body}\n  }}")
        else:
            parts.append(f"  {json.dumps(k)}: {json.dumps(v)}")
    return "{\n" + ",\n".join(parts) + "\n}"


def read(path: Path) -> dict:
    return json.loads(Path(path).read_text())
