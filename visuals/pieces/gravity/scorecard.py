"""One screen per song: what was heard, what plays what, the shape found, and how the
picture moves - every line against a stated bound, with a verdict.

    python -m visuals make <song> [--render]                   ends with it
    python -m visuals.pieces.gravity --track <song> --style cosmos scorecard [--render]

`--render` adds what can only be known by drawing: whether the sparse parts are seen
(recall against the null, static camera) and the frame time at 1080p. It takes minutes.

Written to `scorecard.json` beside the bundle, so it travels with what it describes.
"""

from __future__ import annotations

import functools
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import cosmos, direct, follow, grid, render
from .listen import STEMS
from .track import Track

PASS, WARN, FAIL, INFO = "pass", "warn", "fail", "info"

# Each part's own channels: what it alone moves. (A role in render.ROLES also lists
# channels others move - the planets' lean answers the kick and their own idle dance - so
# "did any of them move" never finds a dead part.)
OWN = {
    "pulse": ("uKickA", "uSunPulse", "uKickE"),
    "ring": tuple(f"uRingA{k}" for k in range(direct.N_RINGS)),
    "stars": ("uHatA", "uHatE0", "uHatE1", "uHatE2"),
    "corona": ("uBass",) + tuple(f"uPromA{k}" for k in range(4)),
    "planets": tuple(f"uNoteA{k}" for k in range(direct.N_SATS)),
    "heart": ("uVoice", "uSyllA", "uSyllE"),
}

# The theme's parts, and what plays each until casting decides otherwise: the event
# kind, the stem it is heard in, and the channels (render.ROLES) that move with it.
PARTS = {
    "pulse": ("kick", "drums", "kick"),
    "ring": ("snare", "drums", "snare"),
    "stars": ("hat", "drums", "hat"),
    "corona": ("bass_note", "bass", "bass"),
    "planets": ("note", "other", "note"),
    "heart": ("syllable", "vocals", "voice"),
}
DEAD = 0.10                  # a part that moves in fewer 2 s windows than this is dead
JOLT = {"slide_peak": 0.40, "zoom_peak": 0.45, "planet_speed_peak": 1.0, "planet_speed_p99": 0.30}
SEEN = {"pulse": ("kick", 0.90), "ring": ("snare", 0.50), "heart": ("syllable", 0.50)}
FRAME_MS = 1000.0 / 60.0


@dataclass
class Line:
    group: str
    name: str
    value: str
    bound: str = ""
    verdict: str = INFO
    data: dict = field(default_factory=dict)


def _check(ok: bool, bad: str = FAIL) -> str:
    return PASS if ok else bad


# ------------------------------------------------------------------- listening


