"""The studio: a gesture on the timeline asks for the edit it looks like; an edit is baked
into the bundle the player shows, or turned away with the reason and nothing touched."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from visuals.pieces.gravity import editor, sheet as sheet_

TIMELINE = Path(__file__).resolve().parents[1] / "studio" / "timeline.js"


def _node(tmp_path, body: str, data: dict):
    (tmp_path / "in.json").write_text(json.dumps(data))
    (tmp_path / "t.mjs").write_text(f"""
import * as tl from {json.dumps(TIMELINE.as_uri())};
import {{ readFileSync }} from "node:fs";
const d = JSON.parse(readFileSync({json.dumps(str(tmp_path / "in.json"))}, "utf8"));
{body}
""")
    return json.loads(subprocess.run(["node", str(tmp_path / "t.mjs")], capture_output=True, text=True, check=True).stdout)


from visuals.tests.test_editor import SHEET, bars   # noqa: E402 - the same small sheet


@pytest.mark.skipif(shutil.which("node") is None, reason="no node to run the page's arithmetic")
def test_dragging_an_edge_moves_only_that_edge(tmp_path):
    acts = SHEET["acts"]
    out = _node(tmp_path, """
console.log(JSON.stringify([
  tl.edgeEdits(d.acts, 4, 110),      // wide|alignment at 116, dragged left: the climax grows
  tl.edgeEdits(d.acts, 4, 120),      // ...dragged right: the wide act takes four bars of it
  tl.edgeEdits(d.acts, 0, 0),        // an act keeps at least a bar
  tl.edgeEdits(d.acts, 2, 77.3),     // back where it was: nothing
]));""", {"acts": acts})
    left, right, least, none = out
    got = bars(editor.apply(SHEET, left)[0]["acts"])
    assert (98, 110, "wide", None) in got and (110, 132, "alignment", None) in got and len(got) == len(acts)
    got = bars(editor.apply(SHEET, right)[0]["acts"])
    assert (98, 120, "wide", None) in got and (120, 132, "alignment", None) in got
    assert bars(editor.apply(SHEET, least)[0]["acts"])[:2] == [(0, 1, "approach", None), (1, 50, "intimate", "earth")]
    assert none == []
    for edits in (left, right, least):
        assert sheet_.validate(editor.apply(SHEET, edits)[0]) == []


@pytest.mark.skipif(shutil.which("node") is None, reason="no node to run the page's arithmetic")
def test_dragging_a_sections_edge(tmp_path):
    out = _node(tmp_path, """
const v1 = d.sections[0];
console.log(JSON.stringify([
  tl.sectionEdgeEdits(v1, "end", 36, 149),     // Verse 1 grows into Chorus 1, which is cut back
  tl.sectionEdgeEdits(v1, "end", 20.2, 149),   // ...or gives up its last six bars
  tl.sectionEdgeEdits(v1, "start", 12, 149),   // ...or starts earlier
  tl.sectionEdgeEdits(v1, "start", 40, 149),   // an edge cannot pass the other
]));""", {"sections": SHEET["heard"]["sections"]})
    grow, shrink, early, most = out
    named = lambda edits: [(x["name"], *x["bars"]) for x in editor.apply(SHEET, edits)[0]["heard"]["sections"]]
    assert named(grow) == [("Verse 1", 17, 36), ("Chorus 1", 36, 50)]
    assert named(shrink) == [("Verse 1", 17, 20), ("Chorus 1", 33, 50)]
    assert named(early) == [("Verse 1", 12, 26), ("Chorus 1", 33, 50)]
    assert named(most) == [("Verse 1", 25, 26), ("Chorus 1", 33, 50)]


@pytest.mark.skipif(shutil.which("node") is None, reason="no node to run the page's arithmetic")
def test_bars_and_moments_on_the_page(tmp_path):
    bar_t = [-0.1 + 2.0 * i for i in range(10)]
    out = _node(tmp_path, """
