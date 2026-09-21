"""Casting: which instrument plays which part of the theme, for this song.

The theme's parts want kinds of signal, not stems. Each part names its candidates in
order; the first one that is really there plays it. A part nothing can play is cast
silent, with the reason, and is never fed leakage. The sheet says who plays what and
why, and the scorecard prints it.

    pulse     the kick; bass attacks on the beat; the mix's low end on the beat; the beat itself, small
    ring      the snare or clap; the mix's strongest accents on the backbeat, rarer
    stars     the hats; the synths' high band; the mix's high band
    corona    the bass line; the synths' low notes
    planets   the synths' notes
    heart     the voice; when nothing sings, the synths' lead line (Jugal, 2026-09-20)

A fallback has to be there for real: at least MIN_EVENTS events, in at least FALLBACK_BARS
of the bars. The first choices keep the looser rule they always had.

Casting rewrites the inputs the directing code reads - listening's arrays, the models'
melody - so direct.py and cosmos.py need not know it happened.
"""

from __future__ import annotations

import numpy as np

from .listen import RATE, smooth, trailing_max

# A stem playing in fewer bars than this is not there. Real drums play in 77-97 % of the
# bars of three songs; with the drums taken out, their leakage still "plays" in 3-5 %.
MIN_PLAYS = 0.15
MIN_EVENTS = 16              # nor is a part with fewer events than this in the song
LEAD_MIN = 0.10              # a lead line must cover this much of the song to take the heart
NOTE_CHANGE = 0.7            # semitones: the lead has moved to a new note
NOTE_HOLD = 0.06             # s: ...and stayed there
SNAP = 0.045                 # s: models say what, stems say when
FALLBACK_BARS = 0.20         # a stand-in must play in this share of the bars
ON_BEAT = 0.040              # s


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


def _norm(amp: np.ndarray) -> np.ndarray:
    """Sizes as listening gives them - the 90th percentile is 1 - and no bigger than 1.1,
    about the most Gravity's own kicks and claps reach: a stand-in's sizes spread wider
    (Gravity without drums: 29 % of its bass pulses past the range the picture was made in)."""
    amp = np.asarray(amp, np.float64)
    if not len(amp):
        return amp.astype(np.float32)
    return np.clip(amp / max(float(np.percentile(amp, 90)), 1e-9), 0.0, 1.1).astype(np.float32)


def _nearest(beats: np.ndarray, t: np.ndarray) -> np.ndarray:
    j = np.clip(np.searchsorted(beats, t), 1, len(beats) - 1)
    return np.where(np.abs(t - beats[j - 1]) < np.abs(t - beats[j]), j - 1, j)


