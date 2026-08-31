"""Rendering a finished song to video.

The lyrics are burned in as ASS karaoke - libass sweeps the fill word by word
off the timings this project already has - over visuals generated from the same
analysis the review UI draws: the mix envelope, the vocal envelope, the tracked
beat and the section list. No supplied footage and no still image; the picture
moves on the structure the words do.

    song/video/beats.py     tempo, beats and downbeats, cached like analysis.json
    song/video/karaoke.py   project.json -> .ass, stdlib only
    song/video/scene.py     the generated frames
    song/video/render.py    scale, burn, mux - one ffmpeg process

The names below resolve lazily for the same reason `song.align` does: karaoke.py
is pure stdlib and the test suite covers it with nothing installed, which an
eager `from .render import run` here would quietly take away, because
importing any submodule runs this file first.
"""

__all__ = ["run", "write_ass"]


def __getattr__(name: str):
    if name == "run":
        from .render import run
        return run
    if name == "write_ass":
        from .karaoke import write
        return write
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
