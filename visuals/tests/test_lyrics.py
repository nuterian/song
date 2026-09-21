"""Lyrics in the picture: when each line is up, how bright each word is, where it goes."""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest

from visuals.pieces.gravity import lyrics
from visuals.pieces.gravity.lyrics import Line

PLAYER_LYRICS = lyrics.ROOT / "visuals" / "player" / "lyrics.js"


def _lines():
    # three lines: the first two back to back (0.05 s between), the third after a rest
    return lyrics.timed([Line([("one", 1.0, 1.4), ("two", 1.5, 2.2)]),
                         Line([("three", 2.25, 2.6), ("four", 2.7, 3.4)]),
                         Line([("five", 8.0, 8.5), ("six", 8.6, 9.0)])])


def test_a_word_peaks_as_it_is_sung_and_settles_brighter_than_it_began():
    s, e = 5.0, 5.6
    assert lyrics.ink(s - lyrics.LEAD - 0.01, s, e) == lyrics.UNSUNG
    assert lyrics.ink(s, s, e) == lyrics.PEAK
    ts = np.linspace(s - 0.3, e + 0.5, 2000)
    assert ts[int(np.argmax([lyrics.ink(t, s, e) for t in ts]))] == pytest.approx(s, abs=0.001)
    assert lyrics.ink(e + 0.1, s, e) == lyrics.SUNG > lyrics.UNSUNG


def test_lines_never_cut_and_are_up_for_all_their_words():
    lines = _lines()
    for ln in lines:
        assert ln.in1 <= ln.first + 2 * lyrics.DISSOLVE          # in, or nearly, by its first word
        assert ln.out0 >= ln.last - lyrics.DISSOLVE              # not fading before its last
        assert ln.out1 - ln.out0 >= 2 * lyrics.DISSOLVE - 1e-9 and ln.in1 - ln.in0 >= 2 * lyrics.DISSOLVE - 1e-9
    a, b, c = lines
    assert b.in0 <= a.out1 and a.out1 - a.out0 == pytest.approx(2 * lyrics.DISSOLVE)   # back to back: a dissolve
    assert c.in0 == pytest.approx(c.first - lyrics.INTRO) and b.out1 == pytest.approx(b.last + lyrics.OUTRO + lyrics.FADE_OUT)
    ts = np.linspace(0, 10, 20001)
    for ln in lines:                                          # and nothing steps
        op = np.array([lyrics.opacity(ln, t) for t in ts])
        assert np.abs(np.diff(op)).max() < 0.01


@pytest.mark.skipif(shutil.which("node") is None, reason="no node to run the player's copy")
def test_the_players_copy_is_the_same_curve(tmp_path):
    lines = _lines()
    ts = np.linspace(0, 10, 1500)
    style = {"lead": lyrics.LEAD, "unsung": lyrics.UNSUNG, "peak": lyrics.PEAK, "sung": lyrics.SUNG}
    ref = {"style": style, "t": ts.tolist(),
           "lines": [{"in": [l.in0, l.in1], "out": [l.out0, l.out1], "words": l.words} for l in lines],
           "opacity": [[lyrics.opacity(l, t) for t in ts] for l in lines],
           "ink": [[[lyrics.ink(t, s, e) for t in ts] for _, s, e in l.words] for l in lines]}
    (tmp_path / "ref.json").write_text(json.dumps(ref))
    script = f"""
import {{ lyricInk, lyricOpacity }} from {json.dumps(PLAYER_LYRICS.as_uri())};
import {{ readFileSync }} from "node:fs";
const ref = JSON.parse(readFileSync({json.dumps(str(tmp_path / "ref.json"))}, "utf8"));
let d = 0;
ref.lines.forEach((line, i) => ref.t.forEach((t, k) => {{
  d = Math.max(d, Math.abs(lyricOpacity(t, line) - ref.opacity[i][k]));
  line.words.forEach(([, s, e], j) => {{ d = Math.max(d, Math.abs(lyricInk(t, s, e, ref.style) - ref.ink[i][j][k])); }});
}}));
console.log(d);
"""
    (tmp_path / "check.mjs").write_text(script)
    got = subprocess.run(["node", str(tmp_path / "check.mjs")], capture_output=True, text=True, check=True)
    assert float(got.stdout.strip()) < 1e-12


def test_on_the_gold_example_no_line_crosses_a_body_on_the_static_camera():
    from visuals.pieces.gravity import cosmos, listen, models
    from visuals.pieces.gravity.track import Track

    tr = Track.resolve()
    got = listen.load_cached(tr.cache)
    src = lyrics.source(tr)
    if got is None or src is None:
        pytest.skip("no listening cache or no lyrics for the real track")
    ch = cosmos.bake(got, models.load_cached(tr.cache))
    lines = lyrics.read(src)
    assert len(lines) >= 30
    cost = lyrics.place(lines, ch, "static")
    assert cost["crossed"] == 0.0
    for ln in lines:                                           # and each fits across the frame where it went
        x0, _, x1, _ = lyrics.box(ln.place["static"], ln.text)
        assert x0 >= -lyrics.ASPECT / 2 and x1 <= lyrics.ASPECT / 2


@pytest.mark.skipif(shutil.which("node") is None, reason="no node to run the player's copy")
def test_a_line_stays_where_it_appeared_even_if_the_camera_changes(tmp_path):
    """Jugal, watching the cinematic camera: the lyrics moved from one corner to another while
    shown. A line is set where it belongs the moment it appears and held there until it has
    gone; the next line takes the camera's place then."""
    script = f"""
import {{ seating }} from {json.dumps(PLAYER_LYRICS.as_uri())};
const lines = [
  {{ in: [1.0, 1.35], out: [3.0, 3.4], place: {{ static: "low", cinematic: "top-left" }} }},
  {{ in: [3.2, 3.6], out: [5.0, 5.4], place: {{ static: "high", cinematic: "side-right" }} }},
];
const seat = seating();
const seen = [[], []];
for (let t = 0; t < 6; t += 1 / 60) {{
  const cam = t < 2.0 ? "cinematic" : "static";       // switched in the middle of the first line
  lines.forEach((line, k) => {{ const r = seat(k, line, t, cam); if (r !== null) seen[k].push(r); }});
}}
console.log(JSON.stringify(seen.map(s => [...new Set(s)])));
"""
    (tmp_path / "seat.mjs").write_text(script)
    got = json.loads(subprocess.run(["node", str(tmp_path / "seat.mjs")], capture_output=True, text=True, check=True).stdout)
    assert got == [["top-left"], ["high"]]


def test_nothing_animates_a_lyric_into_place():
    css = (lyrics.ROOT / "visuals" / "player" / "index.html").read_text()
    rule = css[css.index("#lyrics .line {"):]
    rule = rule[: rule.index("}")]
    assert "transition" not in rule and "animation" not in rule
