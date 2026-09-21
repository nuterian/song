"""Any song, up to the player: prepare, listen, the models, stage. Each step is cached
under the track's cache directory and is skipped when its result is already there.

    python -m visuals make <audio file | song workdir> --theme cosmos
"""

from __future__ import annotations

import time
from pathlib import Path

from . import MODELS
from .track import Track, prepare


def cache_of(track: Track, fix: dict | None) -> Path:
    """Where a listening, and the models run on it, are kept: the song's cache as heard, and
    a folder in it for each correction of the grid - so going back to one is not listening
    again, and a correction never overwrites what was heard."""
    from .grid import normal_fix

    fix = normal_fix(fix)
    if not fix:
        return track.cache
    return track.cache / f"grid-x{fix['tempo_times']:g}-m{fix['meter'] or 0}-b{fix['bar_one']:+d}"


def listened(track: Track, force: bool = False, verbose: bool = True, grid_fix="sheet") -> dict:
    """The song heard - with the grid as the song's kept sheet corrects it, if it does
    (`grid_fix`: "sheet", or a correction, or None). Beat This! is not run again for a
    correction: its beats are the audio's, whatever the grid made of them."""
    from . import listen, sheet as sheet_

    fix = sheet_.grid_fix(track) if grid_fix == "sheet" else grid_fix
    cache = cache_of(track, fix)
    got = None if force else listen.load_cached(cache, fix)
    if got is None:
        prepare(track, say=print if verbose else _quiet)
        bt = None if force else listen.cached_beat_this(track.cache) or listen.cached_beat_this(cache)
        got = listen.listen(track.audio, track.stems_dir, track.workdir, verbose=verbose, grid_fix=fix, bt=bt)
        listen.save(got, cache)
    return got


def modelled(track: Track, got: dict, force: bool = False, verbose: bool = True) -> tuple[dict, dict]:
    from . import models

    cache = cache_of(track, got["meta"].get("grid_fix"))
    mod = None if force else models.load_cached(cache)
    if mod is not None and mod[1].get("listened") != models.listened_key(got["meta"]):
        mod = None                      # run on another listening: its sections are stale
    if mod is None:
        arrays, meta = models.run(got, track.audio, track.stems_dir, track.project, MODELS, verbose=verbose)
        cache.mkdir(parents=True, exist_ok=True)
        models.save(arrays, meta, cache)
        mod = models.load_cached(cache)
    return mod


def directed(track: Track, got: dict, fresh: bool = False):
    """The song baked from its direction sheet (sheet.py): a curated one if there is one and
    `fresh` is not asked for; else the director's own, which is written beside the bundle.
    Returns the channels, the sheet, and where it came from."""
    from . import render, sheet as sheet_

    path = sheet_.path_for(track)
    if not fresh and path.parent == sheet_.CURATED:
        the = sheet_.read(path)
        if the.get("sheet") == 1:                    # written before `heard`: given one, and kept so
            the = sheet_.upgrade(the, track, got, render.bake(got, track, the | {"sheet": sheet_.VERSION}))
            sheet_.write(the, path)
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
