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

A song is added from the page (`/api/import`): its audio, and its lyrics if it has them,
are kept where a song given on the command line would be, and a background job (`Jobs`,
one at a time: the machine cannot separate two songs at once) does what `make` does -
the stems, the words aligned on their vocals, listening, the models, the bundle - and
opens it. With no songs named, the studio offers every song already listened to.

An mp4 of the song as the studio shows it - this sheet, the camera chosen, the words on or
off - is written in the background (`Export`, one at a time), and the page is told how far
it has got and, at the end, where the file is.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from . import ROOT, cosmos, decide, editor, lyrics, make, render, sheet as sheet_
from .cast import CHOICES
from .grid import normal_fix
from .track import AUDIO_SUFFIXES, DEMUCS_PYTHON, LOSSLESS, Track, prepare, slugify

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

    def export(self, camera: str, words: bool = True, jobs: "Jobs | None" = None, shape: str = "wide") -> dict:
        """The whole song to an mp4, as the studio shows it now: this sheet, this camera, the
        frame wide or tall, the words burned in or not. One job of the studio's runner
        (`Jobs`: after any song being added, and never beside another export); `exporting`
        says how far it has got."""
        if camera not in cosmos.MODES:
            return {"ok": False, "refused": [f"no camera {camera!r}: the cameras are {', '.join(cosmos.MODES)}"]}
        if shape not in cosmos.SHAPES:
            return {"ok": False, "refused": [f"no shape {shape!r}: the frame is {' or '.join(cosmos.SHAPES)}"]}
        if self.exporting and not self.exporting.finished:
            return {"ok": False, "refused": ["an mp4 of this song is already being written: one at a time"]}
        self.exporting = Export(self, camera, bool(words), shape)
        (jobs or Jobs()).start("export", self.track.slug, self.exporting.run)
        return {"ok": True} | self.exporting.view()

    def export_path(self, camera: str, words: bool = True, shape: str = "wide") -> Path:
        return self.out / render.mp4_name(self.track, camera, words, shape=shape)


