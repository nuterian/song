"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import exports
from .align import pipeline
from .project import Project, slugify
from .align.score import format_report


def _workdir_for(audio: Path, explicit: str | None) -> Path:
    return Path(explicit) if explicit else Path("workdir") / slugify(audio.stem)


def _build_config(args) -> pipeline.Config:
    return pipeline.Config(
        whisper_model=args.model,
        whisper_model_retry=args.retry_model,
        device=args.device,
        demucs_device=args.demucs_device,
        max_iterations=args.max_iterations,
        skip_separation=args.no_separate,
    )


def _align(args) -> tuple[Project, Path]:
    audio = Path(args.audio)
    lyrics = Path(args.lyrics)
    workdir = _workdir_for(audio, args.workdir)
    existing = workdir / "project.json"

    if existing.exists() and not args.force:
        print(f"reusing existing alignment at {existing}")
        print("   (pass --force to re-run and discard manual edits)")
        return Project.load(existing), workdir

    project, card = pipeline.run(
        audio, lyrics, workdir=workdir, config=_build_config(args)
    )
    print(format_report(project, card, per_line=not args.quiet))
    return project, workdir


def cmd_align(args) -> int:
    project, workdir = _align(args)
    written = exports.write_all(project, workdir)
    print("\nexports:")
    for kind, path in written.items():
        print(f"  {kind:>13}  {path}")
    return 0


def cmd_ui(args) -> int:
    from .server import serve

    if args.audio and args.lyrics:
        project, workdir = _align(args)
        exports.write_all(project, workdir)
        target = workdir
    elif args.audio or args.lyrics:
        print("give both an audio file and a lyrics file, or neither", file=sys.stderr)
        return 2
    else:
        # Nothing to align. Open on the directory tracks live in, so the first
        # one can be added from inside the app instead of from here.
        target = Path(args.workdir) if args.workdir else Path("workdir")
        target.mkdir(parents=True, exist_ok=True)
        if not any(d.joinpath("project.json").exists() for d in target.iterdir() if d.is_dir()):
            print("no aligned tracks yet - add one from the app")

    serve(
        target, host=args.host, port=args.port, open_browser=not args.no_browser,
        device=args.device,
    )
    return 0


def cmd_score(args) -> int:
    workdir = Path(args.workdir)
    project = Project.load(workdir / "project.json")
    card = pipeline.rescore(project)
    print(format_report(project, card, per_line=not args.quiet))
    project.save(workdir / "project.json")
    return 0


def cmd_audit(args) -> int:
    from . import analysis, vad
    from .align import refine
    from .audio import TARGET_SR, load_mono

    workdir = Path(args.workdir)
    project = Project.load(workdir / "project.json")
    stem = Path(project.stem_path or project.audio_path)
    if not stem.exists():
        print(f"  no vocal stem at {stem}")
        return 1

    analysis.build(project.audio_path, str(stem), workdir)
    samples, _ = load_mono(stem, TARGET_SR)
    result = refine.run(
        project, stem, activity=vad.analyse(samples, TARGET_SR), samples=samples,
        device=args.device, progress=None if args.quiet else lambda m: print(m),
    )

    # write_all() already saves project.json; an explicit save here duplicated it.
    exports.write_all(project, workdir)
    (workdir / "audit.json").write_text(json.dumps(result, indent=1), encoding="utf-8")

    print(f"\n  {result['n_verified']}/{result['n_words']} words agreed on by both "
          f"aligners - nothing to check there")
    if result["repairs"]:
        print(f"  {len(result['repairs'])} impossible timing(s) repaired automatically:")
        for r in result["repairs"]:
            print(f"     line {r['line']:>3}  {r['text']:<14} {r['was']:8.3f} -> {r['now']:8.3f}   {r['why']}")
    print(f"  {len(result['queue'])} word(s) need an ear\n")
    for q in result["queue"][: args.limit]:
        arrow = f"{q['current']:.2f} -> {q['proposed']:.2f} ({q['delta']:+.2f}s)"
        print(f"     line {q['line']:>3}  {q['text']:<14} {arrow:<28} [{q['scope']}]")
        for why in q["reasons"]:
            print(f"                  - {why}")
    if len(result["queue"]) > args.limit:
        print(f"     ... and {len(result['queue']) - args.limit} more")
    print(f"\n  open the review UI and click \"Check timings\" to work through them\n")
    return 0


def cmd_export(args) -> int:
    workdir = Path(args.workdir)
    project = Project.load(workdir / "project.json")
    for kind, path in exports.write_all(project, workdir).items():
        print(f"  {kind:>13}  {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="song",
        description="Time-synchronize a lyrics file against an audio track.",
    )
    sub = parser.add_subparsers(dest="command")

    def add_align_args(p, inputs_optional: bool = False):
        # `ui` can be asked for with no files at all - that opens the app on
        # its first-run screen, where a track is added by dropping it in.
        p.add_argument("audio", nargs="?" if inputs_optional else None,
                       help="wav/mp3/flac/m4a track")
        p.add_argument("lyrics", nargs="?" if inputs_optional else None,
                       help="plain-text lyrics")
        p.add_argument("--workdir", default=None)
        p.add_argument("--model", default="medium", help="whisper model for refinement")
        p.add_argument("--retry-model", default="large-v3-turbo")
        p.add_argument("--device", default="cpu")
        p.add_argument("--demucs-device", default="cpu")
        p.add_argument("--max-iterations", type=int, default=2)
        p.add_argument(
            "--no-separate",
            action="store_true",
            help="align against the full mix instead of an isolated vocal stem",
        )
        p.add_argument("--force", action="store_true", help="re-run, discarding edits")
        p.add_argument("--quiet", action="store_true", help="scorecard summary only")

    p_align = sub.add_parser("align", help="align and export, no UI")
    add_align_args(p_align)
    p_align.set_defaults(func=cmd_align)

    p_ui = sub.add_parser(
        "ui", help="open the review UI; align first if given an audio + lyrics pair"
    )
    add_align_args(p_ui, inputs_optional=True)
    p_ui.add_argument("--host", default="127.0.0.1")
    p_ui.add_argument("--port", type=int, default=8420)
    p_ui.add_argument("--no-browser", action="store_true")
    p_ui.set_defaults(func=cmd_ui)

    p_score = sub.add_parser("score", help="re-run the benchmark on saved timings")
    p_score.add_argument("workdir")
    p_score.add_argument("--quiet", action="store_true")
    p_score.set_defaults(func=cmd_score)

    p_audit = sub.add_parser(
        "audit", help="repair impossible word timings and list the ones needing an ear"
    )
    p_audit.add_argument("workdir")
    p_audit.add_argument("--device", default="cpu")
    p_audit.add_argument("--limit", type=int, default=20)
    p_audit.add_argument("--quiet", action="store_true")
    p_audit.set_defaults(func=cmd_audit)

    p_export = sub.add_parser("export", help="rewrite lrc/srt/vtt from project.json")
    p_export.add_argument("workdir")
    p_export.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # `song song.wav lyrics.txt` is the common case, and a bare `song` should
    # open the app rather than print usage - that is where a first track is
    # added from.
    if not argv:
        argv = ["ui"]
    if argv and not argv[0].startswith("-") and argv[0] not in {
        "align",
        "ui",
        "score",
        "export",
        "audit",
    }:
        argv.insert(0, "ui")

    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
