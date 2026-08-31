"""Turning an audio file and a lyrics file into timed lines.

Three passes cross-examine each other - a CTC anchor, a Whisper refinement and
a blind transcription that adjudicates - and everything is scored from evidence
rather than against a reference. `pipeline.run` is the whole of it.
"""

from .pipeline import Config, run  # noqa: F401
