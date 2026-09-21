"""Which song, and where everything made from it lives.

A track is an audio file, the `song` tool's workdir for it if there is one (lyrics, word
timings, a mix.m4a), and two directories this package writes: `visuals/cache/<slug>/`
(stems, listening, models) and `visuals/out/<slug>-<style>/` (what the player and the
mp4 read).

    Track.resolve("examples/Gravity in Motion.wav")     an audio file
    Track.resolve("workdir/gravity-in-motion")          a song workdir: its project names the audio

The slug is the `song` tool's, so an audio file and the workdir `song` made from it
resolve to the same track and share one cache.

`prepare` makes what listening needs and does nothing that is already there: a lossless
copy of a lossy file, the four Demucs stems, the player's mix.m4a.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import ROOT

# soundfile reads these sample for sample. Anything else is decoded once, by ffmpeg, into
# the cache, and every step - Demucs, listening, the mux - reads that one decode, so an
# mp3's encoder delay cannot put the stems and the mix on different clocks.
LOSSLESS = {".wav", ".flac", ".aif", ".aiff"}
AUDIO_SUFFIXES = LOSSLESS | {".mp3", ".m4a", ".aac", ".ogg", ".opus"}
STEMS = ("drums", "bass", "other", "vocals")
DEMUCS_MODEL = "htdemucs"
# torch and demucs live in the repository's root venv, not in visuals/.venv
DEMUCS_PYTHON = ROOT / ".venv" / "bin" / "python"
# where the Gravity piece's own song lives: the default when no track is named
GRAVITY_AUDIO = ROOT / "examples" / "Gravity in Motion.wav"


def slugify(name: str) -> str:
    """The `song` tool's slug (song/project.py), repeated: no import crosses between the two."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[-\s]+", "-", name) or "track"


@dataclass(frozen=True)
class Track:
    slug: str
    source: Path                  # the file that was given
    workdir: Path | None = None   # the song tool's workdir for it, if it has one

    @property
    def cache(self) -> Path:
        return ROOT / "visuals" / "cache" / self.slug

    @property
    def audio(self) -> Path:
        """What every step reads: the source itself if lossless, else its decode."""
        if self.source.suffix.lower() in LOSSLESS:
            return self.source
        return self.cache / "audio.wav"

    @property
    def stems_dir(self) -> Path:
        return self.cache / "demucs_raw" / DEMUCS_MODEL / self.audio.stem

    @property
    def project(self) -> Path | None:
        """The song tool's project.json - lines, words, sections - if it has aligned this track."""
        p = self.workdir / "project.json" if self.workdir else None
        return p if p is not None and p.exists() else None

    @property
    def mix_m4a(self) -> Path:
        """The player's audio: the song tool's copy if it made one, otherwise ours."""
        if self.workdir and (self.workdir / "mix.m4a").exists():
            return self.workdir / "mix.m4a"
        return self.cache / "mix.m4a"

    def out(self, style: str) -> Path:
        # "glow" was the first style, and its directory kept the first name
        return ROOT / "visuals" / "out" / f"{self.slug}-{'piece' if style == 'glow' else style}"

    @classmethod
    def resolve(cls, path: str | Path | None = None, audio: str | Path | None = None) -> Track:
        """An audio file or a song workdir; nothing means the Gravity piece's own song.

        `audio` names the audio outright, for a workdir whose project no longer points at it.
        """
        p = Path(path or GRAVITY_AUDIO).expanduser().absolute()
        if p.is_dir():
            if not (p / "project.json").exists():
                raise SystemExit(f"{p} is not a song workdir (no project.json) and not an audio file")
            src = Path(audio).expanduser().absolute() if audio else _find_audio(p)
            _check_audio(src)
            return cls(p.name, src, p)
        if not p.exists():
            raise SystemExit(f"no such file or directory: {p}")
        _check_audio(p)
        slug = slugify(p.stem)
        wd = ROOT / "workdir" / slug
        return cls(slug, p, wd if (wd / "project.json").exists() else None)


def _check_audio(p: Path) -> None:
    if not p.is_file():
        raise SystemExit(f"no audio at {p}")
    if p.suffix.lower() not in AUDIO_SUFFIXES:
        raise SystemExit(f"{p.name}: not an audio file this reads ({', '.join(sorted(AUDIO_SUFFIXES))})")


def _find_audio(workdir: Path) -> Path:
    """Where the project last saw its audio, then the obvious places near it."""
    recorded = Path(json.loads((workdir / "project.json").read_text()).get("audio_path") or "")
    tries = [recorded] if recorded.is_absolute() else [ROOT / recorded, workdir / recorded]
    if recorded.name:
        tries.append(ROOT / "examples" / recorded.name)
    for t in tries:
        if t.is_file():
            return t
    raise SystemExit(f"{workdir.name}: the project's audio is not at {recorded} or near it; name it "
                     f"with --audio (its own mix.m4a works, but stems from a 128k copy are worse)")


# ------------------------------------------------------------------ preparing


def prepare(track: Track, say=print) -> None:
    """Everything listening needs, made once: decode, stems, the player's audio."""
    track.cache.mkdir(parents=True, exist_ok=True)
    if not track.audio.exists():
        say(f"decoding {track.source.name} -> {track.audio.relative_to(ROOT)}")
        _ffmpeg("-i", str(track.source), "-c:a", "pcm_s16le", str(track.audio))
    if not all((track.stems_dir / f"{s}.wav").exists() for s in STEMS):
        separate(track, say)
    if not track.mix_m4a.exists():
        # the song tool's recipe (song/server.py), so both players hear the same thing
        _ffmpeg("-i", str(track.audio), "-ac", "2", "-c:a", "aac", "-b:a", "128k", str(track.mix_m4a))


def separate(track: Track, say=print) -> None:
    """Four stems, htdemucs, on the CPU: on MPS it fails ("Output channels > 65536")."""
    if not DEMUCS_PYTHON.exists():
        raise SystemExit(f"Demucs runs from the root venv, and there is none at {DEMUCS_PYTHON}; "
                         f"run ./setup.sh at the repository root")
    say(f"separating {track.audio.name} into {', '.join(STEMS)} (htdemucs, CPU; a few minutes)")
    t0 = time.time()
    got = subprocess.run([str(DEMUCS_PYTHON), "-m", "demucs", "-n", DEMUCS_MODEL, "-d", "cpu",
                          "-o", str(track.cache / "demucs_raw"), str(track.audio)],
                         capture_output=True, text=True)
    missing = [s for s in STEMS if not (track.stems_dir / f"{s}.wav").exists()]
    if got.returncode != 0 or missing:
        raise SystemExit(f"demucs failed (exit {got.returncode}, missing {missing}):\n{got.stderr[-1500:]}")
    say(f"  stems in {track.stems_dir.relative_to(ROOT)}  ({time.time() - t0:.0f}s)")


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)
