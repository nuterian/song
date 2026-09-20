"""The piece's claims, on synthetic audio, so nobody's music is needed to check them.

What is asserted here is the chain the sync rests on: an attack is timed to a
millisecond or two with no filter delay; a grid is recovered from sharp hits and
phased by where the kick comes back; an event never reaches the shader before it
happened; and the first frame that shows a hit is the frame that is on screen when
the hit arrives - up to a frame early, never late.
"""

from __future__ import annotations

import numpy as np
import pytest

from visuals.pieces.gravity import colour, cosmos, direct, listen, models, shader, shader_cosmos, shader_ink, sky

SR = 48000


def clicks(times, seconds, decay=0.015, freq=3000.0, seed=0):
    """Decaying sine bursts at the given times, over a little noise."""
    rng = np.random.default_rng(seed)
    x = 0.002 * rng.standard_normal(int(seconds * SR))
    n = int(6 * decay * SR)
    burst = np.sin(2 * np.pi * freq * np.arange(n) / SR) * np.exp(-np.arange(n) / (decay * SR))
    for t in times:
        i = int(round(t * SR))
        x[i:i + n] += burst[: len(x) - i]
    return x


def test_attacks_are_timed_to_a_couple_of_milliseconds():
    truth = np.array([0.5003, 0.9871, 1.4402, 2.0139, 2.6508, 3.1117])
    env = listen.power_env(clicks(truth, 4.0), SR, 120)
    got = listen.pick_onsets(env, min_gap=0.05, sensitivity=0.2)
    assert len(got) == len(truth)
    assert np.abs(got.t - truth).max() < 0.002


