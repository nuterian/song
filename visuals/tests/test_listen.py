"""Reading a workdir, and the uniform timeline that comes out of it.

The synthetic track has its beats at exact half-seconds and its bars at exact
even seconds, so every assertion here is arithmetic rather than a tolerance
chosen to make the test pass.
"""

from __future__ import annotations

import numpy as np
import pytest

from visuals import schema
from visuals.listen import RATE, Track
from visuals.uniforms import GAIN_MAX, UNIFORM_NAMES, UniformTrack

from .conftest import BAR, BEAT, DURATION


def test_workdir_is_never_written_to(track: Track, workdir):
    before = {p.name: p.stat().st_mtime_ns for p in workdir.iterdir()}
    track.timeline()
    UniformTrack(_simple_score(track), track)
    after = {p.name: p.stat().st_mtime_ns for p in workdir.iterdir()}
    assert before == after
    assert set(before) == {"project.json", "analysis.json", "beats.json"}


def test_a_workdir_without_the_files_says_so(tmp_path):
    with pytest.raises(FileNotFoundError, match="project.json"):
        Track(tmp_path)


def test_beat_phase_resets_on_every_beat(track: Track):
    tl = track.timeline()
    for i in range(1, 40):
        t = i * BEAT
        assert tl.at(t)["beat_phase"] == pytest.approx(0.0, abs=1e-6)
        # A hair before the next beat it has all but arrived.
        assert tl.at(t - 1 / RATE)["beat_phase"] == pytest.approx(1 - 1 / (RATE * BEAT), abs=1e-3)
        assert tl.at(t + BEAT / 2)["beat_phase"] == pytest.approx(0.5, abs=1e-3)


def test_bar_phase_resets_on_every_downbeat(track: Track):
    tl = track.timeline()
    for i in range(1, 10):
        assert tl.at(i * BAR)["bar_phase"] == pytest.approx(0.0, abs=1e-6)
        assert tl.at(i * BAR + BAR / 4)["bar_phase"] == pytest.approx(0.25, abs=1e-3)


def test_impulses_land_on_their_own_instants(track: Track):
    tl = track.timeline()
    for name, times in (("beat", track.beats), ("bar", track.downbeats),
                        ("onset", track.onsets)):
        col = tl.column(name)
        assert col.sum() == pytest.approx(len(np.unique(np.round(times * RATE))), abs=1)
        for t in times[:6]:
            assert col[int(round(float(t) * RATE))] == 1.0


def test_sections_tile_the_song_and_land_on_downbeats(track: Track):
    assert track.sections[0].start == 0.0
    assert track.sections[-1].end == pytest.approx(DURATION)
    for a, b in zip(track.sections, track.sections[1:]):
        assert a.end == b.start
        assert float(b.start) in {round(float(x), 6) for x in track.downbeats}


def test_bars_tile_the_song_one_per_downbeat(track: Track):
    spans = track.bar_spans()
    assert len(spans) == track.n_bars == len(track.downbeats)
    assert spans[0, 0] == 0.0                      # the count-in belongs to bar 0
    assert spans[-1, 1] == pytest.approx(DURATION)
    assert np.all(np.diff(spans[:, 0]) > 0)
    assert np.allclose(spans[:-1, 1], spans[1:, 0])


def test_word_progress_runs_nought_to_one_across_each_word(track: Track):
    tl = track.timeline()
    word = track.lines[0].words[1]
    assert tl.at(word.start)["word"] == pytest.approx(0.0, abs=0.05)
    assert tl.at((word.start + word.end) / 2)["word"] == pytest.approx(0.5, abs=0.05)
    assert tl.at(word.end - 1 / RATE)["word"] == pytest.approx(1.0, abs=0.05)
    assert tl.at(1.0)["line"] == -1.0               # nothing sung yet
    assert tl.at(word.start)["line"] == 0.0


def _simple_score(track: Track, **bar_a) -> schema.Score:
    """A legal score whose only routing is lane a of every bar."""
    shape = schema.Shape(len(track.sections), track.n_bars)
    lane = dict(route_source_a="none", route_target_a="none",
                route_gain_a=0, route_env_a="snap")
    lane.update(bar_a)
    silent = {}
    for other in schema.ROUTE_LANES[1:]:
        silent |= {f"route_source_{other}": "none", f"route_target_{other}": "none",
                   f"route_gain_{other}": 0, f"route_env_{other}": "snap"}
    return schema.Score(
        shape,
        song=dict(palette_family="ice", palette_shift=0, block_set="orbital",
                  motif="circle", motion_character="drift", symmetry="none", grain=0),
        # The same destination for every section, so nothing ramps except out of
        # the silence the song opens from, and a test can read one number.
        sections=[dict(scene="wash", warp="none", post="clean", density=16,
                       energy=16, softness=16, palette_rotate=0,
                       transition_bars="2", transition_curve="linear")
                  for _ in track.sections],
        bars=[lane | silent for _ in range(track.n_bars)],
        track=track.name, seed=0,
    )