def listening(got: dict) -> list[Line]:
    a, m = got["arrays"], got["meta"]
    g = m["grid"]
    out = [Line("listening", "tempo", f"{m['tempo']:.3f} BPM, {m.get('meter', 4)} to a bar, {g.get('source', '?')} grid")]
    lat = g.get("lattice")
    if g.get("source") == "lattice":
        out.append(Line("listening", "on the lattice", f"{lat['on_lattice']:.2f} of hats and claps within 4 ms",
                        f">= {grid.GATE}", _check(lat["on_lattice"] >= grid.GATE)))
        out.append(Line("listening", "lattice residual", f"{lat['sharp_residual_ms']:.2f} ms rms", "<= 3 ms",
                        _check(lat["sharp_residual_ms"] <= 3.0)))
        drift = max((abs(d) for d in lat.get("drift_ms_per_30s", [])), default=0.0)
        out.append(Line("listening", "tempo drift", f"{drift:.2f} ms, worst 30 s mean", "<= 2 ms", _check(drift <= 2.0, WARN)))
    else:
        tr = g.get("tracked", {})
        why = f"{lat['on_lattice']:.2f} of hits on the best lattice" if lat else "too few hats and claps for a lattice"
        out.append(Line("listening", "no lattice", f"{why}; Beat This!'s beats, {tr.get('snapped', 0):.2f} snapped to attacks",
                        f"lattice >= {grid.GATE}", WARN))
    out.append(Line("listening", "meter agreement", f"{g.get('meter_agreement', 0):.2f} of Beat This!'s bars have {m.get('meter', 4)} beats",
                    ">= 0.80", _check(g.get("meter_agreement", 0) >= 0.8, WARN)))
    votes = g["bar_phase_votes"] if g.get("bar_phase_from") == "kick re-entries" else g.get("beat_this_downbeat_votes", [])
    agree = max(votes) / max(sum(votes), 1) if votes else 0.0
    out.append(Line("listening", "bar phase", f"from {g.get('bar_phase_from')}: {agree:.2f} agree ({votes})", ">= 0.75",
                    _check(agree >= 0.75, WARN)))
    if len(a.get("bt_beats", [])):
        beats = a["beats"]
        late = grid.lateness(a["bt_beats"], beats, np.ones(len(beats)))
        b = a["bt_beats"] + late
        j = np.clip(np.searchsorted(beats, b), 1, len(beats) - 1)
        share = float((np.minimum(np.abs(b - beats[j - 1]), np.abs(b - beats[j])) < 0.025).mean())
        steady = g.get("beat_this", {}).get("steady", 1.0)
        if steady < grid.BT_STEADY:
            out.append(Line("listening", "Beat This! agrees", f"{share:.2f} of its beats within 25 ms; not a referee here: "
                            f"its beats are steady for only {steady:.2f} of gaps"))
        else:
            out.append(Line("listening", "Beat This! agrees", f"{share:.2f} of its beats within 25 ms (after its {1000 * -late:.0f} ms lateness)",
                            ">= 0.80", _check(share >= 0.8, WARN)))
    pres = m.get("presence", {})
    for s in STEMS:
        p = pres.get(s)
        if p is not None:
            dropped = sum(p.get("dropped", {}).values())
            out.append(Line("listening", f"{s} plays", f"{p['playing']:.2f} of bars" + (f"; {dropped} leakage events dropped" if dropped else "")))
    return out


# --------------------------------------------------------------------- casting


def _moves(ch: direct.Channels, names: tuple[str, ...], window: float = 2.0) -> float:
    """Share of `window`-second stretches in which any of these channels changes by more
    than 1 % of its whole-song range."""
    idx = [ch.index(n) for n in names if n in ch.names]
    if not idx:
        return 0.0
    x = ch.data[:, idx].astype(np.float64)
    rng = x.max(0) - x.min(0)
    rng[rng == 0] = 1.0
    n = int(window * direct.RATE)
    k = len(x) // n
    seg = x[: k * n].reshape(k, n, -1)
    return float((((seg.max(1) - seg.min(1)) / rng) > 0.01).any(1).mean())


def casting(got: dict, ch: direct.Channels) -> list[Line]:
    a, m = got["arrays"], got["meta"]
    cast = (ch.info or {}).get("cast", {}) if isinstance(ch.info, dict) else {}
    out = []
    for part, (kind, stem, role) in PARTS.items():
        c = cast.get(part, {"source": stem, "why": "by stem name"})
        moves = _moves(ch, OWN[part])
        plays = float(np.mean(a[f"present_{c['source']}"])) if f"present_{c['source']}" in a else None
        n_ev = c.get("events", len(a.get(f"ev_{kind}_t", [])))
        where = f"plays in {plays:.2f} of bars" if plays is not None else f"from the {c['source']}"
        value = f"{c['source']} ({c.get('why', '')}): {where}, {n_ev} events; moves in {moves:.2f} of the song"
        if c.get("silent"):
            out.append(Line("casting", part, f"silent: {c.get('why', '')}", "", WARN, {"moves": moves}))
        else:
            out.append(Line("casting", part, value, f"moves >= {DEAD}", _check(moves >= DEAD),
                            {"source": c["source"], "moves": moves, "plays": plays}))
    return out


# ------------------------------------------------------------------- structure


