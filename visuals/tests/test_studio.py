"""The studio: a gesture on the timeline asks for the edit it looks like; an edit is baked
into the bundle the player shows, or turned away with the reason and nothing touched."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import threading
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


def test_an_export_names_one_of_the_three_cameras(session):
    from http.server import ThreadingHTTPServer
    import functools
    from visuals.pieces.gravity import studio

    Handler = studio.handler({session.track.slug: session})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(session.out.parent)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        req = urllib.request.Request(f"{base}/api/export?track={session.track.slug}", method="POST",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps({"camera": "drone", "lyrics": True}).encode())
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 422 and "no camera 'drone'" in json.loads(e.value.read())["refused"][0]
        assert session.exporting is None and not studio.Export.running.locked()      # nothing was started
        where = json.loads(urllib.request.urlopen(f"{base}/api/export?track={session.track.slug}&camera=hybrid&lyrics=0").read())
        assert where["job"] is None and where["path"].endswith(f"{session.track.slug}-hybrid-no-lyrics.mp4")
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
