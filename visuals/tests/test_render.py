"""The grammar compiles, and the renderer draws something that moves.

These need a GL context. On a machine without one they skip rather than fail, but
on this one they are the tests that matter most: the claim that a legal score
always compiles is only worth anything if something tries to compile it.
"""

from __future__ import annotations

import itertools
import shutil

import numpy as np
import pytest

from visuals import authoring, grammar, schema
from visuals.grammar import blocks
from visuals.listen import Track
from visuals.render import Renderer, render_frames, render_mp4
from visuals.uniforms import UniformTrack


@pytest.fixture(scope="module")
def renderer():
    moderngl = pytest.importorskip("moderngl")
    try:
        r = Renderer(160, 90)
    except Exception as exc:  # no display, no GL, no test
        pytest.skip(f"no standalone GL context here: {exc}")
    yield r
    r.release()


def _score(**kw) -> schema.Score:
    """A two-section, one-bar score whose second section carries `kw`."""
    song = dict(palette_family="dusk", palette_shift=5, block_set="orbital",
                motif="circle", motion_character="drift", symmetry="none", grain=4)
    section = dict(scene="wash", warp="breathe", post="soft", density=11,
                   energy=13, softness=16, palette_rotate=3,
                   transition_bars="2", transition_curve="ease")
    bar = {}
    for lane in schema.ROUTE_LANES:
        bar |= {f"route_source_{lane}": "none", f"route_target_{lane}": "none",
                f"route_gain_{lane}": 0, f"route_env_{lane}": "snap"}
    for k, v in kw.items():
        (song if k in song else section)[k] = v
    if "scene" in kw:
        song["block_set"] = next(b for b, s in schema.BLOCK_SET_SCENES.items()
                                 if kw["scene"] in s)
    # Keep the parts the case did not ask about legal, rather than testing an
    # illegal score by accident.
    if song["palette_family"] == "mono":
        section["palette_rotate"] = 0
    if song["motion_character"] == "still":
        if section["warp"] not in schema.STILL_WARPS:
            section["warp"] = "none"
        if section["post"] not in schema.STILL_POSTS:
            section["post"] = schema.STILL_POSTS[0]
    if song["motif"] not in schema.RADIAL_MOTIFS and song["symmetry"].startswith("kaleido"):
        song["symmetry"] = "mirror_x"
    score = schema.Score(schema.Shape(2, 1), song, [dict(section), section], [bar], seed=0)
    assert not score.violations(), score.violations()
    return score


def _axis_cases():
    """Every song-level axis, which is everything the one program depends on."""
    for f in schema.PALETTE_FAMILIES:
        yield f"palette:{f}", _score(palette_family=f)
    for m in schema.MOTIFS:
        for sym in schema.SYMMETRIES:
            yield f"motif:{m}/{sym}", _score(motif=m, symmetry=sym)
    for c in schema.MOTION_CHARACTERS:
        yield f"motion:{c}", _score(motion_character=c)
    for b in schema.BLOCK_SETS:
        yield f"block_set:{b}", _score(scene=schema.BLOCK_SET_SCENES[b][0])


def test_every_song_level_combination_compiles(renderer):
    """The grammar's promise: a legal score is a shader that builds."""
    failures = []
    n = 0
    for label, score in _axis_cases():
        n += 1
        try:
            renderer.program(score)
        except RuntimeError as exc:
            failures.append(f"{label}: {exc}")
    assert n >= len(schema.PALETTE_FAMILIES) + len(schema.MOTIFS) * len(schema.SYMMETRIES)
    assert not failures, "\n".join(failures[:5])


def test_a_song_has_exactly_one_program(renderer, track: Track):
    """No section-level choice can change the program, so nothing is ever swapped."""
    score = authoring.sampled(track, 0)
    renderer.program(score)
    before = renderer.n_programs
    keys = {grammar.program_key(score)}
    for i in range(score.shape.n_sections):
        for scene in schema.BLOCK_SET_SCENES[score.song["block_set"]]:
            score.sections[i]["scene"] = scene
            keys.add(grammar.program_key(score))
        renderer.program(score)
    assert keys == {grammar.program_key(score)}
    assert renderer.n_programs == before


def test_a_random_legal_score_compiles_and_draws(renderer, track: Track):
    for seed in range(6):
        score = authoring.sampled(track, seed)
        assert not score.violations()
        frame = renderer.frame(score, UniformTrack(score, track).at(4.0))
        assert frame.shape == (90, 160, 3)
        assert frame.dtype == np.uint8


def test_an_illegal_score_is_refused_before_it_reaches_the_compiler():
    """A scene the block set does not admit is a grammar error, not a GLSL one."""
    score = _score()
    score.sections[1]["scene"] = "bands"          # block_set is "orbital"
    assert score.violations()
    with pytest.raises(ValueError, match="not in block set"):
        grammar.fragment_source(score)


