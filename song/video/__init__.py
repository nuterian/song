"""Rendering a finished song to video.

The lyrics are burned in as ASS karaoke - libass sweeps the fill word by word
off the timings this project already has.

    song/video/karaoke.py   project.json -> .ass, stdlib only

The name below resolves lazily for the same reason `song.align` does: karaoke.py
is pure stdlib and the test suite covers it with nothing installed, which an
eager re-export here would quietly take away, because importing any submodule
runs this file first.
"""

__all__ = ["write_ass"]


def __getattr__(name: str):
    if name == "write_ass":
        from .karaoke import write
        return write
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
