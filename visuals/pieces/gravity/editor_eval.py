"""Which local model edits a sheet best: a fixed set of requests, each with the outcome it
should have, on Gravity (whose sections have names) and Shattered Voices (which has none).

    python -m visuals.pieces.gravity.editor_eval [--models qwen3.5:9b qwen3:8b gpt-oss:20b]

A request passes when the sheet it leads to - after validation - does what was asked and
leaves the rest alone. A request that cannot be done passes when nothing is changed; any
other request fails if the model's answer was refused, even where the sheet already had
what was asked (an answer refused twice changes nothing, and that is not the model's doing).
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

from . import editor, make, sheet as sheet_
from .track import GRAVITY_AUDIO, Track


def covers(s, bars, shot=None, subject=None, share=0.8):
    """Some act of this shot (and subject) covers at least `share` of these bars."""
    a, b = bars
    for act in (s or {}).get("acts", []):
        x0, x1 = act["bars"]
        ok = (shot is None or act["shot"] in (shot if isinstance(shot, tuple) else (shot,))) and \
             (subject is None or act.get("subject") == subject)
        if ok and max(0, min(b, x1) - max(a, x0)) >= share * (b - a):
            return True
    return False


def only(before, after, *keys):
    """Nothing outside `keys` changed."""
    return after is not None and all(after[k] == before[k] for k in ("cast", "reentries", "acts", "feel", "lyrics") if k not in keys)


def sec(named, name):
    return next([b0, b1] for n, b0, b1 in named if n == name)


GRAVITY = [
    ("close on Saturn during the second chorus",
     lambda b, a, n: (a is None and covers(b, sec(n, "Chorus 2"), ("eclipse", "intimate"), "saturn")) or
                     (covers(a, sec(n, "Chorus 2"), ("eclipse", "intimate"), "saturn") and only(b, a, "acts"))),
    ("a two-shot of the Sun and Jupiter through the bridge",
     lambda b, a, n: covers(a, sec(n, "Bridge"), "intimate", "jupiter") and only(b, a, "acts")),
    ("the planets should line up during the final chorus",           # already so, near enough
     lambda b, a, n: (a is None and covers(b, sec(n, "Final Chorus"), "alignment", share=0.7)) or
                     (covers(a, sec(n, "Final Chorus"), "alignment") and only(b, a, "acts")
                      and sum(x["shot"] == "alignment" for x in a["acts"]) == 1)),
    ("the planets should line up during the first chorus",           # the climax moves
     lambda b, a, n: covers(a, sec(n, "Chorus 1"), "alignment") and only(b, a, "acts")
                     and sum(x["shot"] == "alignment" for x in a["acts"]) == 1),
    ("a wide shot for the whole of the first verse",
     lambda b, a, n: covers(a, sec(n, "Verse 1"), "wide") and only(b, a, "acts")),
    ("fewer solar flares, please", lambda b, a, n: a is not None and a["feel"]["flares_every_bars"] > b["feel"]["flares_every_bars"] and only(b, a, "feel")),
    ("make the orbits breathe more when the beat drops out",
     lambda b, a, n: a is not None and a["feel"]["orbits_breathe"] > b["feel"]["orbits_breathe"] and only(b, a, "feel")),
    ("slow the cinematic camera's moves down",
     lambda b, a, n: a is not None and a["feel"]["camera_move_bars"] > b["feel"]["camera_move_bars"] and only(b, a, "feel")),
    ("hide the lyrics", lambda b, a, n: a is not None and a["lyrics"]["show"] is False and only(b, a, "lyrics")),
    ("make the lyrics a little bigger",
     lambda b, a, n: a is not None and b["lyrics"]["size"] < a["lyrics"]["size"] <= 0.05 and only(b, a, "lyrics")),
    ("words that have been sung should stay brighter",
     lambda b, a, n: a is not None and a["lyrics"]["sung"] > b["lyrics"]["sung"] and only(b, a, "lyrics")),
    ("take out the re-entry at bar 42",
     lambda b, a, n: a is not None and 42 not in [r["bar"] for r in a["reentries"]] and len(a["reentries"]) == len(b["reentries"]) - 1 and only(b, a, "reentries")),
    ("add a strong re-entry at bar 58",
     lambda b, a, n: a is not None and any(r["bar"] == 58 and r["strength"] >= 0.7 for r in a["reentries"]) and only(b, a, "reentries")),
    ("the heart should be silent", lambda b, a, n: a is not None and a["cast"]["heart"] == "silent" and only(b, a, "cast")),
    ("let the drums play the heart", lambda b, a, n: a is None, True),  # the heart cannot be the drums: nothing changes
    ("make the sun blue", lambda b, a, n: a is None, True),             # the colours are fixed
    ("keep everything as it is", lambda b, a, n: a is None),
]
SHATTERED = [
    ("close on Jupiter from bar 20 to bar 30",
     lambda b, a, n: covers(a, [20, 30], ("eclipse", "intimate"), "jupiter", share=0.9) and only(b, a, "acts")),
    ("the heart should not follow the synth", lambda b, a, n: a is not None and a["cast"]["heart"] == "silent" and only(b, a, "cast")),
    ("more rings from the planets",
     lambda b, a, n: a is not None and a["feel"]["planet_rings_every_bars"] < b["feel"]["planet_rings_every_bars"] and only(b, a, "feel")),
]


def _unload(model: str) -> None:
    body = json.dumps({"model": model, "keep_alive": 0}).encode()
    urllib.request.urlopen(urllib.request.Request(editor.OLLAMA.replace("/chat", "/generate"), data=body,
                                                  headers={"Content-Type": "application/json"}), timeout=60).read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["qwen3.5:9b", "qwen3:8b", "gpt-oss:20b"])
    args = ap.parse_args(argv)
    songs = [(Track.resolve(GRAVITY_AUDIO), GRAVITY),
             (Track.resolve(os.path.expanduser("~/Downloads/Shattered Voices.wav")), SHATTERED)]
    prepared = []
    for tr, cases in songs:
        got = make.listened(tr, verbose=False)
        _, sh, _ = make.directed(tr, got)
        prepared.append((tr, got, sh, editor.named_sections(tr, got["arrays"]["bar_t"]), cases))
    report = {}
    for model in args.models:
        _unload(model)                                     # each model starts alone in memory, and cold
    for model in args.models:
        rows = []
        for tr, got, sh, named, cases in prepared:
            for prompt, ok, *impossible in cases:
                t0 = time.time()
                try:
                    r = editor.edit(tr, got, sh, prompt, model=model)
                    passed = bool(ok(sh, r["sheet"], named)) and (bool(impossible) or not r["refused"])
                    rows.append({"song": tr.slug, "request": prompt, "passed": passed, "did": r["did"], "said": r["said"],
                                 "refused": r["refused"], "attempts": r["attempts"], "seconds": round(r["seconds"], 1)})
                except Exception as e:                    # a model that cannot answer fails the request
                    rows.append({"song": tr.slug, "request": prompt, "passed": False, "error": str(e)[:200],
                                 "seconds": round(time.time() - t0, 1)})
                row = rows[-1]
                print(f"  {model:12s} {'pass' if row['passed'] else 'FAIL'}  {row['seconds']:5.1f}s  {prompt}  -> {row.get('did') or row.get('error') or ''}", flush=True)
        n = len(rows)
        report[model] = {"passed": sum(r["passed"] for r in rows), "of": n,
                         "median_seconds": sorted(r["seconds"] for r in rows)[n // 2], "rows": rows}
        print(f"{model}: {report[model]['passed']}/{n} passed, median {report[model]['median_seconds']}s a request", flush=True)
        _unload(model)                                     # so the next model has the memory to itself
    out = sheet_.ROOT / "visuals" / "out" / "editor-eval.json"
    out.write_text(json.dumps(report, indent=1))
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
