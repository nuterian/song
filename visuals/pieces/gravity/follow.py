"""Detectors that follow the bodies through whichever camera is looking at them.

`measure` watches a fixed, centred Sun. Here the camera turns, zooms and slides, so a
detector cannot be a fixed region of the frame. But nothing on screen is anywhere the
channels did not put it: `geometry` repeats the shader's arithmetic and says where the
Sun and each planet are in every frame, and how big, and each detector looks there.

    limb      the Sun's radius (from its area), over its resting radius   the kick
    corona    the tallest tongue of the Sun's silhouette, over the usual    the bass
    heart     light in the middle of the Sun's face                     the voice
    plane     light in the plane close round the Sun, to either side    the clap's rings
    planets   light on and close round the planets                      the notes
    sky       light of the stars, outside the system                    the hats, the crash

Two more things are measured from the channels alone, with no picture at all, because
they are what "jarring" is: how fast each camera slides, zooms and turns, and how
steadily a shot holds the thing it is a shot of (`jolt`).
"""

from __future__ import annotations

import numpy as np

from . import cosmos, direct, measure, render
from . import shader_cosmos as sc

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
DETECTORS = ("limb", "corona", "heart", "plane", "planets", "sky")
# which detector answers for which instrument, and how loud a hit has to be to be asked about
ASK = {"kick": ("limb", 0.5), "bass_note": ("corona", 0.30), "syllable": ("heart", 0.60),
       "snare": ("plane", 0.30), "note": ("planets", 0.25), "hat": ("sky", 0.25), "crash": ("sky", 0.30)}


def geometry(ch: direct.Channels, rows: np.ndarray, camera: str | None = None) -> dict[str, np.ndarray]:
    """Where things are, in frame heights from the middle of the frame (x right, y up),
    for each of `rows` (indices into the channels). The shader's own arithmetic."""
    def col(name):
        return ch.data[rows, ch.index(name)].astype(np.float64)

    def cam(name):
        return col(f"{name}.{camera}" if camera else name)

    turn, tilt, roll, span, cx, cy = (cam(n) for n in cosmos.CAMERA_UNIFORMS)
    e = np.clip(tilt, 0.20, 0.98)
    c = np.sqrt(1.0 - e * e)
    cr, sr = np.cos(roll), np.sin(roll)
    pulse = col("uSunPulse")
    a0 = np.maximum(0.255, 0.156 / e)
    tug = cam("uSpreadSlow")

    def to_frame(qx, qy):                    # the inverse of the shader's q = rot2(-roll) * (p * span + cam)
        return ((cr * qx + sr * qy) - cx) / span, ((-sr * qx + cr * qy) - cy) / span

    sun_x, sun_y = to_frame(np.zeros_like(span), np.zeros_like(span))
    rest = 0.078 * (0.50 + 0.80 * col("uMass"))
    px, py, pr = [], [], []
    for i in range(sc.N_PLANETS):
        a = (a0 + sc.ORBIT_STEP[i]) * tug
        th = 2 * np.pi * col(f"uPh{i}") + turn
        x, y, depth = a * np.cos(th), a * np.sin(th) * e, -a * np.sin(th) * c
        fx, fy = to_frame(x, y)
        size = sc.PLANET_SIZE[i] * (1.0 + 0.30 * col(f"uSwell{sc._PLANET_SLOT[i]}")) * (1.0 + 0.10 * depth / np.maximum(a, 1e-3))
        px.append(fx); py.append(fy); pr.append(size / span)
    return {"sun_x": sun_x, "sun_y": sun_y, "sun_rest": rest / span, "sun_r": rest * (1.0 + 0.22 * pulse) / span,
            "planet_x": np.stack(px, 1), "planet_y": np.stack(py, 1), "planet_r": np.stack(pr, 1),
            "outer": (a0 + sc.ORBIT_STEP[-1] + 0.05) * tug / span, "e": e, "roll": roll, "span": span}


