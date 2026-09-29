"""Edit a song's direction sheet by asking, with a small model that runs on this machine.

    python -m visuals edit <song> "close on Saturn in the second chorus" [--model gpt-oss:20b] [--dry]

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
    section   bars [a, b] are named (a section there before is cut back); no name unnames them

and, from the studio only (a person's correction of what was heard, which listens again):

    grid      the beat twice or half as fast, the beats in a bar, where bar 1 falls

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
MODEL = "gpt-oss:20b"             # 20/20 and 19/20 on editor_eval, ~7 s a request (NOTES.md)


# ------------------------------------------------------------------ the song, in words


def _mmss(t: float) -> str:
    t = max(t, 0.0)                     # the first bar line can fall a hair before the song starts
    return f"{int(t // 60)}:{int(t % 60):02d}"


def song_map(track: Track, got: dict, sheet: dict, focus: dict | None = None) -> str:
    """Everything the model needs to turn a request into bars and choices, in words. `focus`
    is where the person is: what they have selected ({"bars": [a, b]} or {"bar": b}) and the
    bar the playhead is on ({"playhead": b})."""
    bar_t, dur = got["arrays"]["bar_t"], float(got["meta"]["duration"])
    at = lambda b: _mmss(float(bar_t[b]) if b < len(bar_t) else dur)
    rows = [f"Song: {track.slug}, {sheet['song']['tempo']:.1f} BPM, {sheet['song']['meter']} beats to a bar, "
            f"{len(bar_t)} bars (numbered 0-{len(bar_t) - 1}), {_mmss(dur)} long."]
    named = [(x["name"], *x["bars"]) for x in sheet.get("heard", {}).get("sections", [])]
    if named:
        rows.append("Sections, by name (bars [first, after-last], and time):")
        rows += [f"  {n}: bars [{b0}, {b1}], {at(b0)}-{at(b1)}" for n, b0, b1 in named]
    else:
        rows.append("The song's sections have no names; its parts are the acts below.")
    rows.append("Acts now (the camera's shot for each; the 'alignment' act is the climax, where the planets line up):")
    rows += [f"  act {i}: bars [{a['bars'][0]}, {a['bars'][1]}], {at(a['bars'][0])}-{at(a['bars'][1])}: {a['shot']}"
             + (f" on {a['subject']}" if a.get("subject") else "") for i, a in enumerate(sheet["acts"])]
    rows.append("Re-entries now (where the beat comes back, with strength): "
                + ", ".join(f"bar {r['bar']} ({at(r['bar'])}) {r['strength']:.2f}" for r in sheet["reentries"]))
    rows.append("Parts of the cast (what each does in the picture; a part cast silent stops doing it, and every "
                "body is still there): " + "; ".join(f"{k} - {v}" for k, v in sheet_.PARTS.items()))
    rows.append("Cast now (what plays each part): " + ", ".join(f"{k} = {v}" for k, v in sheet["cast"].items()))
    rows.append("Shots: " + "; ".join(f"{k} - {v}" for k, v in sheet_.SHOTS.items()))
    rows.append("Planets (subjects): " + ", ".join(sheet_.PLANETS))
    rows.append("Cast choices: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in CHOICES.items()))
    rows.append("Feel dials now: " + "; ".join(f"{k} = {sheet['feel'].get(k, dflt)} ({lo}-{hi}: {what})"
                                               for k, (dflt, lo, hi, what) in sheet_.FEEL.items()))
    rows.append("Lyrics now: " + "; ".join(f"{k} = {json.dumps(sheet['lyrics'][k])}" + (f" ({lo}-{hi}: {what})" if lo is not None else f" ({what})")
                                           for k, (_, lo, hi, what) in sheet_.LYRICS.items()))
    if focus:
        sel = focus.get("bars") or ([focus["bar"], focus["bar"] + 1] if focus.get("bar") is not None else None)
        if sel:
            name = next((x["name"] for x in sheet.get("heard", {}).get("sections", []) if x["bars"] == list(sel)), None)
            rows.append(f'Selected by the person now - what "this", "here", "these bars" and "now" mean: '
                        f"bars [{sel[0]}, {sel[1]}], {at(sel[0])}-{at(sel[1])}" + (f" ({name})" if name else ""))
        elif focus.get("playhead") is not None:
            rows.append(f'Nothing is selected; the playhead is at bar {focus["playhead"]} ({at(focus["playhead"])}): '
                        f'"here" and "now" mean the section or act that bar is in')
    return "\n".join(rows)


# ------------------------------------------------------------------ what it may answer


def schema() -> dict:
    """The only shape an answer can take: each edit one of the five, with exactly its own
    fields, all of them given, and a part's choice one of that part's own. (With one loose
    shape for all five, a model left fields out - a shot with no shot - or filled in ones
    that belonged to another edit.)"""
    def op(kind: str, **fields) -> dict:
        return {"type": "object", "properties": {"op": {"const": kind}} | fields,
                "required": ["op", *fields], "additionalProperties": False}

    num = {"type": "number"}
    edits = [op("shot", bars={"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
                shot={"enum": list(sheet_.SHOTS)}, subject={"enum": list(sheet_.PLANETS) + ["none"]})]
    edits += [op("cast", part={"const": part}, choice={"enum": list(choices)}) for part, choices in CHOICES.items()]
    edits += [op("reentry", bar={"type": "integer"}, strength=num),
              op("feel", dial={"enum": list(sheet_.FEEL)}, value=num)]
    flags = [k for k, v in sheet_.LYRICS.items() if isinstance(v[0], bool)]
    edits += [op("lyrics", key={"enum": flags}, value={"type": "boolean"}),
              op("lyrics", key={"enum": [k for k in sheet_.LYRICS if k not in flags]}, value=num),
              op("section", bars={"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
                 name={"type": "string", "maxLength": 40})]
    return {"type": "object", "properties": {
        "edits": {"type": "array", "items": {"anyOf": edits}},
        "said": {"type": "string"},
    }, "required": ["edits", "said"], "additionalProperties": False}


SYSTEM = """You edit the direction sheet of a music video: a solar system that moves with the song.
Answer only with edits, from this vocabulary:
  {"op": "shot", "bars": [first, after-last], "shot": <shot>, "subject": <planet, only for intimate or eclipse>}
  {"op": "cast", "part": <part>, "choice": <one of that part's choices>}
  {"op": "reentry", "bar": <bar>, "strength": <0 to 1; 0 removes it>}
  {"op": "feel", "dial": <dial>, "value": <number in its range>}
  {"op": "lyrics", "key": <setting>, "value": <number in its range, or true/false for show>}
  {"op": "section", "bars": [first, after-last], "name": <what to call those bars; "" to unname them>}
Use the song's bars: find the section the request names in the map, and use its bars exactly.
"This", "here", "these bars" and "now" mean what the map says is selected - all of it, its bars exactly.
Make the smallest change that does what is asked, and nothing else: only the edits the request
needs, never one that restates what the sheet already has. If the request cannot be done with
this vocabulary, answer with no edits and say why in "said". "said" is one short sentence
saying what you changed."""

# Models that cannot answer with their thinking off (gpt-oss answers nothing at all), and
# the least thinking they can do instead.
THINK = {"gpt-oss": "low"}
KEEP = "30m"                 # the model stays loaded this long after a request: loading it takes ~20 s


def models() -> dict:
    """The models installed, and those loaded now (a model not loaded takes ~20 s to load)."""
    get = lambda path: json.loads(urllib.request.urlopen(OLLAMA.replace("/api/chat", path), timeout=5).read())
    return {"installed": sorted(m["name"] for m in get("/api/tags")["models"]),
            "loaded": [m["name"] for m in get("/api/ps")["models"]]}


def warm(model: str = MODEL) -> None:
    """Load the model now, so the first request does not wait for it."""
    body = json.dumps({"model": model, "keep_alive": KEEP}).encode()
    urllib.request.urlopen(urllib.request.Request(OLLAMA.replace("/chat", "/generate"), data=body,
                                                  headers={"Content-Type": "application/json"}), timeout=120).read()


def ask(prompt: str, context: str, model: str = MODEL, retry: tuple[dict, str] | None = None,
        timeout: float = 300.0) -> dict:
    """The model's answer to a request; `retry` is its last answer and why it was refused."""
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"{context}\n\nRequest: {prompt}"}]
    if retry:
        messages += [{"role": "assistant", "content": json.dumps(retry[0])},
                     {"role": "user", "content": f"Those edits were refused: {retry[1]}\nTry again."}]
    think = next((v for k, v in THINK.items() if model.startswith(k)), False)
    body = {"model": model, "messages": messages, "format": schema(), "stream": False,
            "think": think, "options": {"temperature": 0}, "keep_alive": KEEP}
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
    out = _join(out)
    if shot == "alignment":
        # the climax is the alignment act the span is now part of - joined, first, to the
        # alignment act beside it, if it was moving that act's edge; any other goes wide
        out = _join([x if x["bars"][0] <= a and x["bars"][1] >= b or x["shot"] != "alignment"
                     else {"bars": x["bars"], "shot": "wide"} for x in out])
    return out


