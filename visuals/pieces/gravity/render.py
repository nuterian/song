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

from . import AUDIO, TRACK, WORKDIR, direct, shader

FULLSCREEN = np.array([-1.0, -1.0, 3.0, -1.0, -1.0, 3.0], dtype="f4")

# Which channels belong to which instrument. `solo` keeps one role live and holds
# every other channel still, which is how the separation matrix is measured.
ROLES: dict[str, tuple[str, ...]] = {
    "kick": ("uKickA",),
    "snare": tuple(f"uRingA{k}" for k in range(direct.N_RINGS)),
    "hat": ("uHatA",),
    "note": tuple(f"uNoteA{k}" for k in range(direct.N_SATS)),
    "voice": ("uVoice", "uSyllA", "uPitch"),
    "bass": ("uBass",),
    "drop": ("uDropA",),
}
STILL_AT_MEDIAN = ("uMass", "uSpread", "uBass", "uSynth", "uVoice", "uPitch", "uField",
                   "uAir", "uHue", "uWarm", "uExposure")


def solo_channels(ch: direct.Channels, role: str) -> direct.Channels:
    if role not in ROLES:
        raise SystemExit(f"--solo takes one of {sorted(ROLES)}")
    data = ch.data.copy()
    live = set(ROLES[role])
    for other, names in ROLES.items():
        for name in names:
            if name not in live and name not in STILL_AT_MEDIAN:
                data[:, ch.index(name)] = 0.0    # an event's size: no size, no event
    for name in STILL_AT_MEDIAN:
        if name not in live:
            c = ch.index(name)
            data[:, c] = 0.0 if name in ("uVoice",) else np.median(ch.data[:, c])
    # the orbits keep turning in a solo; freeze them so only the role moves
    c = ch.index("uOrbit")
    data[:, c] = ch.data[len(ch.data) // 2, c]
    return direct.Channels(ch.names, ch.kinds, data, ch.drops, ch.duration)


class Renderer:
    def __init__(self, width: int, height: int) -> None:
        self.size = (width, height)
        self.ctx = moderngl.create_standalone_context(require=330)
        self.prog = self.ctx.program(vertex_shader=shader.vertex_source(),
                                     fragment_shader=shader.fragment_source())
        quad = self.ctx.buffer(FULLSCREEN.tobytes())
        self.vao = self.ctx.vertex_array(self.prog, [(quad, "2f", "aPos")])
        self.tex = self.ctx.texture((width, height), 4, dtype="f1")
        self.fbo = self.ctx.framebuffer(color_attachments=[self.tex])
        self.prog["uResolution"].value = (float(width), float(height))
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
    ch = direct.direct(got)
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
        "program": {"key": "gravity-in-motion-piece",
                    "fragment": shader.fragment_source(shader.WEBGL_HEADER)},
        "vertex": shader.vertex_source(shader.WEBGL_HEADER),
        "frames_file": "frames.bin", "audio_file": "mix.m4a",
        "drops": ch.drops,
    }
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
