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

Every change, a hand's or the model's, goes into one history, described the same way
(`editor.changes`: what kind of thing, where, what it was and what it is now); undo, redo
and going back to any point in it move along that history, and it is kept with the song,
so it is there when the studio is opened again.

A correction of the grid (the beat twice or half as fast, the beats in a bar, where bar 1
falls) is not an edit like the others: the song is listened to again on the corrected
grid (about a minute and a half, and the models after it, the first time; a correction
made before is kept), and the director makes its shots and moments again on the new
bars. What is the person's and does not depend on bars - the cast, the dials, the words -
is kept, and the sections' names are carried over by time.

An mp4 of the song as the studio shows it - this sheet, the camera chosen, the words on or
off - is written in the background (`Export`, one at a time), and the page is told how far
it has got and, at the end, where the file is.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from . import ROOT, cosmos, decide, editor, lyrics, make, render, sheet as sheet_
from .cast import CHOICES
from .grid import normal_fix
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
                 log_path: Path | None = None, history_path: Path | None = None) -> None:
        self.track = track
        self.got = make.listened(track, verbose=False)
        make.modelled(track, self.got, verbose=False)
        render.STYLE = "cosmos"
        ch, self.sheet, self.came_from = make.directed(track, self.got)
        self.out = Path(out_dir or track.out("cosmos"))
        self.sheet_path = Path(sheet_path or sheet_.CURATED / f"{track.slug}.json")
        if self.sheet_path.exists() and self.sheet_path != self.came_from:     # a sheet kept somewhere of its own
            kept = sheet_.read(self.sheet_path)
            if not sheet_.validate(kept, self.got):
                self.sheet, self.came_from = kept, self.sheet_path
                ch = render.bake(self.got, track, kept)
        self.log_path = Path(log_path or track.cache / "edits.jsonl")
        self.history_path = Path(history_path or track.cache / "history.json")
        self.lock = threading.Lock()
        self.version = 0
        self.exporting: Export | None = None
        self._open_history()
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
        grid = m.get("grid", {})
        return {
            "slug": self.track.slug, "bundle": self.out.name, "duration": duration,
            "tempo": float(m["tempo"]), "meter": int(m.get("meter", 4)),
            "bar_t": [round(float(t), 4) for t in bar_t],
            "beats": [round(float(t), 4) for t in a["beats"]],
            "grid": {"source": grid.get("source"), "fixed": m.get("grid_fix"),
                     "sure": grid.get("lattice", {}).get("on_lattice") if grid.get("source") == "lattice" else None},
            "energy": [decide.STATE_NAMES[int(s)] for s in table["state"]],
            "loud": [round(x, 3) for x in env],
            "lines": [{"in": round(ln.in0, 3), "out": round(ln.out1, 3), "text": ln.text} for ln in lines],
            "lyrics_from": str(src.relative_to(ROOT)) if src and src.is_relative_to(ROOT) else (str(src) if src else None),
            "sheet": self.sheet, "version": self.version, "sheet_path": _shown(self.sheet_path),
            **self.history_view(),
            "vocabulary": vocabulary(), "model": editor.MODEL,
        }

    # ------------------------------------------------------------------ changing it

    def edit(self, edits: list[dict], source: str = "hand", request: str | None = None) -> dict:
        """Edits in the sheet's vocabulary, applied, checked, baked - and a step in the history."""
        with self.lock:
            before = self.sheet
            new, did = editor.apply(self.sheet, edits)
            r = self._take(new, did, {"source": source, "request": request, "edits": edits})
            if r.get("ok") and r.get("changed"):
                del self.history[self.at + 1:]            # a change after an undo: what was undone is gone
                self.history.append({"sheet": self.sheet, "source": source, "request": request,
                                     "changes": editor.changes(before, self.sheet), "at": time.strftime("%H:%M")})
                self.at = len(self.history) - 1
                self._save_history()
            return r | self.history_view()

    def goto(self, k: int) -> dict:
        """The sheet as it was at step `k` of the history (undo, redo, or further)."""
        with self.lock:
            if not 0 <= k < len(self.history) or k == self.at:
                return {"ok": True, "changed": False, "did": [], "sheet": self.sheet, "version": self.version} | self.history_view()
            r = self._take(self.history[k]["sheet"], ["undo" if k < self.at else "redo"],
                           {"source": "undo" if k < self.at else "redo", "to": k})
            if r.get("ok"):
                self.at = k
                self._save_history()
            return r | self.history_view()

    def history_view(self) -> dict:
        return {"history": [{k: h[k] for k in ("source", "request", "changes", "at")} for h in self.history],
                "at": self.at}

    def _open_history(self) -> None:
        """The history kept with the song, if it ends where the sheet is; else a new one."""
        try:
            kept = json.loads(self.history_path.read_text())
            if kept["entries"][kept["at"]]["sheet"] == sheet_.normal(self.sheet):
                self.history, self.at = kept["entries"], kept["at"]
                return
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            pass
        self.history = [{"sheet": sheet_.normal(self.sheet), "source": "open", "request": None, "changes": [],
                         "at": time.strftime("%H:%M")}]
        self.at = 0

    def _save_history(self) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(json.dumps({"at": self.at, "entries": self.history}))

    def replace(self, sheet: dict, why: str = "undo") -> dict:
        """A whole sheet: going back to one the page had (undo, redo)."""
        with self.lock:
            return self._take(sheet, [why], {"source": why})

    def ask(self, request: str, model: str | None = None, focus: dict | None = None) -> dict:
        """What the model would do: a proposal, not applied. Accepting it sends its edits
        back through `edit`, the same way a hand's do. `focus` is what the person has
        selected and where the playhead is, for "this" and "here"."""
        try:
            r = editor.edit(self.track, self.got, self.sheet, request, model=model or editor.MODEL, focus=focus)
        except urllib.error.URLError:
            return {"ok": False, "refused": ["the local model is not running: start Ollama (ollama serve)"]}
        return {"ok": not r["refused"], "edits": r["edits"], "did": r["did"], "said": r["said"],
                "changes": editor.changes(self.sheet, r["sheet"]) if r["sheet"] else [],
                "refused": r["refused"], "proposes": r["sheet"] is not None, "already": r.get("already", False),
                "proposal": r["sheet"], "seconds": round(r["seconds"], 1), "model": model or editor.MODEL}

    def refresh(self) -> dict:
        """The words read again (after they were changed in the song app), and baked in."""
        with self.lock:
            ch = render.bake(self.got, self.track, self.sheet)
            render.export(self.got, ch, self.track, self.out)
            self.version += 1
        return {"ok": True, "changed": True, "song": self.song(), "sheet": self.sheet, "version": self.version, "did": ["words read again"]}

    def _take(self, new: dict, did: list[str], why: dict) -> dict:
        new = sheet_.normal(new)
        grid = lambda sh: normal_fix({k: sh.get("heard", {}).get(k) for k in sheet_.GRID})
        if grid(new) != grid(self.sheet):
            return self._regrid(new, grid(new), did, why)
        bad = sheet_.validate(new, self.got)
        if bad:
            return {"ok": False, "refused": bad, "did": did}
        if new == self.sheet:
            return {"ok": True, "changed": False, "did": did, "sheet": self.sheet, "version": self.version}
        t0 = time.time()
        names_only = lambda sh: {**sh, "heard": {k: v for k, v in sh["heard"].items() if k != "sections"}}
        if names_only(new) != names_only(self.sheet):       # names change nothing in the picture: no bake
            ch = render.bake(self.got, self.track, new)
            render.export(self.got, ch, self.track, self.out)
        self.sheet, self.version = new, self.version + 1
        sheet_.write(new, self.sheet_path)
        seconds = round(time.time() - t0, 2)
        self._log(did, seconds, why)
        return {"ok": True, "changed": True, "did": did, "sheet": new, "version": self.version, "seconds": seconds}


    def _regrid(self, new: dict, fix: dict | None, did: list[str], why: dict) -> dict:
        """The song heard again on a corrected grid, and the sheet made again on its bars."""
        t0 = time.time()
        got = make.listened(self.track, verbose=False, grid_fix=fix)
        make.modelled(self.track, got, verbose=False)
        if sheet_.validate(new, got):                 # bars of the old grid: made again on the new one
            fresh = sheet_.default(self.track, got, render.bake(got, self.track))
            for k in ("cast", "feel", "lyrics"):
                fresh[k] = new[k]
            fresh["heard"]["sections"] = carry_sections(new["heard"].get("sections", []), self.got, got)
            new = fresh
        bad = sheet_.validate(new, got)               # (a whole sheet on the new grid - an undo - is kept as it is)
        if bad:
            return {"ok": False, "refused": bad, "did": did}
        ch = render.bake(got, self.track, new)
        render.export(got, ch, self.track, self.out)
        self.got, self.sheet, self.version = got, new, self.version + 1
        sheet_.write(new, self.sheet_path)
        seconds = round(time.time() - t0, 2)
        self._log(did, seconds, why)
        return {"ok": True, "changed": True, "regrid": True, "did": did, "sheet": new, "song": self.song(),
                "version": self.version, "seconds": seconds}

    def _log(self, did: list[str], seconds: float, why: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "version": self.version, "did": did,
                                "seconds": seconds} | why) + "\n")


    # ------------------------------------------------------------------ the mp4

    def export(self, camera: str, words: bool = True) -> dict:
        """The whole song to an mp4, as the studio shows it now: this sheet, this camera, the
        words burned in or not. Written in the background; `exporting` says how far it has got."""
        if camera not in cosmos.MODES:
            return {"ok": False, "refused": [f"no camera {camera!r}: the cameras are {', '.join(cosmos.MODES)}"]}
        if not Export.running.acquire(blocking=False):
            return {"ok": False, "refused": ["an mp4 is already being written: one at a time"]}
        self.exporting = Export(self, camera, bool(words))
        return {"ok": True} | self.exporting.view()

    def export_path(self, camera: str, words: bool = True) -> Path:
        return self.out / render.mp4_name(self.track, camera, words)


