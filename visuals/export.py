"""Staging what the browser needs, next to what the renderer produced.

The player is static: one page, one script, and per-track data fetched at load.
The data is the same baked uniform grid the mp4 was rendered from and the same
shader sources, recompiled under the GLSL ES 3.0 header. Nothing is computed twice.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from . import grammar, schema
from .listen import Track
from .uniforms import UniformTrack

FRAMES = "frames.bin"
PLAN = "plan.json"


def export(score: schema.Score, track: Track, out_dir: str | Path) -> Path:
    """Write plan.json, frames.bin and the audio into `out_dir`. Returns the path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    uni = UniformTrack(score, track)

    # One program, for the whole song, exactly as the renderer builds it - so the
    # browser and the mp4 run the same source, and neither of them ever swaps it.
    plan = uni.plan()
    plan["program"] = {
        "key": grammar.program_key(score),
        "fragment": grammar.fragment_source(score, grammar.WEBGL_HEADER),
    }
    plan["vertex"] = grammar.vertex_source(grammar.WEBGL_HEADER)
    plan["frames_file"] = FRAMES
    plan["audio_file"] = "mix.m4a"

    (out / FRAMES).write_bytes(uni.frames_bytes())
    (out / PLAN).write_text(json.dumps(plan, indent=1) + "\n")
    _link_audio(track.workdir / "mix.m4a", out / "mix.m4a")
    return out


def _link_audio(src: Path, dst: Path) -> None:
    """Point at the workdir's mix rather than copying five megabytes of it.

    A symlink is enough for a local static server, and it keeps `out/` small. If
    the filesystem will not have one, the copy is the fallback.
    """
    if not src.exists():
        return
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    try:
        os.symlink(src, dst)
    except OSError:
        shutil.copy2(src, dst)
