"""Compose the visuals, burn the karaoke in, mux the audio.

One ffmpeg process does all three. Generated frames go in on stdin as raw RGB,
get scaled up to output size, have the .ass burned onto them by libass, and come
out muxed against the track. Writing the frames to a temporary directory first
would double the IO and cost a gigabyte of PNGs for a five-minute song.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from ..audio import probe_duration
from ..project import Project
from . import beats as beat_track
from . import karaoke
from .scene import Scene

FPS = 30
HEIGHT = 720
CRF = "18"          # a smooth gradient is the worst case for h264; cheap insurance
Progress = Callable[[str], None]


def _source_audio(project: Project, workdir: Path) -> tuple[Path, bool]:
    """The best copy of the track on disk, and whether it is only the preview.

    The original if it is still where the alignment found it. The workdir keeps
    a cached mix.m4a for scrubbing in the browser, which will do - but it is a
    lossy encode made for a waveform, so falling back to it is said out loud
    rather than quietly shipped as the audio track of a finished video.
    """
    original = Path(project.audio_path)
    if original.exists():
        return original, False
    if (workdir / "mix.m4a").exists():
        return workdir / "mix.m4a", True
    raise FileNotFoundError(
        f"no audio for {workdir}: neither {project.audio_path} nor mix.m4a"
    )


def _filter_path(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument.

    Backslash, colon and quote all mean something to the filter parser, and a
    path that contains one silently produces a video with no subtitles rather
    than an error.
    """
    text = str(path.resolve())
    for char in ("\\", ":", "'"):
        text = text.replace(char, "\\" + char)
    return text


def _chain(ass: Path, width: int, height: int, offset: float) -> str:
    """The video filter chain: scale, burn, and hand back yuv420p.

    `offset` is non-zero only for a preview. Rather than writing a second,
    shifted .ass for the window - which would mean the thing under test is not
    the thing that ships - the frames are given their real timestamps on the
    track, burned, and then pulled back to zero for the muxer.
    """
    steps = [f"scale={width}:{height}:flags=bicubic"]
    if offset:
        steps.append(f"setpts=PTS+{offset}/TB")
    steps.append(f"ass=f='{_filter_path(ass)}'")
    if offset:
        steps.append(f"setpts=PTS-{offset}/TB")
    steps.append("format=yuv420p")
    return ",".join(steps)


def _window(preview: tuple[float, float] | None, duration: float) -> tuple[float, float]:
    if not preview:
        return 0.0, duration
    start = max(0.0, min(float(preview[0]), duration))
    end = max(start + 0.5, min(float(preview[1]), duration))
    return start, end


def run(
    workdir: Path | str,
    out: Path | str | None = None,
    preview: tuple[float, float] | None = None,
    fps: int = FPS,
    height: int = HEIGHT,
    progress=print,
) -> Path:
    workdir = Path(workdir)
    project = Project.load(workdir / "project.json")
    audio, is_preview = _source_audio(project, workdir)
    duration = probe_duration(audio)

    width = int(round(height * 16 / 9)) // 2 * 2
    start, end = _window(preview, duration)
    frames = math.ceil((end - start) * fps)
    out = Path(out) if out else workdir / ("karaoke-preview.mp4" if preview else "karaoke.mp4")

    progress(f"[1/4] beat tracking {audio}")
    if is_preview:
        progress(
            f"      {project.audio_path} is gone; the video will carry the "
            f"cached preview encode"
        )
    cached = (workdir / "beats.json").exists()
    grid = beat_track.build(audio, workdir)
    progress(
        f"      {grid['tempo']:.1f} BPM, {len(grid['beats'])} beats, "
        f"{len(grid['downbeats'])} downbeats"
        f"{'  (cached)' if cached else ''}"
    )

    progress("[2/4] karaoke subtitles")
    ass = karaoke.write(project, workdir / "lyrics.ass")
    timed = [ln for ln in project.lines if ln.end > ln.start]
    progress(
        f"      {len(timed)} lines, {sum(len(ln.words) for ln in timed)} words"
        f"  ->  {ass}"
    )

    progress("[3/4] visuals from the analysis payload")
    from .. import analysis as analysis_module

    # Returns the cache untouched when analysis.json is already there, which it
    # is for anything that has been opened in the UI. Without the stem the
    # vocal envelope collapses onto the mix one - the picture keeps its beat and
    # loses only the part that opens for the voice.
    stem = Path(project.stem_path or project.audio_path)
    data = analysis_module.build(audio, str(stem if stem.exists() else audio), workdir)
    scene = Scene(project, data, grid, width=width // 2, height=height // 2)
    progress(
        f"      {len(scene.section_at)} sections, "
        f"{scene.w}x{scene.h} upscaled to {width}x{height}"
    )

    span = f"{start:.0f}s..{end:.0f}s" if preview else "whole track"
    progress(f"[4/4] rendering {frames} frames at {fps} fps ({span})")

    part = out.with_suffix(".part.mp4")
    log = Path(tempfile.mkstemp(prefix="song-ffmpeg-", suffix=".log")[1])
    command = [
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{scene.w}x{scene.h}", "-r", str(fps), "-i", "-",
    ]
    if preview:
        command += ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}"]
    command += [
        "-i", str(audio),
        "-filter_complex", f"[0:v]{_chain(ass, width, height, start if preview else 0.0)}[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", CRF,
        "-profile:v", "high", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        # The generated video always runs a frame or two past the audio, since
        # it is a whole number of frames covering a duration that is not.
        "-shortest",
        str(part),
    ]

    started = time.time()
    written = 0
    with open(log, "wb") as errors:
        ffmpeg = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        try:
            spoke = started
            for n in range(frames):
                ffmpeg.stdin.write(scene.frame(start + n / fps).tobytes())
                written = n + 1
                now = time.time()
                if now - spoke > 4.0:
                    spoke = now
                    done = written / frames
                    left = (now - started) * (1 - done) / max(done, 1e-6)
                    progress(
                        f"      {written}/{frames}  {done * 100:3.0f}%  "
                        f"{now - started:.0f}s in, ~{left:.0f}s left"
                    )
            ffmpeg.stdin.close()
            ffmpeg.wait()
        except (KeyboardInterrupt, BrokenPipeError) as exc:
            # No partial resume: x264 output cannot be concatenated without
            # keyframe bookkeeping that costs more than re-running the render,
            # and --preview already makes iterating cheap. So the half-written
            # file goes, rather than sitting there looking finished.
            ffmpeg.kill()
            ffmpeg.wait()
            part.unlink(missing_ok=True)
            if isinstance(exc, KeyboardInterrupt):
                progress(f"      interrupted at frame {written}/{frames}; nothing written")
                raise
            raise RuntimeError(
                f"ffmpeg exited after {written} frames:\n{log.read_text()[-2000:]}"
            ) from exc

        if ffmpeg.returncode != 0:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg failed:\n{log.read_text()[-2000:]}")

    log.unlink(missing_ok=True)
    # Renamed only once ffmpeg is happy, so an interrupted run never leaves
    # something with the right name and half the song in it.
    shutil.move(str(part), str(out))
    size = out.stat().st_size / 1048576
    progress(
        f"      done in {time.time() - started:.0f}s  ->  {out}  "
        f"({size:.1f} MB, {end - start:.0f}s)"
    )
    return out