class Export:
    """An mp4 being written in a thread of its own. One at a time, whatever the song: two
    would share the GPU and the encoder, and each take twice as long."""

    running = threading.Lock()

    def __init__(self, session: Session, camera: str, words: bool) -> None:
        self.session, self.camera, self.words = session, camera, words
        self.path = session.export_path(camera, words)
        self.done, self.total, self.error, self.finished = 0, 0, None, False
        self.t0, self.t1, self.first = time.time(), None, None
        with session.lock:                                   # the sheet as it is at the click
            self.got, self.sheet = session.got, session.sheet
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            ch = render.bake(self.got, self.session.track, self.sheet)
            render.render(self.got, self.session.track, self.session.out, camera=self.camera, words=self.words,
                          ch=ch, quiet=True, progress=self._progress)
        except Exception as e:                               # said to the page
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.finished, self.t1 = True, time.time()
            Export.running.release()

    def _progress(self, done: int, total: int) -> None:
        if self.first is None:
            self.first = (time.time(), done)
        self.done, self.total = done, total

    def view(self) -> dict:
        now = time.time()
        remaining = None
        if self.first is not None and self.done > self.first[1]:
            rate = (self.done - self.first[1]) / max(now - self.first[0], 1e-6)
            remaining = round((self.total - self.done) / rate, 1)
        state = "failed" if self.error else "done" if self.finished else "running"
        return {"state": state, "camera": self.camera, "lyrics": self.words, "done": self.done, "total": self.total,
                "elapsed": round((self.t1 or now) - self.t0, 1), "remaining": 0.0 if self.finished else remaining, "error": self.error,
                "path": _shown(self.path), "url": f"/out/{self.path.parent.name}/{self.path.name}"}