def on_beats(t: np.ndarray, amp: np.ndarray, beats: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The attacks that land on a beat."""
    if not len(t):
        return t, amp
    k = np.abs(t - beats[_nearest(beats, t)]) < ON_BEAT
    return t[k], amp[k]


def backbeats(t: np.ndarray, amp: np.ndarray, beats: np.ndarray, downbeats: np.ndarray,
              meter: int) -> tuple[np.ndarray, np.ndarray]:
    """The strongest accent on each backbeat - 2 and 4 in four, any beat but the one in an
    odd meter - keeping the stronger half, so the rings are rarer than a snare's."""
    if not len(t):
        return t, amp
    down = np.unique(_nearest(beats, downbeats))
    idx = np.arange(len(beats))
    pos = idx - down[np.clip(np.searchsorted(down, idx, side="right") - 1, 0, len(down) - 1)]   # beats since the bar began
    back = (pos % 2 == 1) if meter % 2 == 0 else (pos % meter != 0)
    j = _nearest(beats, t)
    k = back[j] & (np.abs(t - beats[j]) < ON_BEAT)
    best: dict[int, int] = {}
    for i in np.flatnonzero(k):
        if j[i] not in best or amp[i] > amp[best[j[i]]]:
            best[j[i]] = i
    idx = np.array(sorted(best.values()), int)
    if not len(idx):
        return t[:0], amp[:0]
    strong = amp[idx] >= np.median(amp[idx])
    return t[idx][strong], amp[idx][strong]


def _bars_with(t: np.ndarray, bars: np.ndarray) -> float:
    if not len(t) or not len(bars):
        return 0.0
    return len(np.unique(np.clip(np.searchsorted(bars, t, side="right") - 1, 0, len(bars) - 1))) / len(bars)


def _stand_in(t: np.ndarray, bars: np.ndarray) -> bool:
    return len(t) >= MIN_EVENTS and _bars_with(t, bars) >= FALLBACK_BARS


def _events(a: dict, kind: str, t: np.ndarray, amp: np.ndarray) -> None:
    a[f"ev_{kind}_t"], a[f"ev_{kind}_amp"] = np.asarray(t, np.float64), _norm(amp)


def stand_ins(got: dict, mod: tuple[dict, dict] | None, sheet: dict) -> tuple[dict, tuple[dict, dict] | None]:
    """For each part whose first choice is silent, the first stand-in that is really there."""
    a, m = dict(got["arrays"]), dict(mod[0]) if mod else {}
    meta = got["meta"]
    beats, downbeats, bars = a["beats"], a["downbeats"], a["bar_t"]
    meter = int(meta.get("meter", 4))

    def take(part: str, why: str, source: str, t: np.ndarray) -> None:
        sheet[part] = {"source": source, "why": why, "stand_in": True, "events": int(len(t)),
                       "plays": _plays(got, source) if source in ("drums", "bass", "other", "vocals") else 1.0,
                       "first_choice": sheet[part]["why"]}

    if sheet["pulse"].get("silent"):
        loud = a["loud"][np.clip((beats * RATE).astype(int), 0, len(a["loud"]) - 1)] > 0.35
        down = np.isin(np.arange(len(beats)), _nearest(beats, downbeats))
        for why, source, (t, amp) in (
                ("bass attacks on the beat", "bass", on_beats(a["ev_bass_note_t"], a["ev_bass_note_amp"], beats)),
                ("the mix's low end on the beat", "mix", on_beats(a.get("ev_mixlow_t", np.zeros(0)), a.get("ev_mixlow_amp", np.zeros(0)), beats)),
                ("the beat itself, small", "grid", (beats[loud], np.where(down[loud], 0.6, 0.35)))):
            if _stand_in(t, bars):
                _events(a, "kick", t, amp)
                if source == "grid":
                    a["ev_kick_amp"] = np.asarray(amp, np.float32)          # small, as said: not scaled up
                take("pulse", why, source, t)
                break

    if sheet["ring"].get("silent"):
        t, amp = backbeats(a.get("ev_mixmid_t", np.zeros(0)), a.get("ev_mixmid_amp", np.zeros(0)), beats, downbeats, meter)
        if _stand_in(t, bars):
            _events(a, "snare", t, amp)
            a["ev_snare_bright"] = np.full(len(t), 0.5, np.float32)
            take("ring", "the mix's accents on the backbeat, the stronger half", "mix", t)

    if sheet["stars"].get("silent"):
        for why, source, key in (("the synths' high band", "other", "otherhi"), ("the mix's high band", "mix", "mixhi")):
            t, amp = a.get(f"ev_{key}_t", np.zeros(0)), a.get(f"ev_{key}_amp", np.zeros(0))
            if _stand_in(t, bars):
                _events(a, "hat", t, amp)
                take("stars", why, source, t)
                break

    if sheet["corona"].get("silent") and "other_midi" in m and len(m["other_midi"]):
        split = min(float(np.percentile(m["other_midi"], 33)), 60.0)
        low = m["other_midi"] <= split
        t = m["other_t"][low]
        if _stand_in(t, bars):
            _events(a, "bass_note", t, m["other_amp"][low])
            for k in ("t", "end", "midi", "amp"):
                m[f"bass_{k}"] = m[f"other_{k}"][low]
            a["bass"] = a["other_low"]
            take("corona", f"the synths' low notes (MIDI {split:.0f} and under)", "other", t)

    return {"arrays": a, "meta": meta}, ((m, mod[1]) if mod else mod)


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
    got, mod = stand_ins(got, mod, sheet)
    return got, mod, sheet
