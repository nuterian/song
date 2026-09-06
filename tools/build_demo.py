#!/usr/bin/env python3
"""Freeze an aligned track into the read-only demo that GitHub Pages serves.

The app is a local server. This writes the same UI out against files instead:
the project (audit included), the analysis payload the server would have sent,
and the two audio previews re-encoded down to something reasonable to ship.

Reproducible on purpose - the demo is generated from a real workdir by this
script, never hand-copied, so it cannot quietly drift from the app it claims
to be a copy of.

    python tools/build_demo.py workdir/gravity-in-motion
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "song" / "ui"
OUT = ROOT / "docs" / "demo"

# Enough to judge a word boundary by ear, a third the size of the originals.
BITRATE = "64k"


def encode(src: Path, dst: Path, force: bool = False) -> None:
    """Re-encode one preview, unless one is already sitting there.

    A UI change is the usual reason to rebuild, and the encoder does not produce
    the same bytes twice - so re-encoding unchanged audio every time would put a
    megabyte of meaningless diff in front of a one-line change to app.js. Pass
    --media to force it when the track itself has actually moved.
    """
    if dst.exists() and not force:
        print(f"  keeping {dst.name} (pass --media to re-encode)")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-ac", "1", "-b:a", BITRATE, str(dst)],
        check=True,
    )


def build(workdir: Path, media: bool = False) -> None:
    project = workdir / "project.json"
    if not project.exists():
        sys.exit(f"no project.json in {workdir}")

    OUT.mkdir(parents=True, exist_ok=True)
    # The project carries its own audit, so this is the one document.
    shutil.copy(project, OUT / "project.json")
    if "audit" not in (json.loads(project.read_text(encoding="utf-8")).get("meta") or {}):
        print("  note: no audit in this project - run `song audit` first if the "
              "demo should have a Check timings queue")

    # Exactly what /api/analysis sends: the mix peaks are cached on disk but
    # never drawn, and they are half the payload.
    analysis = json.loads((workdir / "analysis.json").read_text(encoding="utf-8"))
    (OUT / "analysis.json").write_text(
        json.dumps({k: v for k, v in analysis.items() if k != "mix_peaks"}),
        encoding="utf-8",
    )

    for name, src in (("mix", workdir / "mix.m4a"), ("vocals", workdir / "vocals.m4a")):
        if not src.exists():
            sys.exit(f"missing {src} - open the track in the app once to cache it")
        encode(src, OUT / "media" / f"{name}.m4a", force=media)

    shutil.copy(UI / "app.js", OUT / "app.js")
    shutil.copy(UI / "styles.css", OUT / "styles.css")

    # The page is the app's own index.html with absolute asset paths made
    # relative and static mode switched on. Generated, so the demo tracks the
    # app rather than being a fork of it.
    # Each asset link carries a hash of its content. Pages serves everything
    # with a ten-minute cache, and without this a returning visitor gets the
    # new page with the old script for up to ten minutes after a deploy -
    # which broke the demo the first time an element the script binds was
    # removed.
    def stamp(name: str) -> str:
        digest = hashlib.sha256((OUT / name).read_bytes()).hexdigest()[:10]
        return f"{name}?v={digest}"

    html = (UI / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="/styles.css"', f'href="{stamp("styles.css")}"')
    html = html.replace('src="/app.js"', f'src="{stamp("app.js")}"')
    html = html.replace(
        "<script src=", "<script>window.SONG_STATIC = './';</script>\n<script src=", 1
    )
    html = html.replace("<title>song</title>", "<title>song — live demo</title>")
    (OUT / "index.html").write_text(html, encoding="utf-8")

    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"  demo written to {OUT.relative_to(ROOT)}  ({total / 1048576:.2f} MB)")
    for f in sorted(OUT.rglob("*")):
        if f.is_file():
            print(f"    {f.relative_to(OUT)!s:22} {f.stat().st_size / 1024:8.0f} KB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workdir", help="an aligned track directory")
    ap.add_argument("--media", action="store_true",
                    help="re-encode the audio previews as well as the app")
    args = ap.parse_args()
    build(Path(args.workdir), media=args.media)