def carry_sections(sections: list[dict], old: dict, new: dict) -> list[dict]:
    """Named sections moved from one grid's bars to another's, by the time they start and
    end: each edge to the new bar line nearest it."""
    ob, nb = old["arrays"]["bar_t"], new["arrays"]["bar_t"]
    od, nd = float(old["meta"]["duration"]), float(new["meta"]["duration"])
    at = lambda b: float(ob[b]) if b < len(ob) else od
    near = lambda t: len(nb) if t >= nd - 1e-6 else int(np.argmin(np.abs(nb - t)))
    out, end = [], 0
    for sec in sections:
        a, b = max(near(at(sec["bars"][0])), end), near(at(sec["bars"][1]))
        if b > a:
            out.append({"name": sec["name"], "bars": [a, b]})
            end = b
    return out


def _shown(p: Path) -> str:
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


# ---------------------------------------------------------------------------- serving


def handler(sessions: dict[str, Session]):
    """The static handler for visuals/, and the page's few questions."""
    from ...cli import _RangeHandler

    class Handler(_RangeHandler):
        def copyfile(self, source, outputfile):             # a page that stops a download midway is not an error
            try:
                super().copyfile(source, outputfile)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, fmt, *args):                  # the static files are many and dull, and so is an export's progress
            if "/api/" in self.path and not (self.command == "GET" and self.path.startswith("/api/export")):
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
            if url.path == "/api/models":
                try:
                    return self._reply(editor.models() | {"default": editor.MODEL})
                except OSError as e:
                    return self._reply({"installed": [], "loaded": [], "default": editor.MODEL, "down": str(e)})
            if url.path == "/api/song":
                s = self._session(url)
                return s and self._reply(s.song())
            if url.path == "/api/export":                   # how far the mp4 has got, and where one would go
                s = self._session(url)
                if s is None:
                    return None
                q = parse_qs(url.query)
                camera, words = q.get("camera", ["static"])[0], q.get("lyrics", ["1"])[0] != "0"
                return self._reply({"job": s.exporting.view() if s.exporting else None,
                                    "path": _shown(s.export_path(camera, words)) if camera in cosmos.MODES else None})
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
                    out = s.ask(body["request"], body.get("model"), body.get("focus"))
                elif url.path in ("/api/undo", "/api/redo"):
                    out = s.goto(s.at + (-1 if url.path == "/api/undo" else 1))
                elif url.path == "/api/goto":
                    out = s.goto(int(body["to"]))
                elif url.path == "/api/refresh":
                    out = s.refresh()
                elif url.path == "/api/export":
                    out = s.export(str(body.get("camera", "static")), bool(body.get("lyrics", True)))
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
        print(f"  {tr.slug}: ready ({time.time() - t0:.0f}s), sheet {_shown(sessions[tr.slug].sheet_path)}", flush=True)
    visuals = ROOT / "visuals"
    Handler = handler(sessions)
    def warm():                                            # the model loaded before it is first asked
        try:
            editor.warm()
            print(f"  {editor.MODEL}: loaded", flush=True)
        except Exception as e:                             # Ollama not running: asking will say so
            print(f"  {editor.MODEL}: not loaded ({e})", flush=True)
    threading.Thread(target=warm, daemon=True).start()
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=str(visuals))) as httpd:
        for slug in sessions:
            print(f"http://127.0.0.1:{port}/studio/?track={slug}", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
