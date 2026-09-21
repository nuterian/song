"""The studio: a song's video and its direction sheet side by side, edited by hand or by asking.

    python -m visuals studio <song> [<song> ...] [--port 8777]

One page (visuals/studio/) shows the player and, under it, the song on a timeline in bars:
its sections, how full it is, the shots, the moments the beat comes back, the lines of the
words; and the cast, the dials and the words' look beside it. Every change - a shot picked,
an edge dragged, a dial moved, a request answered by the local model - is an edit in the
sheet's own vocabulary, applied by `editor.apply`: the very edits the model makes. So a
hand and a model change the video the same way, and every change reads back in words.

The server holds each song's listening in memory, bakes the edited sheet (2-3 s on
Gravity), writes the bundle over the one the player is showing, and keeps the sheet in
visuals/sheets/, where a person's sheets are kept. The player takes the new bake without
stopping. Each change is logged, with who made it (a hand, or a request and the model's
answer), to the song's cache: what people change is what the director gets wrong.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from . import ROOT, decide, editor, lyrics, make, render, sheet as sheet_
from .cast import CHOICES
from .track import Track

ENVELOPE = 1600              # points in the loudness strip under the timeline


def vocabulary() -> dict:
    """Everything the page may offer, with what each means: the sheet's own words."""
    spec = lambda d: {k: {"default": v[0], "low": v[1], "high": v[2], "what": v[3]} for k, v in d.items()}
    return {"shots": sheet_.SHOTS, "needs_subject": list(sheet_.NEEDS_SUBJECT), "planets": list(sheet_.PLANETS),
            "parts": sheet_.PARTS, "choices": {k: list(v) for k, v in CHOICES.items()},
            "feel": spec(sheet_.FEEL), "lyrics": spec(sheet_.LYRICS)}


class Session:
    """One song, open for editing."""

    def __init__(self, track: Track, out_dir: Path | None = None, sheet_path: Path | None = None,
                 log_path: Path | None = None) -> None:
        self.track = track
        self.got = make.listened(track, verbose=False)
        make.modelled(track, self.got, verbose=False)
        render.STYLE = "cosmos"
        ch, self.sheet, self.came_from = make.directed(track, self.got)
        self.out = Path(out_dir or track.out("cosmos"))
        self.sheet_path = Path(sheet_path or sheet_.CURATED / f"{track.slug}.json")
        self.log_path = Path(log_path or track.cache / "edits.jsonl")
        self.lock = threading.Lock()
        self.version = 0
        self.out.mkdir(parents=True, exist_ok=True)
        render.export(self.got, ch, track, self.out)          # the bundle shown is this sheet's

    # ------------------------------------------------------------------ what the page shows

    def song(self) -> dict:
        a, m = self.got["arrays"], self.got["meta"]
        bar_t, duration = a["bar_t"], float(m["duration"])
        table = decide.bar_table(a, duration)
        loud = np.asarray(a["loud"], dtype=np.float64)
        edges = np.linspace(0, len(loud), ENVELOPE + 1).astype(int)
        env = [float(loud[i:max(j, i + 1)].max()) for i, j in zip(edges[:-1], edges[1:])]
        src = lyrics.source(self.track)
        lines = lyrics.read(src) if src else []
        return {
            "slug": self.track.slug, "bundle": self.out.name, "duration": duration,
            "tempo": float(m["tempo"]), "meter": int(m.get("meter", 4)),
            "bar_t": [round(float(t), 4) for t in bar_t],
            "sections": [{"name": n, "bars": [b0, b1]} for n, b0, b1 in editor.named_sections(self.track, bar_t)],
            "energy": [decide.STATE_NAMES[int(s)] for s in table["state"]],
            "loud": [round(x, 3) for x in env],
            "lines": [{"in": round(ln.in0, 3), "out": round(ln.out1, 3), "text": ln.text} for ln in lines],
            "lyrics_from": str(src.relative_to(ROOT)) if src and src.is_relative_to(ROOT) else (str(src) if src else None),
            "sheet": self.sheet, "version": self.version, "sheet_path": _shown(self.sheet_path),
            "vocabulary": vocabulary(), "model": editor.MODEL,
        }

    # ------------------------------------------------------------------ changing it

    def edit(self, edits: list[dict], source: str = "hand", request: str | None = None) -> dict:
        """Edits in the sheet's vocabulary, applied, checked, baked."""
        with self.lock:
            new, did = editor.apply(self.sheet, edits)
            return self._take(new, did, {"source": source, "request": request, "edits": edits})

    def replace(self, sheet: dict, why: str = "undo") -> dict:
        """A whole sheet: going back to one the page had (undo, redo)."""
        with self.lock:
            return self._take(sheet, [why], {"source": why})

    def ask(self, request: str, model: str | None = None) -> dict:
        """What the model would do: a proposal, not applied. Accepting it sends its edits
        back through `edit`, the same way a hand's do."""
        try:
            r = editor.edit(self.track, self.got, self.sheet, request, model=model or editor.MODEL)
        except urllib.error.URLError:
            return {"ok": False, "refused": ["the local model is not running: start Ollama (ollama serve)"]}
        return {"ok": not r["refused"], "edits": r["edits"], "did": r["did"], "said": r["said"],
                "refused": r["refused"], "changes": r["sheet"] is not None, "already": r.get("already", False),
                "proposal": r["sheet"], "seconds": round(r["seconds"], 1), "model": model or editor.MODEL}

    def _take(self, new: dict, did: list[str], why: dict) -> dict:
        new = sheet_.normal(new)
        bad = sheet_.validate(new, self.got)
        if bad:
            return {"ok": False, "refused": bad, "did": did}
        if new == self.sheet:
            return {"ok": True, "changed": False, "did": did, "sheet": self.sheet, "version": self.version}
        t0 = time.time()
        ch = render.bake(self.got, self.track, new)
        render.export(self.got, ch, self.track, self.out)
        self.sheet, self.version = new, self.version + 1
        sheet_.write(new, self.sheet_path)
        seconds = round(time.time() - t0, 2)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "version": self.version, "did": did,
                                "seconds": seconds} | why) + "\n")
        return {"ok": True, "changed": True, "did": did, "sheet": new, "version": self.version, "seconds": seconds}


