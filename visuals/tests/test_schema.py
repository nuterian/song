"""The score schema: the layout, the round trip, legality, and determinism."""

from __future__ import annotations

import json

import numpy as np
import pytest

from visuals import schema
from visuals.schema import MASK, Score, Shape

SHAPE = Shape(n_sections=4, n_bars=17)


def test_layout_is_song_then_sections_then_bars():
    n_song, n_sec, n_bar = len(schema.SONG_SLOTS), len(schema.SECTION_SLOTS), len(schema.BAR_SLOTS)
    assert SHAPE.n_slots == n_song + n_sec * 4 + n_bar * 17
    assert SHAPE.index("song", "motif") < SHAPE.section_offset
    assert SHAPE.section_offset <= SHAPE.index("section", "scene", 0) < SHAPE.bar_offset
    assert SHAPE.index("bar", "route_source_a", 0) == SHAPE.bar_offset
    # Bar j's slots sit together and in order, so a model's bar tokens line up
    # with the audio's bar tokens without a gather.
    for j in range(17):
        first = SHAPE.index("bar", schema.BAR_SLOTS[0].name, j)
        assert first == SHAPE.bar_offset + j * n_bar


def test_describe_inverts_index():
    for i in range(SHAPE.n_slots):
        tier, slot, group = SHAPE.describe(i)
        assert SHAPE.index(tier, slot.name, group) == i


def test_index_rejects_groups_out_of_range():
    with pytest.raises(IndexError):
        SHAPE.index("section", "scene", 4)
    with pytest.raises(IndexError):
        SHAPE.index("bar", "route_gain_a", 17)


def test_full_score_round_trips_exactly():
    slots = schema.random_fill(SHAPE, seed=7)
    assert (slots != MASK).all()
    score = Score.from_slots(SHAPE, slots, track="t", seed=7)
    assert np.array_equal(score.to_slots(), slots)
    # And through JSON as well, which is the form it is actually stored in.
    again = Score.from_dict(json.loads(json.dumps(score.to_dict())))
    assert np.array_equal(again.to_slots(), slots)


@pytest.mark.parametrize("keep", [0.0, 0.3, 0.75, 1.0])
def test_partially_masked_scores_round_trip(keep):
    """A half-filled score is representable, and survives the trip unchanged."""
    rng = np.random.default_rng(int(keep * 1000))
    slots = schema.random_fill(SHAPE, seed=3)
    slots[rng.random(SHAPE.n_slots) > keep] = MASK
    score = Score.from_slots(SHAPE, slots)
    assert np.array_equal(score.to_slots(), slots)
    assert score.is_complete() == bool(keep == 1.0)
    # A masked slot is absent from the dicts and null in JSON, never a value.
    d = score.to_dict()
    assert all(v is None for name, v in d["song"].items()
               if slots[SHAPE.index("song", name)] == MASK)
    assert np.array_equal(Score.from_dict(d).to_slots(), slots)


def test_masked_bins_are_not_confused_with_bin_zero():
    """Bin 0 is a decision; MASK is the absence of one. They must not collide."""
    score = Score(SHAPE, song={"grain": 0})
    slots = score.to_slots()
    assert slots[SHAPE.index("song", "grain")] == 0
    assert slots[SHAPE.index("song", "palette_shift")] == MASK
    back = Score.from_slots(SHAPE, slots)
    assert back.song["grain"] == 0
    assert "palette_shift" not in back.song


# --------------------------------------------------------------------------- #
# Legality
# --------------------------------------------------------------------------- #


def test_random_fill_is_always_legal():
    for seed in range(40):
        slots = schema.random_fill(SHAPE, seed)
        assert schema.is_legal(SHAPE, slots), schema.violations(SHAPE, slots)


def test_determinism_same_seed_same_score():
    a = schema.random_fill(SHAPE, 11)
    b = schema.random_fill(SHAPE, 11)
    assert np.array_equal(a, b)
    assert a.tobytes() == b.tobytes()
    # And the bytes on disk match too, which is what "deterministic" has to mean
    # for a score a person may have kept.
    left = json.dumps(Score.from_slots(SHAPE, a, track="x", seed=11).to_dict(), indent=1)
    right = json.dumps(Score.from_slots(SHAPE, b, track="x", seed=11).to_dict(), indent=1)
    assert left == right
    assert not np.array_equal(a, schema.random_fill(SHAPE, 12))


