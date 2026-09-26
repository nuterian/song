"""What small local models hear that arithmetic on the stems does not.

DSP on stems says *when* to the millisecond and says nothing about *what*. These
say what: which note, which chord, which key, what the passage feels like, what a
lyric is about. None of them is trusted for timing - a model frame is 10 to 20 ms
wide - so wherever a model names something that `listen` has an attack for, the
attack's time is used and the model's label is attached to it.

All permissively licensed, all local, all small:

    Beat This!        MIT          beats and downbeats, as an independent check
    basic-pitch       Apache-2.0   notes, from the synth stem and the bass stem
    SwiftF0           MIT          the sung melody
    lv-chordia        MIT          chords
    larger_clap_music Apache-2.0   what each passage sounds like, against words
    all-MiniLM-L6-v2  Apache-2.0   what each lyric line is about, against words

Results are cached in `models.npz` / `models.json` beside the listening cache.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import ndimage, signal

VERSION = 2          # 2: the synths' lead line, for the heart when nothing sings

# ------------------------------------------------------------------ basic-pitch

BP_SR = 22050
BP_HOP = 256
BP_WINDOW = 43844                  # samples the network takes at once
BP_OVERLAP_FRAMES = 30
BP_FRAMES = 172                    # frames it gives back for that
BP_MIDI_LOW = 21                   # its 88 bins are the piano: A0 upward


# basic-pitch's pip package stops at Python 3.11, so only its network is fetched: the
# file its v0.4.0 release ships, checked against the hash of that file.
BP_URL = ("https://raw.githubusercontent.com/spotify/basic-pitch/v0.4.0/"
          "basic_pitch/saved_models/icassp_2022/nmp.onnx")
BP_SHA256 = "2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec"


def basic_pitch_model(model_dir: Path) -> Path:
    """nmp.onnx in `model_dir`, fetched the first time (230 KB)."""
    import hashlib
    import urllib.request

    path = model_dir / "nmp.onnx"
    if path.exists():
        return path
    model_dir.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(BP_URL, timeout=60) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != BP_SHA256:
        raise RuntimeError(f"{BP_URL} is not the file basic-pitch v0.4.0 shipped (sha256 differs)")
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def _resample(x: np.ndarray, sr: int, to: int) -> np.ndarray:
    g = np.gcd(sr, to)
    return signal.resample_poly(x, to // g, sr // g).astype(np.float32)


def basic_pitch_activations(x: np.ndarray, sr: int, model_path: Path) -> dict[str, np.ndarray]:
    """Run nmp.onnx over a whole stem. Returns note and onset posteriors, (frames, 88).

    The windowing is basic-pitch's own: windows overlap by thirty frames, the audio
    is padded by half of that in front, and half of the overlap is dropped from each
    end of each window's output, so the pieces butt together.
    """
    import onnxruntime as ort

    y = _resample(x, sr, BP_SR)
    n_orig = len(y)
    overlap = BP_OVERLAP_FRAMES * BP_HOP
    hop = BP_WINDOW - overlap
    y = np.concatenate([np.zeros(overlap // 2, np.float32), y])
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    outs = {o.shape[-1]: [] for o in sess.get_outputs()}
    by_name = [o.name for o in sess.get_outputs()]
    notes, onsets = [], []
    for i in range(0, len(y), hop):
        w = y[i:i + BP_WINDOW]
        if len(w) < BP_WINDOW:
            w = np.pad(w, (0, BP_WINDOW - len(w)))
        res = dict(zip(by_name, sess.run(None, {name: w[None, :, None]})))
        # :1 is the note posterior and :2 the onset posterior (:0 is the contour)
        notes.append(res["StatefulPartitionedCall:1"][0])
        onsets.append(res["StatefulPartitionedCall:2"][0])
    k = BP_OVERLAP_FRAMES // 2
    cut = lambda parts: np.concatenate([p[k:-k] for p in parts], axis=0)
    n_frames = int(n_orig / BP_HOP)
    return {"note": cut(notes)[:n_frames], "onset": cut(onsets)[:n_frames]}


def decode_notes(act: dict[str, np.ndarray], onset_thresh: float = 0.45,
                 frame_thresh: float = 0.30, min_frames: int = 4,
                 midi_range: tuple[int, int] = (21, 108)) -> dict[str, np.ndarray]:
    """Posteriors to notes: a peak in the onset map starts one, and it lasts while
    the note map stays up. Deliberately simpler than basic-pitch's decoder - the
    picture wants which note and roughly how long, not a score."""
    note, onset = act["note"], act["onset"]
    rate = BP_SR / BP_HOP
    starts, ends, pitches, amps = [], [], [], []
    for b in range(note.shape[1]):
        midi = BP_MIDI_LOW + b
        if not (midi_range[0] <= midi <= midi_range[1]):
            continue
        peaks, _ = signal.find_peaks(onset[:, b], height=onset_thresh, distance=3)
        for j, p in enumerate(peaks):
            limit = peaks[j + 1] if j + 1 < len(peaks) else len(note)
            e, gap = p + 1, 0
            while e < limit:
                gap = gap + 1 if note[e, b] < frame_thresh else 0
                if gap > 3:
                    break
                e += 1
            e -= gap
            if e - p >= min_frames:
                starts.append(p / rate)
                ends.append(e / rate)
                pitches.append(midi)
                amps.append(float(note[p:e, b].mean()))
    order = np.argsort(starts)
    return {"t": np.asarray(starts)[order], "end": np.asarray(ends)[order],
            "midi": np.asarray(pitches, dtype=np.int16)[order],
            "amp": np.asarray(amps, dtype=np.float32)[order]}


def snap(model_t: np.ndarray, attack_t: np.ndarray, within: float = 0.045) -> np.ndarray:
    """Move each model time onto the nearest measured attack, if one is close."""
    if len(attack_t) == 0 or len(model_t) == 0:
        return model_t
    i = np.clip(np.searchsorted(attack_t, model_t), 1, len(attack_t) - 1)
    left, right = attack_t[i - 1], attack_t[i]
    near = np.where(np.abs(model_t - left) <= np.abs(right - model_t), left, right)
    return np.where(np.abs(near - model_t) <= within, near, model_t)


# ---------------------------------------------------------------------- the rest


def sung_melody(vocals: np.ndarray, sr: int) -> dict[str, np.ndarray]:
    from swift_f0 import SwiftF0

    res = SwiftF0().detect(_resample(vocals, sr, 16000), 16000, fmin=80.0, fmax=1200.0)
    return {"t": np.asarray(res.timestamps, dtype=np.float64),
            "hz": np.asarray(res.pitch_hz, dtype=np.float32),
            "conf": np.asarray(res.confidence, dtype=np.float32)}


def _runs(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    e = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    return np.flatnonzero(e == 1), np.flatnonzero(e == -1)


def lead_line(f0: dict, sure: float = 0.6, still: float = 0.3, bridge: float = 0.25,
              shortest: float = 0.25, median: float = 0.07) -> dict:
    """The most prominent single line in a busy stem, in phrases.

    SwiftF0 on the synths alone is choppy (on Shattered Voices, 434 confident runs of a
    median 0.13 s). A line starts where it is sure and carries on while it is fairly
    sure; gaps under `bridge` are closed and fragments under `shortest` dropped. Tried
    against a sung melody mixed into TIDAL CORE's synths: 78 % of its frames found on the
    right pitch (60 % before; a skyline of basic-pitch's notes, 35-40 %), in phrases a
    median 2.6 s long. Where nothing is sung it follows whichever synth line leads."""
    t, hz, conf = f0["t"], np.asarray(f0["hz"], np.float64), np.asarray(f0["conf"], np.float64)
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.01
    keep = np.zeros(len(t), bool)
    for a, b in zip(*_runs(conf > still)):
        if (conf[a:b] > sure).any():
            keep[a:b] = True
    for a, b in zip(*_runs(~keep)):
        if 0 < a and b < len(t) and (b - a) * dt < bridge:
            keep[a:b] = True
    for a, b in zip(*_runs(keep)):
        if (b - a) * dt < shortest:
            keep[a:b] = False
    st = 12.0 * np.log2(np.maximum(hz, 1.0) / 220.0)
    idx = np.where(conf > still, np.arange(len(st)), 0)
    np.maximum.accumulate(idx, out=idx)
    st = ndimage.median_filter(st[idx], size=max(1, int(median / dt)) | 1)
    return {"t": t, "st": st.astype(np.float32), "keep": keep}


from .grid import tracked_beats  # noqa: E402,F401  (Beat This! runs while listening now)


def chords(path: Path) -> list[dict]:
    from lv_chordia.chord_recognition import chord_recognition

    return [{"start": float(c["start_time"]), "end": float(c["end_time"]), "chord": str(c["chord"])}
            for c in chord_recognition(str(path))]


# Krumhansl-Kessler profiles: how much each scale degree belongs in a key.
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def key_from_notes(midi: np.ndarray, weight: np.ndarray) -> dict:
    hist = np.bincount(np.asarray(midi) % 12, weights=weight, minlength=12)
    best = (-2.0, 0, "major")
    for tonic in range(12):
        for mode, prof in (("major", _MAJOR), ("minor", _MINOR)):
            r = float(np.corrcoef(np.roll(prof, tonic), hist)[0, 1])
            if r > best[0]:
                best = (r, tonic, mode)
    return {"tonic": int(best[1]), "mode": best[2], "name": f"{NAMES[best[1]]} {best[2]}",
            "fit": best[0], "histogram": (hist / max(hist.sum(), 1e-9)).round(4).tolist()}


def clap_scores(mix: np.ndarray, sr: int, spans: list[tuple[float, float]],
                prompts: list[str]) -> dict[str, np.ndarray]:
    """For each span of the song: its CLAP embedding, and how close it sits to each
    prompt. A span longer than ten seconds is embedded in ten-second pieces and the
    pieces averaged, because ten seconds is what the model was trained to hear."""
    import torch
    from transformers import ClapModel, ClapProcessor

    name = "laion/larger_clap_music"
    model, proc = ClapModel.from_pretrained(name).eval(), ClapProcessor.from_pretrained(name)
    y = _resample(mix, sr, 48000)
    with torch.no_grad():
        text = model.get_text_features(**proc(text=prompts, return_tensors="pt", padding=True))
        text = torch.nn.functional.normalize(text, dim=-1)
        embs = []
        for a, b in spans:
            pieces = []
            t = a
            while t < b - 1.0:
                seg = y[int(t * 48000): int(min(t + 10.0, b) * 48000)]
                pieces.append(seg)
                t += 10.0
            if not pieces:                     # a section under a second: hear it whole
                pieces.append(y[int(a * 48000): int(max(b, a + 1.0) * 48000)])
            inp = proc(audios=pieces, sampling_rate=48000, return_tensors="pt")
            e = torch.nn.functional.normalize(model.get_audio_features(**inp), dim=-1).mean(dim=0)
            embs.append(torch.nn.functional.normalize(e, dim=-1))
        embs = torch.stack(embs)
        sims = embs @ text.T
    return {"embedding": embs.numpy(), "similarity": sims.numpy()}


def text_similarity(texts: list[str], anchors: list[str]) -> np.ndarray:
    """(len(texts), len(anchors)) cosine similarities, from all-MiniLM-L6-v2."""
    import torch
    from transformers import AutoModel, AutoTokenizer

    name = "sentence-transformers/all-MiniLM-L6-v2"
    tok, model = AutoTokenizer.from_pretrained(name), AutoModel.from_pretrained(name).eval()

    def embed(batch):
        enc = tok(batch, padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():
            out = model(**enc).last_hidden_state
        mask = enc["attention_mask"].unsqueeze(-1).float()
        return torch.nn.functional.normalize((out * mask).sum(1) / mask.sum(1), dim=-1)

    return (embed(texts) @ embed(anchors).T).numpy()


# ---------------------------------------------------------------------- run all


def run(got: dict, audio: Path, stems_dir: Path, project: Path | None, model_dir: Path,
        verbose: bool = True) -> tuple[dict, dict]:
    """`project` is the song tool's project.json; without one there are no lyrics to read."""
    import tempfile
    import time

    from . import decide, direct

    def say(*args):
        if verbose:
            print(*args, flush=True)

    a, lmeta = got["arrays"], got["meta"]
    period, duration = float(lmeta["period"]), float(lmeta["duration"])
    arrays: dict[str, np.ndarray] = {}
    meta: dict = {"version": VERSION, "listened": listened_key(lmeta)}

    mix, sr = load_stem(audio)
    stems = {name: load_stem(stems_dir / f"{name}.wav")[0] for name in ("bass", "other", "vocals")}
    ssr = load_stem(stems_dir / "bass.wav")[1]

    # beats: Beat This! ran while listening (the grid needs it); how far it agrees
    meter = int(lmeta.get("meter", 4))
    tb = {"beats": a["bt_beats"], "downbeats": a["bt_downbeats"]}
    beats = a["beats"]
    r = ((tb["beats"] - beats[0] + period / 2) % period) - period / 2
    phase = np.round((tb["downbeats"] - a["downbeats"][0]) / period) % meter
    meta["beat_this"] = {
        "tempo": float(60.0 / np.median(np.diff(tb["beats"]))),
        "median_offset_from_lattice_ms": float(1000 * np.median(r)),
        "within_25ms": float((np.abs(r) < 0.025).mean()),
        "downbeats_agreeing_with_kick_reentries": [int((phase == 0).sum()), int(len(phase))],
    }
    say(f"Beat This!  {meta['beat_this']}")

    # notes: what the model names, when the stems say
    nmp = basic_pitch_model(model_dir)
    for stem, rng, attacks in (("other", (36, 96), a["ev_note_t"]), ("bass", (24, 60), a["ev_bass_note_t"])):
        t0 = time.time()
        notes = decode_notes(basic_pitch_activations(stems[stem], ssr, nmp),
                             midi_range=rng)
        snapped = snap(notes["t"], attacks)
        keep = playing_at(a, stem, snapped)       # the model hears leakage too
        meta[f"notes_{stem}"] = {"count": int(keep.sum()), "dropped_not_playing": int((~keep).sum()),
                                 "snapped_to_an_attack": float((snapped[keep] != notes["t"][keep]).mean()) if keep.any() else 0.0}
        arrays[f"{stem}_t"], arrays[f"{stem}_end"] = snapped[keep], notes["end"][keep]
        arrays[f"{stem}_midi"], arrays[f"{stem}_amp"] = notes["midi"][keep], notes["amp"][keep]
        say(f"basic-pitch {stem}: {meta[f'notes_{stem}']}  ({time.time() - t0:.0f}s)")
    w = np.concatenate([(arrays["other_end"] - arrays["other_t"]).clip(0.05) * arrays["other_amp"],
                        2 * (arrays["bass_end"] - arrays["bass_t"]).clip(0.05) * arrays["bass_amp"]])
    meta["key"] = key_from_notes(np.concatenate([arrays["other_midi"], arrays["bass_midi"]]), w)
    say(f"key: {meta['key']['name']} (fit {meta['key']['fit']:.2f})")

    f0 = sung_melody(stems["vocals"], ssr)
    arrays["f0_t"], arrays["f0_hz"] = f0["t"], f0["hz"]
    arrays["f0_conf"] = np.where(playing_at(a, "vocals", f0["t"]), f0["conf"], 0.0)

    # the synths' lead line: what the heart follows when nothing sings (cast.py)
    lead = lead_line(sung_melody(stems["other"], ssr))
    lead["keep"] &= playing_at(a, "other", lead["t"])
    arrays["lead_t"], arrays["lead_st"], arrays["lead_keep"] = lead["t"], lead["st"], lead["keep"]
    meta["lead"] = {"covers": float(lead["keep"].mean())}
    say(f"lead line in the synths: {meta['lead']['covers']:.2f} of the song")

    # chords, from everything pitched and nothing struck
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        pitched = Path(tmp) / "pitched.wav"
        sf.write(str(pitched), (stems["other"] + stems["bass"] + 0.5 * stems["vocals"]).astype(np.float32), ssr)
        meta["chords"] = chords(pitched)
    say(f"lv-chordia: {len(meta['chords'])} chord spans  ({time.time() - t0:.0f}s)")

    # what each section sounds like
    t0 = time.time()
    drops = direct.find_drops(a, period, duration, meter)
    sections = decide.find_sections(a, drops, duration)
    prompts = [p for pair in decide.AXES.values() for p in pair]
    clap = clap_scores(mix, sr, [(s.start, s.end) for s in sections], prompts)
    arrays["clap_embedding"], arrays["clap_similarity"] = clap["embedding"], clap["similarity"]
    meta["clap_prompts"] = prompts
    say(f"CLAP: {len(sections)} sections x {len(prompts)} prompts  ({time.time() - t0:.0f}s)")

    # what each lyric line, and each word, is about
    if project is None:
        say("MiniLM: no lyrics (the song tool has not aligned this track)")
        return arrays, meta
    t0 = time.time()
    project = json.loads(project.read_text())
    anchors = [text for text, _ in decide.IMAGES.values()]
    lines = [ln for ln in project["lines"] if ln.get("start") is not None]
    words = [(w_["text"], float(w_["start"]), float(w_["end"]), i)
             for i, ln in enumerate(lines) for w_ in ln.get("words", []) if w_.get("start") is not None]
    arrays["line_similarity"] = text_similarity([ln["text"] for ln in lines], anchors)
    arrays["word_similarity"] = text_similarity([w_[0].strip(" ,.!?\u2026").lower() for w_ in words], anchors)
    arrays["line_t"] = np.array([[ln["start"], ln["end"]] for ln in lines], dtype=np.float64)
    arrays["word_t"] = np.array([[w_[1], w_[2]] for w_ in words], dtype=np.float64)
    arrays["word_line"] = np.array([w_[3] for w_ in words], dtype=np.int32)
    meta["lines"] = [ln["text"] for ln in lines]
    meta["words"] = [w_[0] for w_ in words]
    meta["images"] = list(decide.IMAGES)
    say(f"MiniLM: {len(lines)} lines, {len(words)} words x {len(anchors)} images  ({time.time() - t0:.0f}s)")
    return arrays, meta


# -------------------------------------------------------------------- the cache


def cache_paths(cache: Path) -> tuple[Path, Path]:
    return cache / "models.npz", cache / "models.json"


def playing_at(a: dict, stem: str, t: np.ndarray) -> np.ndarray:
    """Whether `stem` is playing (or about to) in the bar of each time: listen.presence."""
    from .listen import near_playing

    return near_playing(t, a["bar_t"], a[f"near_{stem}"]) if f"near_{stem}" in a else np.ones(len(t), bool)


def listened_key(lmeta: dict) -> list:
    """Which listening these models were run on: sections, and so CLAP's rows, follow the grid."""
    key = [lmeta.get("version"), round(float(lmeta["period"]), 9), round(float(lmeta["grid"].get("t0", 0.0)), 9),
           int(lmeta.get("meter", 4))]
    return key + [lmeta["grid_fix"]] if lmeta.get("grid_fix") else key     # a corrected grid: bars moved


def save(arrays: dict, meta: dict, cache: Path) -> None:
    npz, js = cache_paths(cache)
    np.savez_compressed(npz, **arrays)
    js.write_text(json.dumps(meta, indent=1) + "\n")


def load_cached(cache: Path) -> tuple[dict, dict] | None:
    npz, js = cache_paths(cache)
    if not (npz.exists() and js.exists()):
        return None
    meta = json.loads(js.read_text())
    if meta.get("version") != VERSION:
        return None
    with np.load(npz) as z:
        return {k: z[k] for k in z.files}, meta


def load_stem(path: Path) -> tuple[np.ndarray, int]:
    x, sr = sf.read(str(path), always_2d=True)
    return x.mean(axis=1), sr
