"""Gravity in Motion: one body, its satellites, and a field, moved by the song.

    python -m visuals.pieces.gravity listen     stems -> events and streams, cached
    python -m visuals.pieces.gravity models     what small local models hear: notes, chords, mood, lyrics
    python -m visuals.pieces.gravity render     the mp4, and the player's files
    python -m visuals.pieces.gravity measure    decode the mp4 and check it against the audio
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TRACK = "gravity-in-motion"
AUDIO = ROOT / "examples" / "Gravity in Motion.wav"
WORKDIR = ROOT / "workdir" / TRACK
CACHE = ROOT / "visuals" / "cache" / TRACK
STEMS_DIR = CACHE / "demucs_raw" / "htdemucs" / "Gravity in Motion"
MODELS = ROOT / "visuals" / "cache" / "models"      # nmp.onnx lives here; see models.py
OUT = ROOT / "visuals" / "out" / f"{TRACK}-piece"

# Two ways of drawing the same baked channels. "glow" is soft light on black;
# "ink" is the printed, cel-shaded space of github.com/nuterian/forge.
STYLES = ("glow", "ink")


def out_dir(style: str = "glow") -> Path:
    return OUT if style == "glow" else ROOT / "visuals" / "out" / f"{TRACK}-{style}"