def test_kaleidoscope_needs_a_radial_motif():
    slots = np.full(SHAPE.n_slots, MASK, dtype=np.int16)
    si = SHAPE.index("song", "symmetry")

    slots[SHAPE.index("song", "motif")] = schema.MOTIFS.index("bar")
    allow = schema.legal_values(SHAPE, slots, si)
    assert not allow[schema.SYMMETRIES.index("kaleido_6")]
    assert allow[schema.SYMMETRIES.index("mirror_x")]

    slots[SHAPE.index("song", "motif")] = schema.MOTIFS.index("star")
    assert schema.legal_values(SHAPE, slots, si).all()


def test_scene_must_come_from_the_block_set():
    slots = np.full(SHAPE.n_slots, MASK, dtype=np.int16)
    slots[SHAPE.index("song", "block_set")] = schema.BLOCK_SETS.index("linear")
    allow = schema.legal_values(SHAPE, slots, SHAPE.index("section", "scene", 1))
    legal = {schema.SCENES[i] for i, ok in enumerate(allow) if ok}
    assert legal == set(schema.BLOCK_SET_SCENES["linear"])


def test_every_scene_is_a_point_in_layer_space():
    """A scene names a vector, which is what makes any two of them blendable."""
    for name, weights in schema.SCENE_LAYERS.items():
        assert len(weights) == len(schema.LAYERS), name
        assert all(0.0 <= w <= 1.0 for w in weights), name
        assert sum(weights) > 0.0, f"{name} draws nothing"
    assert set(schema.SCENES) == set(schema.SCENE_LAYERS)
    # And every scene some block set admits is one that exists.
    for block_set, scenes in schema.BLOCK_SET_SCENES.items():
        assert set(scenes) <= set(schema.SCENES), block_set


def test_a_still_song_may_not_churn_or_trail():
    slots = np.full(SHAPE.n_slots, MASK, dtype=np.int16)
    slots[SHAPE.index("song", "motion_character")] = schema.MOTION_CHARACTERS.index("still")
    warp = schema.legal_values(SHAPE, slots, SHAPE.index("section", "warp", 0))
    assert {schema.WARPS[i] for i, ok in enumerate(warp) if ok} == set(schema.STILL_WARPS)
    post = schema.legal_values(SHAPE, slots, SHAPE.index("section", "post", 0))
    trails = schema.POST_STAGES.index("trails")
    for i, ok in enumerate(post):
        if ok:
            assert schema.POST_WEIGHTS[schema.POSTS[i]][trails] == 0.0, schema.POSTS[i]


def test_mono_pins_the_palette_rotation():
    slots = np.full(SHAPE.n_slots, MASK, dtype=np.int16)
    i = SHAPE.index("section", "palette_rotate", 2)
    slots[SHAPE.index("song", "palette_family")] = schema.PALETTE_FAMILIES.index("mono")
    allow = schema.legal_values(SHAPE, slots, i)
    assert allow.sum() == 1 and allow[0]
    slots[SHAPE.index("song", "palette_family")] = schema.PALETTE_FAMILIES.index("ice")
    assert schema.legal_values(SHAPE, slots, i).all()


def test_the_song_does_not_open_on_a_one_bar_ramp():
    """A one-bar ramp out of darkness is a cut with extra steps."""
    slots = np.full(SHAPE.n_slots, MASK, dtype=np.int16)
    allow = schema.legal_values(SHAPE, slots, SHAPE.index("section", "transition_bars", 0))
    assert not allow[schema.TRANSITION_BARS.index("1")]
    assert allow[schema.TRANSITION_BARS.index("8")]
    assert schema.legal_values(SHAPE, slots, SHAPE.index("section", "transition_bars", 1)).all()


def test_every_transition_curve_starts_at_nought_and_ends_at_one():
    """A ramp that did not arrive would leave the section it introduced wrong."""
    from visuals.uniforms import curve

    x = np.linspace(0.0, 1.0, 101)
    for kind in schema.TRANSITION_CURVES:
        y = curve(x, kind)
        assert y[0] == pytest.approx(0.0, abs=1e-9), kind
        assert y[-1] == pytest.approx(1.0, abs=1e-9), kind
        assert np.all(np.diff(y) >= -1e-9), f"{kind} goes backwards"
        assert np.all((y >= 0.0) & (y <= 1.0)), kind
    # Past the window it stays arrived, and before it, at rest.
    assert curve(np.array([-0.5, 1.5]), "ease").tolist() == [0.0, 1.0]


