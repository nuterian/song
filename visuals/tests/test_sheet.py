"""The direction sheet: the default is the video, an edit changes what it names and not
much else, and an edit that means nothing is refused with the reason."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from visuals.pieces.gravity import render, sheet as sheet_

pytestmark = pytest.mark.local      # every test here reads the example song's listening


@pytest.fixture(scope="module")
def gravity():
    from visuals.pieces.gravity import listen
    from visuals.pieces.gravity.track import Track

    tr = Track.resolve()
    got = listen.load_cached(tr.cache)
    if got is None:
        pytest.skip("no listening cache for the real track")
    render.STYLE = "cosmos"
    ch = render.bake(got, tr)
    return tr, got, ch, sheet_.default(tr, got, ch)


def col(ch, name):
    return ch.data[:, ch.index(name)].astype(np.float64)


def test_the_default_sheet_is_the_video(gravity):
    tr, got, ch, sh = gravity
    assert sheet_.validate(sh, got) == []
    again = render.bake(got, tr, json.loads(sheet_.dumps(sh)))          # through its written form
    assert again.names == ch.names and np.array_equal(again.data, ch.data)
    # and it reads as the song does: the re-entries NOTES.md found from the audio
    assert [r["bar"] for r in sh["reentries"]] == [2, 34, 42, 50, 66, 82, 90, 98, 116, 132]
    assert [a["shot"] for a in sh["acts"]].count("alignment") == 1


def test_changing_a_shot_moves_only_the_cinematic_camera_and_only_near_that_act(gravity):
    tr, got, ch, sh = gravity
    edit = copy.deepcopy(sh)
    k = next(i for i, a in enumerate(edit["acts"]) if a["shot"] == "eclipse")
    edit["acts"][k] = {"bars": edit["acts"][k]["bars"], "shot": "wide"}
    out = render.bake(got, tr, edit)
    t = np.arange(len(ch.data)) / 120.0
    b0, b1 = edit["acts"][k]["bars"]
    bar = 4 * got["meta"]["period"]
    t0, t1 = sheet_.span(got["arrays"]["bar_t"], got["meta"]["duration"], [b0, b1])
    near = (t > t0 - 9 * bar) & (t < t1 + 9 * bar)                   # the act, and the move into and out of it
    moved = np.abs(col(out, "uCamSpan.cinematic") - col(ch, "uCamSpan.cinematic")) > 1e-6
    assert moved[near].any() and not moved[~near].any()
    for name in ("uCamSpan.static", "uCamTurn.static", "uKickA", "uSunPulse", "uVoice"):
        assert np.array_equal(col(out, name), col(ch, name))


def test_the_climax_goes_where_the_alignment_act_is(gravity):
    tr, got, ch, sh = gravity
    edit = copy.deepcopy(sh)
    acts = edit["acts"]
    i = next(i for i, a in enumerate(acts) if a["shot"] == "alignment")
    j = next(i for i, a in enumerate(acts) if a["shot"] == "wide")      # an earlier wide act takes the row
    acts[i]["shot"], acts[j]["shot"] = "wide", "alignment"
    out = render.bake(got, tr, edit)
    t0, t1 = sheet_.span(got["arrays"]["bar_t"], got["meta"]["duration"], acts[j]["bars"])
    assert out.climax == pytest.approx(t0 + 0.30 * (t1 - t0))


def test_a_reentry_taken_out_is_gone_from_the_picture(gravity):
    tr, got, ch, sh = gravity
    edit = copy.deepcopy(sh)
    gone = edit["reentries"].pop(3)
    out = render.bake(got, tr, edit)
    t = float(got["arrays"]["bar_t"][gone["bar"]])
    k = int(t * 120)
    assert col(ch, "uFlashE")[k:k + 12].max() > 0.3 and col(out, "uFlashE")[k:k + 12].max() < 0.01
    assert len(out.drops) == len(ch.drops) - 1


def test_the_dials_do_what_they_say(gravity):
    tr, got, ch, sh = gravity
    edit = copy.deepcopy(sh)
    edit["feel"]["flares_every_bars"] = 6.0
    out = render.bake(got, tr, edit)
    assert 0 < len(out.flares) < 0.6 * len(ch.flares)                  # a third as many, give or take
    edit = copy.deepcopy(sh)
    edit["cast"]["heart"] = "silent"
    out = render.bake(got, tr, edit)
    assert col(out, "uVoice").max() == 0.0 and col(ch, "uVoice").max() > 0.5


DANCE = {"planets_breathe": 0.5, "planets_sway": 1.0, "kick_pull": 0.3, "accents": 1.0}


def test_the_dance_dials_at_their_defaults_change_nothing(gravity):
    tr, got, ch, sh = gravity
    edit = copy.deepcopy(sh)
    for k in DANCE:
        del edit["feel"][k]                                            # a sheet written before them
    out = render.bake(got, tr, edit)
    assert out.names == ch.names and np.array_equal(out.data, ch.data)
    assert all(not col(ch, f"uSway{i}").any() for i in range(8))


WHOLE = {"planets_arc": 0.35, "near_dance": 1.0, "belts_breathe": 0.5, "sky_breathes": 1.0, "wave": 1.0}


def test_the_whole_system_dials_at_their_defaults_change_nothing(gravity):
    tr, got, ch, sh = gravity
    danced = dict(sh, feel=dict(sh["feel"], **DANCE))
    out = render.bake(got, tr, danced)
    edit = copy.deepcopy(danced)
    for k in WHOLE:
        del edit["feel"][k]                                            # a sheet written before them
    again = render.bake(got, tr, edit)
    assert again.names == out.names and np.array_equal(again.data, out.data)
    for c in (ch, out):                                                # the belts, the sky and the close shot are as they were
        assert all(not col(c, name).any() for name in ("uBeltLean0", "uBeltLean1", "uBeltSwell0", "uBeltSwell1", "uSky", "uNearDance", "uTrailRise", "uSpreadHome", "uInnerHome"))


@pytest.mark.parametrize("dial,inside,outside", [("planets_breathe", 1.0, 1.2), ("planets_sway", 2.0, -0.1),
                                                 ("kick_pull", 0.0, 1.6), ("accents", 0.5, 2.0),
                                                 ("planets_arc", 1.0, 1.1), ("near_dance", 0.5, -0.1),
                                                 ("belts_breathe", 0.0, 1.5), ("sky_breathes", 1.0, 2.0), ("wave", 0.3, -1.0),
                                                 ("comet", 1.0, 1.5), ("gravity", 0.6, 0.7)])
def test_the_dance_dials_are_taken_in_their_range_and_refused_outside_it(gravity, dial, inside, outside):
    tr, got, ch, sh = gravity
    assert sheet_.validate(dict(sh, feel=dict(sh["feel"], **{dial: inside})), got) == []
    bad = sheet_.validate(dict(sh, feel=dict(sh["feel"], **{dial: outside})), got)
    assert bad and any("outside" in b for b in bad), bad


def _clearance(ch, mode):
    """Mercury's least distance from the Sun's limb on screen, disc to disc, in frame heights."""
    from visuals.pieces.gravity import follow

    g = follow.geometry(ch, np.arange(len(ch.data)), mode)
    return float((np.hypot(g["planet_x"][:, 0] - g["sun_x"], g["planet_y"][:, 0] - g["sun_y"]) - g["sun_r"] - g["planet_r"][:, 0]).min())


def test_the_planets_dance_together_smoothly_clear_of_the_sun_and_never_backward(gravity):
    from visuals.pieces.gravity import cosmos, dance, follow

    tr, got, ch, sh = gravity
    out = render.bake(got, tr, dict(sh, feel=dict(sh["feel"], **DANCE)))
    deepest = render.bake(got, tr, dict(sh, feel=dict(sh["feel"], **dict(DANCE, planets_breathe=1.0))))
    for i in range(8):
        for name in ("uLean", "uHop", "uSway", "uGlow", "uBig", "uSwing"):
            x = col(out, f"{name}{i}")
            assert np.abs(np.diff(x)).max() < 0.25 * max(np.ptp(x), 1e-9), (name, i)      # nothing jumps
            assert np.abs(np.diff(x, 2)).max() < 0.09 * max(np.ptp(x), 1e-9), (name, i)   # and nothing has a corner in it
        assert np.ptp(col(out, f"uSway{i}")) > 0                                         # and every planet sways
    for mode in cosmos.MODES:
        j = follow.jolt(out, mode)
        assert j["planet_speed_peak"] < 1.0 and j["planet_speed_p99"] < 0.30, (mode, j)  # the bounds of test_no_camera_jolts
        for moved in (out, deepest):                                                     # Mercury is no nearer the Sun than it was
            assert _clearance(moved, mode) >= _clearance(ch, mode), mode
        # and each planet goes on round, its own way (the camera's turn left out): slower and faster, never back
        e = np.clip(col(out, f"uCamTilt.{mode}"), 0.20, 0.98)
        tug, gain = col(out, f"uSpreadSlow.{mode}"), np.clip(col(out, f"uCamSpan.{mode}"), 0.0, 1.0)
        for i in range(8):
            a = (np.maximum(0.255, 0.156 / e) + col(out, f"uPd{i}")) * tug + gain * col(out, f"uLean{i}")
            th = 2 * np.pi * col(out, f"uPh{i}") + gain * col(out, f"uSway{i}") / np.maximum(a, 0.05)
            assert np.diff(th).min() > 0, (mode, i)
    # the score's turns are on the song's own downbeats
    a = got["arrays"]
    n, bar = len(out.data), 4 * float(got["meta"]["period"])
    t = np.arange(n) / 120.0
    downs = a["downbeats"].astype(np.float64)
    score, _ = dance.score(downs, a["beats"].astype(np.float64), [d["t"] for d in out.drops] + [s.start for s in out.sections],
                           col(out, "uHold"), np.ones(n), bar)(t)
    turns = 0
    for k in range(1, len(downs) - 1):
        if not bar < downs[k] < t[-1] - bar:
            continue
        v = score[np.round(downs[k - 1:k + 2] * 120).astype(int)]
        if (v[1] - v[0]) * (v[2] - v[1]) > -1e-3:                          # not a turn: a bar held still
            continue
        i, h = int(round(downs[k] * 120)), int(round(bar / 2 * 120))
        assert abs(int(np.argmax(score[i - h:i + h] * np.sign(v[1] - v[0]))) - h) <= 0.030 * 120, downs[k]
        turns += 1
    assert turns > 0.8 * len(downs)


def test_the_whole_system_dances_smoothly_clear_of_itself_and_the_wave_runs_outward(gravity):
    from visuals.pieces.gravity import cosmos, dance, follow, orrery
    from visuals.pieces.gravity import shader_cosmos as sc

    tr, got, ch, sh = gravity
    whole = dict(sh, feel=dict(sh["feel"], **DANCE, **WHOLE))
    out = render.bake(got, tr, whole)
    for name in [f"{k}{i}" for k in ("uLean", "uHop", "uSway") for i in range(8)] + ["uBeltLean0", "uBeltLean1", "uBeltSwell0", "uBeltSwell1", "uSky"]:
        x = col(out, name)
        assert np.ptp(x) > 0, name                                                       # it moves
        assert np.abs(np.diff(x)).max() < 0.25 * np.ptp(x), name                          # nothing jumps
        assert np.abs(np.diff(x, 2)).max() < 0.09 * np.ptp(x), name                       # and nothing has a corner in it
    near = col(out, "uNearDance")
    for mode in cosmos.MODES:
        j = follow.jolt(out, mode)
        assert j["planet_speed_peak"] < 1.0 and j["planet_speed_p99"] < 0.30, (mode, j)  # the bounds of test_no_camera_jolts
        assert _clearance(out, mode) >= _clearance(ch, mode), mode                       # Mercury is no nearer the Sun than it was
        e = np.clip(col(out, f"uCamTilt.{mode}"), 0.20, 0.98)
        a0, tug, g = np.maximum(0.255, 0.156 / e), col(out, f"uSpreadSlow.{mode}"), np.clip(col(out, f"uCamSpan.{mode}"), 0.0, 1.0)
        gain = g * (1.0 - near) + np.sqrt(g) * near                                      # the shader's pullGain
        for i in range(8):                                                               # each planet goes on round, never back
            a = (a0 + col(out, f"uPd{i}")) * tug + gain * col(out, f"uLean{i}")
            th = 2 * np.pi * col(out, f"uPh{i}") + gain * col(out, f"uSway{i}") / np.maximum(a, 0.05)
            assert np.diff(th).min() > 0, (mode, i)
        # Mars's disc stays out of the asteroid belt, in the plane
        mars = (a0 + col(out, "uPd3")) * tug + gain * col(out, "uLean3") + sc.PLANET_SIZE[3] * (1.0 + 0.22 * col(out, "uBig3"))
        assert ((a0 + sc.BELTS[0][0]) * tug + gain * col(out, "uBeltLean0") - mars).min() > 0, mode
    # The wave, alone (the hops are springs: less the same without it): on a re-entry each
    # planet tops out as the shock's front reaches it where the shader draws the two of them,
    # in every camera (the front is reckoned in the home camera and drawn among this one's orbits);
    # at every other phrase's start, and every section's, as a kick's pull would - one after
    # another outward, on time.
    calm = render.bake(got, tr, dict(whole, feel=dict(whole["feel"], wave=0.0)))
    n, bar = len(out.data), 4 * float(got["meta"]["period"])
    t = np.arange(n) / 120.0
    home_a0, home = col(out, "uInnerHome"), col(out, "uSpreadHome")
    assert np.array_equal(home, col(out, "uSpreadSlow.static"))
    assert np.allclose(home_a0, np.maximum(0.255, 0.156 / np.clip(col(out, "uCamTilt.static"), 0.20, 0.98)), rtol=1e-6, atol=0)
    sun = 0.078 * (0.5 + 0.8 * col(out, "uMass")) * (1.0 + 0.22 * col(out, "uSunPulse"))
    downs = got["arrays"]["downbeats"].astype(np.float64)
    drops = np.array([d["t"] for d in out.drops])
    anchors = list(drops) + [s.start for s in out.sections]
    silent = [(s.start, s.end) for s in out.sections if s.state == "silent"]
    light = [d for d, k in zip(downs, dance.phrase_bars(downs, anchors, 8)) if k == 0 and np.abs(drops - d).min() > bar / 2
             and not any(s0 <= d < s1 for s0, s1 in silent) and 1.0 < d < t[-1] - 2.0]     # (with room for its run-up and its fall)
    assert len(light) > 5
    wave = [col(out, f"uHop{i}") - col(calm, f"uHop{i}") for i in range(8)]
    for mode in cosmos.MODES:
        e = np.clip(col(out, f"uCamTilt.{mode}"), 0.20, 0.98)
        a0, tug, gain = np.maximum(0.255, 0.156 / e), col(out, f"uSpreadSlow.{mode}"), np.sqrt(np.clip(col(out, f"uCamSpan.{mode}"), 0.0, 1.0))
        for d, shock in [(d, True) for d in drops] + [(d, False) for d in light]:
            moments = []
            for i in range(8):
                if shock:
                    a = (a0 + col(out, f"uPd{i}")) * tug + gain * col(out, f"uLean{i}")
                    takes = (np.maximum((a / tug - a0 + home_a0) * home - sun, 0.0) / 0.60) ** (1 / 0.70)
                    k = np.arange(int(np.ceil(d * 120)), n)
                    moments.append(t[k[t[k] - d >= takes[k]][0]])
                else:
                    moments.append(d + (dance.R_MEAN[i] - dance.R_MEAN[0]) / orrery.PULL_SPEED)
            tops = np.array([(int((m - 0.4) * 120) + np.argmax(w[int((m - 0.4) * 120):int((m + 0.4) * 120)])) / 120 for m, w in zip(moments, wave)])
            assert np.all(np.diff(tops) > 0) and np.abs(tops - moments).max() <= 0.020, (mode, d, tops - moments)


COMET = ("uCometPh", "uCometTurn", "uCometTail")


def test_the_comet_at_its_default_changes_nothing_and_moves_nothing_but_itself(gravity):
    tr, got, ch, sh = gravity
    whole = dict(sh, feel=dict(sh["feel"], **DANCE, **WHOLE))
    out = render.bake(got, tr, whole)
    edit = copy.deepcopy(whole)
    del edit["feel"]["comet"]                                          # a sheet written before it
    again = render.bake(got, tr, edit)
    assert again.names == out.names and np.array_equal(again.data, out.data)
    assert all(not col(out, name).any() for name in COMET)
    moved = render.bake(got, tr, dict(whole, feel=dict(whole["feel"], comet=1.0)))
    others = [c for c, name in enumerate(out.names) if name not in COMET]
    assert moved.names == out.names and np.array_equal(moved.data[:, others], out.data[:, others])


def test_the_comet_rounds_the_sun_on_the_strongest_reentry_clear_of_its_face(gravity):
    from visuals.pieces.gravity import cosmos, follow
    from visuals.pieces.gravity import shader_cosmos as sc

    tr, got, ch, sh = gravity
    out = render.bake(got, tr, dict(sh, feel=dict(sh["feel"], **DANCE, **WHOLE, comet=1.0)))
    n = len(out.data)
    late = [d for d in out.drops if d["t"] > float(got["meta"]["duration"]) / 8]      # (the song starting is not a return)
    t_s = max(late, key=lambda d: d["strength"])["t"]
    # at perihelion, within a frame: its mean anomaly, as the shader has it, passes a whole turn there
    m = col(out, "uOrbitSlow") * sc.COMET_RATE + sc.COMET_PHASE + col(out, "uCometPh")
    k = np.flatnonzero(np.floor(m[1:]) > np.floor(m[:-1]))
    assert np.abs((k + (np.floor(m[k + 1]) - m[k]) / (m[k + 1] - m[k])) / 120.0 - t_s).min() < 1 / 60
    tail = col(out, "uCometTail")                                      # the kicks blow its tail out, to 1.3 at most
    assert 0.2 < tail.max() <= cosmos.COMET_TAIL + 1e-6
    assert np.abs(np.diff(tail)).max() < 0.25 * np.ptp(tail)          # nothing jumps
    assert np.abs(np.diff(tail, 2)).max() < 0.09 * np.ptp(tail)       # and nothing has a corner in it
    head, at = 1.9 / 1080, int(round(t_s * 120))                       # its head at its largest, in frame heights at 1080p
    for mode in cosmos.MODES:
        g = follow.geometry(out, np.arange(n), mode)
        gap = np.hypot(g["comet_x"] - g["sun_x"], g["comet_y"] - g["sun_y"]) - g["sun_r"]
        assert gap[~g["comet_behind"]].min() > head, mode                                # it never crosses the Sun's face
        assert gap[at] > head and abs(g["comet_x"][at]) < 16 / 18 and abs(g["comet_y"][at]) < 0.5, mode   # and is seen rounding it
        assert follow.jolt(out, mode)["comet_speed_peak"] < 1.0, mode                    # the planets' bound (test_no_camera_jolts)


def test_the_gravity_dial_at_its_default_changes_nothing(gravity):
    tr, got, ch, sh = gravity
    whole = dict(sh, feel=dict(sh["feel"], **DANCE, **WHOLE, comet=1.0))
    out = render.bake(got, tr, whole)
    edit = copy.deepcopy(whole)
    del edit["feel"]["gravity"]                                        # a sheet written before it
    again = render.bake(got, tr, edit)
    assert again.names == out.names and np.array_equal(again.data, out.data)
    # and the dance the other dials make is left as it is: the planets hop, and a trail rises with its planet
    assert all(np.ptp(col(out, f"uHop{i}")) > 0 for i in range(8)) and col(out, "uTrailRise").min() == 1.0


# the planets follow the Sun, and the dance of the rounds before is off
GRAVITY = {"gravity": 0.3, "planets_breathe": 0.0, "planets_sway": 0.0, "kick_pull": 0.0, "planets_arc": 0.0, "wave": 0.0}


@pytest.fixture(scope="module", params=["gravity-in-motion", "shattered-voices"])
def following(request):
    """A song with a curated sheet, baked from it with GRAVITY; and with every planet at rest (no lean, hop or sway)."""
    from visuals.pieces.gravity import ROOT, listen, make, models
    from visuals.pieces.gravity.track import Track

    slug = request.param
    tr = Track.resolve() if slug == "gravity-in-motion" else Track(slug, ROOT / "visuals" / "cache" / slug / "source.wav")
    fix = sheet_.grid_fix(tr)
    cache = make.cache_of(tr, fix)
    got = listen.load_cached(cache, fix)
    mod = models.load_cached(cache)
    if got is None or mod is None or mod[1].get("listened") != models.listened_key(got["meta"]):
        pytest.skip(f"no current listening and models cached for {slug}")
    render.STYLE = "cosmos"
    the = sheet_.read(sheet_.CURATED / f"{slug}.json")
    out = render.bake(got, tr, dict(the, feel=dict(the["feel"], **GRAVITY)))
    rest = copy.copy(out)
    rest.data = out.data.copy()
    for i in range(8):
        for name in ("uLean", "uHop", "uSway"):
            rest.data[:, rest.index(f"{name}{i}")] = 0.0
    return got, out, rest


def _placed(ch, mode):
    """Each planet's distance from the Sun in the plane and its angle along its orbit, as the shader has them
    (scene units, radians; n x 8); and the camera's innermost orbit, spread and gain."""
    e = np.clip(col(ch, f"uCamTilt.{mode}"), 0.20, 0.98)
    a0, tug, g = np.maximum(0.255, 0.156 / e), col(ch, f"uSpreadSlow.{mode}"), np.clip(col(ch, f"uCamSpan.{mode}"), 0.0, 1.0)
    near = col(ch, "uNearDance")
    gain = g * (1.0 - near) + np.sqrt(g) * near                                  # the shader's pullGain
    a = np.stack([(a0 + col(ch, f"uPd{i}")) * tug + gain * col(ch, f"uLean{i}") for i in range(8)], 1)
    th = np.stack([2 * np.pi * col(ch, f"uPh{i}") for i in range(8)], 1) + gain[:, None] * np.stack([col(ch, f"uSway{i}") for i in range(8)], 1) / np.maximum(a, 0.05)
    return a, th, a0, tug, gain


