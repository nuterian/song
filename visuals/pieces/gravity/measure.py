"""Decode the mp4 and check it against the audio. Numbers, not opinions.

Nothing here looks inside the renderer. The video is decoded with ffmpeg exactly as
a player would decode it, reduced to a handful of per-frame signals, and those are
compared with what `listen` heard:

    lag        event-triggered average of each instrument's region of the frame.
               Events fall at every phase of the 60 Hz frame clock, so stacking a
               few hundred of them resolves the response to a couple of
               milliseconds. It should begin inside the frame before the hit and
               never after it.
    coverage   recall - what fraction of audio events moved their region at once;
               precision - what fraction of the frame's largest jumps had an audio
               event under them.
    impact     the biggest frame-to-frame steps of the whole video, against the
               re-entries the audio has.
    arc        bar by bar, does the picture's energy follow the song's?
    container  the mp4's own audio against the wav, to the sample.
    flicker    how much of the mean luminance moves faster than 3 Hz.

Frame n is on screen from n / fps. That is the time it is given here.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import ndimage, signal

from . import direct
from .track import Track
from .listen import RATE

W, H = 480, 270

# Regions, as radius in units of frame height - the shader's own unit.
REGIONS = {
    "core": (0.0, 0.030),      # the voice's light
    "heart": (0.0, 0.062),     # ...and the disc it swells in, when the light is an ink and saturates
    "edge": (0.088, 0.135),    # where the body's edge goes when the kick lands
    "near": (0.140, 0.230),    # where a ring is born
    "field": (0.145, 0.70),    # rings, lines, satellites
}
# What each instrument is looked for in. `detail` is the field's fine structure -
# hairlines - and `peak` its few brightest pixels - satellites.
# `radius` is the body's own radius, found as the steepest fall of the radial
# profile in a full-resolution crop of the centre; `sparks` is how much of the
# field is lit nearly white; `ring` is the tallest narrow peak of the radial profile
# just off the body - a ring being born, and not the broad glow a kick makes; `points` is the field's brightest few pixels once
# everything round - rings, glow - has been taken away, which leaves satellites.
ROLE_REGION = {"kick": "radius", "snare": "ring", "hat": "detail", "note": "points",
               "syllable": "core", "drop": "lum"}
CROP = 0.40          # side of the centre crop, in frame heights
CROP_PX = 288


def decode(video: Path):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
           "-vf", f"scale={W}:{H}:flags=area", "-pix_fmt", "gray", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = W * H
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, dtype=np.uint8).reshape(H, W).astype(np.float32) / 255.0
    proc.wait()


def body_radius(video: Path) -> np.ndarray:
    """The body's radius in frame heights, per frame, to a fraction of a pixel."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
           "-vf", f"crop=ih*{CROP}:ih*{CROP},scale={CROP_PX}:{CROP_PX}:flags=area",
           "-pix_fmt", "gray", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    yy, xx = np.mgrid[0:CROP_PX, 0:CROP_PX]
    r = np.hypot(xx - (CROP_PX - 1) / 2, yy - (CROP_PX - 1) / 2) * (CROP / CROP_PX)
    width = 0.002
    nb = int(0.19 / width)
    rbin = np.minimum((r / width).astype(int), nb).ravel()
    count = np.maximum(np.bincount(rbin, minlength=nb + 1), 1)
    out = []
    size = CROP_PX * CROP_PX
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        f = np.frombuffer(buf, dtype=np.uint8).astype(np.float32)
        prof = (np.bincount(rbin, weights=f, minlength=nb + 1) / count)[:nb]
        g = np.diff(ndimage.uniform_filter1d(prof, 3))
        # The body is the one *hard* edge near the centre. A glow, the voice's
        # light or a ring being born can fall as far, but over five bins or more;
        # the body's rim falls in one or two. So: the fall that most exceeds its
        # own surroundings three bins either side.
        # ...and, of the hard edges, the innermost that has the dark beyond it. A
        # clap's ring, printed as ink, is as hard an edge as the rim, but it is always
        # outside it; the voice's heart is a hard edge *inside* the star, but past it
        # there is still star, and past the rim there is not.
        lo, hi = int(0.030 / width), int(0.160 / width)
        sharp = g[lo:hi] - 0.5 * (g[lo - 3:hi - 3] + g[lo + 3:hi + 3])
        inside = np.maximum.accumulate(prof)[lo:hi]
        beyond = ndimage.uniform_filter1d(prof, 4, origin=-2)[lo + 3:hi + 3]
        ok = (sharp <= 0.45 * sharp.min()) & (beyond < 0.62 * inside)
        i = lo + int(np.argmax(ok)) if ok.any() else lo + int(np.argmin(sharp))
        while i + 1 < hi and sharp[i + 1 - lo] < sharp[i - lo]:
            i += 1
        # parabolic refinement of the steepest point
        if 0 < i < len(g) - 1:
            d = g[i - 1] - 2 * g[i] + g[i + 1]
            i_f = i + (0.5 * (g[i - 1] - g[i + 1]) / d if d != 0 else 0.0)
        else:
            i_f = float(i)
        out.append((i_f + 1.0) * width)
    proc.wait()
    return np.asarray(out)


