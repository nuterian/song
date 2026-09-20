"""listen / render / measure, for this one piece."""

from __future__ import annotations

import argparse

from . import AUDIO, CACHE, MODELS, OUT, STEMS_DIR, WORKDIR


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
    ap.add_argument("--style", choices=("glow", "ink", "cosmos"), default="glow",
                    help="glow: soft light on black. ink: flat cel-shaded system, fixed view. "
                         "cosmos: the real solar system in 3D through a moving camera")
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

    p = sub.add_parser("models", help="notes, melody, chords, mood, lyrics - from small local models")
    p.add_argument("--force", action="store_true")

    sub.add_parser("stage", help="export to the browser player only: no mp4, a few seconds")

    sub.add_parser("smooth", help="only section decisions live: is there a step anywhere?")

    p = sub.add_parser("matrix", help="solo each instrument; which detectors does it move?")
    p.add_argument("--start", type=float, default=120.0)
    p.add_argument("--duration", type=float, default=40.0)

    args = ap.parse_args(argv)
    from . import out_dir
    out = out_dir(args.style)
    if args.cmd in ("render", "stage", "measure", "matrix", "smooth"):
        from . import measure as _m, render as _r
        _r.STYLE = args.style
        _m.OUT = out
        if args.style == "ink":
            # printed, the voice's light is an ink and saturates at the centre; it is
            # looked for in the disc it swells in instead
            _m.ROLE_REGION["syllable"] = "heart"

    if args.cmd == "listen":
        from . import report
        report.print_listen(_listen(args.force))
        return 0

    if args.cmd == "render":
        from . import render
        w, h = (int(v) for v in args.size.lower().split("x"))
        made = render.render(_listen(), out if args.out is None else args.out,
                            start=args.start, duration=args.duration,
                            size=(w, h), fps=args.fps, crf=args.crf, solo=args.solo)
        print(made)
        return 0

    if args.cmd == "measure":
        from . import measure
        return measure.main(_listen(), args.video)

    if args.cmd == "models":
        from . import models
        if args.force or models.load_cached(CACHE) is None:
            arrays, meta = models.run(_listen(), AUDIO, STEMS_DIR, WORKDIR, MODELS)
            models.save(arrays, meta, CACHE)
        from . import report
        report.print_models(_listen(), *models.load_cached(CACHE))
        return 0

    if args.cmd == "stage":
        from . import render
        staged = render.stage(_listen(), out)
        print(f"staged {staged}\n  python -m visuals serve   ->   http://localhost:8765/player/?track={staged.name}")
        return 0

    if args.cmd == "smooth":
        from . import measure
        measure.smoothness(_listen())
        return 0

    if args.cmd == "matrix":
        from . import measure
        measure.matrix(_listen(), args.start, args.duration)
        return 0

    return 1