const m = { bar: 42, strength: 0.35 };
console.log(JSON.stringify({
  there: [0, 1.9, 5.0, 18.5, 19.9, 20.0].map((t) => tl.barOf(d.bar_t, 20.0, t)),
  back: [0, 2.5, 9.5, 10].map((b) => tl.timeOf(d.bar_t, 20.0, b)),
  moved: tl.momentEdits(m, 58.4), stay: tl.momentEdits(m, 41.8),
  changed: tl.changedMoments([{bar: 2, strength: 0.9}, {bar: 42, strength: 0.35}], [{bar: 2, strength: 0.5}, {bar: 58, strength: 0.35}]),
}));""", {"bar_t": bar_t})
    # bar 0 starts a tenth before the song; the last bar runs 2.1 s, to the end of the song
    assert out["there"] == pytest.approx([0.05, 1.0, 2.55, 9 + 0.6 / 2.1, 9 + 2.0 / 2.1, 10])
    assert out["back"] == pytest.approx([0.0, 4.9, 18.95, 20.0])
    s = editor.apply(SHEET, out["moved"])[0]
    assert [(r["bar"], r["strength"]) for r in s["reentries"]] == [(2, 0.9), (58, 0.35)]
    assert out["stay"] == [] and out["changed"] == {"added": [58], "removed": [42], "changed": [2]}


# ---------------------------------------------------------------------------- the server


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    from visuals.pieces.gravity import listen, studio
    from visuals.pieces.gravity.track import Track

    tr = Track.resolve()
    if listen.load_cached(tr.cache) is None:
        pytest.skip("no listening cache for the real track")
    d = tmp_path_factory.mktemp("studio")
    return studio.Session(tr, out_dir=d / "bundle", sheet_path=d / "sheet.json", log_path=d / "edits.jsonl",
                          history_path=d / "history.json")


def test_the_page_is_told_the_song_and_the_words_to_edit_it_in(session):
    song = session.song()
    assert len(song["bar_t"]) == song["sheet"]["song"]["bars"] == 149 and len(song["beats"]) >= 4 * 148
    assert {"name": "Chorus 2", "bars": [81, 90]} in song["sheet"]["heard"]["sections"]
    assert len(song["energy"]) == 149 and set(song["energy"]) <= {"drive", "float", "void", "silent"}
    assert len(song["lines"]) == 34 and song["lines"][0]["text"].startswith("Light breaks")
    assert set(song["vocabulary"]["shots"]) == set(sheet_.SHOTS) and set(song["vocabulary"]["parts"]) == set(sheet_.PARTS)
    assert (session.out / "plan.json").exists() and (session.out / "frames.bin").exists()


def test_an_edit_is_baked_kept_and_logged_and_undone(session):
    before = copy.deepcopy(session.sheet)
    frames = (session.out / "frames.bin").read_bytes()
    r = session.edit([{"op": "feel", "dial": "flares_every_bars", "value": 6.0}])
    assert r["ok"] and r["changed"] and r["did"] == ["flares_every_bars = 6.0"] and r["version"] == 1
    assert (session.out / "frames.bin").read_bytes() != frames                  # the player gets a new bake
    assert sheet_.read(session.sheet_path)["feel"]["flares_every_bars"] == 6.0  # and it is kept
    logged = [json.loads(x) for x in session.log_path.read_text().splitlines()]
    assert logged[-1]["source"] == "hand" and logged[-1]["edits"][0]["dial"] == "flares_every_bars"
    r = session.replace(before)
    assert r["ok"] and session.sheet == before and (session.out / "frames.bin").read_bytes() == frames


def test_an_edit_that_means_nothing_touches_nothing(session):
    version, sheet = session.version, copy.deepcopy(session.sheet)
    r = session.edit([{"op": "feel", "dial": "orbits_breathe", "value": 9.0}])
    assert not r["ok"] and any("outside" in x for x in r["refused"])
    assert session.version == version and session.sheet == sheet
    r = session.edit([{"op": "cast", "part": "heart", "choice": "voice"}])        # already so
    assert r["ok"] and not r["changed"] and session.version == version


def test_the_server_answers_the_page(session):
    from http.server import ThreadingHTTPServer
    import functools
    from visuals.pieces.gravity import studio

    Handler = studio.handler({session.track.slug: session})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(session.out.parent)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        song = json.loads(urllib.request.urlopen(f"{base}/api/song?track={session.track.slug}").read())
        assert song["slug"] == session.track.slug
        req = urllib.request.Request(f"{base}/api/edit", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"edits": [{"op": "shot", "bars": [20, 30], "shot": "eclipse", "subject": "none"}]}).encode())
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 422 and "needs a subject" in json.loads(e.value.read())["refused"][0]
    finally:
        httpd.shutdown()


def test_every_change_is_one_history_to_move_along(session):
    from visuals.pieces.gravity import studio

    start = session.at
    r = session.edit([{"op": "feel", "dial": "orbits_breathe", "value": 1.0}])
    assert r["at"] == start + 1 and r["history"][-1]["source"] == "hand"
    assert r["history"][-1]["changes"] == [{"kind": "feel", "title": "Orbits breathe", "before": "0.55", "after": "1"}]
    r = session.edit([{"op": "section", "bars": [50, 66], "name": "Drop"}], source="ask", request="call the drop the drop")
    assert r["history"][-1]["request"] == "call the drop the drop" and r["history"][-1]["changes"][0]["after"] == "Drop"
    r = session.goto(start)                                       # back to where it began, two steps
    assert r["ok"] and session.sheet["feel"]["orbits_breathe"] == 0.55 and len(r["history"]) == start + 3
    r = session.goto(start + 2)                                   # and forward again
    assert session.sheet["feel"]["orbits_breathe"] == 1.0 and any(x["name"] == "Drop" for x in session.sheet["heard"]["sections"])
    # the history is kept with the song: opened again, it is all there, and where it was
    again = studio.Session(session.track, out_dir=session.out, sheet_path=session.sheet_path,
                           log_path=session.log_path, history_path=session.history_path)
    assert again.at == session.at and [h["changes"] for h in again.history] == [h["changes"] for h in session.history]
    session.goto(start + 1)
    r = session.edit([{"op": "feel", "dial": "flares_every_bars", "value": 4.0}])   # a change after an undo
    assert len(r["history"]) == start + 3 and r["history"][-1]["changes"][0]["title"] == "Flares"
    session.goto(start)


# ---------------------------------------------------------------------------- adding songs


def _wait(jobs, until, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        view = jobs.view()
        if until(view):
            return view
        time.sleep(0.02)
    raise AssertionError(f"the jobs never got there: {jobs.view()}")


def test_jobs_run_one_at_a_time_in_order_and_say_where_they_are():
    from visuals.pieces.gravity import studio

    jobs, ran = studio.Jobs(), []

    def slow(name):
        def fn(step):
            ran.append((name, "in", time.time()))
            step("first")
            print(f"{name} is working")
            time.sleep(0.15)
            step("second")
            time.sleep(0.05)
            ran.append((name, "out", time.time()))
        return fn

    def broken(step):
        step("only")
        raise SystemExit("no audio at nowhere.wav")

    a = jobs.start("import", "a", slow("a"))
    b = jobs.start("export", "b", slow("b"))
    c = jobs.start("import", "c", broken)
    assert (a["id"], b["id"], c["id"]) == (1, 2, 3) and b["state"] == "queued" and c["step"] == "waiting"
    view = _wait(jobs, lambda v: v[0]["state"] == "running" and v[0]["step"] == "first")
    assert view[1]["state"] == "queued" and jobs.pending("b") and not jobs.pending("z")
    view = _wait(jobs, lambda v: all(j["state"] in ("done", "failed") for j in v))
    assert [j["state"] for j in view] == ["done", "done", "failed"]
    at = {(n, w): t for n, w, t in ran}
    assert at[("b", "in")] >= at[("a", "out")]                       # one at a time: b began after a ended
    first = view[0]
    assert "a is working" in first["log"] and [s["name"] for s in first["steps"]] == ["first", "second"]
    assert first["steps"][0]["seconds"] >= 0.15 and first["seconds"] >= 0.2 and first["started"] > 0
    assert view[2]["error"] == "no audio at nowhere.wav" and view[2]["steps"][0]["seconds"] is not None
    assert not jobs.pending("a")


def _post(url, fields):
    """A multipart/form-data POST, as the page's FormData sends one."""
    boundary = "----studio-test"
    body = b""
    for name, (filename, data) in fields.items():
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_a_song_is_refused_when_it_is_not_audio_or_is_in_the_studio_already(tmp_path):
    from http.server import ThreadingHTTPServer
    import functools
    from visuals.pieces.gravity import studio

    jobs = studio.Jobs()
    sessions = {"rise-and-glow": object()}             # in the studio: only its name is looked at
    Handler = studio.handler(sessions, jobs)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(tmp_path)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, r = _post(f"{base}/api/import", {"audio": ("notes.pdf", b"%PDF-1.4")})
        assert status == 415 and not r["ok"] and "not audio" in r["refused"][0]
        status, r = _post(f"{base}/api/import", {"audio": ("Some Song.wav", b"RIFF"), "lyrics": ("words.docx", b"PK")})
        assert status == 415 and ".txt" in r["refused"][0]
        status, r = _post(f"{base}/api/import", {"audio": ("Rise and Glow.wav", b"RIFF....WAVE")})
        assert status == 409 and r["refused"] == ["Rise and Glow is already in the studio"]
        status, r = _post(f"{base}/api/import", {"lyrics": ("words.txt", b"la la")})
        assert status == 400
        assert json.loads(urllib.request.urlopen(f"{base}/api/jobs").read()) == {"jobs": []}   # nothing started
    finally:
        httpd.shutdown()


