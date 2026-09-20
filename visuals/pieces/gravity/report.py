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
