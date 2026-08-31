"""Writers for the standard synced-lyric formats."""

from __future__ import annotations

from pathlib import Path

from .project import Project

# A caption still on screen through a 4-bar instrumental looks broken, so a
# blank cue is emitted when the gap to the next line exceeds this.
CLEAR_GAP = 2.5


def _lrc_time(t: float) -> str:
    t = max(0.0, t)
    minutes, seconds = divmod(t, 60)
    return f"[{int(minutes):02d}:{seconds:05.2f}]"


def _srt_time(t: float) -> str:
    t = max(0.0, t)
    hours, rem = divmod(t, 3600)
    minutes, seconds = divmod(rem, 60)
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms == 1000:
        whole, ms = whole + 1, 0
    return f"{int(hours):02d}:{int(minutes):02d}:{whole:02d},{ms:03d}"


def _vtt_time(t: float) -> str:
    return _srt_time(t).replace(",", ".")


def _timed(project: Project):
    return [ln for ln in project.lines if ln.end > ln.start]


def write_lrc(project: Project, path: Path | str, title: str = "", artist: str = "") -> Path:
    out = []
    if title:
        out.append(f"[ti:{title}]")
    if artist:
        out.append(f"[ar:{artist}]")
    out.append("[re:song]")

    lines = _timed(project)
    for i, line in enumerate(lines):
        out.append(f"{_lrc_time(line.start)}{line.text}")
        next_start = lines[i + 1].start if i + 1 < len(lines) else project.duration
        if next_start - line.end > CLEAR_GAP:
            out.append(f"{_lrc_time(line.end)}")

    return _write(path, "\n".join(out) + "\n")


def write_enhanced_lrc(
    project: Project, path: Path | str, title: str = "", artist: str = ""
) -> Path:
    """Word-level LRC: [line]<word><word>... - what karaoke players highlight.

    Only word starts are written; a word's end is the next word's start and the
    last word's end is the line end. That is exactly the model the review UI
    edits under, so the two cannot disagree.
    """
    out = []
    if title:
        out.append(f"[ti:{title}]")
    if artist:
        out.append(f"[ar:{artist}]")
    out.append("[re:song]")

    lines = _timed(project)
    for i, line in enumerate(lines):
        if line.words:
            body = " ".join(
                f"<{_lrc_time(w.start)[1:-1]}>{w.text}" for w in line.words
            )
        else:
            body = line.text
        out.append(f"{_lrc_time(line.start)}{body}")
        next_start = lines[i + 1].start if i + 1 < len(lines) else project.duration
        if next_start - line.end > CLEAR_GAP:
            out.append(f"{_lrc_time(line.end)}")

    return _write(path, "\n".join(out) + "\n")


def write_srt(project: Project, path: Path | str) -> Path:
    out = []
    for n, line in enumerate(_timed(project), start=1):
        out.append(str(n))
        out.append(f"{_srt_time(line.start)} --> {_srt_time(line.end)}")
        out.append(line.text)
        out.append("")
    return _write(path, "\n".join(out))


def write_vtt(project: Project, path: Path | str) -> Path:
    out = ["WEBVTT", ""]
    for line in _timed(project):
        out.append(f"{_vtt_time(line.start)} --> {_vtt_time(line.end)}")
        out.append(line.text)
        out.append("")
    return _write(path, "\n".join(out))


def _write(path: Path | str, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_all(project: Project, outdir: Path | str, stem: str = "lyrics") -> dict[str, Path]:
    outdir = Path(outdir)
    project.normalize_words()
    return {
        "lrc": write_lrc(project, outdir / f"{stem}.lrc"),
        "enhanced_lrc": write_enhanced_lrc(project, outdir / f"{stem}.word.lrc"),
        "srt": write_srt(project, outdir / f"{stem}.srt"),
        "vtt": write_vtt(project, outdir / f"{stem}.vtt"),
        "json": project.save(outdir / "project.json"),
    }
