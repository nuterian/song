"""The direction sheet: every decision the director makes for a song, in words a person -
or a small local model, prompted - can read and change.

What was heard is not in it - where the beats fall, what each instrument played, how
loud; that is the song - except where a person has corrected it, and the names the song's
parts go by. The sheet is what was made of it:

    heard       corrections to the grid (the beat twice or half as fast, the beats in a
                bar, where bar 1 falls) and the song's sections by name - from its lyric
                sheet, or, with none, from how full it is - which a person may rename,
                move and add to. Sections change nothing in the picture; they are how a
                person, or the model, says where.
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

VERSION = 2                  # 2: `heard`, the grid's corrections and the sections by name
CURATED = ROOT / "visuals" / "sheets"
GRID = {"tempo_times": 1.0, "meter": None, "bar_one": 0}      # as heard: nothing corrected
TEMPO_TIMES = (0.5, 1.0, 2.0)
METERS = (2, 3, 4, 5, 6, 7)
STATE_NAME = {"drive": "Drive", "float": "Float", "void": "Break", "silent": "Silence"}

SHOTS = {
    "approach": "from far out and low, coming in to the home view",
    "wide": "home, turning slowly, coming down low over the plane mid-act",
    "intimate": "a two-shot: the Sun and one planet (subject), framed to fit both",
    "eclipse": "close on one planet (subject) while the ripples sweep past it",
    "alignment": "the climax: the planets stand in a row, filling the frame",
    "pullback": "up over the plane and away, until the system is a mark on the galaxy",
}
NEEDS_SUBJECT = ("intimate", "eclipse")
# What each part of the cast does in the picture. A part cast silent stops doing it; every
# body is still there.
PARTS = {
    "pulse": "the Sun swells, and the orbits are tugged in, on each hit",
    "ring": "a ring goes out from the Sun across the plane, striking the planets it reaches",
    "stars": "the stars swell and subside, a third of them at a time",
    "corona": "the corona charges with the line and lets go in flares",
    "planets": "each planet throws out rings on the notes, in its own manner",
    "heart": "the light inside the Sun, and a band off its corona that reaches with the melody",
}
PLANETS = ("mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune")

# name: (default, low, high, what it means)
FEEL = {
    "flares_every_bars": (2.0, 0.5, 16.0, "a solar flare about once every this many bars of the bass line"),
    "planet_rings_every_bars": (1.5, 0.5, 16.0, "a planet throws a ring about once every this many bars of its notes"),
    "camera_move_bars": (8.0, 1.0, 32.0, "cinematic camera: how many bars a move from one shot to the next takes"),
    "hybrid_turn_bars": (96.0, 16.0, 1024.0, "hybrid camera: bars for one slow turn all the way round"),
    "orbits_breathe": (0.55, 0.0, 1.5, "how far the orbits widen when the floor goes (0 = not at all)"),
    "planets_breathe": (0.0, 0.0, 1.0, "how far the planets go out and in together with the bars, as a share of the gap to the next orbit"),
    "planets_sway": (0.0, 0.0, 2.0, "how far they surge along their orbits as they come in and fall back as they go out, against how far they breathe"),
    "kick_pull": (1.0, 0.0, 1.5, "how hard a kick pulls the planets toward the Sun"),
    "accents": (0.0, 0.0, 1.0, "0: a planet answers every note; 1: only the note that stands out in each bar, and more"),
    "planets_arc": (0.0, 0.0, 1.0, "how far the planets rise and fall together off the plane, once in a phrase, as a share of the gap to the next orbit"),
    "near_dance": (0.0, 0.0, 1.0, "0: in a close shot a planet dances as small on screen as from afar; 1: as large as the planet is seen"),
    "belts_breathe": (0.0, 0.0, 1.0, "how far the belts go out and in with the bars, as planets_breathe says for the planet just inside each; and how much larger a kick makes their rocks as it passes"),
    "sky_breathes": (0.0, 0.0, 1.0, "how far the stars move out and in with the phrase, the nearest furthest: at 1, 1.2 percent of the way from the middle of the frame"),
    "wave": (0.0, 0.0, 1.0, "how high a wave of hops runs out through the planets on a re-entry, and more lightly at every other phrase"),
    "comet": (0.0, 0.0, 1.0, "0: the comet answers nothing; above 0 it rounds the Sun on the song's strongest re-entry, and a strong kick blows its tail out as it passes, at 1 to 1.3 times its length"),
    "gravity": (0.0, 0.0, 0.6, "how far the Sun's pull, which is its size, draws the orbits and the belts in and lets them out, as a share of each orbit; above 0 the planets follow it alone, and do not hop"),
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
        "heard": dict(GRID, **(m.get("grid_fix") or {}), sections=default_sections(track, got, ch)),
        "cast": {part: cast[part]["choice"] for part in CHOICES},
        "reentries": [{"bar": bar_of(bar_t, d["t"]), "strength": float(d["strength"])} for d in ch.drops],
        "acts": acts,
        "feel": {k: v[0] for k, v in FEEL.items()},
        "lyrics": {k: v[0] for k, v in LYRICS.items()},
    }


def default_sections(track: Track, got: dict, ch) -> list[dict]:
    """The song's parts by name. With a lyric sheet, its sections, and the stretches
    between them of four bars or more: the first "Intro", the last "Outro" (or "End",
    after a sung "Outro"), those between "Instrumental". With none, the director's own
    sections (cut where the floor comes back), a section shorter than four bars joined to
    the next, each named by how full it is - Drive (the kick in), Float (no kick), Break
    (nothing below) - and numbered; the first "Intro" unless it drives."""
    from . import lyrics

    bar_t = got["arrays"]["bar_t"]
    n = len(bar_t)
    sung = lyrics.sung_sections(track, bar_t)
    if sung:
        named = [(b0, b1, name) for name, b0, b1 in sung]
        edges = [0] + [x for b0, b1, _ in named for x in (b0, b1)] + [n]
        gaps = [(a, b) for a, b in zip(edges[0::2], edges[1::2]) if b - a >= 4]
        middle = [g for g in gaps if g[0] > 0 and g[1] < n]
        for a, b in gaps:
            if a == 0:
                name = "Intro"
            elif b == n:
                name = "End" if "outro" in sung[-1][0].lower() else "Outro"
            else:
                name = "Instrumental" + (f" {middle.index((a, b)) + 1}" if len(middle) > 1 else "")
            named.append((a, b, name))
    else:
        runs = []
        for sec in ch.sections or []:
            if runs and runs[-1][1] - runs[-1][0] < 4:           # too short to be a part: joined to this one
                runs[-1] = [runs[-1][0], sec.bar1, sec.state]
            else:
                runs.append([sec.bar0, sec.bar1, sec.state])
        if len(runs) > 1 and runs[-1][1] - runs[-1][0] < 4:
            runs[-2][1] = runs.pop()[1]
        if runs and runs[0][2] != "drive":
            runs[0][2] = "intro"
        count = {st: sum(r[2] == st for r in runs) for st in {r[2] for r in runs}}
        seen: dict[str, int] = {}
        named = []
        for b0, b1, st in runs:
            seen[st] = seen.get(st, 0) + 1
            name = "Intro" if st == "intro" else STATE_NAME.get(st, st.title()) + (f" {seen[st]}" if count[st] > 1 else "")
            named.append((b0, b1, name))
    return [{"name": name, "bars": [int(b0), int(b1)]} for b0, b1, name in sorted(named)]


def upgrade(sheet: dict, track: Track, got: dict, ch) -> dict:
    """A sheet written before `heard` (version 1), with its sections worked out now."""
    if sheet.get("sheet") != 1:
        return sheet
    out = {"sheet": VERSION, "song": sheet["song"],
           "heard": dict(GRID, sections=default_sections(track, got, ch))}
    return out | {k: v for k, v in sheet.items() if k not in ("sheet", "song")}


def grid_fix(track: Track) -> dict | None:
    """The correction of the grid a kept sheet asks for, if any."""
    from .grid import normal_fix

    path = CURATED / f"{track.slug}.json"
    if not path.exists():
        return None
    heard = read(path).get("heard") or {}
    return normal_fix({k: heard.get(k) for k in GRID})


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
    heard = sheet.get("heard", {})
    if heard.get("tempo_times") not in TEMPO_TIMES:
        bad.append(f"heard.tempo_times: {heard.get('tempo_times')!r} - the beat can be as heard (1), twice as fast (2) or half (0.5)")
    if heard.get("meter") is not None and heard.get("meter") not in METERS:
        bad.append(f"heard.meter: {heard.get('meter')!r} beats to a bar - it can be {', '.join(map(str, METERS))}, or null for as heard")
    if not isinstance(heard.get("bar_one"), int) or abs(heard.get("bar_one", 0)) > 7:
        bad.append(f"heard.bar_one: {heard.get('bar_one')!r} - bar 1 moves by a whole number of beats, at most 7")
    at = 0
    for i, sec in enumerate(heard.get("sections", [])):
        b, name = sec.get("bars"), sec.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 40:
            bad.append(f"heard.sections[{i}]: a section needs a name of 1-40 characters")
        if not (isinstance(b, list) and len(b) == 2 and all(isinstance(x, int) for x in b) and 0 <= b[0] < b[1] <= n_bars):
            bad.append(f"heard.sections[{i}]: bars {b!r} are not bars of this song (0-{n_bars})")
            continue
        if b[0] < at:
            bad.append(f"heard.sections[{i}] ({name}): starts at bar {b[0]}, inside the section before - sections may leave gaps but not overlap")
        at = b[1]
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
            bad.append(f"acts[{i}]: the {act.get('shot')} shot needs a subject: one of {', '.join(PLANETS)}")
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


def normal(sheet: dict) -> dict:
    """The sheet with each number the kind the vocabulary says: a dial or a strength a
    decimal, a bar a whole number. A sheet that has been through a browser comes back with
    2 for 2.0; written as it came, the file would change where nothing had."""
    s = json.loads(json.dumps(sheet))
    for k in ("tempo", "seconds"):
        if isinstance(s.get("song", {}).get(k), (int, float)):
            s["song"][k] = float(s["song"][k])
    heard = s.get("heard") or {}
    if isinstance(heard.get("tempo_times"), (int, float)) and not isinstance(heard["tempo_times"], bool):
        heard["tempo_times"] = float(heard["tempo_times"])
    for r in s.get("reentries", []):
        if isinstance(r.get("strength"), (int, float)) and not isinstance(r["strength"], bool):
            r["strength"] = float(r["strength"])
    for group, spec in (("feel", FEEL), ("lyrics", LYRICS)):
        for k, v in s.get(group, {}).items():
            if k in spec and not isinstance(spec[k][0], bool) and isinstance(v, (int, float)) and not isinstance(v, bool):
                s[group][k] = float(v)
    return s


def dumps(sheet: dict) -> str:
    """JSON, one act or re-entry to a line and one dial to a line, so a sheet reads - and
    diffs - like a list. Numbers are written exactly (a re-entry's strength round-trips),
    and each as the kind it is (`normal`)."""
    parts = []
    for k, v in normal(sheet).items():
        if isinstance(v, list) and v:
            body = ",\n".join("    " + json.dumps(x) for x in v)
            parts.append(f"  {json.dumps(k)}: [\n{body}\n  ]")
        elif isinstance(v, dict):
            def entry(kk, vv):
                if isinstance(vv, list) and vv:
                    rows = ",\n".join("      " + json.dumps(x) for x in vv)
                    return f"    {json.dumps(kk)}: [\n{rows}\n    ]"
                return f"    {json.dumps(kk)}: {json.dumps(vv)}"
            body = ",\n".join(entry(kk, vv) for kk, vv in v.items())
            parts.append(f"  {json.dumps(k)}: {{\n{body}\n  }}")
        else:
            parts.append(f"  {json.dumps(k)}: {json.dumps(v)}")
    return "{\n" + ",\n".join(parts) + "\n}"


def read(path: Path) -> dict:
    return json.loads(Path(path).read_text())
