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


# Each part's candidates, by the word the direction sheet uses for them, in the order they
# are tried: the first is the part's own instrument, the rest stand in for it.
CHOICES = {
    "pulse": ("kick", "bass-on-beat", "low-end-on-beat", "beat", "silent"),
    "ring": ("snare", "backbeat-accents", "silent"),
    "stars": ("hats", "synth-highs", "mix-highs", "silent"),
    "corona": ("bass", "synth-lows", "silent"),
    "planets": ("synths", "silent"),
    "heart": ("voice", "lead-synth", "silent"),
}
OWN = {"pulse": ("kick", "drums"), "ring": ("snare", "drums"), "stars": ("hat", "drums"),
       "corona": ("bass_note", "bass"), "planets": ("note", "other"), "heart": ("syllable", "vocals")}


def _silence(part: str, a: dict, m: dict) -> None:
    """A part that nothing plays: nothing of it is left to move the picture."""
    kind = OWN[part][0]
    a[f"ev_{kind}_t"], a[f"ev_{kind}_amp"] = np.zeros(0), np.zeros(0, np.float32)
    if part == "ring":
        a["ev_snare_bright"] = np.zeros(0, np.float32)
    if part == "planets":
        a["ev_note_pitch"] = np.zeros(0, np.float32)
        for k in ("t", "end", "midi", "amp"):
            if f"other_{k}" in m:
                m[f"other_{k}"] = m[f"other_{k}"][:0]
    if part == "corona":
        if "bass" in a:
            a["bass"] = np.zeros_like(a["bass"])
        for k in ("t", "end", "midi", "amp"):
            if f"bass_{k}" in m:
                m[f"bass_{k}"] = m[f"bass_{k}"][:0]
    if part == "heart":
        for k in ("voice", "voice_presence", "voice_pitch"):
            if k in a:
                a[k] = np.zeros_like(a[k])
        if "f0_conf" in m:
            m["f0_conf"] = np.zeros_like(m["f0_conf"])


def _candidate(part: str, token: str, got: dict, a: dict, m: dict) -> tuple[np.ndarray, dict] | None:
    """What `token` would give `part`: the events it would play (for judging it) and a
    function that puts them in place. None when there is nothing to take it from."""
    beats, downbeats = a["beats"], a["downbeats"]
    meter = int(got["meta"].get("meter", 4))
    kind = OWN[part][0]
    if token == CHOICES[part][0] or token == "silent":
        return a[f"ev_{kind}_t"], {}
    if part == "pulse":
        if token == "bass-on-beat":
            t, amp = on_beats(a["ev_bass_note_t"], a["ev_bass_note_amp"], beats)
            return t, {"kick": (t, amp)}
        if token == "low-end-on-beat":
            t, amp = on_beats(a.get("ev_mixlow_t", np.zeros(0)), a.get("ev_mixlow_amp", np.zeros(0)), beats)
            return t, {"kick": (t, amp)}
        if token == "beat":
            loud = a["loud"][np.clip((beats * RATE).astype(int), 0, len(a["loud"]) - 1)] > 0.35
            down = np.isin(np.arange(len(beats)), _nearest(beats, downbeats))
            t = beats[loud]
            return t, {"kick_small": (t, np.where(down[loud], 0.6, 0.35).astype(np.float32))}
    if part == "ring" and token == "backbeat-accents":
        t, amp = backbeats(a.get("ev_mixmid_t", np.zeros(0)), a.get("ev_mixmid_amp", np.zeros(0)), beats, downbeats, meter)
        return t, {"snare": (t, amp)}
    if part == "stars" and token in ("synth-highs", "mix-highs"):
        key = "otherhi" if token == "synth-highs" else "mixhi"
        t, amp = a.get(f"ev_{key}_t", np.zeros(0)), a.get(f"ev_{key}_amp", np.zeros(0))
        return t, {"hat": (t, amp)}
    if part == "corona" and token == "synth-lows":
        if "other_midi" not in m or not len(m["other_midi"]):
            return None
        split = min(float(np.percentile(m["other_midi"], 33)), 60.0)
        low = m["other_midi"] <= split
        return m["other_t"][low], {"synth_lows": (low, split)}
    if part == "heart" and token == "lead-synth":
        if "lead_keep" not in m:
            return None
        return m["lead_t"][m["lead_keep"]], {"lead": True}
    return None


