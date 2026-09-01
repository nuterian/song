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
CWEBP = "cwebp"

# Everything ships as WebP. These are 2x screenshots of a dark UI - large flat
# fields with hairline text over them - and PNG spends most of its bytes on the
# gradients rather than on the text. At q82, measured after the 2x file is
# halved to the size it is actually drawn at, SSIM is 0.995 or better on all
# three and the type is indistinguishable from the PNG side by side. The three
# shots go from 1258 KB to 332 KB.
WEBP_Q = "82"

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

# Eight bars of the final chorus, downbeat to downbeat, and every part of that
# is doing something.
#
# It is a loop, so the only length that is right is a musical one. At 123.05 BPM
# a bar is 1.950s and eight of them are 15.60s; this window is 15.35s because it
# runs from one tracked downbeat to the eighth one after it rather than from an
# arithmetic multiple. Starting and ending on a downbeat is what lets the audio
# wrap without a seam, and it is also where the bar light is at zero - it swells
# from nothing at each downbeat, so the frame it teleports on is a frame it is
# not on screen for.
#
# The chorus opens and closes on the same words, so the wrap goes from the tail
# of "You're my gravity in motion." straight back into the middle of "You're my
# gravity in motion," - the same phrase, mid-word, which is about as close to
# invisible as a lyric loop gets.
#
# Of the three eight-bar chorus windows in this track it is the one that wraps
# best. Measured on the generated picture, last frame against first: mean
# absolute difference 11.0 of 255, against 14.4 for the second chorus and 15.9
# for the first. It is also the loudest of the three, and 99% of it has a word
# being sung. The two lines the scorecard wants an ear on, 5 and 31, are
# nowhere near it.
#
# It does not wrap invisibly and it cannot: the four fields of light drift on
# periods with no common multiple, by design, so after 15s they are somewhere
# else. 11 of 255 is a soft shift, not a cut.
DEMO_CLIP = "3:38.895-3:54.243"

# 1920 now, where the 42-second version was 1600. That was the right call at
# that length - the clip is drawn in a 1232 px box, and 1920 cost 55% more bytes
# for a difference invisible at 2x - and this is the right call at this one,
# because the whole thing is short enough that the comparison changes. Measured
# at 2464 device pixels against the render:
#
#     1600 wide, CRF 20   3301 KB   0.99209
#     1920 wide, CRF 23   3381 KB   0.99267
#
# The same bytes buy a better picture at the higher resolution once there are
# only fifteen seconds of them. CRF 20 at 1920 is better again and is not taken:
# 0.0004 of SSIM for another 2.1 MB, on something that autoplays.
DEMO_WIDTH = 1920
DEMO_CRF = "23"
DEMO_X264 = "aq-mode=3:aq-strength=0.8"
# The render now muxes the original file rather than the workdir's scrub cache,
# so there is finally something here worth carrying. 96k was throwing it away.
DEMO_AUDIO = "160k"   # it is a music video; muting it would be a strange demo
STILL_AT = 4.6        # seconds into the clip: mid-word, mid-line, three lines up

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
    shot = IMG / f"{name}.png"
    out = IMG / f"{name}.webp"
    try:
        subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
             f"--force-device-scale-factor={scale}",
             f"--window-size={size[0]},{size[1]}",
             "--virtual-time-budget=12000",
             f"--screenshot={shot}", f"http://127.0.0.1:{PORT}/demo/_shot.html"],
            check=True, capture_output=True,
        )
        # -sharp_yuv, because the accent and the green score chips are the one
        # place on a grey UI where chroma subsampling has something to ruin.
        subprocess.run([CWEBP, "-quiet", "-q", WEBP_Q, "-m", "6", "-sharp_yuv",
                        str(shot), "-o", str(out)], check=True)
    finally:
        page.unlink(missing_ok=True)
        shot.unlink(missing_ok=True)
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
    video, still = IMG / "video-demo.mp4", IMG / "video-still.webp"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
         "-vf", f"scale={DEMO_WIDTH}:-2:flags=lanczos",
         "-c:v", "libx264", "-preset", "veryslow", "-crf", DEMO_CRF,
         "-x264-params", DEMO_X264,
         "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-c:a", "aac", "-b:a", DEMO_AUDIO, str(video)],
        check=True,
    )
    # The poster is the largest thing the page paints before anything has
    # loaded, so it is the one file worth being fussy about: WebP at q80 is
    # 14 KB where the same frame as JPEG is 27 KB.
    frame = IMG / "_still.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(STILL_AT), "-i", str(source),
         "-frames:v", "1", "-vf", f"scale={DEMO_WIDTH}:-2:flags=lanczos",
         "-update", "1", str(frame)],
        check=True,
    )
    subprocess.run([CWEBP, "-quiet", "-q", "80", "-m", "6", "-sharp_yuv",
                    str(frame), "-o", str(still)], check=True)
    frame.unlink(missing_ok=True)
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
    if shutil.which(CWEBP) is None:
        raise SystemExit(f"need {CWEBP} on PATH (brew install webp)")
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
