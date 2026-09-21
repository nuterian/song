"""Edit a song's direction sheet by asking, with a small model that runs on this machine.

    python -m visuals edit <song> "close on Saturn in the second chorus" [--model qwen3.5:9b] [--dry]

The model is shown the song as a person would describe it - its sections by name, in bars
and in minutes and seconds - and its sheet, and asked for edits from a short vocabulary.
The runner holds its answer to that vocabulary (a JSON schema, so it cannot answer in any
other shape), and every edit is checked by sheet.validate before it is kept; if the sheet
it makes is refused, it is told why, once, and may try again. What it may do:

    shot      bars [a, b] get a shot (and a planet, for intimate and eclipse); an act that
              only partly overlaps is split, the rest of it keeping what it had
    cast      a part is played by one of its choices
    reentry   a re-entry at a bar with a strength; strength 0 takes one out
    feel      a dial is set
    lyrics    a lyric setting is set

The model is Ollama's (localhost:11434): nothing leaves the machine.
"""

from __future__ import annotations

import copy
import json
import time
import urllib.request

from . import sheet as sheet_
from .cast import CHOICES
from .track import Track

OLLAMA = "http://localhost:11434/api/chat"
MODEL = "qwen3.5:9b"


# ------------------------------------------------------------------ the song, in words


def _mmss(t: float) -> str:
    t = max(t, 0.0)                     # the first bar line can fall a hair before the song starts
    return f"{int(t // 60)}:{int(t % 60):02d}"


def named_sections(track: Track, bar_t) -> list[tuple[str, int, int]]:
    """The song's sections as its lyric sheet names them, in bars: from the bar its first
    line starts in to the bar after its last line ends. Repeated names are numbered."""
    from . import lyrics

    src = lyrics.source(track)
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


def song_map(track: Track, got: dict, sheet: dict) -> str:
    """Everything the model needs to turn a request into bars and choices, in words."""
    bar_t, dur = got["arrays"]["bar_t"], float(got["meta"]["duration"])
    at = lambda b: _mmss(float(bar_t[b]) if b < len(bar_t) else dur)
    rows = [f"Song: {track.slug}, {sheet['song']['tempo']:.1f} BPM, {sheet['song']['meter']} beats to a bar, "
            f"{len(bar_t)} bars (numbered 0-{len(bar_t) - 1}), {_mmss(dur)} long."]
    named = named_sections(track, bar_t)
    if named:
        rows.append("Sections, by the lyric sheet's names (bars [first, after-last], and time):")
        rows += [f"  {n}: bars [{b0}, {b1}], {at(b0)}-{at(b1)}" for n, b0, b1 in named]
    else:
        rows.append("The song has no lyrics; its parts are the acts below.")
    rows.append("Acts now (the camera's shot for each; the 'alignment' act is the climax, where the planets line up):")
    rows += [f"  act {i}: bars [{a['bars'][0]}, {a['bars'][1]}], {at(a['bars'][0])}-{at(a['bars'][1])}: {a['shot']}"
             + (f" on {a['subject']}" if a.get("subject") else "") for i, a in enumerate(sheet["acts"])]
    rows.append("Re-entries now (where the beat comes back, with strength): "
                + ", ".join(f"bar {r['bar']} ({at(r['bar'])}) {r['strength']:.2f}" for r in sheet["reentries"]))
    rows.append("Cast now (what plays each part): " + ", ".join(f"{k} = {v}" for k, v in sheet["cast"].items()))
    rows.append("Shots: " + "; ".join(f"{k} - {v}" for k, v in sheet_.SHOTS.items()))
    rows.append("Planets (subjects): " + ", ".join(sheet_.PLANETS))
    rows.append("Cast choices: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in CHOICES.items()))
    rows.append("Feel dials now: " + "; ".join(f"{k} = {sheet['feel'][k]} ({lo}-{hi}: {what})"
                                               for k, (_, lo, hi, what) in sheet_.FEEL.items()))
    rows.append("Lyrics now: " + "; ".join(f"{k} = {json.dumps(sheet['lyrics'][k])}" + (f" ({lo}-{hi}: {what})" if lo is not None else f" ({what})")
                                           for k, (_, lo, hi, what) in sheet_.LYRICS.items()))
    return "\n".join(rows)


# ------------------------------------------------------------------ what it may answer


def schema() -> dict:
    """The only shape an answer can take."""
    num = {"type": "number"}
    edit = {"type": "object", "properties": {
        "op": {"enum": ["shot", "cast", "reentry", "feel", "lyrics"]},
        "bars": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
        "shot": {"enum": list(sheet_.SHOTS)},
        "subject": {"enum": list(sheet_.PLANETS) + ["none"]},
        "part": {"enum": list(CHOICES)},
        "choice": {"enum": sorted({c for v in CHOICES.values() for c in v})},
        "bar": {"type": "integer"},
        "strength": num,
        "dial": {"enum": list(sheet_.FEEL)},
        "key": {"enum": list(sheet_.LYRICS)},
        "value": {"type": ["number", "boolean"]},
    }, "required": ["op"]}
    return {"type": "object", "properties": {
        "edits": {"type": "array", "items": edit},
        "said": {"type": "string"},
    }, "required": ["edits", "said"]}


SYSTEM = """You edit the direction sheet of a music video: a solar system that moves with the song.
Answer only with edits, from this vocabulary:
  {"op": "shot", "bars": [first, after-last], "shot": <shot>, "subject": <planet, only for intimate or eclipse>}
  {"op": "cast", "part": <part>, "choice": <one of that part's choices>}
  {"op": "reentry", "bar": <bar>, "strength": <0 to 1; 0 removes it>}
  {"op": "feel", "dial": <dial>, "value": <number in its range>}
  {"op": "lyrics", "key": <setting>, "value": <number in its range, or true/false for show>}
Use the song's bars: find the section the request names in the map, and use its bars exactly.
Make the smallest change that does what is asked, and nothing else. If the request cannot be
done with this vocabulary, answer with no edits and say why in "said". "said" is one short
sentence saying what you changed."""


def ask(prompt: str, context: str, model: str = MODEL, feedback: str | None = None, timeout: float = 300.0) -> dict:
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"{context}\n\nRequest: {prompt}"}]
    if feedback:
        messages.append({"role": "user", "content": f"Those edits were refused: {feedback}\nTry again."})
    body = {"model": model, "messages": messages, "format": schema(), "stream": False,
            "think": False, "options": {"temperature": 0}}
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        reply = json.loads(r.read())
    return json.loads(reply["message"]["content"])