def _take(part: str, token: str, got: dict, a: dict, m: dict, how: dict) -> dict:
    """Put a candidate in place; returns what the sheet should say about it."""
    info: dict = {}
    if token == "silent":
        _silence(part, a, m)
    elif "kick" in how:
        _events(a, "kick", *how["kick"])
    elif "kick_small" in how:
        t, amp = how["kick_small"]
        a["ev_kick_t"], a["ev_kick_amp"] = np.asarray(t, np.float64), amp          # small, as said: not scaled up
    elif "snare" in how:
        _events(a, "snare", *how["snare"])
        a["ev_snare_bright"] = np.full(len(how["snare"][0]), 0.5, np.float32)
    elif "hat" in how:
        _events(a, "hat", *how["hat"])
    elif "synth_lows" in how:
        low, split = how["synth_lows"]
        _events(a, "bass_note", m["other_t"][low], m["other_amp"][low])
        for k in ("t", "end", "midi", "amp"):
            m[f"bass_{k}"] = m[f"other_{k}"][low]
        a["bass"] = a["other_low"]
        info["split_midi"] = split
    elif "lead" in how:
        g2, m2, info = heart_from_lead({"arrays": a, "meta": got["meta"]}, (m, {}))
        a.update(g2["arrays"]); m.update(m2)
    return info


WHY = {"kick": "the kicks", "snare": "the snares", "hats": "the hats", "bass": "the bass notes",
       "synths": "the notes", "voice": "the voice", "bass-on-beat": "bass attacks on the beat",
       "low-end-on-beat": "the mix's low end on the beat", "beat": "the beat itself, small",
       "backbeat-accents": "the mix's accents on the backbeat, the stronger half",
       "synth-highs": "the synths' high band", "mix-highs": "the mix's high band",
       "synth-lows": "the synths' low notes", "lead-synth": "nothing sings: the synths' lead line"}
SOURCE = {"kick": "drums", "snare": "drums", "hats": "drums", "bass": "bass", "synths": "other", "voice": "vocals",
          "bass-on-beat": "bass", "low-end-on-beat": "mix", "beat": "grid", "backbeat-accents": "mix",
          "synth-highs": "other", "mix-highs": "mix", "synth-lows": "other", "lead-synth": "other", "silent": "none"}


def apply(got: dict, mod: tuple[dict, dict] | None, choose: dict | None = None) -> tuple[dict, tuple[dict, dict] | None, dict]:
    """The listening and models as the directing code should read them, and the cast.

    Without `choose`, each part gets its own instrument if it is really there (playing in
    MIN_PLAYS of the bars, MIN_EVENTS events), else the first stand-in that is (events in
    FALLBACK_BARS of the bars), else silence - and the heart, when nothing sings, the synths'
    lead line. With `choose` (the direction sheet's `cast`), a part gets what it names."""
    a, m = dict(got["arrays"]), dict(mod[0]) if mod else {}
    bars = a["bar_t"]
    choose = choose or {}
    own = {part: _first_choice(got, part, *OWN[part]) for part in CHOICES}
    lead_covers = float(m["lead_keep"].mean()) if "lead_keep" in m else 0.0
    sheet: dict = {}
    # the heart first (the lead is taken from the synths as they are), then the others in order;
    # the pulse's stand-ins read the bass before the corona's may replace it
    for part in ("heart", "pulse", "ring", "stars", "corona", "planets"):
        if part in choose:
            token = choose[part]
            if token not in CHOICES[part]:
                raise ValueError(f"cast: {part} cannot be {token!r}; it can be {', '.join(CHOICES[part])}")
            got_ = _candidate(part, token, got, a, m)
            if got_ is None:
                token, got_ = "silent", (np.zeros(0), {})
            why = f"chosen: {WHY.get(token, token)}"
        elif part == "heart":
            if not own["heart"].get("silent"):
                token = "voice"
            elif lead_covers >= LEAD_MIN and not own["planets"].get("silent"):
                token = "lead-synth"
            else:
                token = "silent"
            got_ = _candidate(part, token, got, a, m)
            why = WHY.get(token, own["heart"]["why"] + f"; and no lead line (covers {lead_covers:.2f})")
            if token == "lead-synth":
                why += f", in {lead_covers:.2f} of the song"
        else:
            token, got_ = "silent", None
            if not own[part].get("silent"):
                token = CHOICES[part][0]
            else:
                for cand in CHOICES[part][1:-1]:
                    c = _candidate(part, cand, got, a, m)
                    if c is not None and _stand_in(c[0], bars):
                        token = cand
                        break
            got_ = _candidate(part, token, got, a, m) or (np.zeros(0), {})
            why = WHY.get(token, own[part]["why"])
        info = _take(part, token, got, a, m, got_[1])
        n_ev = len(a[f"ev_{OWN[part][0]}_t"])
        src = SOURCE[token]
        sheet[part] = {"choice": token, "source": src, "why": why, "events": int(n_ev),
                       "plays": _plays(got, src) if src in ("drums", "bass", "other", "vocals") else 1.0,
                       "stand_in": token not in (CHOICES[part][0], "silent"), **info}
        if token == "silent":
            sheet[part]["silent"] = True
    if sheet["heart"]["choice"] == "lead-synth" and sheet["planets"]["choice"] == "synths":
        sheet["planets"]["why"] += "; shares the synths with the heart"
    return {"arrays": a, "meta": got["meta"]}, ((m, mod[1]) if mod else mod), sheet
