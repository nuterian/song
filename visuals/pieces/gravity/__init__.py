"""Gravity in Motion: one body, its satellites, and a field, moved by the song.

    python -m visuals.pieces.gravity listen     stems -> events and streams, cached
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
OUT = ROOT / "visuals" / "out" / f"{TRACK}-piece"
