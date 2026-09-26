"""The command line.

    python -m visuals make   <audio file | song-workdir> [--theme cosmos]
    python -m visuals render <song-workdir> [--preview START] [--seed N]
    python -m visuals score  <song-workdir> [--seed N]
    python -m visuals serve  [--port 8765]
    python -m visuals demo                 the video demo, as a static page, into docs/video/

`make` is the product: any song in, the themed world staged for the player. It
separates stems, listens, runs the small models and bakes the channels, caching
each step under visuals/cache/<track>/. Lyrics come from the song tool's workdir
when there is one.

`render` is the one that matters. It reads the workdir, takes the score (the
hand-written one for the track if there is one, otherwise a legal draw from the
seed), writes an mp4 with the track's audio under it, and stages the same score
and the same baked uniforms for the browser.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import socketserver
import sys
from pathlib import Path

from . import authoring, export, schema
from .listen import Track
from .render import render_mp4

HERE = Path(__file__).resolve().parent
SCORES = HERE / "scores"
OUT = HERE / "out"

# A preview is twenty-five seconds by default: long enough to cross a section
# boundary on most songs, short enough to watch again after every edit.
PREVIEW_SECONDS = 25.0


def _track(path: str) -> Track:
    return Track(path)


def _score_for(track: Track, seed: int | None, quiet: bool = False) -> schema.Score:
    """The score to use, and where it came from, said out loud."""
    if seed is not None:
        if not quiet:
            print(f"score: sampled from seed {seed}")
        return authoring.sampled(track, seed)
    saved = SCORES / f"{track.name}.json"
    if saved.exists():
        score = schema.Score.read(saved)
        bad = score.violations()
        if bad:
            raise SystemExit(f"{saved} breaks the grammar: {'; '.join(bad)}")
        if not quiet:
            print(f"score: {saved.relative_to(HERE.parent)}")
        return score
    if not quiet:
        print("score: hand-written default (no saved score for this track)")
    return authoring.handwritten(track)


def cmd_render(args) -> int:
    track = _track(args.workdir)
    score = _score_for(track, args.seed)
    if not score.is_complete():
        score = score.filled(args.seed or 0)

    start = 0.0 if args.preview is None else max(0.0, float(args.preview))
    duration = args.duration
    if duration is None:
        duration = PREVIEW_SECONDS if args.preview is not None else None

    out_dir = OUT / track.name
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "preview" if args.preview is not None else "full"
    if args.seed is not None:
        stem += f"-seed{args.seed}"
    mp4 = Path(args.out) if args.out else out_dir / f"{stem}.mp4"

    width, height = (int(v) for v in args.size.split("x"))
    print(f"track:  {track.name}  {track.duration:.1f}s  {track.tempo:.1f} bpm  "
          f"{len(track.sections)} sections  {track.n_bars} bars")
    stats = render_mp4(score, track, mp4, start=start, duration=duration,
                       fps=args.fps, size=(width, height))
    print(f"render: {stats}")
    print(f"mp4:    {mp4}")

    staged = export.export(score, track, out_dir)
    (out_dir / "score.json").write_text(json.dumps(score.to_dict(), indent=1) + "\n")
    print(f"player: {staged}  ->  python -m visuals serve")
    return 0


def cmd_score(args) -> int:
    track = _track(args.workdir)
    score = _score_for(track, args.seed)
    out = Path(args.out) if args.out else SCORES / f"{track.name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    score.write(out)
    slots = score.to_slots()
    print(f"{out}: {int((slots != schema.MASK).sum())}/{len(slots)} slots filled, "
          f"{len(score.violations())} violation(s)")
    return 0


class _RangeHandler(http.server.SimpleHTTPRequestHandler):
    """A static handler that answers Range requests, because <audio> needs them.

    Without `Accept-Ranges` a browser will load the whole file, report it fully
    buffered, and still refuse to seek in it - `seekable` stays empty, and the
    player's scrubber does nothing. The stock handler does not implement Range, so
    this adds the one case that matters: a single `bytes=start-end`.
    """

    def send_head(self):  # noqa: N802 - the base class spells it this way
        path = self.translate_path(self.path)
        header = self.headers.get("Range", "")
        if not header.startswith("bytes=") or not os.path.isfile(path):
            if os.path.isfile(path):
                self.send_header_accept_ranges = True
            return super().send_head()
        try:
            first, _, last = header[len("bytes="):].partition("-")
            size = os.path.getsize(path)
            start = int(first) if first else max(0, size - int(last))
            end = int(last) if first and last else size - 1
            end = min(end, size - 1)
            if start > end:
                raise ValueError(header)
            fh = open(path, "rb")
        except (OSError, ValueError):
            self.send_error(416, "cannot satisfy range")
            return None
        fh.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        return _Slice(fh, end - start + 1)

    def end_headers(self):  # noqa: N802
        # Everything here is being worked on. "no-cache" still lets the browser keep a
        # copy, but makes it ask whether the copy is current - so a page and its script
        # are never from different days. (This was once a second end_headers, above the
        # one that is here now, and so never sent: the browser kept yesterday's player.js.)
        self.send_header("Cache-Control", "no-cache")
        if getattr(self, "send_header_accept_ranges", False):
            self.send_header("Accept-Ranges", "bytes")
            self.send_header_accept_ranges = False
        super().end_headers()


class _Slice:
    """A read-only window onto an open file, which is all copyfile() needs."""

    def __init__(self, fh, remaining: int) -> None:
        self.fh = fh
        self.remaining = remaining

    def read(self, n: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        n = self.remaining if n < 0 else min(n, self.remaining)
        chunk = self.fh.read(n)
        self.remaining -= len(chunk)
        return chunk

    def close(self) -> None:
        self.fh.close()


def cmd_make(args) -> int:
    from .pieces.gravity import make
    from .pieces.gravity.track import Track

    make.make(Track.resolve(args.song, args.audio), args.theme, force=args.force, with_render=args.render,
              fresh_sheet=args.fresh_sheet, keep_sheet=args.keep_sheet)
    return 0


def cmd_edit(args) -> int:
    from .pieces.gravity import editor, make, sheet as sheet_
    from .pieces.gravity.track import Track

    track = Track.resolve(args.song, args.audio)
    got = make.listened(track, verbose=False)
    _, sheet, path = make.directed(track, got)
    model = args.model or editor.MODEL
    print(f"sheet: {path}\nasking {model}: {args.request}")
    got_back = editor.edit(track, got, sheet, args.request, model=model)
    print(f"  said: {got_back['said']}  ({got_back['seconds']:.1f}s, {got_back['attempts']} attempt(s))")
    for d in got_back["did"]:
        print(f"  - {d}")
    if got_back["refused"]:
        print("  refused: " + "; ".join(got_back["refused"]))
        return 1
    if got_back["sheet"] is None:
        print("  it is already so: nothing to change" if got_back.get("already") else "  nothing to change")
        return 0
    if args.dry:
        print(sheet_.dumps(got_back["sheet"]))
        return 0
    print(f"kept: {sheet_.write(got_back['sheet'], sheet_.CURATED / f'{track.slug}.json')}")
    make.make(track, "cosmos")
    return 0


def cmd_studio(args) -> int:
    from .pieces.gravity import studio
    from .pieces.gravity.track import Track

    studio.serve([Track.resolve(song) for song in args.songs], port=args.port)
    return 0


def cmd_demo(args) -> int:
    from .pieces.gravity import demo

    dest = demo.build()
    print(f"{dest}\n{demo.sizes(dest)}")
    print("  python3 -m http.server -d docs 8793   ->   http://127.0.0.1:8793/video/")
    return 0


def cmd_serve(args) -> int:
    """A static server rooted at visuals/, so /player/ can fetch /out/<track>/."""
    handler = functools.partial(_RangeHandler, directory=str(HERE))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        tracks = sorted(p.name for p in OUT.iterdir() if (p / "plan.json").exists()) \
            if OUT.exists() else []
        first = f"?track={tracks[0]}" if tracks else ""
        print(f"http://127.0.0.1:{args.port}/player/{first}")
        if tracks:
            print("staged tracks: " + ", ".join(tracks))
        else:
            print("nothing staged yet; run:  python -m visuals render <song-workdir>")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m visuals", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("make", help="any song, themed and staged for the player")
    m.add_argument("song", help="an audio file (wav, flac, mp3, m4a...) or a song workdir")
    m.add_argument("--theme", choices=("cosmos",), default="cosmos")
    m.add_argument("--audio", default=None, help="the audio, for a song workdir whose project has lost it")
    m.add_argument("--force", action="store_true", help="listen and run the models again")
    m.add_argument("--render", action="store_true",
                   help="add the scorecard's rendered checks: recall and frame time (minutes)")
    m.add_argument("--fresh-sheet", action="store_true",
                   help="ignore a curated direction sheet: bake the director's own decisions")
    m.add_argument("--keep-sheet", action="store_true",
                   help="keep the direction sheet used, in visuals/sheets/, to be edited")
    m.set_defaults(fn=cmd_make)

    e = sub.add_parser("edit", help="change a song's direction sheet by asking, with a local model")
    e.add_argument("song", help="an audio file or a song workdir")
    e.add_argument("request", help='what to change, in words: "close on Saturn in the second chorus"')
    e.add_argument("--model", default=None, help="an Ollama model on this machine (default: the one that edits best, measured)")
    e.add_argument("--audio", default=None)
    e.add_argument("--dry", action="store_true", help="show the edited sheet; keep nothing")
    e.set_defaults(fn=cmd_edit)

    st = sub.add_parser("studio", help="edit songs' videos on a timeline, by hand or by asking")
    st.add_argument("songs", nargs="+", help="audio files or song workdirs")
    st.add_argument("--port", type=int, default=8777)
    st.set_defaults(fn=cmd_studio)

    r = sub.add_parser("render", help="render an mp4 and stage the player")
    r.add_argument("workdir", help="a song workdir, read-only")
    r.add_argument("--preview", type=float, metavar="START", default=None,
                   help=f"render {PREVIEW_SECONDS:.0f}s from START seconds instead of the whole song")
    r.add_argument("--duration", type=float, default=None, help="override the length in seconds")
    r.add_argument("--seed", type=int, default=None,
                   help="sample a legal score from this seed instead of using the written one")
    r.add_argument("--fps", type=int, default=60)
    r.add_argument("--size", default="1280x720")
    r.add_argument("--out", default=None, help="mp4 path")
    r.set_defaults(fn=cmd_render)

    s = sub.add_parser("score", help="write a score to visuals/scores/")
    s.add_argument("workdir")
    s.add_argument("--seed", type=int, default=None)
    s.add_argument("--out", default=None)
    s.set_defaults(fn=cmd_score)

    d = sub.add_parser("demo", help="the video demo, as a static page, into docs/video/")
    d.set_defaults(fn=cmd_demo)

    v = sub.add_parser("serve", help="serve visuals/ so the player page can run")
    v.add_argument("--port", type=int, default=8765)
    v.set_defaults(fn=cmd_serve)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
