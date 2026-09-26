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
