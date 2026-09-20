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

from visuals.pieces.gravity import direct, listen, shader

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


def test_both_dialects_are_one_source():
    gl, web = shader.fragment_source(shader.GL_HEADER), shader.fragment_source(shader.WEBGL_HEADER)
    assert gl.split("\n", 1)[1] == web.split("\n", 1)[1]
    assert "uPrev" not in gl             # no feedback: any frame can be drawn cold


def _one_kick_channels(t_kick: float) -> direct.Channels:
    n = 2 * direct.RATE
    names = ["uMass", "uKickT", "uKickA", "uExposure", "uSpread", "uHue"]
    kinds = [direct.LERP, direct.HOLD, direct.HOLD, direct.LERP, direct.LERP, direct.LERP]
    KT, KA = direct.held_events(np.array([t_kick]), np.array([1.0]), n)
    data = np.stack([np.full(n, 1.0), KT[:, 0], KA[:, 0], np.full(n, 0.8),
                     np.full(n, 1.0), np.full(n, 0.7)], axis=1).astype(np.float32)
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