def _shown(p: Path) -> str:
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


# ---------------------------------------------------------------------------- serving


def handler(sessions: dict[str, Session]):
    """The static handler for visuals/, and the page's few questions."""
    from ...cli import _RangeHandler

    class Handler(_RangeHandler):
        def log_message(self, fmt, *args):                  # the static files are many and dull
            if "/api/" in self.path:
                super().log_message(fmt, *args)

        def _reply(self, body: dict, status: int = 200) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _session(self, url) -> Session | None:
            name = (parse_qs(url.query).get("track") or [next(iter(sessions))])[0]
            s = sessions.get(name)
            if s is None:
                self._reply({"ok": False, "refused": [f"no song {name!r} is open: {', '.join(sessions)}"]}, 404)
            return s

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/api/songs":
                return self._reply({"songs": list(sessions)})
            if url.path == "/api/song":
                s = self._session(url)
                return s and self._reply(s.song())
            if url.path in ("/", "/studio"):
                self.send_response(302)
                self.send_header("Location", "/studio/")
                self.end_headers()
                return None
            return super().do_GET()

        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            s = self._session(url)
            if s is None:
                return None
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if url.path == "/api/edit":
                    out = s.edit(body["edits"], body.get("source", "hand"), body.get("request"))
                elif url.path == "/api/sheet":
                    out = s.replace(body["sheet"], body.get("why", "undo"))
                elif url.path == "/api/ask":
                    out = s.ask(body["request"], body.get("model"))
                else:
                    return self._reply({"ok": False, "refused": [f"no such question: {url.path}"]}, 404)
            except Exception as e:                            # said to the page, not swallowed
                return self._reply({"ok": False, "refused": [f"{type(e).__name__}: {e}"]}, 500)
            return self._reply(out, 200 if out.get("ok") else 422)

    return Handler


def serve(tracks: list[Track], port: int = 8777) -> None:
    import functools
    import http.server

    sessions = {}
    for tr in tracks:
        t0 = time.time()
        sessions[tr.slug] = Session(tr)
        print(f"  {tr.slug}: ready ({time.time() - t0:.0f}s), sheet {_shown(sessions[tr.slug].sheet_path)}")
    visuals = ROOT / "visuals"
    Handler = handler(sessions)
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=str(visuals))) as httpd:
        for slug in sessions:
            print(f"http://127.0.0.1:{port}/studio/?track={slug}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
