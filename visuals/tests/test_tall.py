"""The tall frame, 9:16: the wide picture with the camera turned, and the words set for it."""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest

from visuals.pieces.gravity import burn, cosmos, lyrics
from visuals.pieces.gravity.lyrics import Line


def _in_frame(q, roll, span, cx, cy):
    """follow.geometry's `to_frame`: where a point of the scene is in the frame, in its heights."""
    cr, sr = np.cos(roll), np.sin(roll)
    return ((cr * q[0] + sr * q[1]) - cx) / span, ((-sr * q[0] + cr * q[1]) - cy) / span


def test_the_tall_camera_shows_the_wide_frame_turned_a_quarter_turn():
    rng = np.random.default_rng(5)
    for _ in range(50):
        roll, span = rng.uniform(-3, 3), rng.uniform(0.2, 3.0)
        cx, cy = rng.uniform(-1, 1, 2)
        q = rng.uniform(-2, 2, 2)
        xw, yw = _in_frame(q, roll, span, cx, cy)
        xt, yt = _in_frame(q, *cosmos.turned(roll, span, cx, cy))
        # what was across the wide frame is up the tall one, and the wide frame's width is its height
        assert xt == pytest.approx(yw * 9 / 16) and yt == pytest.approx(-xw * 9 / 16)
    # so the wide frame's corners are the tall frame's
    assert _in_frame((0.0, 0.0), 0.0, 1.0, -8 / 9, 0.5) == pytest.approx((8 / 9, -0.5))
    assert _in_frame((0.0, 0.0), *cosmos.turned(0.0, 1.0, -8 / 9, 0.5)) == pytest.approx((-0.5 * 9 / 16, -0.5))


def test_a_line_is_in_as_few_rows_as_hold_it_and_they_are_of_a_length():
    room = lyrics.TALL.width
    size = lyrics.SIZE * lyrics.TALL.scale
    assert lyrics.wrapped("Hold on tight".split(), size, room) == [3]
    words = "Light breaks through the skyline haze,".split()
    assert lyrics.wrapped(words, size, room) == [3, 3]
    long = "and every single one of them is turning round the sun again tonight with you".split()
    rows = lyrics.wrapped(long, size, room)
    assert sum(rows) == len(long) and len(rows) == 3
    at = np.cumsum([0, *rows])
    widths = [len(" ".join(long[a:b])) * lyrics.CHAR_MAX * size for a, b in zip(at[:-1], at[1:])]
    assert max(widths) <= room and max(widths) - min(widths) < 0.12 * room
    assert lyrics.wrapped(["incomprehensibilities-of-the-heart-and-mind"], size, room) == [1]   # a word is not broken


def test_the_tall_frames_places_are_clear_of_what_the_apps_cover():
    x0, y0, x1, y1 = lyrics.TALL.inside
    assert y0 == pytest.approx(-0.5 + 0.20) and y1 == pytest.approx(0.5 - 0.12)
    assert x1 == pytest.approx((0.5 - 0.13) * 9 / 16) and x0 == -x1
    size = lyrics.SIZE * lyrics.TALL.scale
    assert size * 1920 == pytest.approx(42.24)
    hold_two = 0
    for name, (x, y, align) in lyrics.TALL_REGIONS.items():
        b = lyrics.box(name, "a row of words as long as any", size, lyrics.TALL)
        assert (x, align) == (0.0, "center") and b[1] >= y0 and b[3] <= y1, name
        two = lyrics.box(name, "two rows of words as long as any", size, lyrics.TALL, [4, 4])
        hold_two += two[1] >= y0 and two[3] <= y1
    assert hold_two == 20                                  # the lowest has room for one row only
    assert len(lyrics.TALL_REGIONS) == 21 and len({y for _, y, _ in lyrics.TALL_REGIONS.values()}) == 21