# ------------------------------------------------------------------ applying


def set_shot(acts: list[dict], bars: list[int], shot: str, subject: str | None) -> list[dict]:
    """Bars [a, b] take `shot`: acts wholly inside are replaced, acts that overlap split,
    the parts outside keeping what they had; neighbours the same are joined. There is one
    climax: giving a span `alignment` makes any other alignment act `wide`."""
    a, b = bars
    new = {"bars": [a, b], "shot": shot} | ({"subject": subject} if shot in sheet_.NEEDS_SUBJECT and subject else {})
    out = []
    for act in acts:
        x0, x1 = act["bars"]
        if x1 <= a or x0 >= b:
            out.append(dict(act))
            continue
        if x0 < a:
            out.append(dict(act, bars=[x0, a]))
        if not out or out[-1] is not new:
            out.append(new)
        if x1 > b:
            out.append(dict(act, bars=[b, x1]))
    if shot == "alignment":
        out = [dict(x, shot="wide") if x is not new and x["shot"] == "alignment" else x for x in out]
        for x in out:
            if x["shot"] == "wide":
                x.pop("subject", None)
    joined = []
    for x in out:
        if joined and joined[-1]["shot"] == x["shot"] and joined[-1].get("subject") == x.get("subject"):
            joined[-1] = dict(joined[-1], bars=[joined[-1]["bars"][0], x["bars"][1]])
        else:
            joined.append(dict(x))
    return joined


def apply(sheet: dict, edits: list[dict]) -> tuple[dict, list[str]]:
    """The sheet with the edits made, and what each did, in words."""
    s = copy.deepcopy(sheet)
    did = []
    for e in edits:
        op = e.get("op")
        if op == "shot":
            subject = e.get("subject") if e.get("subject") not in (None, "none") else None
            n = s["acts"][-1]["bars"][1]
            a, b = (list(e.get("bars", [0, 0])) + [0, 0])[:2]
            a, b = max(0, min(int(a), n)), max(0, min(int(b), n))       # a span past the song's end stops at it
            if b <= a:
                did.append(f"bars {e.get('bars')}: not bars of this song - nothing done")
                continue
            s["acts"] = set_shot(s["acts"], [a, b], e.get("shot"), subject)
            did.append(f"bars {e.get('bars')}: {e.get('shot')}" + (f" on {subject}" if subject else ""))
        elif op == "cast":
            s["cast"][e.get("part")] = e.get("choice")
            did.append(f"{e.get('part')} played by {e.get('choice')}")
        elif op == "reentry":
            s["reentries"] = [r for r in s["reentries"] if r["bar"] != e.get("bar")]
            if (e.get("strength") or 0) > 0:
                s["reentries"] = sorted(s["reentries"] + [{"bar": e.get("bar"), "strength": float(e["strength"])}], key=lambda r: r["bar"])
                did.append(f"re-entry at bar {e.get('bar')}, strength {float(e['strength']):.2f}")
            else:
                did.append(f"no re-entry at bar {e.get('bar')}")
        elif op == "feel":
            s["feel"][e.get("dial")] = e.get("value")
            did.append(f"{e.get('dial')} = {e.get('value')}")
        elif op == "lyrics":
            s["lyrics"][e.get("key")] = e.get("value")
            did.append(f"lyrics {e.get('key')} = {e.get('value')}")
    return s, did


def edit(track: Track, got: dict, sheet: dict, prompt: str, model: str = MODEL, tries: int = 2) -> dict:
    """Ask; apply; check; if refused, say why and ask once more. Returns the new sheet (or
    None), what was done, what the model said, what was refused, and how long it took."""
    context = song_map(track, got, sheet)
    feedback, t0 = None, time.time()
    for attempt in range(tries):
        answer = ask(prompt, context, model, feedback)
        new, did = apply(sheet, answer.get("edits", []))
        bad = sheet_.validate(new, got)
        if not bad:
            changed = new != sheet                     # an edit that asks for what is already so changes nothing
            return {"sheet": new if changed else None, "did": did, "already": bool(did) and not changed,
                    "said": answer.get("said", ""), "refused": [],
                    "attempts": attempt + 1, "seconds": time.time() - t0, "edits": answer.get("edits", [])}
        feedback = "; ".join(bad)
    return {"sheet": None, "did": did, "said": answer.get("said", ""), "refused": bad,
            "attempts": tries, "seconds": time.time() - t0, "edits": answer.get("edits", [])}
