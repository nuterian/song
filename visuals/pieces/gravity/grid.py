"""Where every beat and bar of a song is, and how sure that is.

Two sources, in order of trust:

  lattice   The song is on a machine grid: its sharp percussion (hats, claps) lies on one
            constant-tempo lattice to a millisecond. The lattice's spacing comes from a
            scan of how well the hits line up at every spacing; which multiple of it is
            the beat comes from Beat This!, whose tempo is coarse but whose octave is
            right; then `fit_grid` refines both by least squares. Used only when at least
            half the sharp hits fall within 4 ms of the result, and - if Beat This! is
            steady enough to be a referee - half its beats agree.
  tracked   Otherwise - no drums, live playing, a tempo that moves: Beat This!'s beats,
            less its own lateness (the mode of how far the song's onsets sit from them),
            each snapped to an onset within 25 ms when the snap agrees with its
            neighbours' local tempo. It follows a changing tempo.

The meter (beats in a bar) is Beat This!'s. The bar's phase comes from where the kick
re-enters after a rest, when there are at least four such re-entries and three quarters
of them agree; otherwise from Beat This!'s downbeats.

Why a scan: the fit only locks on from within about 0.1 % of the true tempo, and the
old starting point - the median gap between kicks - is not a beat when a kick doubles
(Shattered Voices: 125.39 BPM with 7 % of the hats on it; it is 90.00).
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

GATE = 0.5                   # sharp hits within 4 ms of the lattice, for it to be trusted...
BT_GATE = 0.5                # ...and, if Beat This! is steady, its beats within 25 ms of it
BT_STEADY = 0.8              # Beat This! is steady when this share of its beat gaps is within 5 % of the median
ON_LATTICE = 0.004           # s
MIN_SHARP = 32               # fewer sharp hits than this and there is no lattice to find
OCTAVE_TOL = 0.06            # a lattice beat within 6 % of Beat This!'s
SUBDIVISIONS = (1, 2, 3, 4, 6, 8)


def tracked_beats(mix: np.ndarray, sr: int) -> dict[str, np.ndarray]:
    """Beat This! (MIT, local). Its beats sit on 20 ms frames and read 14-38 ms late."""
    from beat_this.inference import Audio2Beats

    beats, downbeats = Audio2Beats(checkpoint_path="final0", device="cpu", dbn=False)(
        mix.astype(np.float32), sr)
    return {"beats": np.asarray(beats, dtype=np.float64),
            "downbeats": np.asarray(downbeats, dtype=np.float64)}


# --------------------------------------------------------------------- the lattice


def coherence(t: np.ndarray, q: np.ndarray) -> np.ndarray:
    """|mean(exp(2 pi i t / q))| for each spacing q: 1 when every hit is on a multiple of q."""
    c = np.empty(len(q))
    for i in range(0, len(q), 2000):
        c[i:i + 2000] = np.abs(np.exp(2j * np.pi * t[None, :] / q[i:i + 2000, None]).mean(axis=1))
    return c


def lattice_scan(sharp: np.ndarray, lo: float = 0.075, hi: float = 0.25,
                 peaks: int = 4) -> list[tuple[float, float]]:
    """Lattice spacings (s) the hits line up on, best first, with how well (0..1).

    Finer lattices of the same family fit as well in principle and worse in practice
    (jitter counts for more against a smaller step), coarser ones cancel, so the best
    spacing is the one the playing is written on. A peak over the whole song is only
    about q^2 / 2D wide (25 us for five minutes), so the search is coarse over 30 s
    stretches first - where peaks are wide - and then fine, with every hit, around
    each candidate."""
    seg = np.floor(sharp / 30.0)
    parts = [sharp[seg == s] for s in np.unique(seg) if (seg == s).sum() >= 8] or [sharp]
    q = np.arange(lo, hi, 5e-5)
    c = sum(len(p) * coherence(p, q) for p in parts) / sum(len(p) for p in parts)
    span = max(float(sharp.max() - sharp.min()), 1.0)
    found: list[tuple[float, float]] = []
    for i in np.argsort(c)[::-1]:
        if any(abs(q[i] - f) / f < 0.01 for f, _ in found):
            continue
        fine = np.arange(q[i] * 0.996, q[i] * 1.004, q[i] ** 2 / (10 * span))
        cf = coherence(sharp, fine)
        found.append((float(fine[cf.argmax()]), float(cf.max())))
        if len(found) == 2 * peaks:
            break
    return sorted(found, key=lambda x: -x[1])[:peaks]


def beat_multiple(spacing: float, bt_period: float) -> int | None:
    """How many lattice steps make Beat This!'s beat, if a whole number does."""
    best = min(SUBDIVISIONS, key=lambda j: abs(np.log(j * spacing / bt_period)))
    return best if abs(best * spacing / bt_period - 1.0) < OCTAVE_TOL else None