def _spec(rows: list[int]) -> dict:
    words = [("light", 1.0, 1.3), ("breaks", 1.3, 1.6), ("through", 1.6, 1.9), ("the", 1.9, 2.0), ("haze", 2.0, 2.4)]
    lines = lyrics.timed([Line(words)])
    return {"style": {"size": 0.06, "unsung": 0.3, "peak": 0.9, "sung": 0.5},
            "regions": {k: {"x": x, "y": y, "align": a} for k, (x, y, a) in lyrics.REGIONS.items()},
            "tall": {"size": 0.04, "regions": {"here": {"x": 0.0, "y": 0.2, "align": "center"}}},
            "lines": [{"in": [ln.in0, ln.in1], "out": [ln.out0, ln.out1], "place": {"static": "low"},
                       "tall": {"place": {"static": "here"}, "rows": rows},
                       "words": [list(w) for w in ln.words]} for ln in lines]}


def test_the_words_are_burned_into_a_tall_frame_in_their_rows():
    w, h = 270, 480
    one = burn.Words(_spec([5]), "static", (w, h), "tall")
    two = burn.Words(_spec([3, 2]), "static", (w, h), "tall")
    px = 0.04 * h
    for words, rows in ((one, 1), (two, 2)):
        frame = np.zeros((h, w, 3), np.uint8)
        assert words.draw(frame, 1.5)
        lit = frame.max(axis=2) > 60
        ys, xs = np.nonzero(lit)
        # about the region's height (0.2 above the middle), and about the middle of the width
        assert abs(0.5 * (ys.min() + ys.max()) - h * (0.5 - 0.2)) < 0.35 * px
        assert abs(0.5 * (xs.min() + xs.max()) - w / 2) < 0.6 * px
        assert ys.max() - ys.min() == pytest.approx((rows - 1) * burn.LINE_HEIGHT * px + px, abs=0.45 * px)
    a, b = (np.array([wd.x for wd in words.lines[0][1]]) for words in (one, two))
    foot = [wd.y + wd.glyph.shape[0] for wd in two.lines[0][1]]          # a word's patch ends under its letters: its row's
    assert np.ptp(foot[:3]) <= 0.3 * px and np.ptp(foot[3:]) <= 0.3 * px  # foot, or the tail of a g under it
    assert np.mean(foot[3:]) - np.mean(foot[:3]) == pytest.approx(burn.LINE_HEIGHT * px, abs=0.3 * px)
    assert (np.diff(a) > 0).all() and b[3] < b[2]              # the fourth word begins the second row


def test_a_wide_frame_is_burned_as_it_was():
    spec = _spec([3, 2])
    wide = burn.Words(spec, "static", (320, 180))
    assert np.ptp([wd.y + wd.glyph.shape[0] for wd in wide.lines[0][1]]) <= 0.3 * 0.06 * 180   # one row, whatever the tall frame has
    frame = np.zeros((180, 320, 3), np.uint8)
    assert wide.draw(frame, 1.5)
    ys = np.nonzero(frame.max(axis=2) > 60)[0]
    assert abs(0.5 * (ys.min() + ys.max()) - 180 * (0.5 + 0.36)) < 4


def _real():
    from visuals.pieces.gravity import listen, make, render
    from visuals.pieces.gravity.track import Track

    tr = Track.resolve()
    if listen.load_cached(tr.cache) is None or lyrics.source(tr) is None:
        pytest.skip("no listening cache or no lyrics for the real track")
    render.STYLE = "cosmos"
    got = make.listened(tr, verbose=False)
    return tr, got, make.directed(tr, got)[0]


def _gl_or_skip():
    moderngl = pytest.importorskip("moderngl")
    try:
        moderngl.create_standalone_context(require=330).release()
    except Exception as exc:
        pytest.skip(f"no headless GL: {exc}")


