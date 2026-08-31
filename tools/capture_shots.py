#!/usr/bin/env python3
"""Capture the product-page pictures from the product itself.

The landing page is mostly pictures, so the pictures had better be the real
thing. Each shot below is the actual UI, driven into a particular state and
photographed by headless Chrome - not a mockup, and not hand-cropped. Re-run it
after a UI change and the page catches up.

The UI shots work against docs/demo, which build_demo.py already froze, so no
server and no audio decoding is involved. The demo's read-only chrome is taken
off first: these are pictures of the product, and the product can save.

The video section's claim is motion, so it cannot be carried by a screenshot.
The last step runs the real `song video` against a real workdir and cuts the
clip and its poster frame out of the result.

    python tools/build_demo.py workdir/my-track   # first
    python tools/capture_shots.py
"""

from __future__ import annotations

import argparse
import http.server
import re
import shutil
import subprocess
import sys
import threading
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "docs" / "demo"
IMG = ROOT / "docs" / "img"
PORT = 8155

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# name, (width, height), device scale, setup run once the app has booted
SHOTS = [
    ("app-full", (1560, 1000), 2, """
        select(6); document.querySelector('.lyrics').scrollTop = 300;
    """),
    ("app-stage", (1520, 300), 2, """
        document.querySelector('.lyrics').style.display = 'none';
        document.querySelector('.bar').style.display = 'none';
        select(6); focusLine(S.project.lines[6]); S.selWord = 2;
        S.audio.currentTime = S.project.lines[6].start + 1.15;
        draw();
    """),
    ("app-review", (1260, 880), 2, """
        S.additions = [];   // the sheet leads with missing lines; this shot is the queue
        document.getElementById('btn-review').click();
        S.review.at = S.review.queue.findIndex(q => q.scope === 'word');
        rvRender();
        const it = rvCurrent();
        S.review.adj = { t: rvClampT(it, it.proposed + 1.15) };
        rvSyncAdj(); rvDrawStrip();
    """),
]

# The first chorus: four lines back to back, no instrumental to sit through,
# and the section colour has already arrived. Twelve seconds loops without a
# seam because nothing on screen is trying to get anywhere.
# The page's demo. Starts on the first lyric and ends as the first chorus does,
# so it passes through three sections and one instrumental - which is the only
# way to show that the colour is the song's structure and not a slideshow.
DEMO_CLIP = "0:34-1:22"
DEMO_WIDTH = 1920
DEMO_CRF = "31"
DEMO_AUDIO = "112k"   # it is a music video; muting it would be a strange demo
STILL_AT = 36.0       # seconds into the clip: mid-word, mid-chorus

BOOT = """
<script>
(async () => {
  const ready = () => window.S && S.project && !S.project.empty && S.an && S.an.rate;
  for (let i = 0; i < 400 && !ready(); i++) await new Promise(r => setTimeout(r, 25));
  // These are pictures of the app, not of the read-only copy of it.
  document.body.classList.remove('is-demo');
  const badge = document.querySelector('.demo-badge');
  if (badge) badge.remove();
  layout(); draw();
  await new Promise(r => setTimeout(r, 120));
  try { __SETUP__ } catch (e) { document.title = 'setup failed: ' + e.message; }
  await new Promise(r => setTimeout(r, 260));
})();
</script>
"""


def serve() -> http.server.ThreadingHTTPServer:
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "docs"))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def capture(name: str, size: tuple[int, int], scale: int, setup: str) -> Path:
    page = DEMO / "_shot.html"
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    page.write_text(html.replace("</body>", BOOT.replace("__SETUP__", setup) + "</body>"),
                    encoding="utf-8")
    out = IMG / f"{name}.png"
    try:
        subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
             f"--force-device-scale-factor={scale}",
             f"--window-size={size[0]},{size[1]}",
             "--virtual-time-budget=12000",
             f"--screenshot={out}", f"http://127.0.0.1:{PORT}/demo/_shot.html"],
            check=True, capture_output=True,
        )
    finally:
        page.unlink(missing_ok=True)
    return out


