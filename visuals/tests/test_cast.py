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
    beats = 0.5 * np.arange(int(seconds / 0.5) + 1)
    a.update({"beats": beats, "downbeats": beats[::4], "bar_t": beats[::4], "loud": np.full(n, 0.8, np.float32),
              "other_low": np.full(n, 0.4, np.float32)})
    for key in ("mixlow", "mixmid", "mixhi", "otherhi"):
        a[f"ev_{key}_t"], a[f"ev_{key}_amp"] = np.zeros(0), np.zeros(0, np.float32)
    meta = {"period": 0.5, "duration": seconds, "meter": 4, "presence": {
        "drums": {"playing": 0.9}, "bass": {"playing": 0.9}, "other": {"playing": 1.0}, "vocals": {"playing": vocals}}}
    return {"arrays": a, "meta": meta}


def _no(g, *stems):
    """Take stems away, as presence would have: not playing, and no events of theirs."""
    own = {"drums": ("kick", "snare", "hat"), "bass": ("bass_note",), "other": ("note",), "vocals": ("syllable",)}
    for s_ in stems:
        g["meta"]["presence"][s_]["playing"] = 0.0
        for k in own[s_]:
            g["arrays"][f"ev_{k}_t"], g["arrays"][f"ev_{k}_amp"] = np.zeros(0), np.zeros(0, np.float32)
    return g


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


def test_with_nothing_to_stand_in_a_missing_part_is_silent_not_fed_leakage():
    g = _no(_got(), "drums", "bass")
    g["arrays"]["loud"][:] = 0.0                          # not even a beat to fall back on
    _, _, sheet = cast.apply(g, (_lead(), {}))
    for part in ("pulse", "ring", "stars"):
        assert sheet[part]["silent"] and "drums plays in 0.00" in sheet[part]["why"]


def test_no_drums_the_pulse_is_the_bass_on_the_beat():
    g = _no(_got(), "drums")
    beats = g["arrays"]["beats"]
    g["arrays"]["ev_bass_note_t"] = np.sort(np.concatenate([beats[::2] + 0.01, beats[1::2] + 0.23]))   # half on, half off
    g["arrays"]["ev_bass_note_amp"] = np.ones(len(g["arrays"]["ev_bass_note_t"]), np.float32)
    got, _, sheet = cast.apply(g, (_lead(), {}))
    assert sheet["pulse"]["why"] == "bass attacks on the beat" and sheet["pulse"]["stand_in"]
    assert np.allclose(got["arrays"]["ev_kick_t"], beats[::2] + 0.01)


def test_no_drums_no_bass_the_pulse_is_the_low_end_then_the_beat_itself():
    g = _no(_got(), "drums", "bass")
    beats = g["arrays"]["beats"]
    g["arrays"]["ev_mixlow_t"], g["arrays"]["ev_mixlow_amp"] = beats[::4] + 0.005, np.ones(len(beats[::4]), np.float32)
    got, _, sheet = cast.apply(g, (_lead(), {}))
    assert sheet["pulse"]["why"] == "the mix's low end on the beat"
    g = _no(_got(), "drums", "bass")
    got, _, sheet = cast.apply(g, (_lead(), {}))
    assert sheet["pulse"]["why"] == "the beat itself, small" and sheet["pulse"]["source"] == "grid"
    amp = got["arrays"]["ev_kick_amp"]
    assert amp.max() == np.float32(0.6) and np.isclose(amp.min(), 0.35)          # small, the one a little stronger


def test_no_drums_the_ring_is_the_backbeat_accents_and_rarer():
    g = _no(_got(), "drums")
    beats = g["arrays"]["beats"]
    rng = np.random.default_rng(3)
    t = np.sort(np.concatenate([beats + 0.003, beats + 0.25]))            # accents on every beat, and between
    g["arrays"]["ev_mixmid_t"], g["arrays"]["ev_mixmid_amp"] = t, rng.uniform(0.2, 1.0, len(t)).astype(np.float32)
    got, _, sheet = cast.apply(g, (_lead(), {}))
    assert sheet["ring"]["stand_in"]
    rt = got["arrays"]["ev_snare_t"]
    pos = np.round((rt - 0.003) / 0.5).astype(int) % 4
    assert set(pos.tolist()) <= {1, 3}                                   # 2 and 4, never the one or the offbeats
    assert len(rt) <= 0.55 * len(beats) / 2                              # the stronger half of the backbeats


def test_no_bass_the_corona_is_the_synths_low_notes():
    g = _no(_got(), "bass")
    t = np.arange(0.0, 60.0, 0.25)
    midi = np.where(np.arange(len(t)) % 3 == 0, 45, 72).astype(float)   # a low line under a high one
    mod = ({**_lead(), "other_t": t, "other_end": t + 0.2, "other_midi": midi, "other_amp": np.ones(len(t))}, {})
    got, m, sheet = cast.apply(g, mod)
    assert sheet["corona"]["stand_in"] and "low notes" in sheet["corona"]["why"]
    assert np.all(m[0]["bass_midi"] == 45) and len(got["arrays"]["ev_bass_note_t"]) == int(np.sum(midi == 45))
    assert np.array_equal(got["arrays"]["bass"], g["arrays"]["other_low"])


def test_drive_is_this_songs_pulse_not_four_on_the_floor():
    from visuals.pieces.gravity import decide

    assert decide.drive_at(np.array([4, 4, 4, 3, 0, 0, 4, 4.0])) == 3              # four on the floor: as it was
    assert decide.drive_at(np.array([2, 2, 2, 1, 0, 2, 2.0])) == 2                 # half time
    assert decide.drive_at(np.zeros(8)) == 3


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