def set_section(sections: list[dict], bars: list[int], name: str) -> list[dict]:
    """Bars [a, b] named `name` (or unnamed, for ""): a section that overlaps them is cut
    back to what lies outside them, keeping its name. Sections may leave gaps."""
    a, b = bars
    out = []
    for sec in sections:
        x0, x1 = sec["bars"]
        if x1 <= a or x0 >= b:
            out.append(dict(sec))
            continue
        if x0 < a:
            out.append(dict(sec, bars=[x0, a]))
        if x1 > b:
            out.append(dict(sec, bars=[b, x1]))
    if name.strip():
        out.append({"name": name.strip(), "bars": [a, b]})
    return sorted(out, key=lambda x: x["bars"][0])


def _join(acts: list[dict]) -> list[dict]:
    """Neighbours with the same shot and subject, made one."""
    joined = []
    for x in acts:
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
            if e.get("shot") not in sheet_.NEEDS_SUBJECT:
                subject = None                          # every shot is asked for one; only two have one
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
        elif op == "section":
            n = s["song"]["bars"]
            a, b = (list(e.get("bars", [0, 0])) + [0, 0])[:2]
            a, b = max(0, min(int(a), n)), max(0, min(int(b), n))
            if b <= a:
                did.append(f"bars {e.get('bars')}: not bars of this song - nothing done")
                continue
            name = str(e.get("name") or "").strip()
            if name and name == name.lower():
                name = name[0].upper() + name[1:]           # "drop" is written as a section's name is: "Drop"
            s["heard"]["sections"] = set_section(s["heard"].get("sections", []), [a, b], name)
            did.append(f"bars [{a}, {b}]: " + (f"called {name.strip()}" if name.strip() else "no name"))
        elif op == "grid":                           # the studio's, not the model's: it listens again
            for k in ("tempo_times", "meter", "bar_one"):
                if k in e:
                    s["heard"][k] = e[k]
            did.append("grid: " + ", ".join(f"{k} {e[k]}" for k in ("tempo_times", "meter", "bar_one") if k in e))
    return s, did


