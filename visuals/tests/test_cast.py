"""Casting: who plays which part, and the heart finding the lead when nothing sings."""

from __future__ import annotations

import numpy as np

from visuals.pieces.gravity import cast, models
from visuals.pieces.gravity.listen import RATE


def _got(seconds=60.0, vocals=0.0, rng=None):
    rng = rng or np.random.default_rng(0)
    n = int(seconds * RATE)
    ev = lambda k, rate: np.sort(rng.uniform(0, seconds, int(rate * seconds)))
    a = {"voice": np.zeros(n, np.float32), "other": np.full(n, 0.6, np.float32)}
    for kind, rate in (("kick", 2), ("snare", 1), ("hat", 4), ("bass_note", 3), ("note", 6), ("syllable", 3 if vocals else 0)):
        a[f"ev_{kind}_t"] = ev(kind, rate)
        a[f"ev_{kind}_amp"] = np.ones(len(a[f"ev_{kind}_t"]), np.float32)
    meta = {"period": 0.5, "duration": seconds, "presence": {
        "drums": {"playing": 0.9}, "bass": {"playing": 0.9}, "other": {"playing": 1.0}, "vocals": {"playing": vocals}}}
    return {"arrays": a, "meta": meta}


def _lead(seconds=60.0, covers=0.8):
    t = np.arange(0, seconds, 0.016)
    keep = (t % 10.0) < 10.0 * covers
    st = np.where((t % 1.0) < 0.5, 3.0, 5.0).astype(np.float32)        # a two-note figure, a note every half second
    return {"lead_t": t, "lead_st": st, "lead_keep": keep, "f0_t": t, "f0_hz": np.full(len(t), 220.0), "f0_conf": np.ones(len(t))}


def test_a_voice_that_sings_keeps_the_heart():
    got, mod, sheet = cast.apply(_got(vocals=0.6), (_lead(), {}))
    assert sheet["heart"]["source"] == "vocals" and not sheet["heart"].get("silent")
    assert "lead" not in sheet["heart"]["why"]


def test_when_nothing_sings_the_heart_follows_the_lead_synth():
    g = _got(vocals=0.0)
    # the synths strike every note of the figure, and a few other things
    g["arrays"]["ev_note_t"] = np.sort(np.concatenate([np.arange(0.0, 60.0, 0.5) + 0.004, [7.23, 18.61]]))
    g["arrays"]["ev_note_amp"] = np.ones(len(g["arrays"]["ev_note_t"]), np.float32)
    got, mod, sheet = cast.apply(g, (_lead(), {}))
    assert sheet["heart"]["source"] == "other" and "lead" in sheet["heart"]["why"]
    assert "shares" in sheet["planets"]["why"]
    syl = got["arrays"]["ev_syllable_t"]
    # a note every half second inside the phrases (8 s of every 10), each on the synths' own attack
    assert 80 <= len(syl) <= 100
    assert np.all(np.abs(((syl - 0.004 + 0.25) % 0.5) - 0.25) < 1e-9)
    assert got["arrays"]["voice"].max() > 0.5 and mod[0]["f0_conf"].max() == 1.0


def test_nothing_to_sing_and_no_lead_is_silent_with_the_reason():
    got, mod, sheet = cast.apply(_got(vocals=0.0), (_lead(covers=0.05), {}))
    assert sheet["heart"]["silent"] and "no lead line" in sheet["heart"]["why"]


def test_a_part_whose_stem_is_absent_is_silent_not_fed_leakage():
    g = _got()
    g["meta"]["presence"]["drums"]["playing"] = 0.0
    _, _, sheet = cast.apply(g, (_lead(), {}))
    for part in ("pulse", "ring", "stars"):
        assert sheet[part]["silent"] and "drums plays in 0.00" in sheet[part]["why"]


def test_the_lead_line_is_phrases_not_flicker():
    t = np.arange(0, 10, 0.016)
    conf = np.where((t > 1) & (t < 4), 0.8, 0.1)
    conf[(t > 2.0) & (t < 2.1)] = 0.2                                  # a 0.1 s dropout: bridged
    conf[(t > 6.0) & (t < 6.1)] = 0.9                                  # a 0.1 s blip: dropped
    conf[(t > 7.0) & (t < 8.0)] = 0.45                                 # fairly sure, never sure: not a line
    got = models.lead_line({"t": t, "hz": np.full(len(t), 330.0), "conf": conf})
    k = got["keep"]
    assert k[(t > 1.05) & (t < 3.95)].all()
    assert not k[(t > 5.5) & (t < 6.5)].any() and not k[(t > 7) & (t < 8)].any()