def _follows(lead, inward):
    """How well a planet's place, inward, follows the lead, at the lag (0 to 3 s, every sample) where it follows it
    best: (correlation, lag in samples)."""
    n, best = len(lead), (-1.0, 0)
    for k in range(0, 3 * 120):
        x, y = lead[:n - k] - lead[:n - k].mean(), inward[k:] - inward[k:].mean()
        best = max(best, (float((x * y).sum() / np.sqrt((x * x).sum() * (y * y).sum())), k))
    return best


def test_the_planets_follow_the_sun_in_turn_smoothly_and_nothing_hops(following):
    from visuals.pieces.gravity import cosmos, dance, follow

    got, out, rest = following
    lead = 0.078 * (0.5 + 0.8 * col(out, "uMass")) * (1.0 + 0.22 * col(out, "uSunPulse"))
    lead = lead / np.median(lead)
    law = dance.orbits(lead, GRAVITY["gravity"], float(got["meta"]["period"]))[:, :8]
    lags = []
    for i in range(8):
        # the law alone, before any keeper: every planet follows the lead, as late as it is far out. (Today the
        # outermost, Neptune, measures 0.961 on Gravity and 0.902 on Shattered Voices: the further out, the less.)
        r, k = _follows(lead, -law[:, i])
        assert r >= 0.88, (i, r)
        lags.append(k)
        # and the keepers, which hold them off the Sun, off each other and out of the belts, take little from it
        assert _follows(lead, -col(out, f"uLean{i}"))[0] >= r - 0.01, i
    assert np.all(np.diff(lags) > 0), lags                                          # Mercury soonest, Neptune last
    assert all(not col(out, f"uHop{i}").any() for i in range(8)) and not col(out, "uTrailRise").any()   # nothing leaves the plane
    for name in [f"{k}{i}" for k in ("uLean", "uSway", "uBig", "uGlow", "uSwing") for i in range(8)] + ["uBeltLean0", "uBeltLean1"]:
        x = col(out, name)
        assert np.ptp(x) > 0, name                                                  # it moves
        assert np.abs(np.diff(x)).max() < 0.25 * np.ptp(x), name                    # nothing jumps
        assert np.abs(np.diff(x, 2)).max() < 0.09 * np.ptp(x), name                 # and nothing has a corner in it
    k = int(out.climax * 120)
    for mode in cosmos.MODES:
        j = follow.jolt(out, mode)
        assert j["planet_speed_peak"] < 1.0 and j["planet_speed_p99"] < 0.30, (mode, j)    # the bounds of test_no_camera_jolts
        # at the climax the eight stand in a row, run ahead or not (test_acts_cover_the_song_and_the_planets_align_at_the_climax)
        _, th, _, _, _ = _placed(out, mode)
        row = (th[k] + col(out, f"uCamTurn.{mode}")[k] + np.pi) % (2 * np.pi) - np.pi
        assert np.degrees(np.abs(row).max()) < 8.0, (mode, np.degrees(row))


