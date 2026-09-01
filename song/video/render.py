"""Compose the visuals, burn the karaoke in, mux the audio.

One ffmpeg process does all three. Generated frames go in on stdin as raw
planar RGB, have the .ass burned onto them by libass, and come out muxed against
the track. Writing the frames to a temporary directory first would double the IO
and cost a gigabyte of PNGs for a five-minute song.

Planar rather than packed, because Scene builds its frames a channel at a time
and a channel of a packed frame is every fourth byte. gbrp is the same pixels,
in the layout the generator already has them in, so nothing is transposed
between here and there.
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

# 60, not 30. Everything in this picture is either moving or being animated by
# libass, and both are sampled here: the word swell, the line changes, the wave
# and the beat glow all get twice as many positions to be drawn at. It is also
# what halves the worst frame-to-frame change in the thinnest part of the trace,
# because half the flicker in a hairline is the frame rate failing to keep up
# with it. Affordable because the generator got 2.2x faster first - 286 s of
# track is 295 s of scene time at 60 fps, against 327 s for the 30 it replaces.
FPS = 60
# 1080 by default. The words are vector and libass draws them at whatever the
# output is, so height is most of what "sharp" means here - and the picture
# behind them costs about 40 ms a frame at 1920x1080 against 18 at 1280x720,
# which is the encoder's time anyway.
HEIGHT = 1080
CRF = "17"          # a smooth gradient is the worst case for h264; cheap insurance
Progress = Callable[[str], None]


def _nearby(name: str, workdir: Path) -> list[Path]:
    """Where else the track might be, if it is not where the alignment left it.

    A project records where the audio *was*, and moving or reorganising a
    library after aligning it is entirely normal - this repo's own sample track
    is aligned from data/ and kept in examples/. Every one of these is a
    directory the workdir can see from where it sits.
    """
    roots = [workdir, workdir.parent, workdir.parent.parent, Path.cwd()]
    seen, out = set(), []
    for root in roots:
        for folder in (root, root / "examples", root / "data", root / "audio"):
            candidate = folder / name
            if candidate not in seen:
                seen.add(candidate)
                out.append(candidate)
    return out


def _source_audio(project: Project, workdir: Path,
                  override: Path | str | None = None) -> tuple[Path, bool]:
    """The best copy of the track on disk, and whether it is only the preview.

    The original if it is still where the alignment found it, then anywhere
    obvious nearby, and only then the workdir's cached mix.m4a - which is a
    ~130 kbps encode made so a browser could scrub a waveform, and has no
    business being the audio track of a finished video. Falling back to it is
    said out loud rather than quietly shipped, and it was being shipped: this
    project's own sample video carried it for every render until the search
    below existed.

    A candidate has to be the same length as the track that was aligned, to
    within a frame. Matching on filename alone would happily pick up a different
    take, or a radio edit, and burn a whole video against the wrong audio.
    """
    if override is not None:
        path = Path(override)
        if not path.exists():
            raise FileNotFoundError(f"no audio at {path}")
        return path, False

    original = Path(project.audio_path)
    if original.exists():
        return original, False

    for candidate in _nearby(original.name, workdir):
        if not candidate.exists() or candidate.is_dir():
            continue
        try:
            if abs(probe_duration(candidate) - float(project.duration)) < 0.05:
                return candidate, False
        except Exception:
            continue

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


def _chain(ass: Path, offset: float) -> str:
    """The video filter chain: burn the subtitles, hand back yuv420p.

    `offset` is non-zero only for a preview. Rather than writing a second,
    shifted .ass for the window - which would mean the thing under test is not
    the thing that ships - the frames are given their real timestamps on the
    track, burned, and then pulled back to zero for the muxer.
    """
    steps = []
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
    audio_path: Path | str | None = None,
    progress=print,
) -> Path:
    workdir = Path(workdir)
    project = Project.load(workdir / "project.json")
    audio, is_preview = _source_audio(project, workdir, audio_path)
    duration = probe_duration(audio)

    width = int(round(height * 16 / 9)) // 2 * 2
    start, end = _window(preview, duration)
    frames = math.ceil((end - start) * fps)
    out = Path(out) if out else workdir / ("karaoke-preview.mp4" if preview else "karaoke.mp4")

    progress(f"[1/4] beat tracking {audio}")
    if is_preview:
        progress(
            f"      {project.audio_path} is gone and nothing nearby matches it; "
            f"the video will carry the cached ~130 kbps encode"
        )
    elif str(audio) != project.audio_path:
        progress(f"      {project.audio_path} moved; using {audio}")
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
    scene = Scene(project, data, grid, width=width, height=height)
    progress(f"      {len(scene.section_at)} sections at {scene.w}x{scene.h}")

    span = f"{start:.0f}s..{end:.0f}s" if preview else "whole track"
    progress(f"[4/4] rendering {frames} frames at {fps} fps ({span})")

    part = out.with_suffix(".part.mp4")
    log = Path(tempfile.mkstemp(prefix="song-ffmpeg-", suffix=".log")[1])
    command = [
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "gbrp",
        "-s", f"{scene.w}x{scene.h}", "-r", str(fps), "-i", "-",
    ]
    if preview:
        command += ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}"]
    command += [
        "-i", str(audio),
        "-filter_complex", f"[0:v]{_chain(ass, start if preview else 0.0)}[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", CRF,
        "-profile:v", "high", "-movflags", "+faststart",
        # 256k. The source is usually lossless and the video is the artefact
        # people keep, so this is not the place to save four megabytes.
        "-c:a", "aac", "-b:a", "256k",
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
