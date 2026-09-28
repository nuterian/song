"""A loop of a few bars, made to run round without a seam (loop.py): for Spotify's Canvas."""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest

from visuals.pieces.gravity import direct, loop, shader_cosmos

RATE = direct.RATE


def test_a_loop_is_as_many_whole_bars_as_fit_in_eight_seconds():
    assert loop.lengths(1.92, 4) == (pytest.approx(7.68), 4.0)            # 125 BPM
    assert loop.lengths(2.0, 4) == (pytest.approx(8.0), 4.0)              # 120: eight seconds exactly
    assert loop.lengths(3.2, 4) == (pytest.approx(6.4), 2.0)              # 75
    assert loop.lengths(0.9, 3) == (pytest.approx(7.2), 8.0)
    seconds, bars = loop.lengths(10.0, 4)                                 # a bar longer than any loop: its beats
    assert seconds == pytest.approx(7.5) and bars == pytest.approx(0.75)
    for bar in np.linspace(0.4, 12.0, 60):
        seconds, _ = loop.lengths(float(bar), 4)
        assert loop.SHORTEST <= seconds <= loop.LONGEST + 1e-9


def _song(duration: float = 40.0, bar: float = 2.0, drops=(16.0,), busy=(20.0, 28.0)):
    """Channels as the solar system's are named, of a song with a kick on every beat, twice
    as many notes between `busy`, a re-entry at each of `drops`, and a camera that holds."""
    n = int(duration * RATE)
    t = np.arange(n) / RATE
    beat = bar / 4
    cols, kinds = {}, {}

    def hold(name_t, name_a, times, slots=None):
        T, A = direct.held_events(np.asarray(times), np.full(len(times), 0.8), n, slots or 1)
        for k in range(slots or 1):
            tag = "" if slots is None else str(k)
            cols[f"{name_t}{tag}"], cols[f"{name_a}{tag}"] = T[:, k], A[:, k]
            kinds[f"{name_t}{tag}"] = kinds[f"{name_a}{tag}"] = direct.HOLD

    kicks = np.arange(0.0, duration, beat)
    hold("uKickT", "uKickA", kicks)
    hold("uPromT", "uPromA", np.arange(0.0, duration, bar), shader_cosmos.N_PROM)
    hold("uWindT", "uWindA", np.array([5.0]), shader_cosmos.N_WIND)
    hold("uDropT", "uDropA", np.asarray(drops))
    cols["uOrbitSlow"], kinds["uOrbitSlow"] = t / 60.0, direct.LERP        # a clock
    cols["uKickE"], kinds["uKickE"] = np.exp(-((t % beat) / 0.12)), direct.LERP
    cols["uCamSpan.static"], kinds["uCamSpan.static"] = np.ones(n), direct.LERP
    cols["uCamTurn.static"], kinds["uCamTurn.static"] = 0.01 * t, direct.LERP
    names = list(cols)
    ch = direct.Channels(names, [kinds[k] for k in names], np.stack([cols[k] for k in names], axis=1).astype("f4"),
                         [{"t": float(d), "strength": 0.8} for d in drops], duration)
    notes = np.concatenate([np.arange(0.0, duration, beat), np.arange(busy[0], busy[1], beat / 4)])
    ch.planet_notes = [(np.sort(notes), np.full(len(notes), 0.6))] + [(np.array([]), np.array([]))] * 7
    got = {"meta": {"meter": 4, "period": beat, "duration": duration},
           "arrays": {"bar_t": np.arange(0.0, duration, bar)}}
    return ch, got


def test_the_bars_looped_are_where_the_most_is_played_and_no_re_entry_falls():
    ch, got = _song()
    w = loop.window(ch, got, "static")
    assert (w.start, w.length, w.bars, w.bar) == (20.0, pytest.approx(8.0), 4.0, 10) and w.played == pytest.approx(1.0)
    # the busiest bars have a re-entry in them: the loop is of the busiest that have none
    ch, got = _song(drops=(24.0,))
    w = loop.window(ch, got, "static")
    assert not (w.start - 1.0 < 24.0 < w.start + w.length + 0.5) and w.played < 1.0
    assert w.start in (12.0, 26.0)                        # beside them: before the re-entry, or after its flash


def test_the_camera_is_not_on_its_way_anywhere_in_a_loop():
    ch, got = _song()
    span = ch.index("uCamSpan.static")
    t = np.arange(len(ch.data)) / RATE
    ch.data[:, span] = np.where(t < 18.0, 1.0, np.minimum(1.0 + 0.1 * (t - 18.0), 2.0))      # it pulls back from 18 s to 28
    w = loop.window(ch, got, "static")
    assert w.start + w.length <= 18.0 or w.start >= 28.0


