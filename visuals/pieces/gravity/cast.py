"""Casting: which instrument plays which part of the theme, for this song.

The theme's parts want kinds of signal, not stems. Each part names its candidates in
order; the first one that is really there plays it. A part nothing can play is cast
silent, with the reason, and is never fed leakage. The sheet says who plays what and
why, and the scorecard prints it.

    pulse     the kick
    ring      the snare or clap
    stars     the hats
    corona    the bass line
    planets   the synths' notes
    heart     the voice; when nothing sings, the synths' lead line (Jugal, 2026-09-20)

Casting rewrites the inputs the directing code reads - listening's arrays, the models'
melody - so direct.py and cosmos.py need not know it happened.
"""

from __future__ import annotations

import numpy as np

from .listen import RATE, smooth, trailing_max

MIN_PLAYS = 0.05             # a stem playing in fewer bars than this is not there
MIN_EVENTS = 16              # nor is a part with fewer events than this in the song
LEAD_MIN = 0.10              # a lead line must cover this much of the song to take the heart
NOTE_CHANGE = 0.7            # semitones: the lead has moved to a new note
NOTE_HOLD = 0.06             # s: ...and stayed there
SNAP = 0.045                 # s: models say what, stems say when


def _plays(got: dict, stem: str) -> float:
    return float(got["meta"].get("presence", {}).get(stem, {}).get("playing", 1.0))


def _first_choice(got: dict, part: str, kind: str, stem: str) -> dict:
    plays, n = _plays(got, stem), len(got["arrays"][f"ev_{kind}_t"])
    if plays >= MIN_PLAYS and n >= MIN_EVENTS:
        return {"source": stem, "why": f"the {kind.replace('_', ' ')}s", "plays": plays, "events": n}
    return {"source": stem, "silent": True, "plays": plays, "events": n,
            "why": f"no {kind.replace('_', ' ')}s: {stem} plays in {plays:.2f} of bars, {n} events"}


def lead_onsets(t: np.ndarray, st: np.ndarray, keep: np.ndarray,
                att_t: np.ndarray, att_a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Where the lead line starts a note: each phrase's first, and every move of at least
    NOTE_CHANGE semitones that holds NOTE_HOLD - each timed by the synths' own attack
    within SNAP of it (none, and it is not a note)."""
    if not keep.any() or not len(att_t):
        return np.zeros(0), np.zeros(0, np.float32)
    dt = float(np.median(np.diff(t)))
    w = max(1, int(round(NOTE_HOLD / dt)))
    win = np.lib.stride_tricks.sliding_window_view(np.concatenate([np.full(w, st[0]), st, np.full(w, st[-1])]), w)
    before, after = np.median(win[: len(st)], axis=1), np.median(win[w: w + len(st)], axis=1)
    moved = (np.abs(after - before) >= NOTE_CHANGE) & keep
    starts = keep & ~np.concatenate([[False], keep[:-1]])
    cand = t[np.flatnonzero(starts | (moved & ~np.concatenate([[False], moved[:-1]])))]
    j = np.clip(np.searchsorted(att_t, cand), 1, len(att_t) - 1)
    near = np.where(np.abs(cand - att_t[j - 1]) < np.abs(cand - att_t[j]), j - 1, j)
    ok = np.abs(att_t[near] - cand) < SNAP
    idx = np.unique(near[ok])
    inside = np.interp(att_t[idx], t, keep.astype(float)) > 0.5      # a lead note sounds in a phrase
    return att_t[idx][inside], att_a[idx][inside]


def heart_from_lead(got: dict, mod: tuple[dict, dict]) -> tuple[dict, dict, dict]:
    """The voice's inputs, made from the synths' lead line: its level where it is in a
    phrase, its notes as syllables, its melody as the sung pitch."""
    a, m = dict(got["arrays"]), dict(mod[0])
    n = len(a["voice"])
    t = np.arange(n) / RATE
    lt, lst, keep = m["lead_t"], m["lead_st"].astype(np.float64), m["lead_keep"].astype(bool)
    phrase = np.clip(smooth(np.interp(t, lt, keep.astype(float)), RATE, 0.10), 0.0, 1.0)
    level = (a["other"].astype(np.float64) * phrase).astype(np.float32)
    a["voice"] = level
    beat = float(got["meta"]["period"])
    a["voice_presence"] = np.clip(smooth(trailing_max(level, int(2 * beat * RATE)), RATE, 0.6), 0, 1).astype(np.float32)
    centre = float(np.median(lst[keep]))
    a["voice_pitch"] = (np.clip(np.interp(t, lt, lst - centre) / 12.0, -1, 1) * phrase).astype(np.float32)
    on_t, on_a = lead_onsets(lt, lst, keep, a["ev_note_t"], a["ev_note_amp"])
    a["ev_syllable_t"], a["ev_syllable_amp"] = on_t.astype(np.float64), on_a.astype(np.float32)
    m["f0_t"], m["f0_hz"] = lt, (220.0 * 2.0 ** (lst / 12.0)).astype(np.float32)
    m["f0_conf"] = np.where(keep, 1.0, 0.0).astype(np.float32)
    info = {"notes": int(len(on_t)), "notes_per_s_in_phrases": float(len(on_t) / max(keep.mean() * got["meta"]["duration"], 1e-9))}
    return {"arrays": a, "meta": got["meta"]}, m, info


def apply(got: dict, mod: tuple[dict, dict] | None) -> tuple[dict, tuple[dict, dict] | None, dict]:
    """The listening and models as the directing code should read them, and the sheet."""
    sheet = {part: _first_choice(got, part, kind, stem) for part, kind, stem in (
        ("pulse", "kick", "drums"), ("ring", "snare", "drums"), ("stars", "hat", "drums"),
        ("corona", "bass_note", "bass"), ("planets", "note", "other"))}
    voice = _first_choice(got, "heart", "syllable", "vocals")
    lead_covers = float(mod[0]["lead_keep"].mean()) if mod and "lead_keep" in mod[0] else 0.0
    if not voice.get("silent"):
        sheet["heart"] = {**voice, "why": "the voice"}
    elif lead_covers >= LEAD_MIN and not sheet["planets"].get("silent"):
        got, m_arr, info = heart_from_lead(got, mod)
        mod = (m_arr, mod[1])
        sheet["heart"] = {"source": "other", "why": f"nothing sings: the synths' lead line, in {lead_covers:.2f} of the song",
                          "plays": _plays(got, "other"), "events": info["notes"], **info}
        sheet["planets"]["why"] += "; shares the synths with the heart"
    else:
        sheet["heart"] = {**voice, "why": voice["why"] + f"; and no lead line (covers {lead_covers:.2f})"}
    return got, mod, sheet
