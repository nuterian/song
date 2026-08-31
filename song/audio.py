"""Small audio helpers shared by the aligners and the scorer."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

# Both Whisper and the wav2vec2 CTC bundle operate at 16 kHz mono.
TARGET_SR = 16000


def probe_duration(path: Path | str) -> float:
    """Duration in seconds, via libsndfile with an ffprobe fallback for mp3."""
    try:
        info = sf.info(str(path))
        if info.frames > 0:
            return info.frames / float(info.samplerate)
    except Exception:
        pass

    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def load_mono(path: Path | str, sr: int = TARGET_SR) -> tuple[np.ndarray, int]:
    """Decode any audio file to a mono float32 array at `sr`.

    Routed through ffmpeg so mp3/m4a work without extra Python codecs.
    """
    out = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error",
            "-i", str(path),
            "-f", "f32le", "-ac", "1", "-ar", str(sr),
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(out.stdout, dtype=np.float32).copy(), sr


def write_wav(path: Path | str, samples: np.ndarray, sr: int) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), samples, sr)
    return path


def ensure_16k_mono_wav(src: Path | str, dst: Path | str) -> Path:
    """Materialize a 16 kHz mono wav, reusing it if already present."""
    dst = Path(dst)
    if dst.exists():
        return dst
    samples, sr = load_mono(src, TARGET_SR)
    return write_wav(dst, samples, sr)


def rms_envelope(
    samples: np.ndarray, sr: int, hop_seconds: float = 0.01
) -> tuple[np.ndarray, float]:
    """Frame-wise RMS energy. Returns (envelope, seconds_per_frame)."""
    hop = max(1, int(sr * hop_seconds))
    frame = hop * 2
    if len(samples) < frame:
        return np.zeros(1, dtype=np.float32), hop_seconds

    n_frames = 1 + (len(samples) - frame) // hop
    strided = np.lib.stride_tricks.as_strided(
        samples,
        shape=(n_frames, frame),
        strides=(samples.strides[0] * hop, samples.strides[0]),
    )
    env = np.sqrt(np.mean(strided.astype(np.float64) ** 2, axis=1)).astype(np.float32)
    return env, hop / sr