def structure(got: dict, ch: direct.Channels, cast_got: dict | None = None) -> list[Line]:
    """`cast_got` is the song as cast: the pulse's events are whatever plays the pulse."""
    m = got["meta"]
    secs = ch.sections or []
    states = [s.state for s in secs for _ in range(max(s.bar1 - s.bar0, 0))]
    share = {st: states.count(st) / max(len(states), 1) for st in ("drive", "float", "void", "silent")}
    out = [Line("structure", "sections", f"{len(secs)}; bars " + ", ".join(f"{k} {v:.2f}" for k, v in share.items()))]
    a = (cast_got or got)["arrays"]
    kicks = a["ev_kick_t"][a["ev_kick_amp"] > 0.5]
    bars = a["bar_t"]
    pulse_plays = (len(np.unique(np.clip(np.searchsorted(bars, kicks, side="right") - 1, 0, len(bars) - 1))) / len(bars)
                   if len(kicks) and len(bars) else 0.0)
    out.append(Line("structure", "drive", f"{share['drive']:.2f} of bars drive; the pulse strikes in {pulse_plays:.2f} of them",
                    "drive >= half of where the pulse strikes", _check(share["drive"] >= 0.5 * pulse_plays, WARN)))
    out.append(Line("structure", "re-entries", f"{len(ch.drops)}", ">= 1", _check(len(ch.drops) >= 1, WARN)))
    acts = getattr(ch, "acts", []) or []
    out.append(Line("structure", "acts", f"{len(acts)}: " + " ".join(x.function for x in acts)))
    if getattr(ch, "climax", None) is not None:
        out.append(Line("structure", "climax", f"at {ch.climax:.1f} s, {ch.climax / m['duration']:.2f} of the song"))
    return out


# --------------------------------------------------------------------- picture


@functools.lru_cache(maxsize=1)
def drawn() -> frozenset:
    """The uniforms the compiled cosmos program keeps: the channels that can move a pixel."""
    style, render.STYLE = render.STYLE, "cosmos"
    try:
        r = render.Renderer(8, 8)
        names = frozenset(r.prog)
        r.release()
        return names
    finally:
        render.STYLE = style


def envelope(ch: direct.Channels, reference: Path) -> Line:
    """Channels this song drives outside the range the piece was tuned in (Gravity's)."""
    plan, frames = reference / "plan.json", reference / "frames.bin"
    if not frames.exists():
        return Line("picture", "tuned range", f"no reference bundle at {reference}")
    names = [f["name"] for f in json.loads(plan.read_text())["grid"]["features"]]
    ref = np.fromfile(frames, "<f4").reshape(-1, len(names))
    outside = []
    for i, name in enumerate(names):
        base = name.split(".")[0]
        if name not in ch.names or base not in drawn() or base.rstrip("0123456789").endswith("T") or base in render.CLOCKS \
                or base.startswith(("uPh", "uSpin", "uCamTurn", "uPluto")):
            continue                     # times, clocks and orbits run on with the song; a heading is per song
        lo, hi = float(ref[:, i].min()), float(ref[:, i].max())
        x = ch.data[:, ch.index(name)]
        span = max(hi - lo, 1e-9)
        frac = float(((x > hi + 0.02 * span) | (x < lo - 0.02 * span)).mean())
        if frac > 0.01:
            outside.append((frac, name))
    outside.sort(reverse=True)
    return Line("picture", "tuned range", f"{len(outside)} channels outside Gravity's range > 1 % of the time"
                + (": " + ", ".join(f"{n} {f:.2f}" for f, n in outside[:5]) if outside else ""),
                "none", _check(not outside, WARN), {"outside": [[n, f] for f, n in outside]})


def picture(ch: direct.Channels, reference: Path) -> list[Line]:
    out = []
    for mode in cosmos.MODES:
        j = follow.jolt(ch, mode)
        over = [k for k, lim in JOLT.items() if j[k] >= lim]
        out.append(Line("picture", f"jolt, {mode}", ", ".join(f"{k} {j[k]:.2f}" for k in JOLT),
                        ", ".join(f"{k} < {v}" for k, v in JOLT.items()), _check(not over), {k: j[k] for k in JOLT}))
    out.append(envelope(ch, reference))
    return out