def test_the_baked_grid_has_one_column_per_uniform(track: Track):
    u = UniformTrack(_simple_score(track), track)
    assert u.grid.names == UNIFORM_NAMES
    assert u.grid.data.shape == (track.n, len(UNIFORM_NAMES))
    assert np.isfinite(u.grid.data).all()
    assert len(u.frames_bytes()) == track.n * len(UNIFORM_NAMES) * 4


def test_flux_rises_where_the_music_does_and_rests_where_it_does_not(track: Track):
    tl = track.timeline()
    flux = tl.column("flux")
    assert flux.min() >= 0.0 and flux.max() <= 1.0
    # The synthetic track's high band is a sine at the beat, so flux peaks once a
    # beat and sits near zero in between.
    assert flux.mean() < 0.5
    per_beat = [flux[int(i * BEAT * RATE):int((i + 1) * BEAT * RATE)].max()
                for i in range(2, 20)]
    assert min(per_beat) > 0.05


def test_an_unrouted_uniform_is_zero_everywhere(track: Track):
    u = UniformTrack(_simple_score(track), track)
    for name in ("uScale", "uHue", "uShake", "uSpin", "uSpinPhase"):
        assert np.all(u.grid.column(name) == 0.0), name


def test_a_route_follows_its_feature_up_to_the_gain(track: Track):
    """A fully open gain on a fast envelope tracks the feature it listens to."""
    score = _simple_score(track, route_source_a="low", route_target_a="radius",
                          route_gain_a=schema.BINS - 1, route_env_a="snap")
    u = UniformTrack(score, track)
    gain = GAIN_MAX * schema.slot("bar", "route_gain_a").unit(schema.BINS - 1)
    low = track.timeline().column("low")
    scale = u.grid.column("uRadius")
    # Not sample-for-sample - it is a follower, not a copy - but the peaks are
    # the feature's peaks times the gain, and they arrive at the same places.
    assert scale.max() == pytest.approx(low.max() * gain, rel=0.05)
    peak = int(np.argmax(scale[RATE:])) + RATE
    assert abs(peak - int(np.argmax(low[RATE:]) + RATE)) < RATE * 0.1