def fit_grid(sharp: np.ndarray, kicks: np.ndarray, duration: float,
             period_hint: float, div: int = 4, meter: int = 4) -> dict:
    """A constant-tempo grid through the sharp percussion, phased by the kick.

    Hats and claps have attacks a millisecond long, so they say where the grid is.
    `sharp` is fitted on a lattice of `div` steps a beat by iterated least squares over
    the inliers. The bar phase is the kick's: where it comes back after at least two
    bars without it, a drop lands on a downbeat.
    """
    T = period_hint
    # Phase of the lattice at the hint, then refine period and phase together.
    q = T / div
    z = np.exp(2j * np.pi * sharp / q).mean()
    t0 = (np.angle(z) / (2 * np.pi)) * q
    # Coarse to fine, then on until the inliers stop changing: a fixed point, so the
    # grid does not depend on where the fit started (three passes alone stopped 13 us
    # short of it on Gravity).
    prev = None
    for it in range(40):
        tol = (0.012, 0.006)[it] if it < 2 else ON_LATTICE
        q = T / div
        idx = np.round((sharp - t0) / q)
        ok = np.abs(sharp - (t0 + idx * q)) < tol
        if prev is not None and np.array_equal(ok, prev):
            break
        prev = ok if it >= 2 else None
        slope, icpt = np.polyfit(idx[ok], sharp[ok], 1)
        T, t0 = div * slope, icpt
    q = T / div
    idx = np.round((sharp - t0) / q)
    resid = sharp - (t0 + idx * q)
    ok = np.abs(resid) < ON_LATTICE

    # t0 is on the sub-beat lattice; move it onto a beat using the kicks, whose
    # (late-reading) times still sit far closer to a beat than to any other step.
    kq = np.round((kicks - t0) / q).astype(int)
    t0 += q * int(np.bincount(kq % div, minlength=div).argmax()) if len(kq) else 0.0
    t0 -= T * np.floor(t0 / T)            # first beat at or after zero...
    if t0 > T / 2:
        t0 -= T                           # ...unless the file starts just after one

    # Bar phase: kicks that follow at least two bars without one.
    kb = np.round((kicks - t0) / T).astype(int)
    re_entry = kb[1:][np.diff(kicks) > 2 * meter * T * 0.9] if len(kicks) > 1 else kb[:0]
    votes = np.bincount(re_entry % meter, minlength=meter)
    phase = int(votes.argmax())

    n_beats = int(np.ceil((duration - t0) / T)) + 1
    beats = t0 + T * np.arange(n_beats)
    downbeats = beats[(np.arange(n_beats) - phase) % meter == 0]

    # Does the tempo drift? Mean residual of the sharp events in 30 s windows.
    drift = [float(1000 * resid[ok & (sharp >= a) & (sharp < a + 30)].mean())
             for a in range(0, int(duration), 30)
             if (ok & (sharp >= a) & (sharp < a + 30)).sum() > 8]
    return {
        "beats": beats,
        "downbeats": downbeats,
        "period": float(T),
        "tempo": float(60.0 / T),
        "t0": float(t0),
        "bar_phase": phase,
        "bar_phase_votes": votes.tolist(),
        "sharp_used": int(ok.sum()),
        "sharp_residual_ms": float(1000 * resid[ok].std()) if ok.any() else float("nan"),
        "drift_ms_per_30s": [round(d, 2) for d in drift],
    }


