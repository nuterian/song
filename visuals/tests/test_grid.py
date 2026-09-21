"""The beat grid: each test is a way the grid was wrong, or could be, on a real song.

Beat This! is not run here; its output is imitated as measured on three songs: beats on
20 ms frames, 14-38 ms late, with a few milliseconds of jitter.
"""

from __future__ import annotations

import numpy as np
import pytest

from visuals.pieces.gravity import grid


def fake_beat_this(beats: np.ndarray, meter: int, late: float, rng, phase: int = 0) -> dict:
    b = np.round((beats + late + rng.normal(0, 0.004, len(beats))) / 0.02) * 0.02
    return {"beats": b, "downbeats": b[(np.arange(len(b)) - phase) % meter == 0]}


def half_time(bpm: float, bars: int, rng, jitter: float = 0.001):
    """A half-time groove as Shattered Voices plays it: sixteenth hats, claps on 2 and 4,
    and a kick that doubles 0.21 s after the one - which is what fooled the old grid."""
    period = 60.0 / bpm
    beats = 0.02 + period * np.arange(4 * bars)
    hats = (beats[:, None] + period / 4 * np.arange(4)).ravel()
    claps = beats[1::2]
    kicks = np.concatenate([beats[::4], beats[::4] + 0.21, beats[2::4] + period * 0.75])
    sharp = np.sort(np.concatenate([hats, claps]) + rng.normal(0, jitter, len(hats) + len(claps)))
    return beats, sharp, np.sort(kicks + 0.007)


def score(found: np.ndarray, truth: np.ndarray) -> tuple[float, float]:
    """Share of true beats with a found beat within 25 ms, and the median error of those."""
    d = np.abs(truth[:, None] - found[None, :]).min(axis=1)
    return float((d < 0.025).mean()), float(np.median(d[d < 0.025]))


def test_a_doubled_kick_no_longer_sets_the_tempo():
    rng = np.random.default_rng(1)
    beats, sharp, kicks = half_time(90.0, 60, rng)
    # what the old grid did: start from the median gap between kicks
    gaps = np.diff(kicks)
    old = grid.fit_grid(sharp, kicks, beats[-1] + 1, float(np.median(gaps[gaps < 0.8])))
    assert old["sharp_used"] / len(sharp) < grid.GATE           # it fitted, confidently, the wrong thing
    g = grid.find(sharp, kicks, (sharp, np.ones(len(sharp))), fake_beat_this(beats, 4, 0.0135, rng),
                  beats[-1] + 1)
    assert g["source"] == "lattice"
    assert abs(g["tempo"] - 90.0) < 0.01
    found, err = score(g["beats"], beats)
    assert found == 1.0 and err < 0.002


def test_the_scan_finds_the_spacing_and_beat_this_the_octave():
    rng = np.random.default_rng(2)
    beats, sharp, _ = half_time(90.0, 60, rng)
    spacing, c = grid.lattice_scan(sharp)[0]
    assert abs(spacing - 60.0 / 90.0 / 4) < 2e-5 and c > 0.9
    assert grid.beat_multiple(spacing, 0.66) == 4           # Beat This!'s coarse 90.9 BPM
    assert grid.beat_multiple(spacing, 0.333) == 2          # had it said double time, so would we
    assert grid.beat_multiple(spacing, 0.58) is None        # 3.5 steps: nothing whole, no lattice


def test_the_fit_does_not_depend_on_where_it_starts():
    rng = np.random.default_rng(3)
    beats, sharp, kicks = half_time(125.0, 60, rng)
    a = grid.fit_grid(sharp, kicks, beats[-1] + 1, 0.4801)
    b = grid.fit_grid(sharp, kicks, beats[-1] + 1, 0.47995)
    assert a["period"] == b["period"] and a["t0"] == b["t0"]


def test_beat_this_lateness_is_the_mode_not_the_median():
    """Dense notes between the beats pulled a median to -14 ms where the truth was -38."""
    rng = np.random.default_rng(4)
    period = 0.48
    beats = period * np.arange(200)
    on = beats + rng.normal(0, 0.001, len(beats))
    between = np.concatenate([beats + period * f for f in (0.19, 0.31, 0.56, 0.69, 0.81)])
    t = np.concatenate([on, between + rng.normal(0, 0.004, len(between))])
    amp = np.ones(len(t))
    late = beats + 0.038
    assert abs(grid.lateness(late, t, amp) + 0.038) < 0.002


def test_humanised_playing_fails_the_gate_and_is_tracked():
    """A live drummer drifting 88 -> 96 BPM with 12 ms of spread: no lattice fits it, and the
    tracked grid follows the drift."""
    rng = np.random.default_rng(5)
    ibi = 60.0 / np.linspace(88, 96, 240)
    beats = 0.3 + np.concatenate([[0.0], np.cumsum(ibi[:-1])])
    sub = beats[:-1, None] + np.diff(beats)[:, None] * np.arange(4) / 4
    sharp = np.sort(sub.ravel() + rng.normal(0, 0.012, sub.size))
    kicks = beats[::2] + 0.02
    bt = fake_beat_this(beats, 4, 0.02, rng)
    g = grid.find(sharp, kicks, (sharp, np.ones(len(sharp))), bt, beats[-1] + 1)
    assert g["lattice"]["on_lattice"] < grid.GATE and g["source"] == "tracked"
    found, err = score(g["beats"], beats)
    assert found > 0.95 and err < 0.012