# ------------------------------------------------------------------ what changed, for a person

SHOT_NAME = {"approach": "Approach", "wide": "Wide", "intimate": "Two-shot", "eclipse": "Close",
             "alignment": "Alignment", "pullback": "Pull back"}
LABEL = {
    "flares_every_bars": ("Flares", "every {} bars"), "planet_rings_every_bars": ("Planet rings", "every {} bars"),
    "camera_move_bars": ("Camera moves", "{} bars"), "hybrid_turn_bars": ("Hybrid turn", "{} bars"),
    "orbits_breathe": ("Orbits breathe", "{}"), "show": ("Words", "{}"), "size": ("Word size", "{}"),
    "unsung": ("Ink before sung", "{}"), "peak": ("Ink as sung", "{}"), "sung": ("Ink after sung", "{}"),
}


def _num(v) -> str:
    if isinstance(v, bool):
        return "shown" if v else "hidden"
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def _spans(n: int, before, after) -> list[tuple[int, int]]:
    """Runs of bars where `before(bar)` and `after(bar)` differ, and differ the same way."""
    out, start = [], None
    for b in range(n + 1):
        diff = b < n and before(b) != after(b)
        key = (before(b), after(b)) if diff else None
        if start is not None and (not diff or key != run):
            out.append((start, b))
            start = None
        if diff and start is None:
            start, run = b, key
    return out