def probe_fps(video: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True).stdout.strip()
    a, b = out.split("/")
    return float(a) / float(b)


def frame_signals(video: Path) -> dict[str, np.ndarray]:
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot(xx - (W - 1) / 2, yy - (H - 1) / 2) / H
    masks = {k: (r >= lo) & (r < hi) for k, (lo, hi) in REGIONS.items()}
    rbin = np.minimum((r / 0.9 * 96).astype(int), 95).ravel()
    rcount = np.maximum(np.bincount(rbin, minlength=96), 1)
    ringbins = (np.arange(96) * 0.9 / 96 >= 0.115) & (np.arange(96) * 0.9 / 96 < 0.30)
    fieldbins = (np.arange(96) * 0.9 / 96 >= 0.17) & (np.arange(96) * 0.9 / 96 < 0.62)

    out: dict[str, list] = {k: [] for k in ("lum", "motion", "core", "edge", "near", "field",
                                            "peak", "sparks", "points", "detail", "radial", "ring", "heart")}
    prev = None
    prev_prof = None
    for f in decode(video):
        out["lum"].append(f.mean())
        out["motion"].append(0.0 if prev is None else float(np.abs(f - prev).mean()))
        for k, m in masks.items():
            out[k].append(float(f[m].mean()))
        fm = f[masks["field"]]
        out["peak"].append(float(np.partition(fm, -12)[-12:].mean() - fm.mean()))
        out["sparks"].append(float((fm > 0.72).mean()))
        out["detail"].append(float(np.abs(f - ndimage.uniform_filter(f, 3))[masks["field"]].mean()))
        prof = np.bincount(rbin, weights=f.ravel(), minlength=96) / rcount
        narrow = prof - ndimage.median_filter(prof, 13, mode="nearest")
        out["ring"].append(float(narrow[ringbins].max()))
        resid = (f.ravel() - prof[rbin])[masks["field"].ravel()]
        # the brightest sixty pixels, not the brightest dozen: on a printed page a
        # dozen pixels are always at full ink, and what a note adds is *area* of it
        out["points"].append(float(np.partition(resid, -60)[-60:].mean()))
        out["radial"].append(0.0 if prev_prof is None
                             else float(np.abs(prof - prev_prof)[fieldbins].mean()))
        prev, prev_prof = f, prof
    sig = {k: np.asarray(v, dtype=np.float64) for k, v in out.items()}
    # the field's fast part: what the hats do to it, with rings' slow travel removed
    k = np.ones(9) / 9
    sig["field_hp"] = sig["field"] - np.convolve(sig["field"], k, mode="same")
    sig["radius"] = body_radius(video)[: len(sig["lum"])]
    return sig


# ---------------------------------------------------------------------- colour

CW, CH = 160, 90
HUE_BINS = 24