def rendered(got: dict, ch: direct.Channels, cast: list[Line]) -> list[Line]:
    """Draw it: are the sparse parts seen, and how long does a frame take."""
    out = []
    plays = {ln.name: ln.data.get("moves", 0.0) for ln in cast}
    sync = follow.sync(got, ch, "static", quiet=True)
    for part, (kind, bound) in SEEN.items():
        r = sync["roles"].get(kind)
        if r is None or plays.get(part, 0.0) < DEAD or r["asked"] < 10:
            out.append(Line("seen", part, "not playing: nothing to see"))
            continue
        out.append(Line("seen", part, f"recall {r['recall']:.2f} of {r['asked']}, half-way up {r['onset_ms']:+.0f} ms",
                        f">= {bound}", _check(r["recall"] >= bound), r))
    ms = frame_times(ch)
    p95 = float(np.percentile(ms, 95))
    out.append(Line("seen", "frame time 1080p", f"mean {ms.mean():.1f} ms, p95 {p95:.1f}, worst {ms.max():.1f} "
                    f"(headless GL, alongside whatever else the machine is doing)", f"p95 <= {FRAME_MS:.1f} ms",
                    _check(p95 <= FRAME_MS), {"mean": float(ms.mean()), "p95": p95, "worst": float(ms.max())}))
    return out


def frame_times(ch: direct.Channels, frames: int = 120, size: tuple[int, int] = (1920, 1080)) -> np.ndarray:
    """Time per frame at 1080p, over the song and all three cameras. Each frame is closed
    by reading back one pixel: `finish()` alone, on Apple's GL over Metal, let frames
    nobody read be skipped (0.4 ms a frame, which this shader cannot do)."""
    r = render.Renderer(*size)
    try:
        r.bind(ch.names)
        times = np.linspace(1.0, ch.duration - 1.0, frames)
        ms = []
        for mode in cosmos.MODES:
            data = ch.data.copy()
            for name in cosmos.PER_CAMERA:
                data[:, ch.index(name)] = ch.data[:, ch.index(f"{name}.{mode}")]
            for k, t in enumerate(np.concatenate([times[:5], times])):      # five to warm up
                row = data[min(int(round(t * direct.RATE)), len(data) - 1)]
                t0 = time.perf_counter()
                r.prog["uTime"].value = float(t)
                for c, u in r.slots:
                    u.value = float(row[c])
                r.vao.render()
                r.fbo.read(viewport=(0, 0, 1, 1))
                if k >= 5:
                    ms.append(1000 * (time.perf_counter() - t0))
        return np.asarray(ms)
    finally:
        r.release()


# ---------------------------------------------------------------------- the card


def build(track: Track, got: dict, ch: direct.Channels, with_render: bool = False) -> dict:
    from . import cast as cast_
    from .make import modelled

    reference = Track.resolve().out("cosmos")
    cast_got = cast_.apply(got, modelled(track, got, verbose=False))[0]
    lines = listening(got)
    cast = casting(got, ch)
    lines += cast + structure(got, ch, cast_got) + picture(ch, reference)
    if with_render:
        # judged by what each part was given: on an instrumental the heart's notes are the lead's
        lines += rendered(cast_got, ch, cast)
    fails = [f"{ln.group}/{ln.name}" for ln in lines if ln.verdict == FAIL]
    warns = [f"{ln.group}/{ln.name}" for ln in lines if ln.verdict == WARN]
    verdict = f"fail: {', '.join(fails)}" if fails else ("pass" if not warns else f"pass, {len(warns)} warnings")
    return {"track": track.slug, "duration": got["meta"]["duration"], "rendered": with_render,
            "verdict": verdict, "fails": fails, "warnings": warns, "lines": [asdict(ln) for ln in lines]}


def show(card: dict) -> str:
    mark = {PASS: "ok  ", WARN: "WARN", FAIL: "FAIL", INFO: "    "}
    rows = [f"scorecard: {card['track']} ({card['duration']:.0f} s)" + ("" if card["rendered"] else "  [not rendered: --render adds recall and frame time]")]
    group = None
    for ln in card["lines"]:
        if ln["group"] != group:
            group = ln["group"]
            rows.append(f"  {group}")
        rows.append(f"    {mark[ln['verdict']]} {ln['name']:18s} {ln['value']}" + (f"   [{ln['bound']}]" if ln["bound"] and ln["verdict"] != INFO else ""))
    rows.append(f"  verdict: {card['verdict']}")
    return "\n".join(rows)


def write(card: dict, out_dir: Path) -> Path:
    path = Path(out_dir) / "scorecard.json"
    path.write_text(json.dumps(card, indent=1, default=float) + "\n")
    return path
