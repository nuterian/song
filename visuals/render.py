"""Off-screen rendering, and the mp4.

The context is moderngl's standalone one, which on macOS comes up on CGL and
reports itself as OpenGL 4.1. That is the newest desktop GL Apple ships and it
will not accept a `#version 300 es` shader, so the same shader body is compiled
under `#version 410 core` here and under `#version 300 es` in the browser. The
body is written to the intersection of the two dialects; see DESIGN.md.

Frames go to ffmpeg over a pipe as raw RGB, and ffmpeg muxes the track's own audio
alongside, so what comes out is watchable rather than a folder of PNGs.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import moderngl
import numpy as np

from . import grammar, schema
from .listen import Track
from .uniforms import UniformTrack

# A full-screen triangle rather than a quad: one fewer vertex, no seam, and the
# vertex shader stays a single line.
FULLSCREEN = np.array([-1.0, -1.0, 3.0, -1.0, -1.0, 3.0], dtype="f4")


@dataclass
class RenderStats:
    frames: int
    seconds: float
    programs: int
    gl_version: str
    renderer: str

    @property
    def fps(self) -> float:
        return self.frames / self.seconds if self.seconds else 0.0

    def __str__(self) -> str:
        return (f"{self.frames} frames in {self.seconds:.1f}s "
                f"({self.fps:.1f} fps, {self.seconds / max(self.frames, 1) * 1000:.1f} ms/frame), "
                f"{self.programs} program(s), {self.renderer} / GL {self.gl_version}")


class Renderer:
    """One GL context, one ping-pong pair, and a program per distinct section."""

    def __init__(self, width: int = 1280, height: int = 720) -> None:
        self.width = width
        self.height = height
        self.ctx = moderngl.create_standalone_context(require=330)
        self.gl_version = str(self.ctx.info.get("GL_VERSION", "?"))
        self.gl_renderer = str(self.ctx.info.get("GL_RENDERER", "?"))
        self.quad = self.ctx.buffer(FULLSCREEN.tobytes())
        self._programs: dict[str, tuple[moderngl.Program, moderngl.VertexArray]] = {}

        # The pair the feedback and bloom stages read from and write to. Float
        # would hold more headroom, but the tonemap already bounds the frame to
        # 0..1 so eight bits per channel is what the picture actually needs.
        self.tex = [self.ctx.texture((width, height), 4, dtype="f1") for _ in range(2)]
        for t in self.tex:
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = t.repeat_y = False
        self.fbo = [self.ctx.framebuffer(color_attachments=[t]) for t in self.tex]
        for f in self.fbo:
            f.use()
            f.clear(0.0, 0.0, 0.0, 1.0)
        self.front = 0

    def program(self, score: schema.Score):
        """The song's one program. A song has exactly one, which is the point."""
        key = grammar.program_key(score)
        if key not in self._programs:
            try:
                prog = self.ctx.program(
                    vertex_shader=grammar.vertex_source(grammar.GL_HEADER),
                    fragment_shader=grammar.fragment_source(score, grammar.GL_HEADER),
                )
            except Exception as exc:  # the score is legal, so this is a block bug
                raise RuntimeError(f"{key} did not compile: {exc}") from None
            vao = self.ctx.vertex_array(prog, [(self.quad, "2f", "aPos")])
            self._programs[key] = (prog, vao)
        return self._programs[key]

    def frame(self, score: schema.Score, values: dict[str, float]) -> np.ndarray:
        """Draw one frame and read it back as (height, width, 3) uint8, top row first."""
        prog, vao = self.program(score)
        src, dst = self.front, 1 - self.front
        self.fbo[dst].use()
        self.tex[src].use(0)
        if "uPrev" in prog:
            prog["uPrev"].value = 0
        if "uResolution" in prog:
            prog["uResolution"].value = (float(self.width), float(self.height))
        for name, v in values.items():
            # Unused uniforms are optimised away, and a score that routes nothing
            # at a uniform leaves it out of the compiled program entirely.
            if name in prog:
                prog[name].value = float(v)
        vao.render(moderngl.TRIANGLES)
        self.front = dst
        buf = np.frombuffer(self.fbo[dst].read(components=3), dtype=np.uint8)
        # GL's origin is bottom left; everything downstream wants top left.
        return buf.reshape(self.height, self.width, 3)[::-1]

    def release(self) -> None:
        self.ctx.release()

    def __enter__(self) -> "Renderer":
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    @property
    def n_programs(self) -> int:
        return len(self._programs)


def frame_times(start: float, duration: float, fps: int) -> np.ndarray:
    """The instants each frame is sampled at, which is the end of its own span."""
    n = max(1, int(round(duration * fps)))
    return start + (np.arange(n, dtype=np.float64) + 1.0) / fps


def render_frames(
    score: schema.Score,
    track: Track,
    start: float = 0.0,
    duration: float | None = None,
    fps: int = 60,
    size: tuple[int, int] = (1280, 720),
    sink=None,
    renderer: Renderer | None = None,
) -> RenderStats:
    """Render frames, handing each to `sink` if given. Returns timing.

    Rendering always begins at `start`, and the feedback buffer begins black, so a
    preview from the middle of a song looks the way it would if the song had begun
    there. That is a deliberate simplification, not an oversight: warming the
    feedback up would mean rendering the whole song to preview a bar of it.
    """
    uni = UniformTrack(score, track)
    duration = uni.duration - start if duration is None else duration
    duration = max(1.0 / fps, min(duration, max(0.0, uni.duration - start)))
    own = renderer is None
    r = renderer or Renderer(*size)
    try:
        times = frame_times(start, duration, fps)
        t0 = time.perf_counter()
        for t in times:
            frame = r.frame(score, uni.at(float(t), 1.0 / fps))
            if sink is not None:
                sink(frame)
        elapsed = time.perf_counter() - t0
        return RenderStats(len(times), elapsed, r.n_programs, r.gl_version, r.gl_renderer)
    finally:
        if own:
            r.release()


def render_mp4(
    score: schema.Score,
    track: Track,
    out_path: str | Path,
    start: float = 0.0,
    duration: float | None = None,
    fps: int = 60,
    size: tuple[int, int] = (1280, 720),
    crf: int = 20,
) -> RenderStats:
    """Render to an mp4 with the track's own audio under it."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not on PATH; brew install ffmpeg")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    audio = track.workdir / "mix.m4a"
    total = track.duration - start if duration is None else duration
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-",
    ]
    if audio.exists():
        cmd += ["-ss", f"{start:.3f}", "-i", str(audio), "-map", "0:v", "-map", "1:a",
                "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-shortest", str(out_path)]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        stats = render_frames(
            score, track, start=start, duration=duration, fps=fps, size=size,
            sink=lambda f: proc.stdin.write(np.ascontiguousarray(f).tobytes()),
        )
    except BrokenPipeError:  # ffmpeg died; its stderr says why
        proc.wait()
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.read().decode()[:800]}") from None
    proc.stdin.close()
    err = proc.stderr.read().decode()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg exited {proc.returncode}: {err[:800]}")
    return stats
