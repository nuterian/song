"""Which song, and where its derived files go. Paths only: nothing here decodes or separates."""

from __future__ import annotations

import json

import pytest

from visuals.pieces.gravity import ROOT
from visuals.pieces.gravity.track import GRAVITY_AUDIO, Track, slugify


def test_the_slug_is_the_song_tools():
    assert slugify("Gravity in Motion") == "gravity-in-motion"
    assert slugify("TIDAL CORE") == "tidal-core"
    assert slugify("Shattered  Voices (live) - edit") == "shattered-voices-live-edit"
    assert slugify("Café Déjà vu!") == "cafe-deja-vu"
    assert slugify("???") == "track"


def test_the_default_is_the_gravity_piece_where_it_always_was():
    """Nothing about the gold example moved: same cache, same stems, same bundles."""
    if not GRAVITY_AUDIO.exists():
        pytest.skip("no Gravity in Motion.wav")
    t = Track.resolve()
    assert t.slug == "gravity-in-motion"
    assert t.audio == GRAVITY_AUDIO
    assert t.cache == ROOT / "visuals" / "cache" / "gravity-in-motion"
    assert t.stems_dir == t.cache / "demucs_raw" / "htdemucs" / "Gravity in Motion"
    assert t.out("glow").name == "gravity-in-motion-piece"
    assert t.out("cosmos").name == "gravity-in-motion-cosmos"
    if (ROOT / "workdir" / "gravity-in-motion" / "project.json").exists():
        assert t.workdir == ROOT / "workdir" / "gravity-in-motion"
        assert t.mix_m4a == t.workdir / "mix.m4a"
        # and its song workdir names the same track
        w = Track.resolve(ROOT / "workdir" / "gravity-in-motion")
        assert (w.slug, w.audio, w.cache) == (t.slug, t.audio, t.cache)


def test_a_lossy_file_is_read_through_one_decode_in_the_cache(tmp_path):
    mp3 = tmp_path / "TIDAL CORE.mp3"
    mp3.write_bytes(b"")
    t = Track.resolve(mp3)
    assert t.slug == "tidal-core" and t.source == mp3
    assert t.audio == t.cache / "audio.wav"
    assert t.stems_dir == t.cache / "demucs_raw" / "htdemucs" / "audio"
    wav = tmp_path / "Shattered Voices.wav"
    wav.write_bytes(b"")
    t = Track.resolve(wav)                  # lossless, but from outside the repository: read from a copy
    assert t.audio == t.cache / "source.wav"


def test_audio_from_outside_is_copied_in_and_the_copy_is_read(tmp_path, monkeypatch):
    from visuals.pieces.gravity import track as track_

    monkeypatch.setattr(Track, "cache", property(lambda self: tmp_path / "cache" / self.slug))
    wav = tmp_path / "Far Away.wav"
    wav.write_bytes(b"RIFF....")
    t = Track.resolve(wav)
    monkeypatch.setattr(track_, "separate", lambda track, say: None)
    monkeypatch.setattr(track_, "_ffmpeg", lambda *a: None)
    track_.prepare(t, say=lambda *a: None)
    assert t.audio.read_bytes() == b"RIFF...." and t.audio.parent == t.cache
    # stems made before the copy existed keep their folder, named for the source
    (t.cache / "demucs_raw" / "htdemucs" / "Far Away").mkdir(parents=True)
    assert t.stems_dir.name == "Far Away"


def test_a_track_with_no_song_workdir_has_no_lyrics_and_its_own_mix(tmp_path):
    wav = tmp_path / "zz no such song here.wav"
    wav.write_bytes(b"")
    t = Track.resolve(wav)
    assert t.workdir is None and t.project is None
    assert t.mix_m4a == t.cache / "mix.m4a"


def test_a_workdir_finds_its_audio_or_says_how_to_name_it(tmp_path):
    wd = tmp_path / "my-song"
    wd.mkdir()
    (wd / "project.json").write_text(json.dumps({"audio_path": str(tmp_path / "gone.wav")}))
    with pytest.raises(SystemExit, match="--audio"):
        Track.resolve(wd)
    (tmp_path / "gone.wav").write_bytes(b"")
    t = Track.resolve(wd)
    assert t.slug == "my-song" and t.workdir == wd and t.project == wd / "project.json"
    other = tmp_path / "elsewhere.flac"
    other.write_bytes(b"")
    assert Track.resolve(wd, audio=other).source == other


def test_what_is_not_audio_is_refused(tmp_path):
    txt = tmp_path / "lyrics.txt"
    txt.write_text("la la")
    with pytest.raises(SystemExit, match="not an audio file"):
        Track.resolve(txt)
    with pytest.raises(SystemExit, match="no such file"):
        Track.resolve(tmp_path / "missing.wav")
    with pytest.raises(SystemExit, match="not a song workdir"):
        Track.resolve(tmp_path)