def test_a_silent_lane_keeps_every_slot_silent():
    slots = np.full(SHAPE.n_slots, MASK, dtype=np.int16)
    slots[SHAPE.index("bar", "route_source_b", 5)] = schema.ROUTE_SOURCES.index("none")
    for name, expect in (("route_target_b", 1), ("route_gain_b", 1), ("route_env_b", 1)):
        allow = schema.legal_values(SHAPE, slots, SHAPE.index("bar", name, 5))
        assert allow.sum() == expect and allow[0]
    # The other lanes of the same bar are untouched.
    assert schema.legal_values(SHAPE, slots, SHAPE.index("bar", "route_gain_a", 5)).all()


def test_a_driven_lane_may_not_be_pointed_at_nothing():
    slots = np.full(SHAPE.n_slots, MASK, dtype=np.int16)
    slots[SHAPE.index("bar", "route_source_a", 2)] = schema.ROUTE_SOURCES.index("vocal")
    allow = schema.legal_values(SHAPE, slots, SHAPE.index("bar", "route_target_a", 2))
    assert not allow[schema.ROUTE_TARGETS.index("none")]
    assert allow.sum() == len(schema.ROUTE_TARGETS) - 1


def test_two_lanes_of_one_bar_cannot_claim_the_same_uniform():
    slots = np.full(SHAPE.n_slots, MASK, dtype=np.int16)
    hue = schema.ROUTE_TARGETS.index("hue")
    slots[SHAPE.index("bar", "route_target_a", 9)] = hue
    assert not schema.legal_values(SHAPE, slots, SHAPE.index("bar", "route_target_b", 9))[hue]
    # A different bar is free to use it.
    assert schema.legal_values(SHAPE, slots, SHAPE.index("bar", "route_target_b", 10))[hue]


def test_an_unfilled_dependency_leaves_everything_open():
    """Legality is monotone: deciding a slot can only narrow what is legal."""
    empty = np.full(SHAPE.n_slots, MASK, dtype=np.int16)
    i = SHAPE.index("section", "warp", 3)
    wide = schema.legal_values(SHAPE, empty, i)
    assert wide.all()
    for c in range(len(schema.MOTION_CHARACTERS)):
        slots = empty.copy()
        slots[SHAPE.index("song", "motion_character")] = c
        assert (schema.legal_values(SHAPE, slots, i) <= wide).all()


def test_violations_name_every_illegal_slot():
    slots = schema.random_fill(SHAPE, 5)
    slots[SHAPE.index("song", "motif")] = schema.MOTIFS.index("bar")
    slots[SHAPE.index("song", "symmetry")] = schema.SYMMETRIES.index("kaleido_5")
    slots[SHAPE.index("bar", "route_source_a", 0)] = schema.ROUTE_SOURCES.index("none")
    slots[SHAPE.index("bar", "route_target_a", 0)] = schema.ROUTE_TARGETS.index("hue")
    bad = schema.violations(SHAPE, slots)
    assert any("symmetry" in v for v in bad)
    assert any("bar 0.route_target_a" in v for v in bad)
    assert not schema.is_legal(SHAPE, slots)


def test_filling_around_locked_slots_keeps_them():
    """Locking part of a score and infilling the rest is one call."""
    score = Score(SHAPE, song={"palette_family": "ice", "motif": "hex"})
    filled = score.filled(seed=2)
    assert filled.song["palette_family"] == "ice"
    assert filled.song["motif"] == "hex"
    assert filled.is_complete() and not filled.violations()
    # Twice from the same seed is the same score, locks and all.
    assert np.array_equal(filled.to_slots(), score.filled(seed=2).to_slots())


def test_unknown_slot_names_are_refused():
    with pytest.raises(ValueError, match="unknown song slot"):
        Score(SHAPE, song={"paelette_family": "ice"}).to_slots()
    with pytest.raises(ValueError, match="not one of"):
        Score(SHAPE, song={"palette_family": "chartreuse"}).to_slots()