class Export:
    """An mp4 being written, and how far it has got, frame by frame. It runs as a job of
    the studio's runner, so two never share the GPU and the encoder (each would take twice
    as long), and it waits behind a song being added."""

    def __init__(self, session: Session, camera: str, words: bool, shape: str = "wide") -> None:
        self.session, self.camera, self.words, self.shape = session, camera, words, shape
        self.path = session.export_path(camera, words, shape)
        self.done, self.total, self.error, self.finished = 0, 0, None, False
        self.t0, self.t1, self.first = time.time(), None, None
        with session.lock:                                   # the sheet as it is at the click
            self.got, self.sheet = session.got, session.sheet

    def run(self, step) -> None:
        self.t0 = time.time()                                # the wait in the queue is not the render's
        try:
            step("baking")
            ch = render.bake(self.got, self.session.track, self.sheet)
            step("rendering")
            render.render(self.got, self.session.track, self.session.out, camera=self.camera, words=self.words,
                          ch=ch, quiet=True, progress=self._progress, shape=self.shape)
        except Exception as e:                               # said to the page
            self.error = f"{type(e).__name__}: {e}"
            raise
        finally:
            self.finished, self.t1 = True, time.time()

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
        return {"state": state, "camera": self.camera, "lyrics": self.words, "shape": self.shape, "done": self.done, "total": self.total,
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


# ---------------------------------------------------------------------------- the songs there are

CACHE = ROOT / "visuals" / "cache"


def prepared(cache: Path = CACHE, near: tuple[Path, ...] = (ROOT / "examples", CACHE / "testset"),
             workdirs: Path = ROOT / "workdir") -> list[Track]:
    """Every song listened to already (its cache has listen.json), as a track to open: read
    from its copy in the cache (source.*, or the decode audio.wav), else from a file named
    for it in examples/ or the test set, else from its song workdir. A song whose audio is
    nowhere is left out, and said so."""
    out = []
    for d in sorted(p for p in cache.glob("*") if (p / "listen.json").exists()):
        slug = d.name
        wd = workdirs / slug if (workdirs / slug / "project.json").exists() else None
        copies = sorted((p for p in d.glob("source.*") if p.suffix.lower() in AUDIO_SUFFIXES),
                        key=lambda p: p.suffix.lower() not in LOSSLESS) + [d / "audio.wav"]
        named = [p for folder in near if folder.exists() for p in sorted(folder.iterdir())
                 if p.suffix.lower() in AUDIO_SUFFIXES and slugify(p.stem) == slug]
        audio = next((p for p in copies + named if p.is_file()), None)
        if audio is not None:
            out.append(Track(slug, audio, wd))
        elif wd is not None:
            try:
                out.append(Track.resolve(wd))
            except SystemExit as e:
                print(f"  {slug}: left out ({e})", flush=True)
        else:
            print(f"  {slug}: left out (its audio is not in the cache, examples/ or a workdir)", flush=True)
    return out


# ---------------------------------------------------------------------------- long work


class Jobs:
    """Long work in the background, one job at a time and in the order asked: the machine
    cannot separate two songs at once, and a job that waits is better than two that crawl.

    A job is a function given `step(name)`, to say where it is; whatever it prints (and
    whatever a subprocess it runs prints, if it prints that) is its log. `start` queues it
    and returns at once. Adding a song is one kind; exporting a video can be another."""

    LOG = 12                      # the last lines of a job's output the page is shown

    def __init__(self) -> None:
        self.jobs: list[dict] = []
        self.lock = threading.Lock()
        self.queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._work, daemon=True, name="studio-jobs").start()

    def start(self, kind: str, song: str, fn) -> dict:
        with self.lock:
            job = {"id": len(self.jobs) + 1, "kind": kind, "song": song, "state": "queued", "step": "waiting",
                   "log": [], "steps": [], "started": None, "seconds": 0.0, "error": None}
            self.jobs.append(job)
            shown = self.shown(job)
        self.queue.put((job, fn))
        return shown

    def pending(self, song: str) -> bool:
        """Whether a job for this song is waiting or running."""
        with self.lock:
            return any(j["song"] == song and j["state"] in ("queued", "running") for j in self.jobs)

    def view(self) -> list[dict]:
        with self.lock:
            return [self.shown(j) for j in self.jobs]

    @staticmethod
    def shown(job: dict) -> dict:
        out = {k: v for k, v in job.items() if not k.startswith("_")}
        if job["state"] == "running":
            out["seconds"] = round(time.time() - job["started"], 1)
        out["log"] = job["log"][-Jobs.LOG:]
        out["steps"] = [dict(s) for s in job["steps"]]
        return out

    def _step(self, job: dict, name: str) -> None:
        now = time.time()
        with self.lock:
            if job["steps"] and job["steps"][-1]["seconds"] is None:
                job["steps"][-1]["seconds"] = round(now - job["_at"], 1)
            job["steps"].append({"name": name, "seconds": None})
            job["step"], job["_at"] = name, now
        print(f"  [{job['kind']} {job['song']}] {name}", flush=True)

    def _said(self, job: dict, text: str) -> None:
        with self.lock:
            lines = (job.get("_part", "") + text).replace("\r", "\n").split("\n")
            job["_part"] = lines.pop()
            job["log"] += [ln for ln in lines if ln.strip()]
            del job["log"][:-200]

    def _work(self) -> None:
        while True:
            job, fn = self.queue.get()
            with self.lock:
                job["state"], job["started"] = "running", time.time()
                job["_at"] = job["started"]
            tee = _Tee(sys.stdout, threading.get_ident(), lambda s: self._said(job, s))
            sys.stdout = tee
            try:
                fn(lambda name: self._step(job, name))
                state, error = "done", None
            except (Exception, SystemExit) as e:           # SystemExit: how this package says a song cannot be made
                state, error = "failed", str(e) or type(e).__name__
                print(f"  [{job['kind']} {job['song']}] failed: {error}", flush=True)
                if not isinstance(e, SystemExit):              # a fault, not a refusal: where it was, for the terminal
                    traceback.print_exc()
            finally:
                if sys.stdout is tee:
                    sys.stdout = tee.out
            with self.lock:
                now = time.time()
                if job["steps"] and job["steps"][-1]["seconds"] is None:
                    job["steps"][-1]["seconds"] = round(now - job["_at"], 1)
                job["state"], job["error"] = state, error
                job["seconds"] = round(now - job["started"], 1)
                job["step"] = state
            self.queue.task_done()


class _Tee:
    """What is printed, passed on as it was; and what the job's own thread prints, also
    given to the job. Other threads (the server's) print as they did."""

    def __init__(self, out, thread: int, to) -> None:
        self.out, self.thread, self.to = out, thread, to

    def write(self, s: str) -> int:
        if threading.get_ident() == self.thread:
            self.to(s)
        return self.out.write(s)

    def flush(self) -> None:
        self.out.flush()

    def __getattr__(self, name):
        return getattr(self.out, name)