@pytest.mark.local
def test_on_the_gold_example_the_tall_frames_bodies_are_the_wide_frames_turned():
    from visuals.pieces.gravity import follow

    _, _, ch = _real()
    rows = np.arange(120 * 30, 120 * 270, 977)
    for camera in cosmos.MODES:
        wide, tall = follow.geometry(ch, rows, camera), follow.geometry(ch, rows, camera, "tall")
        for body in ("sun", "planet"):
            assert np.allclose(tall[f"{body}_x"], wide[f"{body}_y"] * 9 / 16, atol=1e-6)
            assert np.allclose(tall[f"{body}_y"], -wide[f"{body}_x"] * 9 / 16, atol=1e-6)
            assert np.allclose(tall[f"{body}_r"], wide[f"{body}_r"] * 9 / 16, atol=1e-6)


@pytest.mark.local
def test_on_the_gold_example_the_tall_picture_is_the_wide_picture_turned():
    """Drawn, not reckoned: the Sun and the planets are where the wide frame has them, a
    quarter turn round, and as large. (The sky is not the same to the pixel: its stars are
    sized in pixels.)"""
    from scipy import ndimage

    from visuals.pieces.gravity import render

    _, _, ch = _real()
    _gl_or_skip()
    names = list(ch.names)
    shots = [("static", 100.0), ("cinematic", 60.0), ("cinematic", 235.0)]

    def frames(size, shape):
        r = render.Renderer(*size)
        try:
            out = []
            for camera, t in shots:
                r.bind(names, ch.variants["camera"]["choices"][camera], shape)
                times = t - (59 - np.arange(60)) / 60.0
                for t_, row in zip(times, ch.rows(times)):
                    img = r.frame(float(t_), row)
                out.append(np.ascontiguousarray(img).astype(int))
            return out
        finally:
            r.release()

    tall, wide = frames((270, 480), "tall"), frames((480, 270), "wide")
    for (camera, t), a, b in zip(shots, tall, wide):
        turned = np.rot90(b, 3)
        assert turned.shape == a.shape
        off = np.abs(turned - a).max(axis=2) > 24
        bright = turned.max(axis=2) > 90
        bodies = ndimage.binary_dilation(ndimage.uniform_filter(bright.astype(float), 13) > 0.5, iterations=3)
        assert bodies.mean() > 0.01, (camera, t)
        other = (np.abs(np.rot90(b, 1) - a).max(axis=2) > 24)[bodies].mean()
        print(camera, t, round(float(off[bodies].mean()), 4), round(float(off.mean()), 4), round(float(other), 4))
        # measured: none of the bodies' pixels off, 1 % of the sky's. Turned the other way, a
        # fifth of the bodies' or more
        assert off[bodies].mean() < 0.01 and off.mean() < 0.03, (camera, t, off[bodies].mean(), off.mean())
        assert other > 0.15, (camera, t, other)


@pytest.mark.local
def test_on_the_gold_example_the_tall_lines_keep_inside_and_clear_of_one_another():
    tr, _, ch = _real()
    lines = lyrics.read(lyrics.source(tr))
    size = lyrics.SIZE * lyrics.TALL.scale
    x0, y0, x1, y1 = lyrics.TALL.inside
    for camera in cosmos.MODES:
        cost = lyrics.place(lines, ch, camera, frame=lyrics.TALL)
        assert cost["shape"] == "tall" and cost["crossed"] <= 0.07, cost       # measured: 0.029, 0.028, 0.058
        boxes = []
        for ln in lines:
            assert sum(ln.rows) == len(ln.words) and 1 <= len(ln.rows) <= 2
            words = [w for w, _, _ in ln.words]
            at = np.cumsum([0, *ln.rows])
            assert max(len(" ".join(words[a:b])) for a, b in zip(at[:-1], at[1:])) * lyrics.CHAR_MAX * size <= lyrics.TALL.width
            b = lyrics.box(ln.tall[camera], ln.text, size, lyrics.TALL, ln.rows)
            assert b[1] >= y0 and b[3] <= y1
            boxes.append(b)
        for (ln, a), (nxt, b) in zip(zip(lines, boxes), zip(lines[1:], boxes[1:])):
            if ln.out1 > nxt.in0 and ln.tall[camera] != nxt.tall[camera]:    # they dissolve into each other
                assert not lyrics._touch(a, b, 0.5 * size), (camera, ln.text, nxt.text)
    assert all(set(ln.place) == set(cosmos.MODES) or not ln.place for ln in lines)


