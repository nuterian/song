"""Gravity in Motion: one body, its satellites, and a field, moved by the song.

It was directed by hand for one song; it now takes any (`track.py`), and that song is
the default:

    python -m visuals make <audio file | song workdir> --theme cosmos     everything, up to the player
    python -m visuals.pieces.gravity [--track PATH] listen     stems -> events and streams, cached
    python -m visuals.pieces.gravity [--track PATH] models     what small local models hear: notes, chords, mood, lyrics
    python -m visuals.pieces.gravity [--track PATH] render     the mp4, and the player's files
    python -m visuals.pieces.gravity [--track PATH] measure    decode the mp4 and check it against the audio
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "visuals" / "cache" / "models"      # nmp.onnx lives here; see models.py

# Two ways of drawing the same baked channels. "glow" is soft light on black;
# "ink" is the flat cel-shaded system seen from one fixed angle; "cosmos" is the solar
# system in three dimensions - real planets, the real sky - through a moving camera.
STYLES = ("glow", "ink", "cosmos")