def test_the_planets_following_the_sun_touch_nothing_in_any_camera_and_never_go_back(following):
    from visuals.pieces.gravity import cosmos, follow
    from visuals.pieces.gravity import shader_cosmos as sc

    got, out, rest = following
    n, px = len(out.data), 1.0 / 1080                                           # a pixel at 1080p, in frame heights
    for mode in cosmos.MODES:
        g, g0 = follow.geometry(out, np.arange(n), mode), follow.geometry(rest, np.arange(n), mode)

        def gaps(g):
            sun = np.hypot(g["planet_x"][:, 0] - g["sun_x"], g["planet_y"][:, 0] - g["sun_y"]) - g["sun_r"] - g["planet_r"][:, 0]
            pair = np.hypot(np.diff(g["planet_x"], axis=1), np.diff(g["planet_y"], axis=1)) - g["planet_r"][:, 1:] - g["planet_r"][:, :-1]
            return sun, pair
        sun, pair = gaps(g)
        sun0, pair0 = gaps(g0)
        # Mercury off the Sun's disc, or where at rest it is on it (the hybrid camera), no further on
        assert sun.min() >= min(sun0.min(), 0.0), (mode, sun.min() / px, sun0.min() / px)
        # neighbours' discs apart on screen, or where at rest they overlap, no further (within a pixel)
        assert (pair - np.minimum(pair0, 0.0)).min() > -px, (mode, (pair - np.minimum(pair0, 0.0)).min(0) / px)
        # no disc in a belt, in the plane: Mars and Jupiter either side of the asteroid belt, Neptune inside the Kuiper belt
        a, th, a0, tug, gain = _placed(out, mode)
        size = np.stack([sc.PLANET_SIZE[i] * (1.0 + 0.22 * col(out, f"uBig{i}")) for i in range(8)], 1)
        belt = lambda x, b: (a0 + x) * tug + gain * col(out, f"uBeltLean{b}")  # noqa: E731
        assert (belt(sc.BELTS[0][0], 0) - a[:, 3] - size[:, 3]).min() > 0, mode
        assert (a[:, 4] - size[:, 4] - belt(sc.BELTS[0][0] + sc.BELTS[0][1] * sc.BELTS[0][2], 0)).min() > 0, mode
        assert (belt(sc.BELTS[1][0], 1) - a[:, 7] - size[:, 7]).min() > 0, mode
        # and each goes on round its orbit, slower and faster, never back
        assert np.diff(th, axis=0).min() > 0, (mode, np.diff(th, axis=0).min(0))


