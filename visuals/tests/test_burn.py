"""The words burned into an mp4: as bright as lyrics.py says, where the layout puts them."""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest

from visuals.pieces.gravity import burn, lyrics
from visuals.pieces.gravity.lyrics import Line


def _spec(size: float = 0.1) -> dict:
    lines = lyrics.timed([Line([("light", 1.0, 1.4), ("breaks", 1.5, 2.2)])])
    return {"style": {"size": size, "unsung": 0.3, "peak": 0.9, "sung": 0.5},
            "regions": {k: {"x": x, "y": y, "align": a} for k, (x, y, a) in lyrics.REGIONS.items()},
            "lines": [{"in": [ln.in0, ln.in1], "out": [ln.out0, ln.out1], "place": {"static": "low"},
                       "words": [list(w) for w in ln.words]} for ln in lines]}


def test_how_bright_a_burned_word_is_is_lyrics_py_s_to_say(monkeypatch):
    """No second implementation: the burn-in asks lyrics.opacity and lyrics.ink, with the
    sheet's inks, and a word's light follows their product."""
    words = burn.Words(_spec(), "static", (320, 180))
    asked = {"ink": [], "opacity": 0}
    real_ink, real_opacity = lyrics.ink, lyrics.opacity

    def ink(t, start, end, **inks):
        asked["ink"].append((start, end, inks))
        return real_ink(t, start, end, **inks)

    def opacity(line, t):
        asked["opacity"] += 1
        return real_opacity(line, t)

    monkeypatch.setattr(lyrics, "ink", ink)
    monkeypatch.setattr(lyrics, "opacity", opacity)
    frame = np.zeros((180, 320, 3), np.uint8)
    assert words.draw(frame, 1.2)
    assert asked["opacity"] == 1 and [a[:2] for a in asked["ink"]] == [(1.0, 1.4), (1.5, 2.2)]
    assert all(a[2] == {"unsung": 0.3, "peak": 0.9, "sung": 0.5} for a in asked["ink"])

    # the same word, at moments of different ink: its light is in the ratio lyrics.py gives
    monkeypatch.setattr(lyrics, "ink", real_ink)
    monkeypatch.setattr(lyrics, "opacity", real_opacity)
    line, (first, _) = words.lines[0]
    lit, want = [], []
    for t in (1.0, 2.2):                           # on its peak, and settled while the line is still fully up
        frame = np.zeros((180, 320, 3), np.uint8)
        words.draw(frame, t)
        own = frame[first.y:first.y + first.glyph.shape[0], first.x:first.x + first.glyph.shape[1]].astype(float)
        lit.append(own[first.glyph > 0.3].sum())             # its own letters, not the next word's
        want.append(real_opacity(line, t) * real_ink(t, 1.0, 1.4, unsung=0.3, peak=0.9, sung=0.5))
    assert want[1] / want[0] == pytest.approx(0.5 / 0.9)
    assert lit[1] / lit[0] == pytest.approx(want[1] / want[0], rel=0.02)


def test_no_line_up_leaves_the_frame_as_it_was():
    words = burn.Words(_spec(), "static", (320, 180))
    frame = np.full((180, 320, 3), 40, np.uint8)
    assert not words.draw(frame, 0.2) and not words.draw(frame, 9.0)
    assert (frame == 40).all()


def _gl_or_skip():
    moderngl = pytest.importorskip("moderngl")
    try:
        moderngl.create_standalone_context(require=330).release()
    except Exception as exc:
        pytest.skip(f"no headless GL: {exc}")


@pytest.mark.local
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="no ffmpeg")
def test_a_clip_with_the_words_is_an_mp4_with_the_words_where_the_layout_put_them(tmp_path):
    from visuals.pieces.gravity import listen, make, render
    from visuals.pieces.gravity.track import Track

    tr = Track.resolve()
    if listen.load_cached(tr.cache) is None or lyrics.source(tr) is None:
        pytest.skip("no listening cache or no lyrics for the real track")
    _gl_or_skip()
    old = render.STYLE
    render.STYLE = "cosmos"
    try:
        got = make.listened(tr, verbose=False)
        ch = make.directed(tr, got)[0]
        start = 35.0                                        # the first line is up and being sung
        with_words = render.render(got, tr, tmp_path, start=start, duration=2.0, size=(320, 180), quiet=True, ch=ch)
        bare = render.render(got, tr, tmp_path, start=start, duration=2.0, size=(320, 180), quiet=True, ch=ch, words=False)
    finally:
        render.STYLE = old
    assert with_words.name == f"{tr.slug}-static-clip-35s.mp4" and bare.name == f"{tr.slug}-static-no-lyrics-clip-35s.mp4"
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(with_words)],
                                      capture_output=True, text=True, check=True).stdout)
    video = [s for s in probe["streams"] if s["codec_type"] == "video"][0]
    assert (video["codec_name"], video["width"], video["height"], video["r_frame_rate"]) == ("h264", 320, 180, "60/1")
    assert any(s["codec_type"] == "audio" for s in probe["streams"])
    assert float(probe["format"]["duration"]) == pytest.approx(2.0, abs=0.1)

    def frame(path, t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(180, 320, 3).astype(float)

    spec = lyrics.layout(tr, ch, ch.sheet.get("lyrics"))
    line = next(ln for ln in spec["lines"] if ln["in"][1] <= start + 1.0 <= ln["out"][0])
    text = " ".join(w for w, _, _ in line["words"])
    x0, y0, x1, y1 = lyrics.box(line["place"]["static"], text, spec["style"]["size"])
    cols = slice(int((0.5 + x0 * 9 / 16) * 320) - 2, int(np.ceil((0.5 + x1 * 9 / 16) * 320)) + 2)
    rows = slice(int((0.5 - y1) * 180) - 2, int(np.ceil((0.5 - y0) * 180)) + 2)
    lit = (frame(with_words, 1.0) - frame(bare, 1.0)).mean(axis=2)
    inside = np.zeros_like(lit, bool)
    inside[rows, cols] = True
    assert (lit[inside] > 40).sum() >= 20                  # the letters, where the line was placed
    assert (lit[~inside] > 40).sum() <= 2                  # and nowhere else
