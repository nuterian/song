"""Headless GL to an mp4, and the same piece staged for the browser player.

Frame n is on screen from n / fps, and is drawn from the state at the *end* of its
span, (n + 1) / fps - the convention `visuals.render` already uses. So a hit at
time t first shows in the frame that is on screen when t arrives: the picture is
up to one frame early and never late, which is the side of the line the eye
forgives.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import moderngl
import numpy as np

from . import AUDIO, CACHE, ROOT, TRACK, WORKDIR, cosmos, direct, models, shader, shader_cosmos, shader_ink, sky

# Which shader draws. Set once by the command line; everything that renders reads it.
STYLE = "glow"


def shader_module(style: str | None = None):
    return {"ink": shader_ink, "cosmos": shader_cosmos}.get(style or STYLE, shader)


def bake(got: dict) -> direct.Channels:
    """The channels the current style's shader reads."""
    mod = models.load_cached(CACHE)
    return cosmos.bake(got, mod) if STYLE == "cosmos" else direct.direct(got, mod)


CATALOGUE = ROOT / "visuals" / "cache" / "catalogues" / "bsc5.dat"


def data_textures() -> dict[str, np.ndarray]:
    """Lookup textures the current style's shader samples: (height, width, 4) float32."""
    if STYLE != "cosmos":
        return {}
    if not CATALOGUE.exists():
        raise SystemExit(f"no star catalogue at {CATALOGUE}; see the docstring of sky.py")
    galaxy = CATALOGUE.parent / "milkyway_2020_4k_gal_print.jpg"
    if not galaxy.exists():
        raise SystemExit(f"no Milky Way map at {galaxy}; see sky.milky_way")
    return {"uStarTex": sky.build(CATALOGUE)["texture"], "uGalaxyTex": sky.milky_way(galaxy)[..., None]}


FULLSCREEN = np.array([-1.0, -1.0, 3.0, -1.0, -1.0, 3.0], dtype="f4")

# Which channels belong to which instrument. `solo` keeps one role live and holds
# every other channel still, which is how the separation matrix is measured.
ROLES: dict[str, tuple[str, ...]] = {
    "kick": ("uKickA",),
    "snare": tuple(f"uRingA{k}" for k in range(direct.N_RINGS)),
    "hat": ("uHatA", "uCrashA"),
    "note": tuple(f"uNoteA{k}" for k in range(direct.N_SATS)),
    "voice": ("uVoice", "uSyllA", "uPitch", "uSustain", "uTint"),
    "bass": ("uBass",),
    "drop": ("uDropA",) + tuple(f"uMetA{k}" for k in range(direct.N_METEORS)),
}
# clocks: frozen in a solo, so that only the soloed instrument moves anything
CLOCKS = ("uOrbit", "uOrbitSlow", "uDrift", "uBeats") + tuple(f"uPh{i}" for i in range(8))
SILENT_IN_SOLO = ("uVoice", "uSustain", "uTint", "uPump")


# What a section decides. With only these live - every hit silenced, every follower
# of the audio held still, the clocks running - any step in the picture is a step
# in a decision, and there should not be one.
SECTION_LEVEL = tuple(f"uC{role}{c}" for role in direct.PALETTE_ROLES for c in "RGB") + (
    "uRays", "uBands", "uStars", "uTilt", "uIncl", "uCamTilt", "uCamRoll")


def sections_only(ch: direct.Channels) -> direct.Channels:
    data = ch.data.copy()
    sizes = {name for names in ROLES.values() for name in names}
    for c, (name, kind) in enumerate(zip(ch.names, ch.kinds)):
        if name in SECTION_LEVEL or name in CLOCKS:
            continue
        if kind == direct.HOLD:
            if name in sizes:
                data[:, c] = 0.0
        elif name in SILENT_IN_SOLO:
            data[:, c] = 0.0
        else:
            data[:, c] = np.median(ch.data[:, c])
    return direct.Channels(ch.names, ch.kinds, data, ch.drops, ch.duration, ch.sections, ch.info)