def colour_signals(video: Path) -> dict[str, np.ndarray]:
    """Per frame: how colourful, which hues, and how many of them at once.

    colourful   Hasler and Suesstrunk's measure, on 0..1 RGB: about 0 for grey,
                0.15 moderately colourful, 0.4 and up vivid.
    hues        a 24-bin hue histogram weighted by chroma, so a grey pixel votes
                for nothing however bright it is.
    n_hues      the effective number of hues on screen at once: exp of the
                entropy of that histogram. One flat colour is 1.
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
           "-vf", f"scale={CW}:{CH}:flags=area", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = CW * CH * 3
    colourful, hues, chroma_mean = [], [], []
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        f = np.frombuffer(buf, dtype=np.uint8).reshape(-1, 3).astype(np.float32) / 255.0
        r, g, b = f[:, 0], f[:, 1], f[:, 2]
        rg, yb = r - g, 0.5 * (r + g) - b
        colourful.append(float(np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean())))
        mx, mn = f.max(axis=1), f.min(axis=1)
        c = mx - mn
        h = np.zeros_like(c)
        ok = c > 1e-4
        rmax, gmax = ok & (mx == r), ok & (mx == g) & (mx != r)
        bmax = ok & ~rmax & ~gmax
        h[rmax] = ((g - b)[rmax] / c[rmax]) % 6.0
        h[gmax] = (b - r)[gmax] / c[gmax] + 2.0
        h[bmax] = (r - g)[bmax] / c[bmax] + 4.0
        # the paper is nine tenths of a printed frame and has a breath of colour in
        # it; it is what the inks are on, not one of them, so it does not vote
        hist = np.bincount(np.minimum((h / 6.0 * HUE_BINS).astype(int), HUE_BINS - 1),
                           weights=np.maximum(c - 0.08, 0.0), minlength=HUE_BINS)
        hues.append(hist / max(hist.sum(), 1e-9))
        chroma_mean.append(float(c.mean()))
    proc.wait()
    hues = np.asarray(hues)
    with np.errstate(divide="ignore", invalid="ignore"):
        ent = -np.nansum(np.where(hues > 0, hues * np.log(hues), 0.0), axis=1)
    return {"colourful": np.asarray(colourful), "hues": hues, "n_hues": np.exp(ent),
            "chroma": np.asarray(chroma_mean)}


def colour_report(video: Path, fps: float, start: float, events: np.ndarray) -> dict:
    c = colour_signals(video)
    n = len(c["colourful"])
    whole = c["hues"].mean(axis=0)
    whole = whole / max(whole.sum(), 1e-9)
    with np.errstate(divide="ignore", invalid="ignore"):
        visited = float(np.exp(-np.nansum(np.where(whole > 0, whole * np.log(whole), 0.0))))
    # how fast the palette moves, frame to frame: total-variation distance between
    # consecutive hue histograms. Split by whether an audio event is under the frame.
    tv = 0.5 * np.abs(np.diff(c["hues"], axis=0)).sum(axis=1)
    t_lo = start + (np.arange(1, n) - 0.5) / fps
    t_hi = start + (np.arange(1, n) + 1.0) / fps
    i = np.searchsorted(events, t_lo)
    under = (i < len(events)) & (events[np.minimum(i, len(events) - 1)] <= t_hi)
    out = {
        "colourful_median": float(np.median(c["colourful"])),
        "colourful_p90": float(np.percentile(c["colourful"], 90)),
        "hues_at_once_median": float(np.median(c["n_hues"])),
        "hues_visited_of_24": visited,
        "palette_step_p999_no_event": float(np.percentile(tv[~under], 99.9)) if (~under).any() else 0.0,
        "palette_step_max_no_event": float(tv[~under].max()) if (~under).any() else 0.0,
        "palette_step_p999_on_event": float(np.percentile(tv[under], 99.9)) if under.any() else 0.0,
    }
    print(f"colour: colourfulness median {out['colourful_median']:.3f}, p90 {out['colourful_p90']:.3f}; "
          f"hues on screen at once {out['hues_at_once_median']:.1f} of {HUE_BINS}; "
          f"hues visited over the song {out['hues_visited_of_24']:.1f} of {HUE_BINS}")
    print(f"        palette step between frames with no audio event under them: "
          f"p99.9 {out['palette_step_p999_no_event']:.4f}, max {out['palette_step_max_no_event']:.4f} "
          f"(0 = identical, 1 = no hue in common); on an event p99.9 {out['palette_step_p999_on_event']:.4f}")
    np.savez_compressed(video.with_suffix(".colour.npz"), **c)
    return out


# ------------------------------------------------------------------------- lag


def triggered_average(sig: np.ndarray, fps: float, start: float, events: np.ndarray,
                      lo: float = -0.10, hi: float = 0.20, step: float = 0.002):
    """Stack the signal around each event, at the events' own sub-frame phases."""
    edges = np.arange(lo, hi + step, step)
    total = np.zeros(len(edges) - 1)
    count = np.zeros(len(edges) - 1)
    n = len(sig)
    for te in events:
        f0 = int(np.floor((te + lo - start) * fps))
        f1 = int(np.ceil((te + hi - start) * fps))
        if f0 < 1 or f1 >= n:
            continue
        idx = np.arange(f0, f1 + 1)
        off = start + idx / fps - te
        base = sig[idx][(off > -0.09) & (off < -0.025)]
        if len(base) == 0:
            continue
        b = np.digitize(off, edges) - 1
        ok = (b >= 0) & (b < len(total))
        np.add.at(total, b[ok], sig[idx][ok] - base.mean())
        np.add.at(count, b[ok], 1)
    centres = 0.5 * (edges[:-1] + edges[1:])
    with np.errstate(invalid="ignore"):
        return centres, total / count, count


