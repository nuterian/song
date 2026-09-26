"""The video demo: the player and two songs as a static page, for GitHub Pages.

    python -m visuals make "examples/Gravity in Motion.wav"      stage each song first
    python -m visuals demo                                       -> docs/video/

Each song's staged bundle (visuals/out/<slug>-cosmos/) is packed compact (render.pack)
into docs/video/<slug>/, beside a copy of the player and the page (player/demo.html) with
the songs filled in. Nothing on the page is fetched from anywhere else, and nothing needs
a server: docs/ served as files is the demo.
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from . import ROOT, render

PLAYER = ROOT / "visuals" / "player"
DEST = ROOT / "docs" / "video"
# the songs, in the order the page offers them; the first is the one it opens on
SONGS = (("gravity-in-motion", "Gravity in Motion"), ("shattered-voices", "Shattered Voices"))
FONT = "fonts/Inter-Light.woff2"


def build(dest: Path = DEST, songs=SONGS) -> Path:
    for slug, _ in songs:
        if not (ROOT / "visuals" / "out" / f"{slug}-cosmos" / "plan.json").exists():
            raise SystemExit(f"{slug} is not staged; run:  python -m visuals make <its audio file>")
    dest.mkdir(parents=True, exist_ok=True)
    for slug, _ in songs:
        render.pack(ROOT / "visuals" / "out" / f"{slug}-cosmos", dest / slug)
    for name in ("player.js", "bundle.js", "lyrics.js"):
        shutil.copyfile(PLAYER / name, dest / name)
    # the words' face, if the player has it; without it they are set in Helvetica Neue
    fonts = ""
    if (PLAYER / FONT).exists():
        shutil.copytree(PLAYER / "fonts", dest / "fonts", dirs_exist_ok=True)
        fonts = (f'  @font-face {{ font-family: "Inter"; font-weight: 300; font-display: swap;\n'
                 f'    src: url("{FONT}") format("woff2"); }}')
    page = (PLAYER / "demo.html").read_text()
    for key, value in {"fonts": fonts, "track": songs[0][0], "title": html.escape(songs[0][1]),
                       "songs": html.escape(json.dumps([{"slug": s, "title": t} for s, t in songs]))}.items():
        page = page.replace("{{" + key + "}}", value)
    (dest / "index.html").write_text(page)
    return dest


def sizes(dest: Path = DEST) -> str:
    """What the page weighs: each song's files, and the whole."""
    lines, total = [], 0
    for path in sorted(p for p in dest.rglob("*") if p.is_file()):
        total += path.stat().st_size
        lines.append(f"  {path.stat().st_size / 1e6:6.2f} MB  {path.relative_to(dest)}")
    return "\n".join(lines + [f"  {total / 1e6:6.2f} MB  in all"])
