"""Turning an audio file and a lyrics file into timed lines.

Three passes cross-examine each other - a CTC anchor, a Whisper refinement and
a blind transcription that adjudicates - and everything is scored from evidence
rather than against a reference. `pipeline.run` is the whole of it.

The convenience names below are resolved lazily on purpose. Half of this
package is pure stdlib - mapping, gaps and the parsing they lean on - and the
test suite covers it without installing anything. An eager
`from .pipeline import run` here would make `import song.align.mapping` pull in
numpy, torch and demucs, which is a real cost for a leaf import and cost the
test run its whole point. CI caught it by failing on exactly that.
"""

__all__ = ["Config", "run"]


def __getattr__(name: str):
    if name in __all__:
        from . import pipeline
        return getattr(pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