def onset_of(centres: np.ndarray, avg: np.ndarray) -> tuple[float, float]:
    """Where the stacked response crosses half of its peak, and the peak."""
    avg = np.nan_to_num(avg)
    sm = np.convolve(avg, np.ones(3) / 3, mode="same")
    post = centres > -0.03
    peak_i = int(np.argmax(np.where(post, sm, -np.inf)))
    peak = sm[peak_i]
    if peak <= 0:
        return float("nan"), 0.0
    above = np.where((sm >= 0.5 * peak) & (centres > -0.05) & (np.arange(len(sm)) <= peak_i))[0]
    return float(centres[above[0]]), float(peak)


# -------------------------------------------------------------------- coverage


def first_frame(te: np.ndarray, fps: float, start: float) -> np.ndarray:
    """The frame that is on screen when time te arrives."""
    return np.ceil((te - start) * fps - 1e-9).astype(int) - 1


def response(sig: np.ndarray, frames: np.ndarray) -> np.ndarray:
    """Rise across the hit: best of the two frames from it, over the two before it."""
    frames = frames[(frames >= 2) & (frames < len(sig) - 2)]
    after = np.maximum(sig[frames], sig[frames + 1])
    before = np.minimum(sig[frames - 1], sig[frames - 2])
    return after - before


def recall(sig: np.ndarray, fps: float, start: float, events: np.ndarray,
           rng: np.random.Generator) -> tuple[float, int]:
    dur = len(sig) / fps
    ev = events[(events > start + 0.1) & (events < start + dur - 0.1)]
    if len(ev) == 0:
        return float("nan"), 0
    got = response(sig, first_frame(ev, fps, start))
    # the null: the same measurement where nothing of this kind happened
    cand = rng.uniform(start + 0.1, start + dur - 0.1, 6000)
    gap = np.abs(cand[:, None] - ev[None, :]).min(axis=1)
    null = response(sig, first_frame(cand[gap > 0.06], fps, start))
    thresh = np.percentile(null, 95) if len(null) else 0.0
    return float((got > thresh).mean()), len(ev)


# ---------------------------------------------------------------------- matrix