def signals(ch: direct.Channels, start: float = 0.0, duration: float | None = None, camera: str | None = None,
            size: tuple[int, int] = (960, 540), fps: int = 60, progress: bool = False) -> dict[str, np.ndarray]:
    """Draw every frame of the window and ask each detector about it. `camera` picks one
    of the baked cameras by feeding its channels to the camera uniforms."""
    w, h = size
    data = ch.data
    if camera:
        data = data.copy()
        for name in cosmos.PER_CAMERA:
            data[:, ch.index(name)] = ch.data[:, ch.index(f"{name}.{camera}")]
    duration = ch.duration - start - 0.05 if duration is None else duration
    times = render.frame_times(start, duration, fps)
    rows = np.minimum(np.round(times * direct.RATE).astype(int), len(data) - 1)
    g = geometry(ch, rows, camera)
    yy, xx = np.mgrid[0:h, 0:w]
    fx = ((xx + 0.5 - w / 2) / h).astype(np.float32)
    fy = (-(yy + 0.5 - h / 2) / h).astype(np.float32)          # frames come top row first
    out = {k: np.full(len(times), np.nan) for k in DETECTORS}
    out["change"] = np.zeros(len(times))
    r = render.Renderer(w, h)
    r.bind(ch.names)
    prev = None
    try:
        for k, (t, row) in enumerate(zip(times, rows)):
            img = r.frame(float(t), data[row]).astype(np.float32) / 255.0
            lum = img @ LUMA
            if prev is not None:
                out["change"][k] = np.abs(lum - prev).mean()
            prev = lum
            dx, dy = fx - g["sun_x"][k], fy - g["sun_y"][k]
            d = np.hypot(dx, dy)
            cr_, sr_ = np.cos(g["roll"][k]), np.sin(g["roll"][k])
            ux, uy = cr_ * dx - sr_ * dy, sr_ * dx + cr_ * dy      # un-rolled: the plane's long axis lies along ux
            rho = np.hypot(ux, uy / g["e"][k])                     # distance from the Sun, in the plane
            rest = g["sun_rest"][k]
            near_planet = np.zeros((h, w), dtype=bool)
            on_planet = np.zeros((h, w), dtype=bool)
            for i in range(sc.N_PLANETS):
                x, y, pr = g["planet_x"][k, i], g["planet_y"][k, i], g["planet_r"][k, i]
                if abs(x) > w / h / 2 + 0.1 or abs(y) > 0.6:
                    continue
                dp = np.hypot(fx - x, fy - y)
                near_planet |= dp < 4.0 * pr + 2.0 / h
                on_planet |= dp < 2.2 * pr + 1.0 / h
            if on_planet.sum() > 12:
                out["planets"][k] = lum[on_planet].mean()
            sun_seen = abs(g["sun_x"][k]) < w / h / 2 - 0.5 * rest and abs(g["sun_y"][k]) < 0.5 - 0.5 * rest
            if sun_seen:
                # The limb: the Sun's radius from its *area* - the pixels that are the colour of
                # the Sun (nothing else on screen is that red and that bright: the corona is a
                # darker band, by design). An area is good to a small fraction of a pixel, and
                # a flare standing on the limb does not move it.
                body = (d < 0.90 * rest) | ((d < 1.50 * rest) & (img[..., 0] > 0.86) & (img[..., 1] > 0.40))
                sector = ((np.arctan2(dy, dx) + np.pi) / (2 * np.pi) * 24).astype(int) % 24
                # ...sector by sector, and the *median* sector: a tongue of flame has a hot core the
                # colour of the Sun, and it stands in one or two sectors; the limb is in all of them
                wedge = np.bincount(sector[body], minlength=24)
                out["limb"][k] = np.sqrt(24 * np.median(wedge) / np.pi) / (rest * h)
                # The corona: how much of the dark round the Sun is lit - its silhouette, in units
                # of the Sun's disc - and again sector by sector, because a prominence is
                # *somewhere*: the tallest sector over the usual one. The kick swells the whole rim
                # alike and a clap's ring is born all the way round, and neither changes this.
                # (Everything beyond the limb counts, hot core and all.)
                lit = (d >= (out["limb"][k] + 0.03) * rest) & (d < 2.6 * rest) & (lum > 0.14) & ~near_planet
                per = np.bincount(sector[lit], minlength=24) / (np.pi * (rest * h) ** 2 / 24)
                out["corona"][k] = per.max() - np.median(per)
                out["heart"][k] = lum[d < 0.45 * rest].mean() if (d < 0.45 * rest).sum() > 6 else np.nan
            # the plane of the orbits close round the Sun, to either side of it, where a
            # clap's ring is born and where it is seen edge to edge
            # (from 1.9 radii out: a new ring is there within its second frame, and the corona's
            # tongues are not. Thin lines, so: the share of the region that is lit, not its mean.)
            plane = (rho > 1.90 * rest) & (rho < 3.4 * rest) & (np.abs(ux) > 1.4 * np.abs(uy)) & ~near_planet
            if plane.sum() > 40:
                out["plane"][k] = (lum[plane] > 0.20).mean()
            far = (rho > 1.08 * g["outer"][k]) & ~near_planet
            if far.sum() > 400:
                out["sky"][k] = np.where(lum[far] > 0.30, lum[far], 0.0).mean()
            if progress and k % 3000 == 0:
                print(f"    frame {k}/{len(times)}", flush=True)
    finally:
        r.release()
    out["t"] = times
    return out