# ---------------------------------------------------------------------------- adding a song


def multipart(body: bytes, content_type: str) -> dict[str, tuple[str | None, bytes]]:
    """A multipart/form-data body, as {field: (file name, bytes)}: the few lines the page's
    upload needs (the standard library's parser is gone from Python 3.13)."""
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        return {}
    out = {}
    for part in body.split(b"--" + m.group(1).encode())[1:-1]:
        head, _, data = part.removeprefix(b"\r\n").partition(b"\r\n\r\n")
        head = head.decode("utf-8", "replace")
        name, file = re.search(r'(?:^|[;\s])name="([^"]*)"', head), re.search(r'filename="([^"]*)"', head)
        if name:
            out[name.group(1)] = (file.group(1) if file else None, data.removesuffix(b"\r\n"))
    return out


def importing(sessions: dict, jobs: Jobs, audio: tuple[str | None, bytes] | None,
              lyrics_file: tuple[str | None, bytes] | None = None) -> tuple[dict, int]:
    """A song given from the page: checked, kept where `Track.resolve` would keep a song
    from outside the repository (its lossless audio as cache/<slug>/source.<ext>, which
    every step then reads, so it is not copied again; lossy audio beside it, decoded once
    into cache/<slug>/audio.wav), its lyrics as workdir/<slug>/lyrics.txt, and a job queued
    to make it and open it. Returns the reply and its status."""
    no = lambda status, why: ({"ok": False, "refused": [why]}, status)
    if not audio or not audio[0] or not audio[1]:
        return no(400, "no audio was sent")
    name = Path(audio[0]).name
    suffix = Path(name).suffix.lower()
    if suffix not in AUDIO_SUFFIXES:
        return no(415, f"{name} is not audio the studio reads ({', '.join(sorted(AUDIO_SUFFIXES))})")
    if lyrics_file and lyrics_file[1] and Path(lyrics_file[0] or "").suffix.lower() != ".txt":
        return no(415, f"{Path(lyrics_file[0] or 'the lyrics').name}: lyrics are read from a plain text file (.txt)")
    slug = slugify(Path(name).stem)
    if slug in sessions:
        return no(409, f"{Path(name).stem} is already in the studio")
    if jobs.pending(slug):
        return no(409, f"{Path(name).stem} is already being added")
    cache, data = CACHE / slug, audio[1]
    src = cache / f"source{suffix}"
    for kept in (p for p in cache.glob("source.*") if p.suffix.lower() in AUDIO_SUFFIXES):
        if kept != src or kept.stat().st_size != len(data) or kept.read_bytes() != data:
            return no(409, f"another recording called {Path(name).stem} is in {_shown(cache)}: "
                           f"rename the file, or move that folder away")
    cache.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        src.write_bytes(data)
    words, note = None, None
    wd = ROOT / "workdir" / slug
    if lyrics_file and lyrics_file[1]:
        if (wd / "project.json").exists():            # timed already, perhaps by hand: kept
            note = f"the words are timed already in {_shown(wd)}: the lyrics sent are not used"
        else:
            wd.mkdir(parents=True, exist_ok=True)
            words = wd / "lyrics.txt"
            words.write_bytes(lyrics_file[1])
    track = Track(slug, src, wd if (wd / "project.json").exists() else None)
    job = jobs.start("import", slug, lambda step: _make_and_open(sessions, track, words, step, note))
    return {"ok": True, "job": job}, 202


def _make_and_open(sessions: dict, track: Track, words: Path | None, step, note: str | None = None) -> None:
    """What `make` does for a song, step by step so the page can say where it is, then open
    it. With lyrics, the stems come first and the song tool aligns the words on their
    vocals: Demucs is run once, not once here and once there."""
    if note:
        print(note)
    step("separating")
    prepare(track)
    if words is not None:
        step("aligning the words")
        align(track, words)
        track = Track(track.slug, track.source, words.parent)
    step("listening")
    got = make.listened(track)
    step("the models")
    make.modelled(track, got)
    step("staging")
    make.make(track, "cosmos")
    step("opening")
    sessions[track.slug] = Session(track)