def changes(before: dict, after: dict) -> list[dict]:
    """What changed between two sheets, as a person would read it: for each thing, what
    kind it is, where (bars, a bar, or the whole song), and what it was and is now. Worked
    out from the sheets, not from the edits that made them, so a hand's edit, a model's,
    an undo - any two sheets - read the same way."""
    out = []
    hb, ha = before.get("heard", {}), after.get("heard", {})
    grid = [k for k in ("tempo_times", "meter", "bar_one") if hb.get(k) != ha.get(k)]
    for k in grid:
        name, fmt = {"tempo_times": ("Tempo", lambda v: "as heard" if v in (1, None) else f"×{v:g}"),
                     "meter": ("Beats in a bar", lambda v: "as heard" if v is None else str(v)),
                     "bar_one": ("Bar 1", lambda v: "as heard" if not v else f"{v:+d} beat" + ("s" if abs(v) > 1 else ""))}[k]
        out.append({"kind": "grid", "title": name, "before": fmt(hb.get(k)), "after": fmt(ha.get(k))})
    if grid:                                  # the bars themselves moved: shots and moments were made anew
        out.append({"kind": "shot", "title": "Shots and moments", "before": f"{before['song']['bars']} bars",
                    "after": f"made again on {after['song']['bars']} bars"})
        return out
    n = after["song"]["bars"]

    def at(acts, b):
        for x in acts:
            if x["bars"][0] <= b < x["bars"][1]:
                return SHOT_NAME[x["shot"]] + (f" · {x['subject'].title()}" if x.get("subject") else "")
        return None
    for a, b in _spans(n, lambda k: at(before["acts"], k), lambda k: at(after["acts"], k)):
        out.append({"kind": "shot", "title": "Shot", "bars": [a, b], "before": at(before["acts"], a), "after": at(after["acts"], a),
                    "climax": at(after["acts"], a) == "Alignment"})

    def named(secs, b):
        return next((x["name"] for x in secs if x["bars"][0] <= b < x["bars"][1]), None)
    sb, sa = hb.get("sections", []), ha.get("sections", [])
    for a, b in _spans(n, lambda k: named(sb, k), lambda k: named(sa, k)):
        out.append({"kind": "section", "title": "Name", "bars": [a, b], "before": named(sb, a) or "no name",
                    "after": named(sa, a) or "no name"})

    rb = {r["bar"]: r["strength"] for r in before.get("reentries", [])}
    ra = {r["bar"]: r["strength"] for r in after.get("reentries", [])}
    for bar in sorted(set(rb) | set(ra)):
        if rb.get(bar) != ra.get(bar):
            pct = lambda v: "none" if v is None else f"{round(100 * v)}%"
            out.append({"kind": "moment", "title": "Beat returns", "bar": bar, "before": pct(rb.get(bar)), "after": pct(ra.get(bar))})

    for part in after.get("cast", {}):
        if before["cast"].get(part) != after["cast"][part]:
            out.append({"kind": "cast", "title": part.title(), "before": before["cast"].get(part, "").replace("-", " "),
                        "after": after["cast"][part].replace("-", " ")})
    for group in ("feel", "lyrics"):
        for k, v in after.get(group, {}).items():
            if before.get(group, {}).get(k) != v:
                name, fmt = LABEL.get(k, (k, "{}"))
                out.append({"kind": "words" if group == "lyrics" else "feel", "title": name,
                            "before": fmt.format(_num(before[group].get(k))), "after": fmt.format(_num(v))})
    return out


def edit(track: Track, got: dict, sheet: dict, prompt: str, model: str = MODEL, tries: int = 2,
         focus: dict | None = None) -> dict:
    """Ask; apply; check; if refused, say why and ask once more. Returns the new sheet (or
    None), what was done, what the model said, what was refused, and how long it took."""
    context = song_map(track, got, sheet, focus)
    retry, t0 = None, time.time()
    for attempt in range(tries):
        answer = ask(prompt, context, model, retry)
        answer["edits"] = [e for e in answer.get("edits", []) if apply(sheet, [e])[0] != sheet]   # restating is not changing
        new, did = apply(sheet, answer["edits"])
        bad = sheet_.validate(new, got)
        if not bad:
            changed = new != sheet                     # an edit that asks for what is already so changes nothing
            return {"sheet": new if changed else None, "did": did, "already": bool(did) and not changed,
                    "said": answer.get("said", ""), "refused": [],
                    "attempts": attempt + 1, "seconds": time.time() - t0, "edits": answer.get("edits", [])}
        retry = (answer, "; ".join(bad))
    return {"sheet": None, "did": did, "said": answer.get("said", ""), "refused": bad,
            "attempts": tries, "seconds": time.time() - t0, "edits": answer.get("edits", [])}