def test_lyrics_follow_the_sheet(gravity, tmp_path):
    tr, got, ch, sh = gravity
    from visuals.pieces.gravity import lyrics

    assert lyrics.layout(tr, ch, {**sh["lyrics"], "show": False}) is None
    small = lyrics.layout(tr, ch, {**sh["lyrics"], "size": 0.02, "sung": 0.5})
    assert small["style"]["size"] == 0.02 and small["style"]["sung"] == 0.5


@pytest.mark.parametrize("change,says", [
    (lambda s: s["acts"][2].update(shot="spin"), "is not one of"),
    (lambda s: s["acts"][1].update(shot="eclipse", subject=None), "needs a subject"),
    (lambda s: s["acts"][1]["bars"].__setitem__(1, s["acts"][1]["bars"][1] - 2), "no gaps or overlaps"),
    (lambda s: s["feel"].update(orbits_breathe=9.0), "outside"),
    (lambda s: s["cast"].update(heart="guitar"), "cannot be"),
    (lambda s: s["reentries"].append({"bar": 9999, "strength": 0.5}), "not a bar of this song"),
    (lambda s: s["lyrics"].update(show="yes"), "true or false"),
])
def test_an_edit_that_means_nothing_is_refused_with_the_reason(gravity, change, says):
    tr, got, ch, sh = gravity
    edit = copy.deepcopy(sh)
    change(edit)
    bad = sheet_.validate(edit, got)
    assert bad and any(says in b for b in bad), bad
