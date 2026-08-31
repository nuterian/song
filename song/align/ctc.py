"""Second-opinion aligner: wav2vec2 CTC forced alignment (torchaudio MMS_FA).

This is deliberately a different model family from Whisper - different training
data, different objective, different failure modes. Where the two agree, the
timing is almost certainly right; where they disagree, a human should look.
That disagreement is the backbone of the benchmark in `score.py`.

Long tracks are handled by computing CTC emissions in chunks and then running a
single global Viterbi alignment over the concatenated emissions, so the
alignment itself never loses the long-range ordering that makes repeated
choruses resolve correctly.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .whisper import LineTiming, _assemble
from ..audio import TARGET_SR, load_mono
from ..project import Word

# wav2vec2 feature extractor stride: one frame per 320 samples (20 ms at 16 kHz).
FRAME_STRIDE = 320
FRAME_CENTER = 200
CHUNK_SECONDS = 30.0

_BUNDLE_CACHE: dict[str, tuple] = {}


def _load_bundle(device: str = "cpu"):
    if device not in _BUNDLE_CACHE:
        import torch
        import torchaudio

        bundle = torchaudio.pipelines.MMS_FA
        model = bundle.get_model(with_star=False).to(torch.device(device)).eval()
        tokenizer = bundle.get_tokenizer()
        vocab = bundle.get_dict(star=None)
        _BUNDLE_CACHE[device] = (bundle, model, tokenizer, set(vocab))
    return _BUNDLE_CACHE[device]


def normalize_word(word: str, vocab: set[str]) -> str:
    """Reduce a lyric word to characters the MMS_FA dictionary knows."""
    word = word.lower().replace("’", "'")
    word = re.sub(r"[^a-z']", "", word)
    return "".join(c for c in word if c in vocab)


def _emissions(samples: np.ndarray, model, device: str):
    """Chunked CTC emissions plus the absolute time of every frame."""
    import torch

    chunk = int(CHUNK_SECONDS * TARGET_SR)
    parts, times = [], []

    with torch.inference_mode():
        for offset in range(0, len(samples), chunk):
            block = samples[offset : offset + chunk]
            # A block shorter than the conv receptive field yields no frames.
            if len(block) < FRAME_STRIDE * 4:
                continue
            wave = torch.from_numpy(block).unsqueeze(0).to(torch.device(device))
            emission, _ = model(wave)
            emission = emission[0].cpu()
            parts.append(emission)

            n_frames = emission.shape[0]
            frame_index = np.arange(n_frames, dtype=np.float64)
            times.append((offset + frame_index * FRAME_STRIDE + FRAME_CENTER) / TARGET_SR)

    if not parts:
        raise RuntimeError("audio too short for CTC alignment")

    return torch.cat(parts, dim=0), np.concatenate(times)


def _unflatten(spans: list, lengths: list[int]) -> list[list]:
    out, cursor = [], 0
    for n in lengths:
        out.append(spans[cursor : cursor + n])
        cursor += n
    return out


def align_lines_ctc(
    audio: Path | str | np.ndarray,
    line_texts: list[str],
    line_indices: list[int] | None = None,
    device: str = "cpu",
    offset: float = 0.0,
) -> list[LineTiming]:
    """Force-align `line_texts` against `audio` with wav2vec2 CTC."""
    import torch
    import torchaudio.functional as AF

    from ..parse_lyrics import tokenize

    if not line_texts:
        return []
    if line_indices is None:
        line_indices = list(range(len(line_texts)))

    if not isinstance(audio, np.ndarray):
        audio, _ = load_mono(audio, TARGET_SR)
    audio = np.asarray(audio, dtype=np.float32)

    _, model, tokenizer, vocab = _load_bundle(device)

    # Keep the surface form for line mapping, align on the normalized form.
    surface: list[str] = []
    normalized: list[str] = []
    for text in line_texts:
        for raw in tokenize(text):
            clean = normalize_word(raw, vocab)
            if clean:
                surface.append(raw)
                normalized.append(clean)

    if not normalized:
        return [
            LineTiming(line_index=i, start=0.0, end=0.0) for i in line_indices
        ]

    emission, frame_times = _emissions(audio, model, device)

    token_lists = tokenizer(normalized)
    flat = [t for word in token_lists for t in word]
    targets = torch.tensor([flat], dtype=torch.int32)

    if emission.shape[0] <= len(flat):
        raise RuntimeError(
            f"audio too short ({emission.shape[0]} frames) for {len(flat)} tokens"
        )

    alignments, scores = AF.forced_align(
        emission.unsqueeze(0).float(), targets, blank=0
    )
    token_spans = AF.merge_tokens(alignments[0], scores[0].exp())
    per_word = _unflatten(token_spans, [len(t) for t in token_lists])

    last_frame = len(frame_times) - 1
    words: list[Word] = []
    for text, spans in zip(surface, per_word):
        if not spans:
            continue
        start_frame = min(max(spans[0].start, 0), last_frame)
        end_frame = min(max(spans[-1].end, 0), last_frame)
        probs = [float(s.score) for s in spans]
        words.append(
            Word(
                text=text,
                start=float(frame_times[start_frame]) + offset,
                end=float(frame_times[end_frame]) + offset,
                prob=float(np.mean(probs)) if probs else 0.0,
            )
        )

    return _assemble(words, line_texts, line_indices)