def _recall(sig: np.ndarray, fps: float, start: float, events: np.ndarray, rng) -> tuple[float, int]:
    """`measure.recall`, asked only where the detector could see what it watches."""
    dur = len(sig) / fps
    ev = events[(events > start + 0.1) & (events < start + dur - 0.1)]
    frames = measure.first_frame(ev, fps, start)
    frames = frames[(frames >= 2) & (frames < len(sig) - 2)]
    seen = np.isfinite(sig[frames - 2]) & np.isfinite(sig[frames - 1]) & np.isfinite(sig[frames]) & np.isfinite(sig[frames + 1])
    frames = frames[seen]
    if len(frames) < 5:
        return float("nan"), int(len(frames))
    got = measure.response(sig, frames)
    cand = rng.uniform(start + 0.1, start + dur - 0.1, 6000)
    cand = cand[np.abs(cand[:, None] - ev[None, :]).min(axis=1) > 0.06]
    nf = measure.first_frame(cand, fps, start)
    nf = nf[(nf >= 2) & (nf < len(sig) - 2)]
    null = measure.response(sig, nf)
    null = null[np.isfinite(null)]
    if len(null) < 20:
        return float("nan"), int(len(frames))
    return float((got > np.percentile(null, 95)).mean()), int(len(frames))


def sync(got: dict, ch: direct.Channels, camera: str, start: float = 0.0, duration: float | None = None,
         fps: int = 60, quiet: bool = False) -> dict:
    """The whole mix, one camera: is each instrument's hit seen where it should be, on
    its frame; and in each act, how far do the hits stand above what is always moving."""
    a = got["arrays"]
    sig = signals(ch, start, duration, camera, fps=fps, progress=not quiet)
    rng = np.random.default_rng(0)
    out = {"camera": camera, "roles": {}, "acts": []}
    for name, (det, thr) in ASK.items():
        ev = a[f"ev_{name}_t"][a[f"ev_{name}_amp"] > thr]
        rec, n = _recall(sig[det], fps, start, ev, rng)
        centres, avg, _ = measure.triggered_average(np.nan_to_num(sig[det], nan=float(np.nanmedian(sig[det]))), fps, start, ev)
        onset, peak = measure.onset_of(centres, avg)
        out["roles"][name] = {"detector": det, "recall": rec, "asked": n, "onset_ms": 1000 * onset, "peak": peak}
    change = sig["change"]
    for act in getattr(ch, "acts", []):
        seg = change[int(max(act.start - start, 0) * fps):int(max(act.end - start, 0) * fps)]
        if len(seg) > 60:
            out["acts"].append({"act": act.index, "function": act.function, "floor": float(np.median(seg)),
                                "hits": float(np.percentile(seg, 98)),
                                "ratio": float(np.percentile(seg, 98) / max(np.median(seg), 1e-9))})
    if not quiet:
        print(f"  {camera}: instrument -> detector   recall   asked   onset")
        for name, r_ in out["roles"].items():
            print(f"    {name:10s} -> {r_['detector']:8s} {r_['recall']:6.2f} {r_['asked']:7d} {r_['onset_ms']:+7.1f} ms")
        for r_ in out["acts"]:
            print(f"    act {r_['act']} {r_['function']:10s} hits stand x{r_['ratio']:.1f} above the floor")
    return out


OWNER = {"limb": "kick", "corona": "bass", "heart": "voice", "plane": "snare", "planets": "note", "sky": "hat"}