def test_three_four_is_counted_in_threes():
    rng = np.random.default_rng(6)
    period = 60.0 / 150
    beats = 0.1 + period * np.arange(300)
    hats = (beats[:, None] + period / 2 * np.arange(2)).ravel() + rng.normal(0, 0.001, 2 * len(beats))
    bt = fake_beat_this(beats, 3, 0.02, rng, phase=1)
    g = grid.find(np.sort(hats), beats[1::3] + 0.01, (hats, np.ones(len(hats))), bt, beats[-1] + 1)
    assert g["meter"] == 3 and g["meter_agreement"] > 0.95
    assert np.allclose(np.diff(g["downbeats"]), 3 * period, atol=0.002)
    inside = g["downbeats"][g["downbeats"] < beats[-1]]
    assert np.abs(inside[:, None] - beats[1::3][None, :]).min(axis=1).max() < 0.002


def test_a_tracked_grid_keeps_its_bars_across_a_dropped_beat():
    """One global bar phase puts every bar after a lost beat off its line (on Gravity,
    forced to track, 63 % of bars were right); bars follow Beat This!'s own downbeats."""
    rng = np.random.default_rng(7)
    beats = 0.2 + 0.5 * np.arange(160)
    bt = fake_beat_this(beats, 4, 0.0, rng)
    keep = np.ones(len(beats), bool)
    keep[61] = False                                            # the tracker loses a beat
    bt = {"beats": bt["beats"][keep], "downbeats": bt["downbeats"]}
    downs = grid.local_downbeats(bt["beats"], bt["downbeats"], 4, 0)
    truth = beats[::4]
    assert np.abs(downs[:, None] - truth[None, :]).min(axis=1).max() < 0.03


@pytest.mark.parametrize("votes,expect", [([8, 0, 0, 0], "kick re-entries"), ([2, 0, 0, 1], "beat this")])
def test_the_bar_phase_comes_from_the_kick_only_when_it_is_sure(votes, expect):
    beats = 0.5 * np.arange(400)
    idx, j = [0], 1                          # a first kick, which is not a re-entry
    for phase, n in enumerate(votes):
        for _ in range(n):
            idx.append(12 * j + phase)       # three bars after the last one
            j += 1
    phase, source, kv, _ = grid.bar_phase(beats, beats[np.array(idx)], beats[2::4], 4)
    assert kv == votes and source == expect
    assert phase == (0 if expect == "kick re-entries" else 2)


def test_an_unsteady_beat_tracker_cannot_veto_a_good_lattice():
    """TIDAL CORE with no drums or bass: Beat This! wandered (steady on 59 % of its gaps),
    agreed with a third of an exact lattice, and the song was given its wandering beats."""
    rng = np.random.default_rng(8)
    beats, sharp, kicks = half_time(128.0, 60, rng)
    bt = fake_beat_this(beats, 4, 0.02, rng)
    bt["beats"] = np.sort(bt["beats"] + rng.choice([0.0, 0.12, -0.12, 0.23], len(bt["beats"])))   # lost, a sixteenth off, half a beat off
    g = grid.find(sharp, kicks, (sharp, np.ones(len(sharp))), bt, beats[-1] + 1)
    assert g["beat_this"]["steady"] < grid.BT_STEADY and g["lattice"]["beat_this_agrees"] < grid.BT_GATE
    assert g["source"] == "lattice" and abs(g["tempo"] - 128.0) < 0.01


def test_a_tracked_grid_only_goes_forward():
    b = np.array([0.0, 0.5, 1.0, 1.08, 1.5, 1.265, 2.0, 2.5])      # a beat 80 ms after another, one out of order
    got = grid.in_order(b)
    assert np.all(np.diff(got) >= 0.35 * 0.5) and got[0] == 0.0 and got[-1] == 2.5


def test_eighth_notes_taken_for_the_beat_are_halved():
    """Shattered Voices' synths alone: Beat This! heard 182 BPM in two; the song is 90 in four."""
    rng = np.random.default_rng(9)
    beats = 0.3 + (60.0 / 90.0) * np.arange(200)
    eighths = np.sort(np.concatenate([beats, beats + (60.0 / 180.0)]))
    bt = fake_beat_this(eighths, 2, 0.015, rng)
    g = grid.find(np.zeros(0), np.zeros(0), (eighths, np.ones(len(eighths))), bt, beats[-1] + 1)
    assert g.get("halved") and abs(g["tempo"] - 90.0) < 1.0 and g["meter"] == 4
    d = np.abs(beats[5:-5][:, None] - g["beats"][None, :]).min(axis=1)
    assert np.median(d) < 0.01


def test_a_person_can_correct_the_grid():
    from visuals.pieces.gravity import grid

    beats = np.arange(0.0, 10.0, 0.5)
    assert np.allclose(np.diff(grid.double(beats)), 0.25) and len(grid.double(beats)) == 2 * len(beats)
    bars = beats[::4]
    moved = grid.shift_bars(beats, bars, 1)
    assert np.allclose(moved, beats[1::4][:len(moved)])
    assert grid.normal_fix({"tempo_times": 1, "meter": None, "bar_one": 0}) is None and grid.normal_fix(None) is None
    assert grid.normal_fix({"tempo_times": 2, "bar_one": -1}) == {"tempo_times": 2.0, "meter": None, "bar_one": -1}