def matrix(got: dict, track: Track, start: float = 120.0, duration: float = 40.0) -> dict:
    """Solo each instrument, and ask every detector about every instrument's hits.

    Row: the only instrument allowed to move the picture. Column: a detector.
    The diagonal should be near 1 and everything else near the 0.05 that the
    detector's own false-alarm rate allows.
    """
    from . import render

    a = got["arrays"]
    roles = {"kick": ("kick", 0.5), "snare": ("snare", 0.30), "hat": ("hat", 0.25),
             "note": ("note", 0.25), "voice": ("syllable", 0.60)}
    cols = ["kick", "snare", "hat", "note", "syllable"]
    rng = np.random.default_rng(0)
    table = {}
    print(f"separation over {start:.0f}-{start + duration:.0f}s: row = the one instrument drawn, "
          f"column = detector")
    print("          " + " ".join(f"{c:>9s}" for c in cols))
    for role in roles:
        video = render.render(got, track, track.out(render.STYLE) / "solo", start=start, duration=duration,
                              size=(960, 540), crf=20, solo=role, quiet=True)
        sig = frame_signals(video)
        row = {}
        for c in cols:
            ev_name, thr = (c, dict(v for v in roles.values()).get(c, 0.3))
            ev = a[f"ev_{ev_name}_t"][a[f"ev_{ev_name}_amp"] > thr]
            row[c] = recall(sig[ROLE_REGION[c]], 60.0, start, ev, rng)[0]
        table[role] = row
        print(f"  {role:8s}" + " ".join(f"{row[c]:9.2f}" for c in cols))
    return table


# ------------------------------------------------------------------ smoothness


def smoothness(got: dict, track: Track) -> dict:
    """Render the whole song with only the section-level decisions moving, and look
    for a step. Reported as the largest frame-to-frame change against the median one,
    overall and at each section boundary: in a ramp the boundary frame is an ordinary
    frame; in a cut it is tens of times the median."""
    from . import render
    from .make import modelled

    video = render.render(got, track, track.out(render.STYLE) / "solo", start=0.0, duration=got["meta"]["duration"] - 0.01,
                          size=(640, 360), crf=18, solo="sections", quiet=True)
    ch = direct.direct(got, modelled(track, got, verbose=False))
    step, prev = [], None
    keep: dict[int, np.ndarray] = {}
    wanted = {int(s_.start * 60) + d for s_ in ch.sections[1:] for d in (-480, 480)}
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
           "-vf", "scale=320:180:flags=area", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = 320 * 180 * 3
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        f = np.frombuffer(buf, dtype=np.uint8).astype(np.float32) / 255.0
        if prev is not None:
            step.append(float(np.abs(f - prev).mean()))
        if len(step) in wanted:
            keep[len(step)] = f
        prev = f
    proc.wait()
    step = np.asarray(step)
    med = float(np.median(step))
    worst = int(np.argmax(step))
    print(f"smoothness, with only section decisions live: median frame-to-frame change {med:.5f}; "
          f"largest anywhere {step.max():.5f} = {step.max() / med:.2f}x the median, at {(worst + 1) / 60:.2f}s")
    out = {"median": med, "max_ratio": float(step.max() / med), "boundaries": []}
    for s in ch.sections[1:]:
        f0 = int(s.start * 60)
        around = step[max(f0 - 30, 0): f0 + 30]
        a_, b_ = keep.get(f0 - 480), keep.get(f0 + 480)
        cut = float(np.abs(a_ - b_).mean() / med) if a_ is not None and b_ is not None else float("nan")
        out["boundaries"].append({"bar": s.bar0, "t": s.start, "ratio": float(around.max() / med),
                                  "a_cut_would_be": cut})
    print("   at each section boundary: largest change within half a second, x median "
          "(and what cutting between the two sections' looks would have been):")
    print("   " + "  ".join(f"bar {b['bar']}: {b['ratio']:.1f} ({b['a_cut_would_be']:.0f})"
                            for b in out["boundaries"]))
    return out


# ------------------------------------------------------------------------ main