def latency(ev_t: np.ndarray, beats: np.ndarray, division: int, limit: float = 0.06) -> float:
    """Median distance of a stream's attacks from the lattice: the detector's lag.

    A quantised part played by a machine is on the lattice. If its detected
    attacks sit a steady 23 ms after it, that is how long this band's envelope
    takes to get half way up, not where the part is.
    """
    q = (beats[1] - beats[0]) / division
    r = ((ev_t - beats[0] + q / 2) % q) - q / 2
    r = r[np.abs(r) < limit]
    return float(np.median(r)) if len(r) > 20 else 0.0


# ------------------------------------------------------------------ Beat This!, fixed


def meter_of(bt: dict) -> tuple[int, float]:
    """Beats in a bar by Beat This!'s downbeats, and the share of its bars that agree."""
    b, d = bt["beats"], bt["downbeats"]
    per = np.array([((b >= d0) & (b < d1)).sum() for d0, d1 in zip(d[:-1], d[1:])])
    per = per[(per >= 2) & (per <= 12)]
    if not len(per):
        return 4, 0.0
    vals, cnt = np.unique(per, return_counts=True)
    return int(vals[cnt.argmax()]), float(cnt.max() / len(per))


def lateness(bt_beats: np.ndarray, t: np.ndarray, amp: np.ndarray,
             early: float = 0.06, late: float = 0.02) -> float:
    """How far the song's onsets sit from Beat This!'s beats, by the mode of every onset
    near every beat, weighted by its size. (A median is pulled about by the notes and
    hats between beats: it said -14 ms where the truth was -38.) Looked for only where it
    can be: Beat This! reads 14-38 ms late on three songs, so onsets from `early` before
    its beat to `late` after - a syncopated line's cluster lies outside."""
    near = [t[(t - b > -early) & (t - b < late)] - b for b in bt_beats]
    wts = [amp[(t - b > -early) & (t - b < late)] for b in bt_beats]
    if not near or not sum(len(x) for x in near):
        return 0.0
    h, e = np.histogram(np.concatenate(near), bins=np.arange(-early, late + 5e-4, 1e-3),
                        weights=np.concatenate(wts))
    return float(e[int(np.argmax(ndimage.gaussian_filter1d(h, 2)))] + 5e-4)


def _local_line(t: np.ndarray, ok: np.ndarray, half: int = 4) -> np.ndarray:
    """Each beat placed on the line through its trusted neighbours (index -> time)."""
    i = np.arange(len(t))
    out = t.copy()
    for k in range(len(t)):
        sel = ok & (np.abs(i - k) <= half)
        if sel.sum() >= 3:
            out[k] = np.polyval(np.polyfit(i[sel], t[sel], 1), k)
    return out


def fill_gaps(beats: np.ndarray, reach: int = 8) -> np.ndarray:
    """Beats a tracker skipped: where two beats are a whole number of the local beat
    apart (within 15 %), the missing ones, evenly spaced."""
    if len(beats) < 4:
        return beats
    ibi = np.diff(beats)
    out = [beats[:1]]
    for k, g in enumerate(ibi):
        local = float(np.median(ibi[max(0, k - reach):k + reach + 1]))
        n = int(round(g / local))
        if n >= 2 and abs(g / local - n) < 0.15:
            out.append(beats[k] + g * np.arange(1, n) / n)
        out.append(beats[k + 1:k + 2])
    return np.concatenate(out)


def snap_beats(bt_beats: np.ndarray, t: np.ndarray, amp: np.ndarray,
               tol: float = 0.025, agree: float = 0.010) -> tuple[np.ndarray, float, float]:
    """Beat This!'s beats, on time: less its lateness, each moved to the nearest onset
    within `tol` if that keeps it within `agree` of its neighbours' local tempo.
    Returns the beats, the lateness removed, and the share of beats that snapped."""
    off = lateness(bt_beats, t, amp)
    b = fill_gaps(bt_beats) + off
    ref = np.sort(t)
    j = np.clip(np.searchsorted(ref, b), 1, len(ref) - 1)
    near = np.where(np.abs(b - ref[j - 1]) < np.abs(b - ref[j]), ref[j - 1], ref[j])
    ok = np.abs(near - b) < tol
    snapped = np.where(ok, near, b)
    kept = ok & (np.abs(snapped - _local_line(snapped, ok)) < agree)
    return np.where(kept, snapped, _local_line(snapped, kept)), -off, float(kept.mean())


