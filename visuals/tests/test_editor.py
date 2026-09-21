"""The editor's own arithmetic - no model needed: how edits land on a sheet."""

from __future__ import annotations

import pytest

from visuals.pieces.gravity import editor, sheet as sheet_
from visuals.pieces.gravity.cast import CHOICES

ACTS = [{"bars": [0, 14], "shot": "approach"}, {"bars": [14, 50], "shot": "intimate", "subject": "earth"},
        {"bars": [50, 77], "shot": "wide"}, {"bars": [77, 98], "shot": "eclipse", "subject": "saturn"},
        {"bars": [98, 116], "shot": "wide"}, {"bars": [116, 132], "shot": "alignment"},
        {"bars": [132, 149], "shot": "pullback"}]
SHEET = {"sheet": 1, "song": {"slug": "x", "tempo": 125.0, "meter": 4, "bars": 149, "seconds": 285.8},
         "cast": {"pulse": "kick", "ring": "snare", "stars": "hats", "corona": "bass", "planets": "synths", "heart": "voice"},
         "reentries": [{"bar": 2, "strength": 0.9}, {"bar": 42, "strength": 0.35}],
         "acts": ACTS, "feel": {k: v[0] for k, v in sheet_.FEEL.items()}, "lyrics": {k: v[0] for k, v in sheet_.LYRICS.items()}}


def bars(acts):
    return [(a["bars"][0], a["bars"][1], a["shot"], a.get("subject")) for a in acts]


def test_a_shot_inside_an_act_splits_it():
    got = editor.set_shot(ACTS, [60, 70], "intimate", "jupiter")
    assert bars(got)[2:5] == [(50, 60, "wide", None), (60, 70, "intimate", "jupiter"), (70, 77, "wide", None)]
    assert sheet_.validate(dict(SHEET, acts=got)) == []


def test_a_shot_across_acts_keeps_what_is_left_of_them():
    got = editor.set_shot(ACTS, [40, 90], "wide", None)
    assert bars(got)[1:4] == [(14, 40, "intimate", "earth"), (40, 90, "wide", None), (90, 98, "eclipse", "saturn")]


def test_there_is_one_climax():
    got = editor.set_shot(ACTS, [33, 50], "alignment", None)              # elsewhere: the climax moves
    assert [a["shot"] for a in got].count("alignment") == 1
    assert (33, 50, "alignment", None) in bars(got) and (98, 132, "wide", None) in bars(got)
    got = editor.set_shot(ACTS, [98, 116], "alignment", None)             # beside it: the climax grows
    assert [a["shot"] for a in got].count("alignment") == 1 and (98, 132, "alignment", None) in bars(got)


def test_asking_for_what_is_already_so_changes_nothing():
    got, did = editor.apply(SHEET, [{"op": "shot", "bars": [81, 90], "shot": "eclipse", "subject": "saturn"}])
    assert got == SHEET and did


def test_each_kind_of_edit_lands():
    got, _ = editor.apply(SHEET, [{"op": "reentry", "bar": 42, "strength": 0},
                                  {"op": "reentry", "bar": 58, "strength": 0.8},
                                  {"op": "cast", "part": "heart", "choice": "silent"},
                                  {"op": "feel", "dial": "flares_every_bars", "value": 4.0},
                                  {"op": "lyrics", "key": "show", "value": False}])
    assert [r["bar"] for r in got["reentries"]] == [2, 58]
    assert got["cast"]["heart"] == "silent" and got["feel"]["flares_every_bars"] == 4.0 and got["lyrics"]["show"] is False
    assert sheet_.validate(got) == []


def test_a_span_past_the_end_stops_at_it():
    got, did = editor.apply(SHEET, [{"op": "shot", "bars": [140, 400], "shot": "wide"}])
    assert got["acts"][-1]["bars"] == [140, 149] and sheet_.validate(got) == []


def test_the_answer_can_only_name_what_the_sheet_knows():
    kinds = editor.schema()["properties"]["edits"]["items"]["anyOf"]
    of = lambda name: [k["properties"] for k in kinds if k["properties"]["op"]["const"] == name]
    (shot,), (feel,) = of("shot"), of("feel")
    assert set(shot["shot"]["enum"]) == set(sheet_.SHOTS) and set(shot["subject"]["enum"]) == set(sheet_.PLANETS) | {"none"}
    assert set(feel["dial"]["enum"]) == set(sheet_.FEEL)
    assert {k for p in of("lyrics") for k in p["key"]["enum"]} == set(sheet_.LYRICS)
    # a part can only be given one of its own choices: the heart cannot be the kick
    assert {p["part"]["const"]: tuple(p["choice"]["enum"]) for p in of("cast")} == CHOICES
    # and every edit must say everything it needs, and nothing it does not
    assert all(set(k["required"]) == set(k["properties"]) and k["additionalProperties"] is False for k in kinds)


def test_the_second_chorus_is_where_the_lyric_sheet_puts_it():
    from visuals.pieces.gravity import listen
    from visuals.pieces.gravity.track import Track

    tr = Track.resolve()
    got = listen.load_cached(tr.cache)
    if got is None:
        pytest.skip("no listening cache for the real track")
    named = {n: (b0, b1) for n, b0, b1 in editor.named_sections(tr, got["arrays"]["bar_t"])}
    assert named["Chorus 2"] == (81, 90) and "Final Chorus" in named and named["Verse 1"][0] < named["Chorus 1"][0]


def test_every_part_is_described_to_the_model():
    assert set(sheet_.PARTS) == set(CHOICES)