def test_a_masked_score_cannot_be_compiled():
    score = _score()
    del score.song["motif"]
    with pytest.raises(ValueError, match="masked"):
        grammar.fragment_source(score)


def test_the_two_headers_differ_only_in_the_version_line():
    score = _score()
    gl = grammar.fragment_source(score, grammar.GL_HEADER)
    web = grammar.fragment_source(score, grammar.WEBGL_HEADER)
    assert gl.startswith("#version 410 core\n")
    assert web.startswith("#version 300 es\n")
    assert gl.split("\n", 1)[1] == web.split("\n", 1)[1]


def test_every_loop_in_the_grammar_has_a_constant_bound():
    """Bounded per-frame cost, checked rather than asserted in a comment."""
    sources = [blocks.COMMON, blocks.POST, *blocks.LAYERS.values(),
               *blocks.WARPS.values(), *blocks.MOTIFS.values()]
    for src in sources:
        for line in src.splitlines():
            if "for (" in line:
                assert any(limit in line for limit in grammar.compose.LIMITS), line


def test_every_layer_and_warp_is_reached_by_the_one_shader():
    """Nothing is compiled out, so nothing can be switched in later."""
    src = grammar.fragment_source(_score())
    for name in schema.LAYERS:
        assert f"layer{name.capitalize()}(q)" in src, name
    for name in ("Swirl", "Ripple", "Stretch"):
        assert f"warp{name}(p)" in src, name


# --------------------------------------------------------------------------- #
# Frames
# --------------------------------------------------------------------------- #


def _capture(score, track, **kw):
    frames = []
    stats = render_frames(score, track, sink=frames.append, size=(160, 90), **kw)
    return frames, stats


def test_frames_are_neither_black_nor_blown_out(track: Track):
    pytest.importorskip("moderngl")
    score = authoring.handwritten(track)
    frames, stats = _capture(score, track, start=4.0, duration=2.0, fps=30)
    assert stats.frames == 60
    for i, f in enumerate(frames):
        assert f.mean() > 2.0, f"frame {i} is black"
        assert f.mean() < 235.0, f"frame {i} is blown out"
        assert f.max() > 40, f"frame {i} has nothing in it"


def test_frames_differ_over_time(track: Track):
    pytest.importorskip("moderngl")
    score = authoring.handwritten(track)
    frames, _ = _capture(score, track, start=4.0, duration=1.0, fps=30)
    a = np.stack([f.astype(np.int16) for f in frames])
    assert not np.array_equal(a[0], a[-1])
    # Consecutive frames move, but none of them jumps the whole way - a picture
    # that changed completely every frame would be a flicker, not a visual.
    step = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2, 3))
    assert step.min() > 0.02, "a frame did not change at all"
    assert step.max() < 60.0, "a frame changed almost completely"


def _beat_ratio(score, track: Track, start: float, duration: float, fps: int = 60) -> float:
    """How much more the picture moves on the beat than off it.

    One when the picture is ignoring the beat; more than one when it is not. The
    window is 100 ms, which is about how long after a beat a viewer still reads a
    change as being *on* it.
    """
    frames, _ = _capture(score, track, start=start, duration=duration, fps=fps)
    a = np.stack([f.astype(np.float32).mean(axis=2) for f in frames])
    motion = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2))
    times = start + (np.arange(1, len(a)) + 1) / fps
    on = np.zeros(len(times), dtype=bool)
    for b in track.beats[(track.beats > start) & (track.beats < start + duration)]:
        on |= (times >= b) & (times < b + 0.10)
    if not on.any() or on.all():
        pytest.skip("no beats in this window")
    return float(motion[on].mean() / max(motion[~on].mean(), 1e-9))


def test_the_picture_moves_on_the_beat(real_track: Track):
    """Synchronisation, measured rather than asserted.

    The hand-written score puts the beat on the scale through the choruses, so the
    picture should visibly move more on the beat than off it there - and a score
    that routes nothing should show no such preference at all, which is the
    control that makes the number mean something.
    """
    pytest.importorskip("moderngl")
    score = authoring.handwritten(real_track)
    chorus = next(s for s in real_track.sections
                  if "chorus" in s.name.lower() and "pre" not in s.name.lower())
    start = chorus.start + 4.0
    assert _beat_ratio(score, real_track, start, 12.0) > 1.8
    assert _beat_ratio(_unrouted(real_track), real_track, start, 12.0) < 1.2


def test_the_song_is_not_equally_locked_everywhere(real_track: Track):
    """A chorus should hold the beat harder than an intro. That is the point of
    putting the routing in the score rather than in the shader."""
    pytest.importorskip("moderngl")
    score = authoring.handwritten(real_track)
    chorus = next(s for s in real_track.sections
                  if "chorus" in s.name.lower() and "pre" not in s.name.lower())
    assert _beat_ratio(score, real_track, chorus.start + 4.0, 12.0) > \
        _beat_ratio(score, real_track, 12.0, 12.0) * 1.5