def test_a_loop_comes_back_to_where_it_began():
    ch, got = _song()
    w = loop.window(ch, got, "static")
    times, rows = loop.rows(ch, w, 60)
    n = loop.frames(w.length, 60)
    assert len(times) == len(rows) == n == 480
    assert times[-1] == pytest.approx(w.start + w.length) and times[0] == pytest.approx(w.start + w.length / n)
    before = ch.rows(np.array([w.start]))[0]
    names = list(ch.names)
    for name in ("uOrbitSlow", "uKickE", "uCamTurn.static", "uCamSpan.static"):       # the levels and the clocks
        assert rows[-1][names.index(name)] == pytest.approx(before[names.index(name)], abs=1e-6), name
    # a clock stands, to within what a frame would have moved it; a level that follows the beat is as it was
    clock = rows[:, names.index("uOrbitSlow")]
    assert np.ptp(clock) < 1e-4 and np.ptp(ch.rows(times)[:, names.index("uOrbitSlow")]) > 0.1
    assert np.allclose(rows[:, names.index("uKickE")], ch.rows(times)[:, names.index("uKickE")], atol=1e-3)

    # a hit: how long ago it was goes on across the join as it does from any frame to the next
    step = w.length / n
    for name in ("uKickT", "uPromT0", "uPromT3"):
        c = names.index(name)
        age = times - rows[:, c]
        assert (age >= -1e-6).all() and age.max() < w.length + 1e-6
        joined = np.concatenate([age, age[:1]])
        gone = np.diff(joined)
        assert np.all((np.abs(gone - step) < 1e-4) | (gone < 0)), name    # it grows by a frame, or a new hit has landed
    # and the first frames hold the loop's own last hit, a loop's length ago
    k = names.index("uPromT0")
    assert rows[0][k] == pytest.approx(rows[-1][k] - w.length)
    # what was thrown before the loop's bars, and not again in them, is not in the loop
    assert (rows[:, names.index("uWindT0")] == -1000.0).all() and (rows[:, names.index("uDropT")] == -1000.0).all()


def _real():
    from visuals.pieces.gravity import listen, make, render
    from visuals.pieces.gravity.track import Track

    tr = Track.resolve()
    if listen.load_cached(tr.cache) is None:
        pytest.skip("no listening cache for the real track")
    render.STYLE = "cosmos"
    got = make.listened(tr, verbose=False)
    return tr, got, make.directed(tr, got)[0]


@pytest.mark.local
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="no ffmpeg")
def test_on_the_gold_example_the_loop_is_an_mp4_spotify_takes_and_its_end_meets_its_beginning(tmp_path):
    from visuals.pieces.gravity import render

    tr, got, ch = _real()
    moderngl = pytest.importorskip("moderngl")
    try:
        moderngl.create_standalone_context(require=330).release()
    except Exception as exc:
        pytest.skip(f"no headless GL: {exc}")
    path, w = render.canvas(got, tr, tmp_path, camera="static", ch=ch, size=(270, 480), crf=10)
    assert path.name == f"{tr.slug}-static-canvas.mp4"
    assert w.bars == 4.0 and w.length == pytest.approx(7.68, abs=0.01) and loop.SHORTEST <= w.length <= loop.LONGEST
    drops = np.array([d["t"] for d in ch.drops])
    assert not ((drops > w.start - 1.0) & (drops < w.start + w.length + 0.5)).any()
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)],
                                      capture_output=True, text=True, check=True).stdout)
    assert [s["codec_type"] for s in probe["streams"]] == ["video"]                   # no sound
    video = probe["streams"][0]
    assert (video["codec_name"], video["width"], video["height"], video["r_frame_rate"]) == ("h264", 270, 480, "60/1")
    assert video["width"] * 16 == video["height"] * 9
    assert int(video["nb_read_frames"]) == 461 and loop.SHORTEST <= float(probe["format"]["duration"]) <= loop.LONGEST
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, 480, 270, 3).astype(np.int16)
    steps = np.array([np.abs(a - b).mean() for a, b in zip(frames[1:], frames[:-1])])
    join = np.abs(frames[0] - frames[-1]).mean()
    assert np.median(steps) > 0.3                                  # it moves
    assert join < 1.5 * np.median(steps), (join, np.median(steps))     # measured: 1.1 of a usual step
    # the song's own bars, end to beginning, do not meet: five times a usual step
    plain = ch.rows(w.start + np.array([w.length / 461, w.length]))
    r = render.Renderer(270, 480)
    try:
        r.bind(list(ch.names), ch.variants["camera"]["choices"]["static"], "tall")
        a, b = (np.ascontiguousarray(r.frame(float(t), row)).astype(np.int16) for t, row in zip(w.start + np.array([w.length / 461, w.length]), plain))
    finally:
        r.release()
    assert np.abs(a - b).mean() > 3 * join


@pytest.mark.local
def test_the_studio_exports_a_loop_when_asked(monkeypatch):
    from visuals.pieces.gravity import studio

    tr, _, _ = _real()
    session = studio.Session(tr)
    asked = {}

    def canvas(got, track, out, camera, ch, progress):
        asked.update(camera=camera)
        progress(461, 461)
        return out / "x.mp4", loop.Window(100.0, 7.68, 4.0, 52, 1.0)

    monkeypatch.setattr(studio.render, "canvas", canvas)
    monkeypatch.setattr(studio.render, "render", lambda *a, **k: pytest.fail("a loop is not the whole song"))
    monkeypatch.setattr(studio.render, "bake", lambda *a, **k: None)
    monkeypatch.setattr(loop, "window", lambda ch, got, camera: loop.Window(100.0, 7.68, 4.0, 52, 1.0))
    jobs = studio.Jobs()
    r = session.export("hybrid", True, jobs, "wide", True)
    assert r["ok"] and r["loop"] and r["shape"] == "tall" and r["lyrics"] is False
    assert r["path"].endswith(f"{tr.slug}-hybrid-canvas.mp4")
    jobs.queue.join()
    done = session.exporting.view()
    assert asked == {"camera": "hybrid"} and done["state"] == "done" and done["done"] == 461
    assert done["window"] == {"start": 100.0, "length": 7.68, "bars": 4.0, "bar": 52}
