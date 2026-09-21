"""listen / render / measure, for any song; the Gravity piece's own by default."""

from __future__ import annotations

import argparse

from . import make
from .track import Track


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

    ap.add_argument("--camera", choices=("static", "hybrid", "cinematic"), default="static",
                    help="cosmos only: which camera an mp4 is rendered with (the player can switch between all three)")
    ap.add_argument("--track", default=None,
                    help="an audio file or a song workdir (default: examples/Gravity in Motion.wav)")
    ap.add_argument("--audio", default=None, help="the audio, for a song workdir whose project has lost it")
    args = ap.parse_args(argv)
    track = Track.resolve(args.track, args.audio)
    _listen = lambda force=False: make.listened(track, force)
    from . import cosmos as _cosmos
    _cosmos.CAMERA = args.camera
    out = track.out(args.style)
    if args.cmd in ("render", "stage", "measure", "matrix", "smooth"):
        from . import measure as _m, render as _r
        _r.STYLE = args.style
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
        made = render.render(_listen(), track, out if args.out is None else args.out,
                            start=args.start, duration=args.duration,
                            size=(w, h), fps=args.fps, crf=args.crf, solo=args.solo)
        print(made)
        return 0

    if args.cmd == "measure":
        if args.style == "cosmos":
            # the camera moves, so the detectors follow the bodies; and first, from the
            # channels alone, how hard each camera moves the picture
            import json

            from . import follow, render
            got = _listen()
            ch = render.bake(got, track)
            report = {"jolt": [follow.jolt(ch, m) for m in _cosmos.MODES]}
            for j in report["jolt"]:
                print(f"  {j['camera']:9s} slide peak {100 * j['slide_peak']:5.1f} %/s   zoom peak {100 * j['zoom_peak']:5.1f} %/s   "
                      f"turn peak {j['turn_peak_deg']:4.1f} deg/s   fastest planet {100 * j['planet_speed_peak']:5.1f} %/s")
            report["sync"] = [follow.sync(got, ch, args.camera)]
            out.mkdir(parents=True, exist_ok=True)
            (out / f"sync-{args.camera}.json").write_text(json.dumps(report, indent=1))
            return 0
        from . import measure
        return measure.main(_listen(), track, args.video)

    if args.cmd == "models":
        got = _listen()
        mod = make.modelled(track, got, args.force)
        from . import report
        report.print_models(got, *mod)
        return 0

    if args.cmd == "stage":
        from . import render
        staged = render.stage(_listen(), track, out)
        print(f"staged {staged}\n  python -m visuals serve   ->   http://localhost:8765/player/?track={staged.name}")
        return 0

    if args.cmd == "smooth":
        from . import measure
        measure.smoothness(_listen(), track)
        return 0

    if args.cmd == "matrix":
        if args.style == "cosmos":
            from . import follow, render
            got = _listen()
            follow.matrix(got, render.bake(got, track), args.camera, args.start, args.duration)
            return 0
        from . import measure
        measure.matrix(_listen(), track, args.start, args.duration)
        return 0

    return 1
