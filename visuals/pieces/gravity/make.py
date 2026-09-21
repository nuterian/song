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
    if mod is not None and mod[1].get("listened") != models.listened_key(got["meta"]):
        mod = None                      # run on another listening: its sections are stale
    if mod is None:
        arrays, meta = models.run(got, track.audio, track.stems_dir, track.project, MODELS, verbose=verbose)
        models.save(arrays, meta, track.cache)
        mod = models.load_cached(track.cache)
    return mod


def directed(track: Track, got: dict, fresh: bool = False):
    """The song baked from its direction sheet (sheet.py): a curated one if there is one and
    `fresh` is not asked for; else the director's own, which is written beside the bundle.
    Returns the channels, the sheet, and where it came from."""
    from . import render, sheet as sheet_

    path = sheet_.path_for(track)
    if not fresh and path.parent == sheet_.CURATED:
        the = sheet_.read(path)
        bad = sheet_.validate(the, got)
        if bad:
            raise SystemExit(f"{path} cannot be baked:\n  " + "\n  ".join(bad))
        return render.bake(got, track, the), the, path
    ch = render.bake(got, track)                      # the director's own decisions...
    the = sheet_.default(track, got, ch)              # ...written down; baking that sheet gives the same (a test holds it)
    ch.sheet = the
    return ch, the, sheet_.write(the, track.out("cosmos") / "sheet.json")


def make(track: Track, style: str = "cosmos", force: bool = False, with_render: bool = False,
         fresh_sheet: bool = False, keep_sheet: bool = False) -> Path:
    """The bundle the player reads, for this track in this style, and its scorecard. No mp4."""
    from . import render, scorecard, sheet as sheet_

    t0 = time.time()
    print(f"track: {track.slug}  ({track.source})" + (f"\n  lyrics from {track.project}" if track.project else ""))
    got = listened(track, force)
    modelled(track, got, force)
    render.STYLE = style
    if style == "cosmos":
        ch, the, where = directed(track, got, fresh_sheet)
        if keep_sheet:
            where = sheet_.write(the, sheet_.CURATED / f"{track.slug}.json")
        print(f"direction sheet: {where}")
    else:
        ch = render.bake(got, track)
    out = render.stage(got, track, track.out(style), ch=ch)
    print(f"staged {out}  ({time.time() - t0:.0f}s)")
    if style == "cosmos":
        card = scorecard.build(track, got, ch, with_render)
        scorecard.write(card, out)
        print(scorecard.show(card))
    print(f"  python -m visuals serve   ->   http://localhost:8765/player/?track={out.name}")
    return out


def _quiet(*_a) -> None:
    pass