def test_the_envelope_has_no_delay():
    x = np.zeros(SR)
    x[SR // 2:] = 1.0
    env = listen.power_env(x, SR, 60)
    half = np.argmax(env >= 0.5 * env.max()) / listen.ENV_RATE
    assert abs(half - 0.5) < 0.002


def test_the_grid_comes_from_the_sharp_hits_and_the_bar_from_the_kick():
    rng = np.random.default_rng(1)
    period, first = 0.48, 0.113
    beats = first + period * np.arange(120)
    # off-beat hats and backbeat claps, a millisecond of jitter on each
    hats = beats + period / 2 + rng.normal(0, 0.001, len(beats))
    claps = beats[1::2] + rng.normal(0, 0.001, len(beats[1::2]))
    # the kick rests for four bars twice and comes back on a downbeat both times;
    # its band reads 20 ms late, as a real one does
    playing = np.ones(len(beats), bool)
    playing[32:48] = False
    playing[80:96] = False
    kicks = beats[playing] + 0.020
    grid = listen.fit_grid(np.sort(np.concatenate([hats, claps])), kicks, 58.0, 0.4803)
    assert abs(grid["period"] - period) < 2e-5
    nearest = grid["beats"][np.argmin(np.abs(grid["beats"] - beats[10]))]
    assert abs(nearest - beats[10]) < 0.001
    # beats[48] and beats[96] are where the kick came back: they must be downbeats
    for b in (beats[48], beats[96]):
        assert np.abs(grid["downbeats"] - b).min() < 0.001
    assert abs(listen.latency(kicks, grid["beats"], 1) - 0.020) < 0.001


def test_an_event_is_never_handed_over_before_it_happened():
    times = np.array([0.1004, 0.2571, 0.2600, 1.0])
    T, A = direct.held_events(times, np.ones(4), n=240, slots=1)
    grid_t = np.arange(240) / direct.RATE
    assert (T[:, 0] <= grid_t + 1e-6).all()
    # and it is there by the first grid point at or after it
    for t in times:
        i = int(np.ceil(t * direct.RATE - 1e-6))
        assert T[i, 0] >= t - 1e-4 or T[i, 0] > t


def test_held_channels_are_not_interpolated():
    ch = direct.Channels(["uKickT", "uMass"], [direct.HOLD, direct.LERP],
                         np.array([[0.0, 0.0], [10.0, 1.0]], dtype=np.float32), [], 1.0)
    row = ch.rows(np.array([0.5 / direct.RATE]))[0]
    assert row[0] == 0.0 and abs(row[1] - 0.5) < 1e-6
    assert ch.at(0.5 / direct.RATE) == {"uKickT": 0.0, "uMass": pytest.approx(0.5)}


def test_the_spring_overshoots_once_and_settles():
    target = np.concatenate([np.full(120, 1.8), np.full(600, 1.0)])
    x = direct.spring(target, hz=1.6, damping=0.42)
    assert x[120:].min() < 0.99          # falls in past where it is going...
    assert abs(x[-1] - 1.0) < 0.005      # ...and ends up there


@pytest.mark.parametrize("sh", [shader, shader_ink, shader_cosmos], ids=["glow", "ink", "cosmos"])
def test_both_dialects_are_one_source(sh):
    gl, web = sh.fragment_source(sh.GL_HEADER), sh.fragment_source(sh.WEBGL_HEADER)
    assert gl.split("\n", 1)[1] == web.split("\n", 1)[1]
    assert "uPrev" not in gl             # no feedback: any frame can be drawn cold


def test_the_printed_style_blurs_nothing():
    """Sharpness is a rule of the ink style, so it is checked in the source: no
    gaussian falloff may reach the page as light. `exp(-x*x` is allowed where it
    shapes a *displacement* (the shove of a passing wave) or feeds a posterize()."""
    import re

    body = shader_ink.FRAGMENT_BODY
    for line in body.splitlines():
        if re.search(r"exp\(-\s*\(?[a-z_.]+\s*\*\s*[a-z_.]+", line) and "col = lay" in line:
            assert "posterize" in line, line.strip()


@pytest.mark.parametrize("style", ["glow", "ink"])
def test_each_style_compiles_and_draws(style):
    pytest.importorskip("moderngl")
    from visuals.pieces.gravity import render

    render.STYLE = style
    try:
        r = render.Renderer(160, 90)
    except Exception as exc:
        render.STYLE = "glow"
        pytest.skip(f"no headless GL: {exc}")
    try:
        ch = _one_kick_channels(0.5)
        r.bind(ch.names)
        frame = r.frame(0.6, ch.rows(np.array([0.6]))[0])
        assert frame.shape == (90, 160, 3) and frame.max() > 40 and np.isfinite(frame).all()
    finally:
        r.release()
        render.STYLE = "glow"


def _one_kick_channels(t_kick: float) -> direct.Channels:
    n = 2 * direct.RATE
    names = ["uMass", "uKickT", "uKickA", "uExposure", "uSpread", "uTilt", "uCBodyR", "uCBodyG", "uCBodyB"]
    kinds = [direct.LERP, direct.HOLD, direct.HOLD] + [direct.LERP] * 6
    KT, KA = direct.held_events(np.array([t_kick]), np.array([1.0]), n)
    data = np.stack([np.full(n, 1.0), KT[:, 0], KA[:, 0], np.full(n, 0.8), np.full(n, 1.0),
                     np.full(n, 0.56), np.full(n, 0.8), np.full(n, 0.6), np.full(n, 0.9)],
                    axis=1).astype(np.float32)
    return direct.Channels(names, kinds, data, [], n / direct.RATE)


@pytest.mark.parametrize("t_kick", [0.5000, 0.5041, 0.5100, 0.5166, 0.5167, 0.7333])
def test_a_hit_is_on_screen_when_it_arrives_and_never_after(t_kick):
    moderngl = pytest.importorskip("moderngl")
    from visuals.pieces.gravity import render

    try:
        r = render.Renderer(160, 90)
    except Exception as exc:                       # no GL on this machine
        pytest.skip(f"no headless GL: {exc}")
    fps = 60
    ch = _one_kick_channels(t_kick)
    times = render.frame_times(0.0, 1.0, fps)
    r.bind(ch.names)
    lit = [float(r.frame(float(t), row)[40:50, 70:90].mean()) for t, row in zip(times, ch.rows(times))]
    r.release()
    jump = int(np.argmax(np.diff(lit))) + 1        # first frame that shows the kick
    on_screen_from = jump / fps
    assert on_screen_from <= t_kick + 1e-9                   # never late
    assert t_kick - on_screen_from < 1.0 / fps + 1e-9        # and less than a frame early


# ---------------------------------------------------------------- colour and ramps


def test_oklch_lands_on_known_colours_and_stays_in_gamut():
    assert np.allclose(colour.oklch_to_linear_rgb(1.0, 0.0, 0.0), [1, 1, 1], atol=1e-3)
    assert np.allclose(colour.oklch_to_linear_rgb(0.62796, 0.25768, 29.234 / 360), [1, 0, 0], atol=2e-3)
    wild = colour.oklch_to_linear_rgb(np.full(50, 0.7), np.full(50, 0.4), np.linspace(0, 1, 50))
    assert wild.min() >= 0.0 and wild.max() <= 1.0


def test_a_decision_becomes_a_ramp_with_no_step_and_hue_goes_the_short_way():
    rate, n = 120, 120 * 12
    starts = np.array([0.0, 4.0, 8.0])
    level = colour.hold_then_ramp(np.array([0.0, 1.0, 0.2]), starts, n, rate, ramp_seconds=2.0)
    assert np.abs(np.diff(level)).max() < 1.5 / (2.0 * rate) * 2      # never faster than the ramp allows
    assert abs(level[int(6.0 * rate)] - 1.0) < 1e-6                   # and it does arrive
    hue = colour.hold_then_ramp(np.array([0.95, 0.05, 0.05]), starts, n, rate, 2.0, circular=True)
    crossing = hue[int(3.0 * rate): int(5.0 * rate)]
    assert crossing.min() >= 0.95 - 1e-6 and crossing.max() <= 1.05 + 1e-6   # through 1.0, not back through 0.5


def test_easing_hues_out_of_the_mud_keeps_their_order():
    h = np.linspace(0.0, 1.0, 2001)
    assert (np.diff(direct.avoid_murk(h)) > 0).all()


def test_fifths():
    # from A: E is one fifth up, D one down, Eb is the far side
    assert list(direct.fifths_from(9, np.array([9, 4, 2, 3]))) == [0, 1, -1, 6]


# --------------------------------------------------------------------- the models


def test_notes_are_read_off_the_posteriors():
    frames = 400
    note, onset = np.zeros((frames, 88)), np.zeros((frames, 88))
    a3 = 57 - models.BP_MIDI_LOW
    onset[100, a3] = 0.9
    note[100:140, a3] = 0.8                          # one A3, forty frames long
    onset[200, a3 + 3] = 0.9
    note[200:202, a3 + 3] = 0.8                      # too short to be a note
    got = models.decode_notes({"note": note, "onset": onset})
    assert list(got["midi"]) == [57]
    rate = models.BP_SR / models.BP_HOP
    assert abs(got["t"][0] - 100 / rate) < 1e-9 and abs(got["end"][0] - 140 / rate) < 2 / rate


def test_a_model_names_a_note_and_the_stem_says_when():
    attacks = np.array([1.000, 1.480, 1.960])
    named = np.array([1.012, 1.455, 2.300])
    assert list(models.snap(named, attacks)) == [1.000, 1.480, 2.300]


def test_key_from_a_natural_minor_scale():
    scale = np.array([57, 59, 60, 62, 64, 65, 67, 69, 57, 64, 57])       # A B C D E F G A, leaning on A and E
    assert models.key_from_notes(scale, np.ones(len(scale)))["name"] == "A minor"


def test_every_uniform_the_shader_declares_is_fed():
    import re

    from visuals.pieces.gravity import CACHE

    got = listen.load_cached(CACHE)
    if got is None:
        pytest.skip("no listening cache for the real track")
    ch = direct.direct(got, models.load_cached(CACHE))
    fed = set(ch.names) | {"uTime", "uResolution"}
    for sh in (shader, shader_ink):
        declared = set(re.findall(r"\bu[A-Z][A-Za-z0-9]*", sh.fragment_source()))
        assert declared - fed == set(), sh.__name__
    # and the section-level channels really are step-free
    from visuals.pieces.gravity.render import SECTION_LEVEL

    # The fastest thing these are allowed to do is follow the floor coming back at a
    # re-entry - colour floods in over half a second - which is about 0.02 of full
    # range per grid step. A decision arriving as a step would be ten times that.
    for name in SECTION_LEVEL:
        if name in ch.names:                   # the camera's are only baked for the cosmos style
            assert np.abs(np.diff(ch.data[:, ch.index(name)])).max() < 0.03, name


def test_no_star_is_cut_off_and_every_arm_is_whole():
    """Sky only, five moments. Each four-pointed star is found as a blob; its four arms
    must reach about equally far from its core. An arm cut short is a star drawn by a
    cell it does not fit in, or one whose existence was decided per pixel across the
    edge of a cluster - both of which happened."""
    pytest.importorskip("moderngl")
    from scipy import ndimage

    from visuals.pieces.gravity import CACHE, render

    got = listen.load_cached(CACHE)
    if got is None:
        pytest.skip("no listening cache for the real track")
    render.STYLE = "ink"
    try:
        r = render.Renderer(1920, 1080)
    except Exception as exc:
        render.STYLE = "glow"
        pytest.skip(f"no headless GL: {exc}")
    try:
        ch = render.sections_only(direct.direct(got, models.load_cached(CACHE)))
        ch.data[:, ch.index("uSpread")] = 60.0           # the system off screen: sky only
        r.bind(ch.names)
        checked = 0
        for t in (20.0, 100.3, 136.27, 200.0, 260.0):
            f = r.frame(t, ch.rows(np.array([t]))[0]).astype(np.float32).max(axis=2)
            lab, n = ndimage.label(f > 70)
            for sl, i in zip(ndimage.find_objects(lab), range(1, n + 1)):
                m = lab[sl] == i
                h, w = m.shape
                if max(h, w) < 14 or sl[0].start < 40 or sl[1].start < 40 or sl[0].stop > 1040 or sl[1].stop > 1880:
                    continue
                if np.hypot((sl[1].start + sl[1].stop) / 2 - 960, (sl[0].start + sl[0].stop) / 2 - 540) < 240:
                    continue                             # the star itself
                cy, cx = np.unravel_index(np.argmax(ndimage.distance_transform_edt(m)), m.shape)
                arms = np.array([cx, w - 1 - cx, cy, h - 1 - cy], dtype=float)
                checked += 1
                assert arms.min() >= 0.6 * arms.max() - 1, (t, sl, arms)
        assert checked >= 20
    finally:
        r.release()
        render.STYLE = "glow"


# ------------------------------------------------------------ the solar system, in 3D


def test_a_pulse_with_look_ahead_arrives_on_the_hit_and_never_jumps():
    n = 3 * direct.RATE
    hits = np.array([0.5, 1.0, 1.5])
    x = cosmos.anticipating_pulse(hits, np.ones(3), n, rise=0.055, decay=0.13)
    for t in hits:
        i = int(round(t * direct.RATE))
        assert x[i] == pytest.approx(1.0) and x[i - 1] < x[i] and x[i + 1] < x[i]      # the peak is the hit
    assert np.abs(np.diff(x)).max() < 0.30                                           # and it eased in: mass has inertia


def test_the_sky_frames_put_known_stars_where_they_are():
    def latitude(ra_hours, dec_degrees):
        v = sky.equatorial_to_ecliptic(np.radians([15.0 * ra_hours]), np.radians([dec_degrees]))[0]
        return np.degrees(np.arcsin(v[1]))
    assert latitude(10.1395, 11.967) == pytest.approx(0.46, abs=0.05)       # Regulus, almost on the ecliptic
    assert latitude(2.5303, 89.264) == pytest.approx(66.1, abs=0.1)        # Polaris
    g = sky.galactic_frame()
    assert np.degrees(np.arcsin(g["pole"][1])) == pytest.approx(29.8, abs=0.1)
    assert abs(np.dot(g["pole"], g["centre"])) < 1e-9
    d = np.random.default_rng(0).normal(size=(500, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    uv = sky.oct_encode(d)
    assert uv.min() >= 0.0 and uv.max() <= 1.0


def test_acts_cover_the_song_and_the_planets_align_at_the_climax():
    from visuals.pieces.gravity import CACHE

    got = listen.load_cached(CACHE)
    if got is None:
        pytest.skip("no listening cache for the real track")
    ch = cosmos.bake(got, models.load_cached(CACHE))
    acts = ch.acts
    assert acts[0].function == "approach" and acts[-1].function == "pullback"
    assert [a.function for a in acts].count("alignment") == 1
    for a, b in zip(acts[:-1], acts[1:]):
        assert a.end == pytest.approx(b.start)
    # at the climax the eight planets stand in a row: within a narrow fan, out to the
    # right of the Sun as the camera sees them
    i = int(ch.climax * direct.RATE)
    lon = np.array([2 * np.pi * ch.data[i, ch.index(f"uPh{k}")] + ch.data[i, ch.index("uCamTurn")] for k in range(8)])
    lon = (lon + np.pi) % (2 * np.pi) - np.pi
    assert np.degrees(np.abs(lon).max()) < 8.0
    # three cameras are baked, and each is an orrery's: it never jumps. (Zoom is judged
    # as a ratio - a step of 0.02 means nothing at a span of 3 and a lot at 0.25.)
    for mode in cosmos.MODES:
        for name in cosmos.CAMERA_UNIFORMS:
            x = ch.data[:, ch.index(f"{name}.{mode}")].astype(np.float64)
            step = np.abs(np.diff(np.log(x))) if name == "uCamSpan" else np.abs(np.diff(x))
            assert step.max() < 0.012, (mode, name, step.max())
    # and all three are looking the same way at the climax, so the row is one event
    headings = [ch.data[i, ch.index(f"uCamTurn.{mode}")] for mode in cosmos.MODES]
    assert np.ptp(headings) < 1e-3
    assert set(ch.variants["camera"]["choices"]) == set(cosmos.MODES)


def test_every_uniform_the_3d_shader_declares_is_fed():
    import re

    from visuals.pieces.gravity import CACHE

    got = listen.load_cached(CACHE)
    if got is None:
        pytest.skip("no listening cache for the real track")
    ch = cosmos.bake(got, models.load_cached(CACHE))
    declared = set(re.findall(r"\bu[A-Z][A-Za-z0-9]*", shader_cosmos.fragment_source()))
    # uSS is the renderer's to set (how many render pixels to an output pixel), not the song's
    fed = set(ch.names) | {"uTime", "uResolution", "uSS"} | set(shader_cosmos.TEXTURES)
    assert declared - fed == set()


def test_a_trail_is_the_colour_of_the_planet_that_leaves_it():
    # the table the trails are drawn from is the measured mean of each surface, not a guess
    means = shader_cosmos.surface_means()
    assert np.abs(means - np.array(shader_cosmos.PLANET_TINT)).max() < 0.02
    # and nothing else is mixed into a trail: not the accent, not white
    src = shader_cosmos.fragment_source()
    line = next(l for l in src.splitlines() if "vec3 tc =" in l)
    assert "PLANET_TINT[i] * sunlight * lum" in line and "kA" not in line and "white" not in line

