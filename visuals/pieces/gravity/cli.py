"""listen / render / measure, for this one piece."""

from __future__ import annotations

import argparse

from . import AUDIO, CACHE, OUT, STEMS_DIR, WORKDIR


def _listen(force: bool = False) -> dict:
    from . import listen

    got = None if force else listen.load_cached(CACHE)
    if got is None:
        if not STEMS_DIR.exists():
            raise SystemExit(f"no stems at {STEMS_DIR}; see the docstring of listen.py")
        got = listen.listen(AUDIO, STEMS_DIR, WORKDIR)
        listen.save(got, CACHE)
    return got


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m visuals.pieces.gravity")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("listen", help="stems -> events and streams")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("render", help="the mp4 and the player's files")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--duration", type=float, default=None)
    p.add_argument("--size", default="1920x1080")
    p.add_argument("--fps", type=int, default=60)
    p.add_argument("--crf", type=int, default=17)
    p.add_argument("--out", default=None)
    p.add_argument("--solo", default=None,
                   help="draw only this stream's response (for the separation matrix)")

    p = sub.add_parser("measure", help="decode the mp4 and check it against the audio")
    p.add_argument("--video", default=None)

    p = sub.add_parser("matrix", help="solo each instrument; which detectors does it move?")
    p.add_argument("--start", type=float, default=120.0)
    p.add_argument("--duration", type=float, default=40.0)

    args = ap.parse_args(argv)

    if args.cmd == "listen":
        from . import report
        report.print_listen(_listen(args.force))
        return 0

    if args.cmd == "render":
        from . import render
        w, h = (int(v) for v in args.size.lower().split("x"))
        out = render.render(_listen(), OUT if args.out is None else args.out,
                            start=args.start, duration=args.duration,
                            size=(w, h), fps=args.fps, crf=args.crf, solo=args.solo)
        print(out)
        return 0

    if args.cmd == "measure":
        from . import measure
        return measure.main(_listen(), args.video)

    if args.cmd == "matrix":
        from . import measure
        measure.matrix(_listen(), args.start, args.duration)
        return 0

    return 1