def test_the_form_the_page_sends_is_read_byte_for_byte():
    from visuals.pieces.gravity import studio

    audio = bytes(range(256)) * 4 + b"\r\n--not-the-boundary\r\n\r\n"
    body = (b'--XyZ\r\nContent-Disposition: form-data; name="audio"; filename="R\xc3\xaave.wav"\r\n'
            b"Content-Type: audio/wav\r\n\r\n" + audio + b"\r\n"
            b'--XyZ\r\nContent-Disposition: form-data; name="lyrics"; filename="words.txt"\r\n\r\nla la\n\r\n--XyZ--\r\n')
    got = studio.multipart(body, "multipart/form-data; boundary=XyZ")
    assert got == {"audio": ("Rêve.wav", audio), "lyrics": ("words.txt", b"la la\n")}
    assert studio.multipart(body, "application/json") == {}


def test_with_no_songs_named_every_song_prepared_is_offered(tmp_path):
    from visuals.pieces.gravity import studio

    cache, examples, workdirs = tmp_path / "cache", tmp_path / "examples", tmp_path / "workdir"
    for slug, files in {
        "copied-in": ["listen.json", "source.wav"],            # a lossless song from outside, copied in
        "decoded": ["listen.json", "audio.wav", "source.mp3"],   # a lossy one: its decode is what is read
        "from-examples": ["listen.json"],                       # the repository's own song, not copied
        "from-workdir": ["listen.json"],                        # known by its song workdir
        "nowhere": ["listen.json"],                             # listened to, but its audio is gone
        "half-made": ["source.wav"],                            # not listened to yet
        "models": ["nmp.onnx"],                                 # not a song
    }.items():
        (cache / slug).mkdir(parents=True)
        for f in files:
            (cache / slug / f).write_bytes(b"x")
    examples.mkdir()
    (examples / "From Examples.wav").write_bytes(b"x")
    (workdirs / "from-workdir").mkdir(parents=True)
    (tmp_path / "wd.flac").write_bytes(b"x")
    (workdirs / "from-workdir" / "project.json").write_text(json.dumps({"audio_path": str(tmp_path / "wd.flac")}))
    got = {t.slug: t for t in studio.prepared(cache, (examples,), workdirs)}
    assert sorted(got) == ["copied-in", "decoded", "from-examples", "from-workdir"]
    assert got["copied-in"].source == cache / "copied-in" / "source.wav" and got["copied-in"].workdir is None
    assert got["decoded"].source.name == "source.mp3" and got["decoded"].audio.name == "audio.wav"
    assert got["from-examples"].source == examples / "From Examples.wav"
    assert got["from-workdir"].source == tmp_path / "wd.flac" and got["from-workdir"].workdir == workdirs / "from-workdir"


def test_a_song_opened_from_its_copy_finds_the_stems_named_for_the_original(tmp_path, monkeypatch):
    from visuals.pieces.gravity import track as track_

    monkeypatch.setattr(track_, "ROOT", tmp_path)
    cache = tmp_path / "visuals" / "cache" / "rise-and-glow"
    (cache / "demucs_raw" / "htdemucs" / "Rise and Glow").mkdir(parents=True)
    tr = track_.Track("rise-and-glow", cache / "source.wav")
    assert tr.audio == cache / "source.wav" and tr.stems_dir.name == "Rise and Glow"