def test_a_slow_release_decays_rather_than_cutting_off(track: Track):
    """When a bar stops driving a uniform, the route releases instead of clicking."""
    shape = schema.Shape(len(track.sections), track.n_bars)
    score = _simple_score(track)
    for b in (2, 3):
        score.bars[b].update(route_source_a="mix", route_target_a="bright",
                             route_gain_a=schema.BINS - 1, route_env_a="slow")
    assert not schema.violations(shape, score.to_slots())
    bright = UniformTrack(score, track).grid.column("uBright")
    spans = track.bar_spans()
    end = int(spans[3, 1] * RATE)
    assert bright[end - 2] > 0.3
    # Still audible a tenth of a second later, gone well before the song ends.
    assert bright[end + RATE // 10] > 0.3 * bright[end - 2]
    assert bright[-1] < 0.01


def test_spin_phase_is_the_running_integral_of_spin(track: Track):
    score = _simple_score(track, route_source_a="bar", route_target_a="spin",
                          route_gain_a=20, route_env_a="hold")
    u = UniformTrack(score, track)
    spin, phase = u.grid.column("uSpin"), u.grid.column("uSpinPhase")
    assert np.all(np.diff(phase) >= -1e-7)          # an angle that never goes back
    assert phase[-1] == pytest.approx(spin.sum() / RATE, rel=1e-4)


def test_section_levels_ramp_rather_than_step(track: Track):
    """The one property the whole transition design rests on: nothing jumps."""
    score = _simple_score(track)
    score.sections[0]["density"] = 4
    score.sections[1]["density"] = 28
    score.sections[1]["transition_bars"] = "2"
    score.sections[1]["transition_curve"] = "linear"
    u = UniformTrack(score, track)
    cut = track.sections[1].start
    window, _ = u.transition(1)
    assert window == pytest.approx(2 * BAR)

    low, high = 4.5 / schema.BINS, 28.5 / schema.BINS
    assert u.at(cut - 0.05)["uDensity"] == pytest.approx(low, abs=1e-3)
    assert u.at(cut)["uDensity"] == pytest.approx(low, abs=1e-3)
    assert u.at(cut + window / 2)["uDensity"] == pytest.approx((low + high) / 2, abs=0.01)
    assert u.at(cut + window)["uDensity"] == pytest.approx(high, abs=1e-3)
    assert u.at(cut + window * 2)["uDensity"] == pytest.approx(high, abs=1e-3)

    # And it gets there monotonically, in steps no larger than one 120th of the
    # whole distance - which is what "no cut" means in numbers.
    col = UniformTrack(score, track).grid.column("uDensity")
    i, j = int((cut - 0.2) * RATE), int((cut + window + 0.2) * RATE)
    d = np.diff(col[i:j])
    assert np.all(d >= -1e-6)
    assert d.max() < (high - low) / (window * RATE) * 1.5


def test_a_ramp_never_outlasts_the_section_it_introduces(track: Track):
    score = _simple_score(track)
    for s in score.sections:
        s["transition_bars"] = "8"        # far longer than this song's sections
    u = UniformTrack(score, track)
    for s in track.sections:
        window, _ = u.transition(s.index)
        assert window <= s.end - s.start + 1e-6


def test_the_song_opens_out_of_silence(track: Track):
    """Nothing is drawn at t=0, and what is drawn arrives on the ramp."""
    score = _simple_score(track)
    score.sections[0]["transition_bars"] = "4"
    u = UniformTrack(score, track)
    assert u.at(0.0)["uLayerWash"] == pytest.approx(0.0, abs=1e-4)
    assert u.at(0.0)["uEnergy"] == pytest.approx(0.0, abs=1e-4)
    window, _ = u.transition(0)
    assert u.at(window)["uLayerWash"] > 0.9
    assert u.at(window)["uEnergy"] == pytest.approx(16.5 / schema.BINS, abs=1e-3)


def test_the_morph_channel_says_how_far_through_a_ramp_it_is(track: Track):
    score = _simple_score(track)
    score.sections[1]["transition_curve"] = "linear"
    u = UniformTrack(score, track)
    cut = track.sections[1].start
    window, _ = u.transition(1)
    assert u.at(cut)["uMorph"] == pytest.approx(0.0, abs=0.02)
    assert u.at(cut + window / 2)["uMorph"] == pytest.approx(0.5, abs=0.03)
    assert u.at(cut + window)["uMorph"] == pytest.approx(1.0, abs=1e-6)


def test_a_scene_resolves_to_layer_weights(track: Track):
    score = _simple_score(track)
    score.sections[1]["scene"] = "orbits"
    u = UniformTrack(score, track)
    t = track.sections[1].start + u.transition(1)[0] + 0.1
    at = u.at(t)
    for name, w in zip(schema.LAYERS, schema.SCENE_LAYERS["orbits"]):
        key = "uLayer" + name.capitalize()
        assert at[key] == pytest.approx(w, abs=1e-3), key


def test_the_uniforms_a_frame_gets_are_the_uniforms_declared(track: Track):
    from visuals.uniforms import uniform_names

    u = UniformTrack(_simple_score(track), track)
    assert set(u.at(3.0)) == set(uniform_names())


def test_a_score_of_the_wrong_shape_is_refused(track: Track):
    score = _simple_score(track)
    wrong = schema.Score(schema.Shape(len(track.sections), track.n_bars + 1))
    with pytest.raises(ValueError, match="bars"):
        UniformTrack(wrong, track)
    score.shape = schema.Shape(len(track.sections) + 1, track.n_bars)
    with pytest.raises(ValueError, match="sections"):
        UniformTrack(score, track)


def test_the_real_track_loads_and_lines_up(real_track: Track):
    assert real_track.n_bars == len(real_track.downbeats)
    assert real_track.sections[0].start == 0.0
    assert real_track.sections[-1].end == pytest.approx(real_track.duration)
    tl = real_track.timeline()
    assert tl.n == real_track.n
    assert np.isfinite(tl.data).all()
    assert (tl.data[:, :4] >= 0).all() and (tl.data[:, :4] <= 1).all()
    # The real track's beats do not land on grid samples, so the phase resets on
    # the first sample at or after each one, within a 120th of a second of it.
    for t in real_track.beats[:20]:
        assert tl.at(float(t) + 1 / RATE)["beat_phase"] < 0.05
        assert tl.at(float(t) - 1 / RATE)["beat_phase"] > 0.90