def test_the_same_score_renders_the_same_frames_twice(track: Track):
    pytest.importorskip("moderngl")
    score = authoring.sampled(track, 3)
    a, _ = _capture(score, track, start=6.0, duration=0.5, fps=30)
    b, _ = _capture(score, track, start=6.0, duration=0.5, fps=30)
    assert [f.tobytes() for f in a] == [f.tobytes() for f in b]


def _unrouted(track: Track) -> schema.Score:
    """The hand-written score with every bar silent.

    Routing is the other thing that moves a frame, and on a synthetic track whose
    beats land exactly on the section boundary it moves it hardest right there. To
    measure whether the *score* cuts, the music has to be taken out of the frame.
    """
    score = authoring.handwritten(track)
    for bar in score.bars:
        for lane in schema.ROUTE_LANES:
            bar[f"route_source_{lane}"] = "none"
            bar[f"route_target_{lane}"] = "none"
            bar[f"route_gain_{lane}"] = 0
            bar[f"route_env_{lane}"] = schema.ROUTE_ENVS[0]
    assert not score.violations()
    return score


def test_a_section_boundary_does_not_show(track: Track):
    """The claim the whole transition design makes, measured on real frames.

    With nothing routed, the only thing that can move the picture is the section
    ramp. If the score cut, the boundary frame would be far and away the largest
    step in the run. It is not: it is an ordinary frame.
    """
    pytest.importorskip("moderngl")
    score = _unrouted(track)
    fps = 30
    for si in range(1, len(track.sections)):
        boundary = track.sections[si].start
        frames, _ = _capture(score, track, start=boundary - 3.0, duration=6.0, fps=fps)
        a = np.stack([f.astype(np.int16) for f in frames])
        step = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2, 3))
        times = boundary - 3.0 + (np.arange(1, len(a)) + 1) / fps
        # Drop the first second: a render starts with an empty feedback buffer,
        # and the frames while it fills are a preview's one real discontinuity.
        keep = times > boundary - 2.0
        step, times = step[keep], times[keep]
        at = int(np.argmin(np.abs(times - boundary)))
        median = float(np.median(step))
        assert step[at] < median * 3.0 + 0.5, (
            f"section {si}: the boundary frame changed {step[at] / max(median, 1e-6):.1f}x "
            f"the median step; that is a cut"
        )


def test_nothing_in_a_whole_song_looks_like_a_cut(real_track: Track):
    """The same claim, over every frame of the real track rather than four of them.

    What distinguishes a morph from a cut is not how fast the picture changes - a
    two-bar arrival into a chorus changes it quickly, and should - it is whether
    the change is spread over frames or concentrated in one. So this finds the
    largest step in the song and asks what its neighbours were doing. In a ramp
    they were doing nearly the same thing; in a cut they were doing nothing.
    """
    pytest.importorskip("moderngl")
    score = _unrouted(real_track)
    fps = 12
    frames, _ = _capture(score, real_track, start=1.0,
                         duration=real_track.duration - 2.0, fps=fps)
    a = np.stack([f.astype(np.int16) for f in frames])
    step = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2, 3))
    times = 1.0 + (np.arange(1, len(a)) + 1) / fps

    i = int(np.argmax(step))
    around = step[max(0, i - 3):i + 4]
    assert around.mean() > step[i] * 0.6, (
        f"the largest step in the song, {step[i]:.1f} at {times[i]:.1f}s, stands alone "
        f"(neighbours average {around.mean():.1f}); that is a cut"
    )
    # And no step is anywhere near what replacing the picture outright would cost.
    cut_size = float(np.abs(a[0].astype(int) - a[len(a) // 2].astype(int)).mean())
    assert step.max() < cut_size * 0.6, f"a {step.max():.1f} step against a {cut_size:.1f} cut"


def test_different_seeds_look_different(track: Track):
    pytest.importorskip("moderngl")
    a, _ = _capture(authoring.sampled(track, 1), track, start=6.0, duration=0.2, fps=30)
    b, _ = _capture(authoring.sampled(track, 2), track, start=6.0, duration=0.2, fps=30)
    assert np.abs(a[-1].astype(np.int16) - b[-1].astype(np.int16)).mean() > 1.0


def test_a_preview_starts_where_it_was_asked_to(track: Track):
    pytest.importorskip("moderngl")
    score = authoring.handwritten(track)
    early, _ = _capture(score, track, start=0.0, duration=0.2, fps=30)
    late, _ = _capture(score, track, start=14.0, duration=0.2, fps=30)
    assert not np.array_equal(early[-1], late[-1])


def test_an_mp4_comes_out_with_the_audio_under_it(track: Track, tmp_path):
    pytest.importorskip("moderngl")
    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg")
    out = tmp_path / "preview.mp4"
    stats = render_mp4(authoring.handwritten(track), track, out,
                       start=4.0, duration=1.0, fps=30, size=(160, 90))
    assert stats.frames == 30
    assert out.exists() and out.stat().st_size > 2000
