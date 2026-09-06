"""FastAPI backend for the review UI."""

from __future__ import annotations

import json
import subprocess
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import analysis, decisions, exports, vad
from .align import gaps, pipeline, refine, roundtrip
from .audio import TARGET_SR, load_mono
from .project import Project, slugify

AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".aif", ".aiff", ".ogg"}

UI_DIR = Path(__file__).resolve().parent / "ui"


def _preview(source: Path, target: Path, stereo: bool = True) -> Path:
    """Small AAC copy of a wav, so the browser loads and seeks instantly."""
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-y",
            "-i", str(source),
            "-ac", "2" if stereo else "1",
            "-c:a", "aac", "-b:a", "128k" if stereo else "80k",
            str(target),
        ],
        check=True,
    )
    return target


def create_app(target: Path | str, device: str = "cpu") -> FastAPI:
    """Serve the review UI for a track, or for a root with no tracks in it yet.

    Opening with nothing aligned used to raise. That made the app's own import
    flow - drop an audio file and a lyrics file, watch the pipeline run -
    reachable only *after* you had already done the same job at a command line,
    which is the one moment you would most want it. An empty root is now a
    first-class state: the API says so, and the UI opens on the import panel.
    """
    target = Path(target).resolve()
    opened = (target / "project.json").exists()

    app = FastAPI(title="song")
    # The session is not bound to one track: everything derives from
    # state["workdir"], so importing or opening another track just moves it.
    state: dict = {
        "workdir": target,
        # With a track open, its siblings are the other tracks; with nothing
        # open, the target *is* the place tracks live.
        "root": target.parent if opened else target,
        "project": Project.load(target / "project.json") if opened else None,
        "stem": None,          # (samples, VocalActivity) for the open track, decoded once
        "device": device,
        "job": None,
    }

    def wd() -> Path:
        return state["workdir"]

    def project_file() -> Path:
        return wd() / "project.json"

    def current() -> Project:
        return state["project"]

    def require_project() -> Project:
        """For everything that edits or measures a track: there has to be one."""
        project = state["project"]
        if project is None:
            raise HTTPException(409, "no track is open")
        return project

    stem_lock = threading.Lock()

    def loaded_stem():
        """(samples, VocalActivity) for the open track, decoded once and kept.

        Every save re-scores against this and the timing audit reads it too.
        About a second and a half to build, so it is started in the background
        the moment a track is opened; the lock is for a save that lands first.
        """
        with stem_lock:
            if state["stem"] is None:
                project = require_project()
                stem = Path(project.stem_path or project.audio_path)
                samples, _ = load_mono(stem, TARGET_SR)
                state["stem"] = (samples, vad.analyse(samples, TARGET_SR))
            return state["stem"]

    def warm_stem() -> None:
        threading.Thread(target=loaded_stem, daemon=True).start()

    def switch_to(target: Path) -> None:
        target = Path(target).resolve()
        if not (target / "project.json").exists():
            raise HTTPException(404, f"no project.json in {target}")
        state["workdir"] = target
        state["project"] = Project.load(target / "project.json")
        state["stem"] = None          # a different stem needs a fresh decode
        warm_stem()

    if opened:
        warm_stem()

    @app.get("/api/project")
    def get_project() -> JSONResponse:
        project = current()
        if project is None:
            return JSONResponse({"empty": True, "root": str(state["root"])})
        return JSONResponse(project.to_dict())

    @app.put("/api/project")
    async def put_project(request: Request) -> JSONResponse:
        """Save the project, scored against the timings it now holds.

        The score is a function of the file, so it is computed on every write
        rather than kept as a snapshot the file then drifts away from; it
        costs milliseconds once the stem is in memory. The project comes back
        so the client can take the fresh scores without touching its history.
        Everything runs off the event loop, so a save does not stall audio
        playback or any other request being served concurrently.
        """
        payload = await request.json()
        project = Project.from_dict(payload)
        state["project"] = project

        def write() -> None:
            try:
                samples, act = loaded_stem()
                pipeline.rescore(project, activity=act, samples=samples)
            except Exception as exc:        # a moved stem must not lose an edit
                print(f"  not re-scored: {exc}")
            exports.write_all(project, wd())

        await run_in_threadpool(write)
        return JSONResponse(project.to_dict())

    @app.post("/api/decisions")
    async def log_decisions(request: Request) -> JSONResponse:
        """Append the reviewer's decisions, each with the word's features.

        Never an error to the client: a decision log that could fail a save
        would be worse than no log. The stem is only decoded if it already is
        - features that need it are left out otherwise, and the record is
        written regardless.
        """
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "written": 0})
        entries = payload if isinstance(payload, list) else [payload]
        project = state["project"]
        if project is None:
            return JSONResponse({"ok": False, "written": 0})
        activity = state["stem"][1] if state["stem"] is not None else None
        audit = project.meta.get("audit")
        written = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                line, word = int(entry.get("line", -1)), int(entry.get("word", -1))
            except (TypeError, ValueError):
                continue
            record = {k: v for k, v in entry.items() if k != "features"}
            record["track"] = wd().name
            record["features"] = decisions.features(project, activity, line, word, audit)
            if decisions.record(wd(), record):
                written += 1
        return JSONResponse({"ok": True, "written": written})

    def find_additions(project, act, samples, dismissed) -> list[dict]:
        """Lines that are sung but missing from the lyrics file.

        The round-trip pass already transcribes the whole stem and keeps what
        no line claimed, so a project aligned since that landed costs nothing
        here. Older projects have only the summary, and the holes get listened
        to directly - a fraction of the track, once, then kept with the project.
        """
        words = None
        saved = roundtrip.RoundTrip.from_dict(project.meta.get("roundtrip"))
        if saved is not None and saved.words:
            words = saved.words
        if not words:
            words = gaps.transcribe_gaps(
                project, samples, activity=act, device=state["device"]
            )
        return [c.to_dict() for c in gaps.find(project, act, words, dismissed)]

    @app.post("/api/audit")
    def run_audit() -> JSONResponse:
        """Repair the provably-wrong, then hand back what still needs an ear.

        The audit lands in `project.meta["audit"]`, so the whole project comes
        back: the repair pass has already edited it.
        """
        project = require_project()
        stem = Path(project.stem_path or project.audio_path)
        if not stem.exists():
            raise HTTPException(404, "no vocal stem for this project")

        samples, act = loaded_stem()
        audit = refine.run(
            project, stem, activity=act, samples=samples, device=state["device"]
        )
        dismissed = {a["id"] for a in audit["additions"]}
        audit["additions"] = find_additions(project, act, samples, dismissed)
        exports.write_all(project, wd())
        return JSONResponse(project.to_dict())

    @app.post("/api/additions")
    async def accept_addition(request: Request) -> JSONResponse:
        """Add a proposed line to the project.

        Insertion renumbers every line after it, and everything keyed by line
        index - the aligners' spans, the round-trip's observations, the audit
        - moves with it inside Project.insert_line. Dismissing a proposal is
        only a flag on it, which the client sets and the next save carries.
        """
        cand = (await request.json()).get("candidate") or {}
        project = require_project()
        after = int(cand["after_line"])
        if not (0 <= after < len(project.lines)):
            raise HTTPException(400, "no such line to insert after")

        project.insert_line(after, gaps.build_line(project, cand))
        at = after + 1

        # The candidate *is* a blind observation of this line - it is the only
        # reason we believe the line is there - so record it as one. Without it
        # the scorer marks the new line as never independently heard, which is
        # the opposite of the truth about it.
        rt = project.meta.get("roundtrip")
        if isinstance(rt, dict) and isinstance(rt.get("per_line"), dict):
            n = len(project.lines[at].words) or 1
            rt["per_line"][str(at)] = {
                "start": round(float(cand["start"]), 3),
                "end": round(float(cand["end"]), 3),
                "matched": n,
                "expected": n,
            }
        audit = project.meta.get("audit")
        if isinstance(audit, dict):
            audit["additions"] = [
                a for a in audit.get("additions", []) if a.get("id") != cand.get("id")
            ]

        exports.write_all(project, wd())
        return JSONResponse({"ok": True, "at": at, "project": project.to_dict()})

    @app.post("/api/export")
    def export() -> JSONResponse:
        written = exports.write_all(require_project(), wd())
        return JSONResponse({k: str(v) for k, v in written.items()})

    @app.get("/api/analysis")
    def get_analysis() -> JSONResponse:
        project = current()
        if project is None:
            return JSONResponse({"empty": True})
        data = analysis.build(
            project.audio_path, project.stem_path or project.audio_path, wd()
        )
        # The UI dropped the mix lane - the mix separates singing from silence by
        # 0.18 sd where the stem manages 1.89 - so half the payload is dead
        # weight on the wire. The cache on disk keeps it in case that changes.
        return JSONResponse({k: v for k, v in data.items() if k != "mix_peaks"})

    # FileResponse answers Range requests itself, streaming from disk, which is
    # what lets the browser seek in the audio.
    @app.get("/media/mix")
    def media_mix() -> FileResponse:
        project = require_project()
        return FileResponse(_preview(Path(project.audio_path), wd() / "mix.m4a"))

    @app.get("/media/vocals")
    def media_vocals() -> FileResponse:
        project = require_project()
        stem = Path(project.stem_path or project.audio_path)
        if not stem.exists():
            raise HTTPException(404, "no vocal stem for this project")
        return FileResponse(_preview(stem, wd() / "vocals.m4a", stereo=False))

    # ------------------------------------------------------------ library

    @app.get("/api/tracks")
    def tracks() -> JSONResponse:
        """Every aligned track under the workdir root, newest first."""
        out = []
        for d in sorted(state["root"].iterdir() if state["root"].exists() else []):
            pf = d / "project.json"
            if not d.is_dir() or not pf.exists():
                continue
            try:
                raw = json.loads(pf.read_text(encoding="utf-8"))
            except Exception:
                continue
            card = raw.get("scorecard") or {}
            out.append({
                "dir": str(d),
                "name": Path(raw.get("audio_path", d.name)).stem,
                "lines": len(raw.get("lines", [])),
                "score": round(card.get("mean_score", 0) or 0),
                "flagged": card.get("n_flagged", 0),
                "active": d.resolve() == wd(),
                "mtime": pf.stat().st_mtime,
            })
        out.sort(key=lambda t: -t["mtime"])
        return JSONResponse(out)

    @app.post("/api/open")
    async def open_track(request: Request) -> JSONResponse:
        payload = await request.json()
        await run_in_threadpool(switch_to, Path(payload["dir"]))
        return JSONResponse({"ok": True, "dir": str(wd())})

    # ------------------------------------------------------------ import

    @app.post("/api/upload")
    async def upload(request: Request) -> JSONResponse:
        """Raw-body upload: the browser POSTs a File as the request body.

        Deliberately not multipart - that would pull in another dependency to
        move two files across localhost.
        """
        name = Path(request.query_params.get("name", "upload")).name
        staging = state["root"] / "_import"
        staging.mkdir(parents=True, exist_ok=True)
        target = staging / name
        body = await request.body()
        if not body:
            raise HTTPException(400, "empty upload")
        await run_in_threadpool(target.write_bytes, body)
        return JSONResponse({"path": str(target), "bytes": len(body)})

    @app.get("/api/import")
    def import_status() -> JSONResponse:
        job = state["job"]
        if not job:
            return JSONResponse({"state": "idle"})
        return JSONResponse({
            "state": job["state"],
            "lines": job["lines"][-40:],
            "dir": job.get("dir"),
            "error": job.get("error"),
        })

    @app.post("/api/import")
    async def start_import(request: Request) -> JSONResponse:
        if state["job"] and state["job"]["state"] == "running":
            raise HTTPException(409, "an import is already running")

        payload = await request.json()
        audio = Path(payload["audio"])
        lyrics = Path(payload["lyrics"])
        for f in (audio, lyrics):
            if not f.exists():
                raise HTTPException(400, f"no such file: {f}")
        if audio.suffix.lower() not in AUDIO_SUFFIXES:
            raise HTTPException(400, f"{audio.suffix} is not an audio file")

        target = state["root"] / slugify(audio.stem)
        job = {"state": "running", "lines": [], "dir": str(target), "error": None}
        state["job"] = job

        def note(message: str) -> None:
            job["lines"].append(str(message))

        def work() -> None:
            try:
                note(f"aligning {audio.name} against {lyrics.name}")
                config = pipeline.Config(device=state["device"])
                project, _ = pipeline.run(
                    audio, lyrics, workdir=target, config=config, progress=note
                )
                exports.write_all(project, target)
                switch_to(target)
                note("done")
                job["state"] = "done"
            except Exception as exc:                      # surfaced in the UI
                job["error"] = f"{type(exc).__name__}: {exc}"
                job["state"] = "failed"
                note(f"failed: {job['error']}")

        threading.Thread(target=work, daemon=True).start()
        return JSONResponse({"ok": True, "dir": str(target)})

    # The UI itself. Mounted last, so every route above still wins.
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
    return app


def serve(
    workdir: Path | str,
    host: str = "127.0.0.1",
    port: int = 8420,
    open_browser: bool = True,
    device: str = "cpu",
) -> None:
    import uvicorn

    app = create_app(workdir, device=device)
    url = f"http://{host}:{port}/"
    print(f"\n  review UI -> {url}\n  (ctrl-c to stop)\n")

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