def container_offset(video: Path, audio: Path, start: float) -> float:
    tmp = video.with_suffix(".check.wav")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
                    "-ac", "1", "-ar", "48000", str(tmp)], check=True)
    b, sr = sf.read(str(tmp))
    tmp.unlink()
    a, _ = sf.read(str(audio))
    a = a.mean(axis=1)
    s0 = int(start * sr)
    off = min(len(b) // 2, 5 * sr)
    n = min(6 * sr, len(b) - off)
    x, y = a[s0 + off:s0 + off + n], b[off:off + n]
    xc = signal.correlate(y, x, mode="full", method="fft")
    return 1000.0 * (int(np.argmax(xc)) - (len(x) - 1)) / sr


def main(got: dict, track: Track, video: str | None, start: float = 0.0, save: bool = True) -> int:
    from . import render
    video = Path(video) if video else track.out(render.STYLE) / "piece.mp4"
    if "-clip-" in video.name or "s.mp4" in video.name:
        try:
            start = float(video.stem.rsplit("-", 1)[1].rstrip("s"))
        except ValueError:
            pass
    a, meta = got["arrays"], got["meta"]
    from .make import modelled
    ch = direct.direct(got, modelled(track, got, verbose=False))
    fps = probe_fps(video)
    sig = frame_signals(video)
    n = len(sig["lum"])
    dur = n / fps
    print(f"{video.name}: {n} frames at {fps:g} fps, from {start:.1f}s")
    rng = np.random.default_rng(0)
    report: dict = {"video": video.name, "frames": n, "fps": fps, "start": start}

    events = {
        "kick": a["ev_kick_t"][a["ev_kick_amp"] > 0.5],
        "snare": a["ev_snare_t"][a["ev_snare_amp"] > 0.30],
        "hat": a["ev_hat_t"][a["ev_hat_amp"] > 0.25],
        "note": a["ev_note_t"][a["ev_note_amp"] > 0.25],
        "syllable": a["ev_syllable_t"][a["ev_syllable_amp"] > 0.30],
        "drop": np.array([d["t"] for d in ch.drops]),
    }
    # a crash throws a shooting star (and rings the stars): an event, though no
    # detector here is dedicated to it
    crash = a["ev_crash_t"][a["ev_crash_amp"] > 0.9]

    print("\nlag and coverage   (onset: where the stacked response is half way up, relative")
    print("                    to the audio event; negative is the picture first)")
    print(f"  {'role':9s} {'region':9s} {'events':>6s} {'onset ms':>9s} {'recall':>7s}")
    report["roles"] = {}
    for role, ev in events.items():
        region = ROLE_REGION[role]
        ev_in = ev[(ev > start + 0.12) & (ev < start + dur - 0.25)]
        c, avg, _ = triggered_average(sig[region], fps, start, ev_in)
        onset, peak = onset_of(c, avg) if len(ev_in) >= 3 else (float("nan"), 0.0)
        rec, cnt = recall(sig[region], fps, start, ev, rng)
        print(f"  {role:9s} {region:9s} {cnt:6d} {1000 * onset:9.1f} {rec:7.2f}")
        report["roles"][role] = {"region": region, "events": cnt, "onset_ms": 1000 * onset,
                                 "recall": rec}

    # precision: the moments the picture *starts* doing something - the largest
    # rises in its motion - and whether the audio had anything under each of them
    allev = np.sort(np.concatenate(list(events.values()) + [crash]))
    jump = np.diff(sig["lum"], prepend=sig["lum"][0])
    rise = np.maximum(np.diff(sig["motion"], prepend=sig["motion"][0]), 0.0)
    peaks, _ = signal.find_peaks(rise, distance=3)
    top = peaks[np.argsort(rise[peaks])[::-1][: max(20, n // 30)]]
    # frame n shows the state at (n + 1) / fps, so an event in (n / fps - half a
    # frame, (n + 1) / fps] is the one it is showing
    t_lo, t_hi = start + (top - 0.5) / fps, start + (top + 1.0) / fps
    i = np.searchsorted(allev, t_lo)
    explained = float(np.mean((i < len(allev)) & (allev[np.minimum(i, len(allev) - 1)] <= t_hi)))
    # ...and against every attack `listen` found, however quiet: a soft syllable is
    # below the list above, and the voice's light still, rightly, answers it
    every = np.sort(np.concatenate([a[f"ev_{k}_t"] for k in ("kick", "snare", "hat", "note", "syllable", "crash")]
                                   + [events["drop"]]))
    j = np.searchsorted(every, t_lo)
    explained_any = float(np.mean((j < len(every)) & (every[np.minimum(j, len(every) - 1)] <= t_hi)))
    print(f"\nprecision: of the {len(top)} sharpest visual onsets, "
          f"{100 * explained:.0f}% have a listed audio event in the frame they appear in; "
          f"{100 * explained_any:.0f}% have an attack of any size")
    report["precision_any"] = explained_any
    report["precision"] = explained

    # impact: the biggest steps, against the re-entries
    drops = [d for d in ch.drops if start + 0.1 < d["t"] < start + dur - 0.1]
    if drops:
        order = np.argsort(np.abs(jump))[::-1]
        picked: list[int] = []
        for i in order:
            if all(abs(i - j) > fps * 0.5 for j in picked):
                picked.append(int(i))
            if len(picked) >= len(drops):
                break
        t_big = start + np.array(picked) / fps
        hits = sum(1 for d in drops if np.abs(t_big - d["t"]).min() <= 2.0 / fps)
        print(f"impact: the {len(drops)} largest luminance steps in the video; "
              f"{hits} of them are the {len(drops)} re-entries")
        for d in drops:
            f0 = first_frame(np.array([d["t"]]), fps, start)[0]
            step = sig["lum"][min(f0 + 1, n - 1)] - sig["lum"][max(f0 - 1, 0)]
            print(f"   bar {d['bar']:3d}  {d['t']:7.2f}s  audio {d['jump_db']:+5.1f} dB, strength "
                  f"{d['strength']:.2f}  ->  luminance step {step:+.3f}")
        report["impact_hits"] = [hits, len(drops)]

    # arc: per bar
    db = a["downbeats"]
    db = db[(db >= start) & (db <= start + dur)]
    if len(db) > 8:
        vis, aud = [], []
        for t0, t1 in zip(db[:-1], db[1:]):
            f0, f1 = int((t0 - start) * fps), int((t1 - start) * fps)
            vis.append(sig["lum"][f0:f1].mean() + 8 * sig["motion"][f0:f1].mean())
            aud.append(a["loud"][int(t0 * RATE):int(t1 * RATE)].mean())
        rho = float(np.corrcoef(vis, aud)[0, 1])
        print(f"arc: per-bar picture energy against per-bar loudness, r = {rho:.2f} over {len(vis)} bars")
        report["arc_r"] = rho

    # streams: the continuous things, by correlation and by lag
    print("streams: a region of the picture against the level that should be driving it")
    t_state = start + (np.arange(n) + 1.0) / fps
    report["streams"] = {}
    for region, name in (("core", "uVoice"), ("lum", "uExposure"), ("radius", "uMass")):
        drive = ch.rows(t_state)[:, ch.index(name)].astype(np.float64)
        x = sig[region] - sig[region].mean()
        y = drive - drive.mean()
        lags = np.arange(-6, 7)
        cc = np.array([np.corrcoef(x[6 + l: n - 6 + l], y[6: n - 6])[0, 1] for l in lags])
        k = int(np.argmax(cc))
        print(f"  {region:7s} vs {name:10s} r = {cc[6]:.2f} at zero lag; best {cc[k]:.2f} "
              f"at {lags[k]:+d} frames")
        report["streams"][name] = {"r0": float(cc[6]), "best_lag_frames": int(lags[k])}

    report["colour"] = colour_report(video, fps, start, allev)

    off = container_offset(video, track.audio, start)
    print(f"container: the mp4's audio sits {off:+.2f} ms from the wav")
    report["container_ms"] = off

    lum = sig["lum"] - sig["lum"].mean()
    f, p = signal.welch(lum, fs=fps, nperseg=min(1024, n))
    fast = float(np.sqrt(np.trapz(p[f > 3.0], f[f > 3.0])))
    slow = float(np.sqrt(np.trapz(p[f <= 3.0], f[f <= 3.0])))
    print(f"flicker: mean-luminance rms above 3 Hz {fast:.4f} (of 1.0 full scale), below {slow:.4f}; "
          f"largest single-frame change {np.abs(jump).max():.3f}; "
          f"black frames {(sig['lum'] < 0.004).mean() * 100:.1f}%, mean level {sig['lum'].mean():.3f}")
    report["flicker_fast_rms"] = fast
    report["max_frame_step"] = float(np.abs(jump).max())

    if save:
        (video.with_suffix(".measure.json")).write_text(json.dumps(report, indent=1) + "\n")
        np.savez_compressed(video.with_suffix(".signals.npz"), **sig)
    return 0