@pytest.mark.local
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="no ffmpeg")
def test_a_tall_clip_is_an_mp4_nine_by_sixteen_with_the_words_where_the_layout_put_them(tmp_path):
    from visuals.pieces.gravity import render

    tr, got, ch = _real()
    _gl_or_skip()
    start = 35.0
    kw = dict(start=start, duration=2.0, size=(320, 180), quiet=True, ch=ch, shape="tall")
    with_words = render.render(got, tr, tmp_path, **kw)
    bare = render.render(got, tr, tmp_path, words=False, **kw)
    assert with_words.name == f"{tr.slug}-static-tall-clip-35s.mp4" and bare.name == f"{tr.slug}-static-tall-no-lyrics-clip-35s.mp4"
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(with_words)],
                                      capture_output=True, text=True, check=True).stdout)
    video = [s for s in probe["streams"] if s["codec_type"] == "video"][0]
    assert (video["codec_name"], video["width"], video["height"], video["r_frame_rate"]) == ("h264", 180, 320, "60/1")
    assert any(s["codec_type"] == "audio" for s in probe["streams"])

    def frame(path, t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(320, 180, 3).astype(float)

    spec = lyrics.layout(tr, ch, ch.sheet.get("lyrics"))
    line = next(ln for ln in spec["lines"] if ln["in"][1] <= start + 1.0 <= ln["out"][0])
    text = " ".join(w for w, _, _ in line["words"])
    x0, y0, x1, y1 = lyrics.box(line["tall"]["place"]["static"], text, spec["tall"]["size"], lyrics.TALL, line["tall"]["rows"])
    grow = (lyrics.CHAR_MAX / lyrics.CHAR_W - 1) * (x1 - x0) / 2             # the box is a guess at the letters' width
    cols = slice(int(90 + (x0 - grow) * 320) - 2, int(np.ceil(90 + (x1 + grow) * 320)) + 2)
    rows = slice(int((0.5 - y1) * 320) - 2, int(np.ceil((0.5 - y0) * 320)) + 2)
    lit = (frame(with_words, 1.0) - frame(bare, 1.0)).mean(axis=2)
    inside = np.zeros_like(lit, bool)
    inside[rows, cols] = True
    assert (lit[inside] > 40).sum() >= 12                  # the letters, where the line was placed
    assert (lit[~inside] > 40).sum() <= 2                  # and nowhere else


@pytest.mark.local
def test_the_studio_exports_the_frame_asked_for(monkeypatch, tmp_path):
    from visuals.pieces.gravity import render, studio

    tr, _, _ = _real()
    assert render.mp4_name(tr, "hybrid", True, shape="tall") == f"{tr.slug}-hybrid-tall.mp4"
    assert render.mp4_name(tr, "hybrid", False, shape="tall") == f"{tr.slug}-hybrid-tall-no-lyrics.mp4"
    assert render.mp4_name(tr, "hybrid", True) == f"{tr.slug}-hybrid.mp4"
    session = studio.Session(tr)
    asked = {}
    monkeypatch.setattr(studio.render, "render", lambda *a, **k: asked.update(k) or k["progress"](3, 3))
    monkeypatch.setattr(studio.render, "bake", lambda *a, **k: None)
    refused = session.export("static", True, shape="square")
    assert not refused["ok"] and "no shape 'square'" in refused["refused"][0] and session.exporting is None
    jobs = studio.Jobs()
    r = session.export("cinematic", True, jobs, "tall")
    assert r["ok"] and r["shape"] == "tall" and r["path"].endswith(f"{tr.slug}-cinematic-tall.mp4")
    jobs.queue.join()
    assert asked["shape"] == "tall" and asked["camera"] == "cinematic" and session.exporting.finished