def align(track: Track, words: Path) -> None:
    """The song tool's alignment (run in the root venv, where it lives), given this song's
    vocals stem so it does not separate the song again."""
    wd = words.parent
    vocals = track.stems_dir / "vocals.wav"
    if vocals.exists() and not (wd / "vocals.wav").exists():
        try:
            os.link(vocals, wd / "vocals.wav")         # the same file, not a second copy of it
        except OSError:
            shutil.copy2(vocals, wd / "vocals.wav")
    p = subprocess.Popen([str(DEMUCS_PYTHON), "-m", "song", "align", str(track.audio), str(words), "--workdir", str(wd)],
                         cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env=os.environ | {"PYTHONUNBUFFERED": "1"})   # its progress as it happens, not at the end
    for line in p.stdout:
        print("  " + line.rstrip(), flush=True)
    if p.wait() != 0:
        raise RuntimeError(f"the words could not be aligned (song align exited {p.returncode})")


# ---------------------------------------------------------------------------- serving


def handler(sessions: dict[str, Session | Track], jobs: Jobs | None = None):
    """The static handler for visuals/, and the page's few questions. A song given as a
    track, not yet a session, is opened the first time the page asks for it."""
    from ...cli import _RangeHandler

    jobs = jobs or Jobs()
    opening = threading.Lock()

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
            name = (parse_qs(url.query).get("track") or [next(iter(sessions), "")])[0]
            s = sessions.get(name)
            if s is None:
                self._reply({"ok": False, "refused": [f"no song {name!r} is open: {', '.join(sessions) or 'none yet'}"]}, 404)
            elif isinstance(s, Track):
                with opening:
                    try:
                        if isinstance(sessions[name], Track):
                            t0 = time.time()
                            sessions[name] = Session(s)
                            print(f"  {name}: opened ({time.time() - t0:.0f}s)", flush=True)
                    except (Exception, SystemExit) as e:
                        self._reply({"ok": False, "refused": [f"{name} could not be opened: {e}"]}, 500)
                        return None
                    s = sessions[name]
            return s

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/api/songs":
                return self._reply({"songs": list(sessions), "audio": sorted(AUDIO_SUFFIXES)})
            if url.path == "/api/jobs":
                return self._reply({"jobs": jobs.view()})
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
                shape = q.get("shape", ["wide"])[0]
                known = camera in cosmos.MODES and shape in cosmos.SHAPES
                return self._reply({"job": s.exporting.view() if s.exporting else None,
                                    "path": _shown(s.export_path(camera, words, shape)) if known else None})
            if url.path in ("/", "/studio"):
                self.send_response(302)
                self.send_header("Location", "/studio/")
                self.end_headers()
                return None
            return super().do_GET()

        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/api/import":
                form = multipart(self.rfile.read(int(self.headers.get("Content-Length") or 0)),
                                 self.headers.get("Content-Type", ""))
                try:
                    return self._reply(*importing(sessions, jobs, form.get("audio"), form.get("lyrics")))
                except OSError as e:                          # the disk full, say
                    return self._reply({"ok": False, "refused": [f"{type(e).__name__}: {e}"]}, 500)
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
                    out = s.export(str(body.get("camera", "static")), bool(body.get("lyrics", True)), jobs,
                                   str(body.get("shape", "wide")))
                else:
                    return self._reply({"ok": False, "refused": [f"no such question: {url.path}"]}, 404)
            except Exception as e:                            # said to the page, not swallowed
                return self._reply({"ok": False, "refused": [f"{type(e).__name__}: {e}"]}, 500)
            return self._reply(out, 200 if out.get("ok") else 422)

    return Handler


def serve(tracks: list[Track], port: int = 8777) -> None:
    """The songs named, opened now; or, with none named, every song prepared, each opened
    the first time it is asked for (a song takes seconds to open, and there may be many)."""
    import functools
    import http.server

    sessions: dict[str, Session | Track] = {}
    for tr in tracks:
        t0 = time.time()
        sessions[tr.slug] = Session(tr)
        print(f"  {tr.slug}: ready ({time.time() - t0:.0f}s), sheet {_shown(sessions[tr.slug].sheet_path)}", flush=True)
    if not tracks:
        sessions = {tr.slug: tr for tr in prepared()}
        print(f"  {len(sessions)} songs prepared: {', '.join(sessions) or 'none yet (add one on the page)'}", flush=True)
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
        for slug in sessions if tracks else []:
            print(f"http://127.0.0.1:{port}/studio/?track={slug}", flush=True)
        if not tracks:
            print(f"http://127.0.0.1:{port}/studio/", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