def _lift(sig: np.ndarray, fps: float, start: float, events: np.ndarray) -> float:
    """How far a detector's reading rises across this instrument's hits: the median rise."""
    dur = len(sig) / fps
    ev = events[(events > start + 0.1) & (events < start + dur - 0.1)]
    frames = measure.first_frame(ev, fps, start)
    frames = frames[(frames >= 2) & (frames < len(sig) - 2)]
    rise = measure.response(sig, frames)
    rise = rise[np.isfinite(rise)]
    return float(np.median(rise)) if len(rise) >= 5 else float("nan")


def matrix(got: dict, ch: direct.Channels, camera: str = "static", start: float = 120.0, duration: float = 40.0) -> dict:
    """Solo each instrument; ask every detector how far it rises on that instrument's hits.

    With one instrument drawn and everything else frozen a detector will notice anything
    at all, so "did it notice" says little. What matters is *how much*: each column is
    given as a fraction of what that detector reads for the instrument it belongs to. A
    column should be 1 in its owner's row and small everywhere else.
    """
    a = got["arrays"]
    solos = {"kick": "kick", "bass": "bass_note", "voice": "syllable", "snare": "snare", "note": "note", "hat": "hat"}
    raw = {}
    for role, ev_name in solos.items():
        sig = signals(render.solo_channels(ch, role), start, duration, camera)
        ev = a[f"ev_{ev_name}_t"][a[f"ev_{ev_name}_amp"] > ASK[ev_name][1]]
        raw[role] = {d: _lift(sig[d], 60, start, ev) for d in DETECTORS}
    table = {role: {d: raw[role][d] / max(abs(raw[OWNER[d]][d]), 1e-9) for d in DETECTORS} for role in solos}
    print(f"separation over {start:.0f}-{start + duration:.0f}s ({camera}): row = the one instrument drawn; column = a detector's rise on its hits, as a fraction of its rise for its own instrument")
    print("          " + " ".join(f"{d:>8s}" for d in DETECTORS))
    for role in solos:
        print(f"  {role:8s}" + " ".join(f"{table[role][d]:8.2f}" for d in DETECTORS))
    return table


def jolt(ch: direct.Channels, camera: str) -> dict:
    """From the channels alone: how fast this camera moves the picture, and how steadily
    it holds what it is looking at. Speeds are in frame heights (or ratios) per second."""
    rows = np.arange(len(ch.data))
    g = geometry(ch, rows, camera)
    rate = direct.RATE
    span = g["span"]
    # the slide: how fast the camera's own middle moves over the scene, in frame heights.
    # (Not how fast the Sun moves in the frame - when it is two frames off to the side, a
    # one-percent zoom moves it a long way, and nobody sees it.)
    cx = ch.data[:, ch.index(f"uCamX.{camera}")].astype(np.float64)
    cy = ch.data[:, ch.index(f"uCamY.{camera}")].astype(np.float64)
    sun_v = np.hypot(np.diff(cx), np.diff(cy)) / span[1:] * rate
    zoom_v = np.abs(np.diff(np.log(span))) * rate
    turn = ch.data[:, ch.index(f"uCamTurn.{camera}")].astype(np.float64)
    turn_v = np.abs(np.diff(turn)) * rate
    # every planet that is in frame: how fast it crosses the picture
    inside = (np.abs(g["planet_x"]) < 0.89) & (np.abs(g["planet_y"]) < 0.5)
    pv = np.hypot(np.diff(g["planet_x"], axis=0), np.diff(g["planet_y"], axis=0)) * rate
    pv = np.where(inside[1:] & inside[:-1], pv, 0.0)
    pa = np.abs(np.diff(pv, axis=0)) * rate
    return {"camera": camera,
            "slide_peak": float(sun_v.max()), "slide_p99": float(np.percentile(sun_v, 99)),
            "slide_over_0.4": float((sun_v > 0.4).mean()),
            "zoom_peak": float(zoom_v.max()), "turn_peak_deg": float(np.degrees(turn_v.max())),
            "planet_speed_peak": float(pv.max()), "planet_speed_p99": float(np.percentile(pv[pv > 0], 99)) if (pv > 0).any() else 0.0,
            "planet_accel_p999": float(np.percentile(pa, 99.9)),
            "worst_at": float(np.argmax(sun_v) / rate)}
