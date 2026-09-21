"""The editor's own arithmetic - no model needed: how edits land on a sheet."""

from __future__ import annotations

import pytest

from visuals.pieces.gravity import editor, sheet as sheet_
from visuals.pieces.gravity.cast import CHOICES

ACTS = [{"bars": [0, 14], "shot": "approach"}, {"bars": [14, 50], "shot": "intimate", "subject": "earth"},
        {"bars": [50, 77], "shot": "wide"}, {"bars": [77, 98], "shot": "eclipse", "subject": "saturn"},
        {"bars": [98, 116], "shot": "wide"}, {"bars": [116, 132], "shot": "alignment"},
        {"bars": [132, 149], "shot": "pullback"}]
SECTIONS = [{"name": "Verse 1", "bars": [17, 26]}, {"name": "Chorus 1", "bars": [33, 50]}]
SHEET = {"sheet": 2, "song": {"slug": "x", "tempo": 125.0, "meter": 4, "bars": 149, "seconds": 285.8},
         "heard": dict(sheet_.GRID, sections=SECTIONS),
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
    from visuals.pieces.gravity import lyrics

    named = {n: (b0, b1) for n, b0, b1 in lyrics.sung_sections(tr, got["arrays"]["bar_t"])}
    assert named["Chorus 2"] == (81, 90) and "Final Chorus" in named and named["Verse 1"][0] < named["Chorus 1"][0]


def test_every_part_is_described_to_the_model():
    assert set(sheet_.PARTS) == set(CHOICES)


def test_naming_bars_cuts_back_what_was_there():
    got, did = editor.apply(SHEET, [{"op": "section", "bars": [30, 40], "name": "Drop"}])
    assert got["heard"]["sections"] == [{"name": "Verse 1", "bars": [17, 26]}, {"name": "Drop", "bars": [30, 40]},
                                        {"name": "Chorus 1", "bars": [40, 50]}]
    assert did == ["bars [30, 40]: called Drop"] and sheet_.validate(got) == []
    got, _ = editor.apply(SHEET, [{"op": "section", "bars": [17, 26], "name": "The quiet verse"}])   # a rename
    assert got["heard"]["sections"][0] == {"name": "The quiet verse", "bars": [17, 26]}
    got, _ = editor.apply(SHEET, [{"op": "section", "bars": [45, 50], "name": ""}])                 # the end unnamed
    assert got["heard"]["sections"][1] == {"name": "Chorus 1", "bars": [33, 45]}


@pytest.mark.parametrize("heard,says", [
    ({"tempo_times": 3.0}, "twice as fast"),
    ({"meter": 9}, "beats to a bar"),
    ({"bar_one": 1.5}, "whole number"),
    ({"sections": [{"name": "A", "bars": [10, 20]}, {"name": "B", "bars": [15, 30]}]}, "not overlap"),
    ({"sections": [{"name": " ", "bars": [10, 20]}]}, "needs a name"),
])
def test_a_correction_that_means_nothing_is_refused(heard, says):
    bad = sheet_.validate(dict(SHEET, heard=dict(SHEET["heard"], **heard)))
    assert any(says in b for b in bad), bad


def test_the_grid_is_the_studios_to_change_not_the_models():
    kinds = {k["properties"]["op"]["const"] for k in editor.schema()["properties"]["edits"]["items"]["anyOf"]}
    assert "section" in kinds and "grid" not in kinds
    got, did = editor.apply(SHEET, [{"op": "grid", "tempo_times": 0.5, "bar_one": 1}])
    assert got["heard"]["tempo_times"] == 0.5 and got["heard"]["bar_one"] == 1 and sheet_.validate(got) == []


def test_what_changed_reads_the_same_whoever_changed_it():
    after, _ = editor.apply(SHEET, [{"op": "shot", "bars": [33, 50], "shot": "alignment", "subject": "none"},
                                    {"op": "reentry", "bar": 42, "strength": 0},
                                    {"op": "section", "bars": [50, 66], "name": "drop"},
                                    {"op": "cast", "part": "heart", "choice": "lead-synth"}])
    got = editor.changes(SHEET, after)
    assert {"kind": "shot", "title": "Shot", "bars": [33, 50], "before": "Two-shot · Earth", "after": "Alignment", "climax": True} in got
    assert {"kind": "shot", "title": "Shot", "bars": [116, 132], "before": "Alignment", "after": "Wide", "climax": False} in got
    assert {"kind": "section", "title": "Name", "bars": [50, 66], "before": "no name", "after": "Drop"} in got
    assert {"kind": "moment", "title": "Beat returns", "bar": 42, "before": "35%", "after": "none"} in got
    assert {"kind": "cast", "title": "Heart", "before": "voice", "after": "lead synth"} in got
    assert editor.changes(after, SHEET) and editor.changes(SHEET, SHEET) == []       # an undo reads as its own change
    moved = dict(SHEET, heard=dict(SHEET["heard"], tempo_times=2.0), song=dict(SHEET["song"], bars=298))
    assert [c["title"] for c in editor.changes(SHEET, moved)] == ["Tempo", "Shots and moments"]


def test_the_model_is_told_what_this_means():
    from visuals.pieces.gravity import listen
    from visuals.pieces.gravity.track import Track

    tr = Track.resolve()
    got = listen.load_cached(tr.cache)
    if got is None:
        pytest.skip("no listening cache for the real track")
    sheet = dict(SHEET, song=dict(SHEET["song"], tempo=125.0))
    text = editor.song_map(tr, got, sheet, {"bars": [17, 26], "playhead": 20})
    assert '"this"' in text and "bars [17, 26]" in text and "(Verse 1)" in text and "playhead" not in text
    assert "playhead is at bar 85" in editor.song_map(tr, got, sheet, {"playhead": 85})
