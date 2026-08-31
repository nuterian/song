"""FastAPI backend for the review UI."""

from __future__ import annotations

import json
import mimetypes
import subprocess
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from . import analysis, exports, vad
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


def _ranged(path: Path, request: Request) -> Response:
    """Serve a file with HTTP Range support so audio seeking works."""
    size = path.stat().st_size
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    range_header = request.headers.get("range")

    if not range_header or not range_header.startswith("bytes="):
        return FileResponse(path, media_type=media_type)

    raw = range_header.removeprefix("bytes=").split("-", 1)
    start = int(raw[0]) if raw[0] else 0
    end = int(raw[1]) if len(raw) > 1 and raw[1] else size - 1
    start = max(0, min(start, size - 1))
    end = max(start, min(end, size - 1))

    with path.open("rb") as fh:
        fh.seek(start)
        chunk = fh.read(end - start + 1)

    return Response(
        content=chunk,
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(chunk)),
        },
    )


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

    def audit_file() -> Path:
        return wd() / "audit.json"

    def current() -> Project:
        return state["project"]

    def require_project() -> Project:
        """For everything that edits or measures a track: there has to be one."""
        project = state["project"]
        if project is None:
            raise HTTPException(409, "no track is open")
        return project

    def loaded_stem():
        # Callers are all behind require_project(); this is the belt.
        """(samples, VocalActivity) for the open track, decoded once and kept.

        Re-score and the timing audit both need this; before this cache carried
        the samples too, each one re-ran ffmpeg and re-decoded the stem on every
        click even though the exact same array was already sitting in memory.
        """
        if state["stem"] is None:
            stem = Path(require_project().stem_path or require_project().audio_path)
            samples, _ = load_mono(stem, TARGET_SR)
            state["stem"] = (samples, vad.analyse(samples, TARGET_SR))
        return state["stem"]

    def switch_to(target: Path) -> None:
        target = Path(target).resolve()
        if not (target / "project.json").exists():
            raise HTTPException(404, f"no project.json in {target}")
        state["workdir"] = target
        state["project"] = Project.load(target / "project.json")
        state["stem"] = None          # a different stem needs a fresh decode

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (UI_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/app.js")
    def app_js() -> Response:
        return Response(
            (UI_DIR / "app.js").read_text(encoding="utf-8"),
            media_type="application/javascript",
        )

    @app.get("/styles.css")
    def styles() -> Response:
        return Response(
            (UI_DIR / "styles.css").read_text(encoding="utf-8"), media_type="text/css"
        )

    @app.get("/api/project")
    def get_project() -> JSONResponse:
        project = current()
        if project is None:
            return JSONResponse({"empty": True, "root": str(state["root"])})
        return JSONResponse(project.to_dict())

    @app.put("/api/project")
    async def put_project(request: Request) -> JSONResponse:
        payload = await request.json()
        project = Project.from_dict(payload)
        state["project"] = project
        # write_all() already saves project.json as one of its five outputs, so
        # saving it again first was a pure duplicate write. The disk I/O for all
        # five files runs off the event loop, so a Save does not stall audio
        # playback or any other request being served concurrently.
        await run_in_threadpool(exports.write_all, project, wd())
        return JSONResponse({"ok": True, "saved": str(project_file())})

    @app.post("/api/rescore")
    def rescore() -> JSONResponse:
        project = require_project()
        samples, act = loaded_stem()
        card = pipeline.rescore(project, activity=act, samples=samples)
        project.save(project_file())
        return JSONResponse(card.to_dict())

    @app.get("/api/audit")
    def get_audit() -> JSONResponse:
        if audit_file().exists():
            return JSONResponse(json.loads(audit_file().read_text(encoding="utf-8")))
        return JSONResponse({"queue": [], "repairs": [], "never_run": True})

    def saved_audit() -> dict:
        if audit_file().exists():
            return json.loads(audit_file().read_text(encoding="utf-8"))
        return {}

    def find_additions(project, act, samples, dismissed) -> list[dict]:
        """Lines that are sung but missing from the lyrics file.

        The round-trip pass already transcribes the whole stem and keeps what
        no line claimed, so a project aligned since that landed costs nothing
        here. Older projects have only the summary, and the holes get listened
        to directly - a fraction of the track, once, then cached in audit.json.
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
        """Repair the provably-wrong, then hand back what still needs an ear."""
        project = require_project()
        stem = Path(project.stem_path or project.audio_path)
        if not stem.exists():
            raise HTTPException(404, "no vocal stem for this project")

        samples, act = loaded_stem()
        result = refine.run(
            project, stem, activity=act, samples=samples, device=state["device"]
        )
        # Dismissals are the user's judgement and outlive a re-run of the audit.
        previous = saved_audit()
        dismissed = {
            a["id"] for a in previous.get("additions", []) if a.get("dismissed")
        }
        result["additions"] = find_additions(project, act, samples, dismissed)
        # write_all() already saves project.json; an explicit save here duplicated it.
        exports.write_all(project, wd())
        audit_file().write_text(json.dumps(result, indent=1), encoding="utf-8")
        return JSONResponse(result)

    @app.post("/api/additions")
    async def decide_addition(request: Request) -> JSONResponse:
        """Add a proposed line to the project, or dismiss it for good.

        Insertion renumbers every line after it, and the review queue, the todo
        marks and the line proposals are all keyed by line index - so the cached
        audit is shifted here, in the same breath, rather than left to rot until
        something reads the wrong lyric.
        """
        body = await request.json()
        action = body.get("action")
        cand = body.get("candidate") or {}
        audit = saved_audit()
        additions = audit.get("additions", [])

        if action == "dismiss":
            for a in additions:
                if a.get("id") == cand.get("id"):
                    a["dismissed"] = True
            audit["additions"] = additions
            audit_file().write_text(json.dumps(audit, indent=1), encoding="utf-8")
            return JSONResponse({"ok": True, "audit": audit})

        if action != "accept":
            raise HTTPException(400, "action must be 'accept' or 'dismiss'")

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

        def shift(i: int) -> int:
            return i + 1 if i >= at else i

        for item in audit.get("queue", []):
            item["line"] = shift(int(item["line"]))
        audit["line_proposals"] = {
            str(shift(int(k))): v
            for k, v in (audit.get("line_proposals") or {}).items()
        }
        audit["additions"] = [
            {**a, "after_line": shift(int(a["after_line"]))}
            for a in additions
            if a.get("id") != cand.get("id")
        ]

        exports.write_all(project, wd())
        audit_file().write_text(json.dumps(audit, indent=1), encoding="utf-8")
        return JSONResponse(
            {"ok": True, "at": at, "project": project.to_dict(), "audit": audit}
        )

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

    @app.get("/media/mix")
    def media_mix(request: Request) -> Response:
        project = require_project()
        return _ranged(_preview(Path(project.audio_path), wd() / "mix.m4a"), request)

    @app.get("/media/vocals")
    def media_vocals(request: Request) -> Response:
        project = require_project()
        stem = Path(project.stem_path or project.audio_path)
        if not stem.exists():
            raise HTTPException(404, "no vocal stem for this project")
        return _ranged(_preview(stem, wd() / "vocals.m4a", stereo=False), request)

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