def extend(beats: np.ndarray, duration: float) -> np.ndarray:
    """Carry the first and last beat period out to cover the song, like the lattice does."""
    if len(beats) < 2:
        return beats
    head, tail = beats[1] - beats[0], beats[-1] - beats[-2]
    pre = beats[0] - head * np.arange(int(np.floor((beats[0] + head / 2) / head)), 0, -1)
    post = beats[-1] + tail * np.arange(1, int(np.ceil((duration - beats[-1]) / tail)) + 2)
    return np.concatenate([pre, beats, post])


# ------------------------------------------------------------------------ choosing


def _nearest_beat(beats: np.ndarray, t: np.ndarray) -> np.ndarray:
    idx = np.clip(np.searchsorted(beats, t), 1, len(beats) - 1)
    return np.where(np.abs(t - beats[idx - 1]) < np.abs(t - beats[idx]), idx - 1, idx)


def kick_votes(beats: np.ndarray, kicks: np.ndarray, meter: int) -> list[int]:
    """Where, in the bar, the kick comes back after at least two bars without it."""
    if len(kicks) < 2:
        return [0] * meter
    period = float(np.median(np.diff(beats)))
    back = kicks[1:][np.diff(kicks) > 2 * meter * period * 0.9]
    return np.bincount(_nearest_beat(beats, back) % meter, minlength=meter).tolist()


def agreement(bt_beats: np.ndarray, beats: np.ndarray, onsets: np.ndarray) -> float:
    """Share of Beat This!'s beats, less their lateness against `onsets`, within 25 ms of
    `beats`. On three real songs its beats agree 0.92-0.99 with the lattice; with a lattice
    fitted to leakage, 0.12."""
    if len(bt_beats) < 2 or len(beats) < 2:
        return 0.0
    b = bt_beats + lateness(bt_beats, onsets, np.ones(len(onsets)))
    j = np.clip(np.searchsorted(beats, b), 1, len(beats) - 1)
    return float((np.minimum(np.abs(b - beats[j - 1]), np.abs(b - beats[j])) < 0.025).mean())


def bar_phase(beats: np.ndarray, kicks: np.ndarray, bt_downbeats: np.ndarray,
              meter: int) -> tuple[int, str, list[int], list[int]]:
    """The downbeat's place among the beats: the kick's re-entries if they are enough
    and agree, else Beat This!'s downbeats. Returns the phase, where it came from, and
    the kick's and Beat This!'s votes."""
    kv = np.asarray(kick_votes(beats, kicks, meter))
    bt_votes = (np.bincount(_nearest_beat(beats, bt_downbeats) % meter, minlength=meter).tolist()
                if len(bt_downbeats) else [0] * meter)
    if kv.sum() >= 4 and kv.max() >= 0.75 * kv.sum():
        return int(kv.argmax()), "kick re-entries", kv.tolist(), bt_votes
    if sum(bt_votes):
        return int(np.argmax(bt_votes)), "beat this", kv.tolist(), bt_votes
    return int(kv.argmax()), "none", kv.tolist(), bt_votes


def local_downbeats(beats: np.ndarray, bt_downbeats: np.ndarray, meter: int, phase: int) -> np.ndarray:
    """Bars that follow Beat This!'s downbeats one by one: each lands on its nearest beat,
    a gap of more than a bar and a half is counted out in whole bars, and before the
    first and after the last the global phase carries on."""
    marks = np.unique(_nearest_beat(beats, bt_downbeats)) if len(bt_downbeats) else np.zeros(0, int)
    if not len(marks):
        return beats[(np.arange(len(beats)) - phase) % meter == 0]
    idx = list(range(int(marks[0]) % meter, int(marks[0]), meter))
    for m0, m1 in zip(marks[:-1], marks[1:]):
        gap = int(m1 - m0)
        step = gap if gap < 1.5 * meter else meter
        idx.extend(range(int(m0), int(m1), step) if gap >= 1.5 * meter else [int(m0)])
    idx.extend(range(int(marks[-1]), len(beats), meter))
    idx = np.unique(np.asarray(idx, int))
    return beats[idx[(idx >= 0) & (idx < len(beats))]]