def solo_channels(ch: direct.Channels, role: str) -> direct.Channels:
    if role == "sections":
        return sections_only(ch)
    if role not in ROLES:
        raise SystemExit(f"--solo takes one of {sorted(ROLES)}")
    data = ch.data.copy()
    live = set(ROLES[role])
    sizes = {name for names in ROLES.values() for name in names}
    for c, (name, kind) in enumerate(zip(ch.names, ch.kinds)):
        if name in live:
            continue
        if name in CLOCKS:
            data[:, c] = ch.data[len(ch.data) // 2, c]
        elif kind == direct.HOLD:
            if name in sizes:
                data[:, c] = 0.0                  # an event's size: no size, no event
        elif name in SILENT_IN_SOLO:
            data[:, c] = 0.0
        else:
            data[:, c] = np.median(ch.data[:, c])  # every level, palette included, held still
    return direct.Channels(ch.names, ch.kinds, data, ch.drops, ch.duration)


class Renderer:
    def __init__(self, width: int, height: int, supersample: int = 1) -> None:
        """`supersample` says these pixels are that many to an output pixel along a side:
        the frame is meant to be scaled down by it afterwards. A shader that knows about
        it (`uSS`) keeps its sizes in output pixels, so the scaled-down frame is the same
        picture with its edges resolved from more samples."""
        self.size = (width, height)
        self.ctx = moderngl.create_standalone_context(require=330)
        sh = shader_module()
        self.prog = self.ctx.program(vertex_shader=sh.vertex_source(),
                                     fragment_shader=sh.fragment_source())
        quad = self.ctx.buffer(FULLSCREEN.tobytes())
        self.vao = self.ctx.vertex_array(self.prog, [(quad, "2f", "aPos")])
        self.tex = self.ctx.texture((width, height), 4, dtype="f1")
        self.fbo = self.ctx.framebuffer(color_attachments=[self.tex])
        self.prog["uResolution"].value = (float(width), float(height))
        if "uSS" in self.prog:
            self.prog["uSS"].value = float(supersample)
        self.textures = []
        for unit, (name, arr) in enumerate(data_textures().items()):
            tex = self.ctx.texture((arr.shape[1], arr.shape[0]), arr.shape[2], arr.astype("f4").tobytes(), dtype="f4")
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            tex.use(unit)
            if name in self.prog:
                self.prog[name].value = unit
            self.textures.append(tex)
        self.fbo.use()

    def bind(self, names: list[str]) -> None:
        """Look each uniform up once. One the compiler dropped is simply not set."""
        self.slots = [(c, self.prog[n]) for c, n in enumerate(names) if n in self.prog]

    def frame(self, t: float, row: np.ndarray) -> np.ndarray:
        self.prog["uTime"].value = float(t)
        for c, u in self.slots:
            u.value = float(row[c])
        self.vao.render(moderngl.TRIANGLES)
        buf = np.frombuffer(self.fbo.read(components=3), dtype=np.uint8)
        return buf.reshape(self.size[1], self.size[0], 3)[::-1]

    def release(self) -> None:
        self.ctx.release()


def frame_times(start: float, duration: float, fps: int) -> np.ndarray:
    n = max(1, int(round(duration * fps)))
    return start + (np.arange(n, dtype=np.float64) + 1.0) / fps


def render(got: dict, out_dir: str | Path, start: float = 0.0, duration: float | None = None,
           size: tuple[int, int] = (1920, 1080), fps: int = 60, crf: int = 17,
           solo: str | None = None, quiet: bool = False) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ch = bake(got)
    if solo:
        ch = solo_channels(ch, solo)
    total = ch.duration - start if duration is None else min(duration, ch.duration - start)

    whole = start == 0.0 and duration is None and not solo
    name = "piece.mp4" if whole else f"piece-{solo or 'clip'}-{start:.0f}s.mp4"
    out_path = out_dir / name

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}",
           "-r", str(fps), "-i", "-",
           "-ss", f"{start:.6f}", "-i", str(AUDIO),
           "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "256k",
           "-t", f"{total:.6f}",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None

    r = Renderer(*size)
    t0 = time.perf_counter()
    times = frame_times(start, total, fps)
    rows = ch.rows(times)
    r.bind(ch.names)
    try:
        for t, row in zip(times, rows):
            proc.stdin.write(np.ascontiguousarray(r.frame(float(t), row)).tobytes())
    except BrokenPipeError:
        proc.wait()
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.read().decode()[:800]}") from None
    finally:
        r.release()
    proc.stdin.close()
    err = proc.stderr.read().decode()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg exited {proc.returncode}: {err[:800]}")
    dt = time.perf_counter() - t0
    if not quiet:
        print(f"{len(times)} frames in {dt:.1f}s ({len(times) / dt:.0f} fps)")

    if whole:
        export(got, ch, out_dir)
    return out_path


def stage(got: dict, out_dir: str | Path) -> Path:
    """Only what the browser player needs - the shader and the baked channels - and
    no mp4. Seconds rather than minutes, which is what trying a look wants."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    Renderer(64, 36).release()              # compile it here first: a GLSL error is better read now
    export(got, bake(got), out_dir)
    return out_dir


def export(got: dict, ch: direct.Channels, out_dir: Path) -> None:
    """plan.json + frames.bin + audio, in the format visuals/player already reads."""
    meta = got["meta"]
    bar = 4 * meta["period"]
    edges = [0.0] + [d["t"] for d in ch.drops if d["t"] > bar] + [ch.duration]
    sections = [{"index": i, "name": f"from bar {int(round(a / bar))}", "start": a, "end": b,
                 "scene": "gravity"} for i, (a, b) in enumerate(zip(edges[:-1], edges[1:]))]
    plan = {
        "version": 1, "track": TRACK, "duration": ch.duration, "tempo": meta["tempo"],
        "meter": 4, "seed": 0, "grid": ch.header(), "per_frame": ["uTime"],
        "sections": sections,
        "program": {"key": f"gravity-in-motion-{STYLE}",
                    "fragment": shader_module().fragment_source(shader.WEBGL_HEADER)},
        "vertex": shader_module().vertex_source(shader.WEBGL_HEADER),
        "frames_file": "frames.bin", "audio_file": "mix.m4a",
        "drops": ch.drops,
        "plan": [{"bars": [s.bar0, s.bar1], "state": s.state, "hue": s.hue, "axes": s.axes}
                 for s in (ch.sections or [])],
    }
    plan["textures"] = []
    for name, arr in data_textures().items():
        file = f"{name}.bin"
        (out_dir / file).write_bytes(arr.astype("<f4").tobytes())
        plan["textures"].append({"name": name, "file": file, "width": int(arr.shape[1]),
                                 "height": int(arr.shape[0]), "channels": int(arr.shape[2])})
    if getattr(ch, "acts", None):
        plan["acts"] = [{"start": a.start, "end": a.end, "function": a.function,
                         "subject": a.subject if a.subject >= 0 else None} for a in ch.acts]
    (out_dir / "frames.bin").write_bytes(ch.data.astype("<f4").tobytes())
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    src, dst = WORKDIR / "mix.m4a", out_dir / "mix.m4a"
    if src.exists():
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        try:
            os.symlink(src, dst)
        except OSError:
            shutil.copy2(src, dst)
