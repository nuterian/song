"""Tables. What was heard, printed so it can be argued with."""

from __future__ import annotations

import numpy as np

from .listen import RATE

EVENTS = ("kick", "snare", "hat", "bass_note", "syllable", "note")
STREAMS = ("gravity", "bass", "voice", "other", "bright", "air", "loud", "energy", "width")


def print_listen(got: dict, bars_per_row: int = 4) -> None:
    a, meta = got["arrays"], got["meta"]
    g = meta["grid"]
    print(f"{meta['duration']:.1f}s  {meta['tempo']:.4f} bpm  first beat {1000 * g['t0']:.1f} ms  "
          f"{g['sharp_used']} hats+claps within {g['sharp_residual_ms']:.2f} ms rms  "
          f"detector lag corrected {meta['lag_ms']}")
    db = a["downbeats"]
    db = db[(db >= 0) & (db < meta["duration"])]
    edges = np.append(db, meta["duration"])
    head = "bar    t   " + " ".join(f"{e[:5]:>5}" for e in EVENTS) + "  " + \
           " ".join(f"{s[:5]:>5}" for s in STREAMS) + "  harm"
    print(head)
    for i in range(0, len(db), bars_per_row):
        t0, t1 = edges[i], edges[min(i + bars_per_row, len(edges) - 1)]
        counts = [int(((a[f"ev_{e}_t"] >= t0) & (a[f"ev_{e}_t"] < t1)).sum()) for e in EVENTS]
        lo, hi = int(t0 * RATE), max(int(t0 * RATE) + 1, int(t1 * RATE))
        means = [float(a[s][lo:hi].mean()) for s in STREAMS]
        harm = float(a["harmony"][lo:hi].mean())
        print(f"{i:3d} {t0:6.1f} " + " ".join(f"{c:5d}" for c in counts) + "  " +
              " ".join(f"{m:5.2f}" for m in means) + f" {harm:5.2f}")


def print_models(got: dict, arrays: dict, meta: dict) -> None:
    from . import decide, direct

    a, lmeta = got["arrays"], got["meta"]
    print("Beat This!:", meta["beat_this"])
    print("key:", meta["key"]["name"], f"(fit {meta['key']['fit']:.2f})")
    ch = meta["chords"]
    print(f"chords: {len(ch)} spans; first twelve:", " ".join(c["chord"] for c in ch[:12]))
    drops = direct.find_drops(a, lmeta["period"], lmeta["duration"])
    sections = decide.find_sections(a, drops, lmeta["duration"])
    sim = arrays["clap_similarity"]
    names = list(decide.AXES)
    axes = np.stack([decide.z((sim[:, 2 * k + 1] - sim[:, 2 * k]).tolist()) for k in range(len(names))], axis=1)
    print("CLAP, standardised across the song (positive = the second word of the pair):")
    print("  sec  bars        state   " + " ".join(f"{n:>8s}" for n in names))
    for s, row in zip(sections, axes):
        print(f"  {s.index:3d}  {s.bar0:3d}-{s.bar1:3d}  {s.state:7s} " + " ".join(f"{v:+8.2f}" for v in row))
    if "line_similarity" not in arrays:
        print("lyrics: none")
        return
    ls, ws = arrays["line_similarity"], arrays["word_similarity"]
    images = meta["images"]
    print("lyric lines -> image (similarity):")
    for text, row in zip(meta["lines"], ls):
        k = int(np.argmax(row))
        print(f"  {images[k]:9s} {row[k]:.2f}  {text}")
    top = np.argsort(ws.max(axis=1))[::-1][:16]
    print("strongest single words:", ", ".join(f"{meta['words'][i].strip()}->{images[int(np.argmax(ws[i]))]} {ws[i].max():.2f}" for i in top))
