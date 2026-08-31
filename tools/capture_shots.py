#!/usr/bin/env python3
"""Capture the product-page screenshots from the app itself.

The landing page is mostly pictures, so the pictures had better be the real
thing. Each shot below is the actual UI, driven into a particular state and
photographed by headless Chrome - not a mockup, and not hand-cropped. Re-run it
after a UI change and the page catches up.

It works against docs/demo, which build_demo.py already froze, so no server and
no audio decoding is involved. The demo's read-only chrome is taken off first:
these are pictures of the product, and the product can save.

    python tools/build_demo.py workdir/my-track   # first
    python tools/capture_shots.py
"""

from __future__ import annotations

import http.server
import shutil
import subprocess
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
    ("app-full", (1440, 940), 2, """
        select(6); document.querySelector('.lyrics').scrollTop = 300;
    """),
    ("app-stage", (1420, 300), 2, """
        document.querySelector('.lyrics').style.display = 'none';
        document.querySelector('.bar').style.display = 'none';
        select(6); focusLine(S.project.lines[6]); S.selWord = 2;
        S.audio.currentTime = S.project.lines[6].start + 1.15;
        draw();
    """),
    ("app-review", (1180, 860), 2, """
        S.additions = [];   // the sheet leads with missing lines; this shot is the queue
        document.getElementById('btn-review').click();
        S.review.at = S.review.queue.findIndex(q => q.scope === 'word');
        rvRender();
        const it = rvCurrent();
        S.review.adj = { t: rvClampT(it, it.proposed + 1.15) };
        rvSyncAdj(); rvDrawStrip();
    """),
    ("app-missing", (1180, 860), 2, """
        document.getElementById('btn-review').click();
        adRender();
    """),
]

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


if __name__ == "__main__":
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
