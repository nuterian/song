"""What the player is handed, and whether it describes itself correctly."""

from __future__ import annotations

import json

import numpy as np
import pytest

from visuals import authoring, export, grammar, schema
from visuals.listen import Track
from visuals.uniforms import UNIFORM_NAMES, UniformTrack


@pytest.fixture(scope="module")
def staged(track: Track, tmp_path_factory):
    out = tmp_path_factory.mktemp("staged")
    score = authoring.handwritten(track)
    export.export(score, track, out)
    return out, score


def test_the_plan_describes_the_binary_beside_it(staged, track: Track):
    out, _ = staged
    plan = json.loads((out / "plan.json").read_text())
    data = np.frombuffer((out / "frames.bin").read_bytes(), dtype="<f4")
    grid = plan["grid"]
    assert [f["name"] for f in grid["features"]] == list(UNIFORM_NAMES)
    assert len(data) == grid["frames"] * len(grid["features"])
    assert grid["rate"] == 120
    assert np.isfinite(data).all()


def test_the_binary_is_the_numbers_the_renderer_uses(staged, track: Track):
    out, score = staged
    plan = json.loads((out / "plan.json").read_text())
    stride = len(plan["grid"]["features"])
    data = np.frombuffer((out / "frames.bin").read_bytes(), dtype="<f4").reshape(-1, stride)
    uni = UniformTrack(score, track)
    # The browser interpolates this array; the renderer interpolates the same one.
    assert np.array_equal(data, uni.grid.data)
    i = 900
    at = uni.at(i / plan["grid"]["rate"])
    for c, name in enumerate(UNIFORM_NAMES):
        assert at[name] == pytest.approx(float(data[i, c]), abs=1e-6), name


def test_the_browser_is_given_one_program_for_the_whole_song(staged):
    """There is nothing for the player to swap, which is why it cannot cut."""
    out, _ = staged
    plan = json.loads((out / "plan.json").read_text())
    assert "programs" not in plan
    assert plan["program"]["key"]
    for s in plan["sections"]:
        assert "program" not in s
        assert s["transition_seconds"] > 0.0


def test_the_browser_gets_the_es_dialect(staged):
    out, _ = staged
    plan = json.loads((out / "plan.json").read_text())
    assert plan["vertex"].startswith("#version 300 es\n")
    frag = plan["program"]["fragment"]
    assert frag.startswith("#version 300 es\n")
    # No desktop-only spellings should have crept into a block.
    assert "texture2D(" not in frag
    assert "gl_FragColor" not in frag


def test_the_audio_is_staged_beside_the_plan(staged, track: Track):
    out, _ = staged
    plan = json.loads((out / "plan.json").read_text())
    # The synthetic workdir has no audio, so the name is promised but the file
    # need not be there; on a real workdir it is linked.
    assert plan["audio_file"] == "mix.m4a"
    assert (out / "mix.m4a").exists() == (track.workdir / "mix.m4a").exists()


def test_a_saved_score_round_trips_through_the_file(track: Track, tmp_path):
    score = authoring.handwritten(track)
    path = tmp_path / "score.json"
    score.write(path)
    again = schema.Score.read(path)
    assert np.array_equal(again.to_slots(), score.to_slots())
    assert again.track == score.track
    assert not again.violations()


def test_the_handwritten_score_repeats_itself_across_repeats(real_track: Track):
    """Both choruses arrive at the same place, which is the agreement the model
    has to learn rather than be told."""
    score = authoring.handwritten(real_track)

    def look(i):
        return (score.value("section", "scene", i), score.value("section", "warp", i),
                score.value("section", "post", i), score.value("section", "density", i),
                score.value("section", "energy", i), score.value("section", "softness", i))

    choruses = [s.index for s in real_track.sections if "chorus" in s.name.lower()
                and "pre" not in s.name.lower()]
    verses = [s.index for s in real_track.sections if s.name.lower().startswith("verse")]
    assert len(choruses) >= 2 and len(verses) >= 2
    assert len({look(i) for i in choruses}) == 1
    assert len({look(i) for i in verses}) == 1
    assert look(choruses[0]) != look(verses[0])
    # The chorus is where the edges get crisp; the verse is where they do not.
    assert score.unit("section", "softness", choruses[0]) < \
        score.unit("section", "softness", verses[0])