def find(sharp: np.ndarray, kicks: np.ndarray, onsets: tuple[np.ndarray, np.ndarray],
         bt: dict, duration: float, force: str | None = None) -> dict:
    """The grid for a song. `onsets` (times, sizes) are every attack heard, for snapping;
    `force` ("lattice" or "tracked") is for measuring one source against the other."""
    meter, meter_agree = meter_of(bt)
    bt_period = float(np.median(np.diff(bt["beats"]))) if len(bt["beats"]) > 1 else float("nan")
    gaps = np.diff(bt["beats"])
    out: dict = {"meter": meter, "meter_agreement": meter_agree,
                 "beat_this": {"tempo": 60.0 / bt_period if np.isfinite(bt_period) else None,
                               "beats": int(len(bt["beats"])), "downbeats": int(len(bt["downbeats"])),
                               "steady": float(np.mean(np.abs(gaps / bt_period - 1) < 0.05)) if len(gaps) else 0.0}}

    lat = None
    if len(sharp) >= MIN_SHARP and np.isfinite(bt_period) and force != "tracked":
        scan = lattice_scan(sharp)
        spacing, coherence = scan[0]
        div = beat_multiple(spacing, bt_period)
        out["scan"] = {"spacing_ms": 1000 * spacing, "coherence": coherence, "beat_multiple": div,
                       "peaks": [[round(1000 * s, 3), round(c, 3)] for s, c in scan]}
        if div is not None:
            lat = fit_grid(sharp, kicks, duration, div * spacing, div=div, meter=meter)
            lat["on_lattice"] = lat["sharp_used"] / len(sharp)
            lat["div"] = div
            lat["beat_this_agrees"] = agreement(bt["beats"], lat["beats"], sharp)
            out["lattice"] = {k: v for k, v in lat.items() if k not in ("beats", "downbeats")}
    # Beat This! may veto a lattice only when its own beats are steady. On TIDAL CORE with
    # no drums or bass its beats were steady for 59 % of gaps and agreed with 33 % of a
    # lattice that was exact (every true beat, 0.4 ms); vetoed, the song got its beats.
    # No song yet has needed the veto - it is kept because it is independent and cheap.
    steady = out["beat_this"]["steady"]
    trusted = lat is not None and lat["on_lattice"] >= GATE and (steady < BT_STEADY or lat["beat_this_agrees"] >= BT_GATE)
    if lat is not None and (trusted or force == "lattice"):
        beats, source = lat["beats"], "lattice"
    elif len(bt["beats"]) >= 8:
        t, a = onsets
        fixed, removed, snapped = snap_beats(bt["beats"], t, a)
        beats, source = extend(fixed, duration), "tracked"
        out["tracked"] = {"lateness_removed_ms": 1000 * removed, "snapped": snapped}
    else:
        raise ValueError("no beat to be found: too few sharp hits for a lattice and too few tracked beats")

    phase, phase_from, kv, bt_votes = bar_phase(beats, kicks, bt["downbeats"], meter)
    if source == "lattice":
        downbeats = beats[(np.arange(len(beats)) - phase) % meter == 0]
    else:
        # A tracked grid can drop or double a beat, and one global phase would put every
        # bar after it off its line. Its bars follow Beat This!'s downbeats where it has
        # them, and are counted out in whole bars across any stretch where it has none.
        downbeats, phase_from = local_downbeats(beats, bt["downbeats"], meter, phase), "beat this, bar by bar"
    period = float(np.median(np.diff(beats)))
    out.update({"source": source, "beats": beats, "downbeats": downbeats, "period": period,
                "tempo": 60.0 / period, "bar_phase": phase, "bar_phase_from": phase_from,
                "bar_phase_votes": kv, "beat_this_downbeat_votes": bt_votes,
                "t0": float(beats[0])})
    return out
