"""A synthetic song workdir, so the tests do not need anybody's music.

The real sample track is gitignored - it is somebody's audio - so the tests that
need one build their own: a short song at a known tempo, with beats and downbeats
exactly where arithmetic says they should be, envelopes that are pure functions of
time, and two sections of lyrics. Everything a test asserts about beat phase or
section boundaries can therefore be computed by hand.

`real_track` is there for the cases worth running against the genuine article; it
skips when the workdir is not present.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from visuals.listen import RATE, Track

TEMPO = 120.0          # exactly two beats a second, so the arithmetic is obvious
METER = 4
DURATION = 24.0
BEAT = 60.0 / TEMPO    # 0.5s
BAR = BEAT * METER     # 2.0s

# Where the real thing lives, for the handful of tests that want it.
REAL = Path("/Users/jugalmanjeshwar/Files/code/song/workdir/gravity-in-motion")


def _write_workdir(root: Path) -> Path:
    n = int(round(DURATION * RATE)) + 1
    t = [i / RATE for i in range(n)]

    # Envelopes that a test can predict: a slow swell on the mix, a sine on the
    # bands, and a vocal that is only present while a line is being sung.
    mix = [0.5 + 0.4 * math.sin(2 * math.pi * x / DURATION) for x in t]
    low = [0.5 + 0.5 * math.sin(2 * math.pi * x / BAR) for x in t]
    high = [0.5 + 0.5 * math.cos(2 * math.pi * x / BEAT) for x in t]
    vocal = [0.8 if 4.0 <= x < 8.0 or 12.0 <= x < 16.0 else 0.0 for x in t]

    beats = [round(i * BEAT, 6) for i in range(int(DURATION / BEAT))]
    downbeats = [round(i * BAR, 6) for i in range(int(DURATION / BAR))]

    (root / "beats.json").write_text(json.dumps({
        "version": 2, "rate": RATE, "tempo": TEMPO, "meter": METER, "phase": 0,
        "low": low, "high": high, "beats": beats, "downbeats": downbeats,
    }))
    (root / "analysis.json").write_text(json.dumps({
        "duration": DURATION, "rate": RATE, "mix_peaks": mix, "vocal_peaks": vocal,
        "vocal_spans": [[4.0, 8.0], [12.0, 16.0]],
        "onsets": [4.0, 5.0, 6.0, 12.0, 13.0], "threshold_db": -50.0,
    }))

    def line(index, section, text, start, end, words):
        step = (end - start) / len(words)
        return {
            "index": index, "section": section, "text": text,
            "start": start, "end": end, "source": "test",
            "locked": False, "flagged": False,
            "words": [{"text": w, "start": round(start + i * step, 6),
                       "end": round(start + (i + 1) * step, 6), "prob": 0.9}
                      for i, w in enumerate(words)],
        }

    (root / "project.json").write_text(json.dumps({
        "version": 1, "duration": DURATION, "workdir": str(root),
        "audio_path": "none.wav", "lyrics_path": "none.txt",
        "sections": [
            {"index": 0, "name": "Verse 1", "note": "4 bars", "raw": "Verse 1",
             "line_indices": [0]},
            {"index": 1, "name": "Chorus", "note": "4 bars", "raw": "Chorus",
             "line_indices": [1]},
        ],
        "lines": [
            line(0, 0, "one two three four", 4.0, 8.0, ["one", "two", "three", "four"]),
            line(1, 1, "five six seven eight", 12.0, 16.0,
                 ["five", "six", "seven", "eight"]),
        ],
        "scorecard": {}, "meta": {},
    }))
    return root


@pytest.fixture(scope="session")
def workdir(tmp_path_factory) -> Path:
    return _write_workdir(tmp_path_factory.mktemp("song"))


@pytest.fixture(scope="session")
def track(workdir: Path) -> Track:
    return Track(workdir)


@pytest.fixture(scope="session")
def real_track() -> Track:
    if not (REAL / "project.json").exists():
        pytest.skip(f"no sample workdir at {REAL}")
    return Track(REAL)
