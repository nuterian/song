"""Any song, up to the player: prepare, listen, the models, stage. Each step is cached
under the track's cache directory and is skipped when its result is already there.

    python -m visuals make <audio file | song workdir> --theme cosmos
"""

from __future__ import annotations

import time
from pathlib import Path

from . import MODELS
from .track import Track, prepare


def listened(track: Track, force: bool = False, verbose: bool = True) -> dict:
    from . import listen

    got = None if force else listen.load_cached(track.cache)
    if got is None:
        prepare(track, say=print if verbose else _quiet)
        got = listen.listen(track.audio, track.stems_dir, track.workdir, verbose=verbose)
        listen.save(got, track.cache)
    return got


def modelled(track: Track, got: dict, force: bool = False, verbose: bool = True) -> tuple[dict, dict]:
    from . import models

    mod = None if force else models.load_cached(track.cache)
    if mod is None:
        arrays, meta = models.run(got, track.audio, track.stems_dir, track.project, MODELS, verbose=verbose)
        models.save(arrays, meta, track.cache)
        mod = models.load_cached(track.cache)
    return mod


def make(track: Track, style: str = "cosmos", force: bool = False) -> Path:
    """The bundle the player reads, for this track in this style. No mp4."""
    from . import render

    t0 = time.time()
    print(f"track: {track.slug}  ({track.source})" + (f"\n  lyrics from {track.project}" if track.project else ""))
    got = listened(track, force)
    modelled(track, got, force)
    render.STYLE = style
    out = render.stage(got, track, track.out(style))
    print(f"staged {out}  ({time.time() - t0:.0f}s)\n"
          f"  python -m visuals serve   ->   http://localhost:8765/player/?track={out.name}")
    return out


def _quiet(*_a) -> None:
    pass