def capture_demo(workdir: Path) -> list[Path]:
    """The excerpt the page plays, and the frame it rests on before you press it.

    Rendered at the full default height and scaled down here rather than
    rendered small, so what ships is a downsample of the real thing. One render
    feeds both: a poster cut from a different clip than the video it posters is
    a poster of something else.
    """
    subprocess.run(
        [sys.executable, "-m", "song", "video", str(workdir), "--preview", DEMO_CLIP],
        cwd=ROOT, check=True,
    )
    source = workdir / "karaoke-preview.mp4"
    video, still = IMG / "video-demo.mp4", IMG / "video-still.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
         "-vf", f"scale={DEMO_WIDTH}:-2", "-c:v", "libx264", "-preset", "slow",
         "-crf", DEMO_CRF, "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-c:a", "aac", "-b:a", DEMO_AUDIO, str(video)],
        check=True,
    )
    # JPEG, because the frame is a photograph of a gradient with film grain in
    # it, which is the one thing PNG is bad at.
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(STILL_AT), "-i", str(source),
         "-frames:v", "1", "-update", "1", "-q:v", "3", str(still)],
        check=True,
    )
    return [video, still]


def check_page() -> list[str]:
    """Every width/height on the page against the file it points at.

    Not for equality - the shots are deliberately twice their box, so they stay
    sharp on a retina screen. Two things are worth checking, and both have gone
    wrong here:

    - the *aspect* has to match, because the attributes map to a presentational
      height, and if the CSS ever forgets `height:auto` that height is what gets
      drawn. Every screenshot on the page was stretched that way once.
    - the file has to be at least as many pixels as the box it is drawn in, or
      the browser is upscaling and calling it a screenshot.
    """
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    wrong = []
    for src, w, h in re.findall(
        r'src="(img/[^"]+)"[^>]*?width="(\d+)" height="(\d+)"', page, re.S
    ):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v",
             "-show_entries", "stream=width,height", "-of", "csv=p=0",
             str(ROOT / "docs" / src)],
            capture_output=True, text=True, check=True).stdout
        fw, fh = (int(n) for n in out.strip().rstrip(",").split(",")[:2])
        box, real = int(w) / int(h), fw / fh
        if abs(box - real) > 0.005:
            wrong.append(f"{src}: page shape {box:.3f}, file shape {real:.3f}"
                         f" - it will be drawn stretched")
        if fw < int(w):
            wrong.append(f"{src}: {fw}px wide, drawn in a {w}px box - upscaled")
    return wrong


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workdir", nargs="?", default="workdir/gravity-in-motion",
                    help="the aligned track the video clip is cut from")
    args = ap.parse_args()

    if not Path(CHROME).exists():
        raise SystemExit(f"need Chrome at {CHROME}")
    if not (DEMO / "index.html").exists():
        raise SystemExit("run tools/build_demo.py first")
    IMG.mkdir(parents=True, exist_ok=True)
    httpd = serve()
    try:
        for name, size, scale, setup in SHOTS:
            out = capture(name, size, scale, setup)
            print(f"  {out.relative_to(ROOT)!s:34} {out.stat().st_size / 1024:6.0f} KB  "
                  f"{size[0]}x{size[1]} @{scale}x")
    finally:
        httpd.shutdown()
        shutil.rmtree(DEMO / "_shot.html", ignore_errors=True)

    workdir = Path(args.workdir)
    if not (workdir / "project.json").exists():
        raise SystemExit(f"no aligned track at {workdir}; the video clip is unchanged")
    for out in capture_demo(workdir):
        print(f"  {out.relative_to(ROOT)!s:34} {out.stat().st_size / 1024:6.0f} KB")

    for problem in check_page():
        print(f"  !! {problem}")
