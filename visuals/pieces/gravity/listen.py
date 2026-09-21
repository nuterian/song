"""Listening to one song properly: four stems, each reduced to what the picture needs.

Two kinds of thing come out.

**Events** - a kick, a snare, a hat, a syllable, a synth note - are kept as times
in seconds, not as samples of a grid. An event's time is where its attack crosses
half way up, read off a zero-phase power envelope at 1 kHz, so it is good to a
millisecond or two and carries no filter delay. The shader is handed the time and
works out the age itself, which makes every attack exactly as sharp as the frame
rate allows and makes the picture a pure function of the clock.

**Streams** - how much sub there is, how bright the pad is, where the voice sits -
are levels on the same 120 Hz grid the rest of `visuals` uses.

Stems come from a four-stem htdemucs run, once, from the repository's root venv
(the only place torch lives):

    .venv/bin/python -m demucs -n htdemucs -d cpu \
        -o visuals/cache/<track>/demucs_raw "<audio>"
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import ndimage, signal

from . import grid as grid_
from .grid import fit_grid, latency  # noqa: F401  (the grid is grid.py's; kept here by their old names)

RATE = 120          # the grid streams live on; matches visuals.listen.RATE
ENV_RATE = 1000     # envelopes used for timing attacks
VERSION = 16         # ...14: enough hits for a lattice; 15: a tracked grid only goes forward; 16: a tempo prior (halve at 160+)

STEMS = ("drums", "bass", "other", "vocals")
# Which stem each kind of event is heard in.
OWNER = {"kick": "drums", "snare": "drums", "hat": "drums", "crash": "drums",
         "bass_note": "bass", "note": "other", "syllable": "vocals"}
# A stem is playing in a bar when its energy there is within PRESENT_DB of the mix's
# (and the mix is within AUDIBLE_DB of its loudest bar). Measured per bar on three songs:
# a part that plays sits at -25 dB and up; Demucs' leakage of a part that does not
# never rises above -40 (Shattered Voices' "vocals": -60 to -40, all of them).
PRESENT_DB = -30.0
AUDIBLE_DB = -40.0


# ------------------------------------------------------------------ primitives


def load(path: Path) -> tuple[np.ndarray, int]:
    """(samples, 2) float64 and the rate."""
    x, sr = sf.read(str(path), always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    return x, sr


def band(x: np.ndarray, sr: int, lo: float | None, hi: float | None, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth. No delay, which is the whole reason it is here."""
    nyq = sr / 2
    if lo and hi:
        sos = signal.butter(order, [lo / nyq, hi / nyq], "bandpass", output="sos")
    elif lo:
        sos = signal.butter(order, lo / nyq, "highpass", output="sos")
    else:
        sos = signal.butter(order, hi / nyq, "lowpass", output="sos")
    return signal.sosfiltfilt(sos, x)


def power_env(x: np.ndarray, sr: int, fc: float) -> np.ndarray:
    """Amplitude envelope at ENV_RATE: sqrt of zero-phase low-passed power.

    The smoothing kernel is symmetric, so a step in the input crosses half way up
    at the instant of the step. That is what makes the half-rise point an honest
    onset time rather than one that is early by half a window.
    """
    p = band(x * x, sr, None, fc, order=2)
    # Sampled at exactly ENV_RATE. A step of sr // ENV_RATE samples is 44 at 44.1 kHz, which
    # made every "millisecond" 0.998 ms and every event 0.23 % early: 0.65 s by five minutes.
    idx = np.round(np.arange(env_length(len(x), sr)) * (sr / ENV_RATE)).astype(np.int64)
    return np.sqrt(np.maximum(p[np.minimum(idx, len(p) - 1)], 0.0))


def env_length(samples: int, sr: int) -> int:
    """How many ENV_RATE samples an envelope of `samples` audio samples has."""
    return int(np.ceil(samples * ENV_RATE / sr))


def trailing_max(x: np.ndarray, width: int) -> np.ndarray:
    """max over the last `width` samples, this one included."""
    width = max(1, int(width))
    centred = ndimage.maximum_filter1d(x, size=width, mode="nearest")
    shift = width // 2
    out = np.empty_like(x)
    out[shift:] = centred[: len(x) - shift]
    out[:shift] = np.maximum.accumulate(x[:shift]) if shift else x[:0]
    return out


def smooth(x: np.ndarray, rate: float, seconds: float) -> np.ndarray:
    """Zero-phase gaussian, sigma = seconds / 2."""
    sigma = max(1e-6, seconds * rate / 2.0)
    return ndimage.gaussian_filter1d(x, sigma, mode="nearest")


def to_grid(x: np.ndarray, x_rate: float, n: int) -> np.ndarray:
    t = np.arange(n) / RATE
    return np.interp(t, np.arange(len(x)) / x_rate, x).astype(np.float32)


def unit(x: np.ndarray, lo_pct: float, hi_pct: float, mask: np.ndarray | None = None) -> np.ndarray:
    ref = x if mask is None else x[mask]
    lo, hi = np.percentile(ref, [lo_pct, hi_pct])
    return np.clip((x - lo) / max(hi - lo, 1e-9), 0.0, 1.0)


def db(x: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(x, 1e-7))


# -------------------------------------------------------------------- presence


def presence(x: np.ndarray, mix: np.ndarray, sr: int, starts: np.ndarray, duration: float) -> dict:
    """Per bar: the stem's energy against the mix's (dB); whether it is playing; and
    `near` - playing, or next to a bar that is - which is where its events are kept, so
    that a line sung from the last beat of a bar keeps its first syllable."""
    idx = np.clip((np.append(np.maximum(starts, 0.0), duration) * sr).astype(int), 0, len(mix) - 1)

    def bar_db(y: np.ndarray) -> np.ndarray:
        e = np.add.reduceat(y * y, idx[:-1]) / np.maximum(np.diff(idx), 1)
        return 10.0 * np.log10(np.maximum(e, 1e-14))

    m = bar_db(mix)
    share = bar_db(x) - m
    playing = (share > PRESENT_DB) & (m > m.max() + AUDIBLE_DB)
    near = playing.copy()
    near[1:] |= playing[:-1]
    near[:-1] |= playing[1:]
    return {"share_db": share, "playing": playing, "near": near}


def near_playing(t: np.ndarray, bars: np.ndarray, near: np.ndarray) -> np.ndarray:
    """For each time, whether its bar is one its stem plays in or next to."""
    if not len(t) or not len(bars):
        return np.ones(len(t), bool)
    return near[np.clip(np.searchsorted(bars, t, side="right") - 1, 0, len(bars) - 1)].astype(bool)


def bar_gate(near: np.ndarray, starts: np.ndarray, n: int, period: float) -> np.ndarray:
    """1 where a stem's bars are near playing, 0 where not, eased over a beat either side:
    a part that stops fades rather than being cut at the bar line."""
    t = np.arange(n) / RATE
    k = np.clip(np.searchsorted(starts, t, side="right") - 1, 0, len(starts) - 1)
    return np.clip(smooth(near[k].astype(float), RATE, 2 * period), 0.0, 1.0)


# ---------------------------------------------------------------------- onsets


@dataclass
class Onsets:
    t: np.ndarray      # seconds, the half-rise point of each attack
    amp: np.ndarray    # rise height, normalised so the 90th percentile is 1

    def __len__(self) -> int:
        return len(self.t)


def pick_onsets(env: np.ndarray, min_gap: float, sensitivity: float,
                rise_window: float = 0.045, slope_ms: int = 6) -> Onsets:
    """Attacks in a 1 kHz envelope.

    An attack is a peak in the envelope's rise over `slope_ms`. It is kept if that
    rise clears `sensitivity` times the 99th percentile of all rises. Its time is
    where the envelope crosses half way between the dip before and the crest after.
    """
    k = slope_ms
    d = np.zeros_like(env)
    d[k:] = np.maximum(env[k:] - env[:-k], 0.0)
    ref = np.percentile(d, 99.0)
    if ref <= 0:
        return Onsets(np.zeros(0), np.zeros(0))
    peaks, _ = signal.find_peaks(d, height=sensitivity * ref,
                                 distance=max(1, int(min_gap * ENV_RATE)))
    w = int(rise_window * ENV_RATE)
    times, amps = [], []
    for p in peaks:
        a, b = max(0, p - w), min(len(env), p + w)
        lo_i = a + int(np.argmin(env[a:p + 1]))
        hi_i = p + int(np.argmax(env[p:b]))
        rise = env[hi_i] - env[lo_i]
        if rise <= 0 or hi_i <= lo_i:
            continue
        half = env[lo_i] + 0.5 * rise
        seg = env[lo_i:hi_i + 1]
        j = int(np.argmax(seg >= half))
        if j == 0:
            x = float(lo_i)
        else:
            y0, y1 = seg[j - 1], seg[j]
            x = lo_i + j - 1 + (half - y0) / max(y1 - y0, 1e-12)
        times.append(x / ENV_RATE)
        amps.append(rise)
    t = np.asarray(times)
    amp = np.asarray(amps)
    if len(amp):
        amp = amp / max(np.percentile(amp, 90), 1e-9)
    return Onsets(t, amp)


# ---------------------------------------------------------------------- clocks


def beat_clock(t: np.ndarray, beats: np.ndarray) -> np.ndarray:
    """Beats elapsed at each time, as a real number, 0 at beats[0]."""
    return np.interp(t, beats, np.arange(len(beats)), left=0.0, right=float(len(beats) - 1))


# ------------------------------------------------------------------ the listen


def listen(audio: Path, stems_dir: Path, workdir: Path, verbose: bool = True,
           grid_fix: dict | None = None, bt: dict | None = None) -> dict:
    """Everything, as a dict of numpy arrays plus a small `meta` dict. `grid_fix` is a
    person's correction of the grid (grid.py); `bt`, Beat This!'s beats from an earlier
    listening of the same audio, to save running it again."""
    import librosa  # slow import, and only this function needs it

    def say(*a):
        if verbose:
            print(*a, flush=True)

    mix2, sr = load(audio)
    duration = len(mix2) / sr
    n = int(np.ceil(duration * RATE)) + 1
    mix = mix2.mean(axis=1)
    stem = {}
    for name in STEMS:
        s, ssr = load(stems_dir / f"{name}.wav")
        s = s.mean(axis=1)
        if ssr != sr:  # demucs works, and writes, at 44.1 kHz
            g = np.gcd(sr, ssr)
            s = signal.resample_poly(s, sr // g, ssr // g)
        s = s[: len(mix)]
        stem[name] = np.pad(s, (0, len(mix) - len(s)))

    # The stems must sit exactly under the mix, or every event time is off by the
    # same amount and nothing downstream could tell. Measured, not assumed.
    total = sum(stem.values())
    # six seconds from a minute in - or, in a song too short for that, from its middle
    a0 = int(min(60.0, max(0.0, duration / 2 - 3.0)) * sr)
    seg = slice(a0, min(a0 + 6 * sr, len(mix)))
    xc = signal.correlate(total[seg], mix[seg], mode="full", method="fft")
    stem_lag = int(np.argmax(xc)) - (seg.stop - seg.start - 1)
    say(f"loaded {duration:.1f}s at {sr} Hz, four stems; stems lag the mix by "
        f"{stem_lag} samples ({1000 * stem_lag / sr:.2f} ms)")
    if abs(stem_lag) > sr // 1000:
        for name in STEMS:
            stem[name] = np.roll(stem[name], -stem_lag)

    out: dict[str, np.ndarray] = {}

    # --- drums: three bands of one stem, each with its own attacks ------------
    kick_env = power_env(band(stem["drums"], sr, None, 140), sr, 45)
    snare_env = power_env(band(stem["drums"], sr, 180, 4500), sr, 90)
    hat_env = power_env(band(stem["drums"], sr, 7000, None), sr, 120)
    kick = pick_onsets(kick_env, min_gap=0.16, sensitivity=0.22)
    snare = pick_onsets(snare_env, min_gap=0.11, sensitivity=0.22)
    hat = pick_onsets(hat_env, min_gap=0.055, sensitivity=0.10)

    # A kick rattles the snare band too. A snare-band attack within 25 ms of a
    # kick is the kick's own click unless it is clearly the bigger of the two.
    if len(kick) and len(snare):
        j = np.clip(np.searchsorted(kick.t, snare.t), 1, len(kick) - 1)
        gap = np.minimum(np.abs(snare.t - kick.t[j - 1]), np.abs(snare.t - kick.t[j]))
        near_amp = np.where(np.abs(snare.t - kick.t[j - 1]) < np.abs(snare.t - kick.t[j]),
                            kick.amp[j - 1], kick.amp[j])
        keep = ~((gap < 0.025) & (snare.amp < 1.2 * near_amp))
        snare = Onsets(snare.t[keep], snare.amp[keep])
    say(f"drums: {len(kick)} kicks, {len(snare)} snares, {len(hat)} hats")
    snare_hi = power_env(band(stem["drums"], sr, 2500, 9000), sr, 90)
    snare_lo = power_env(band(stem["drums"], sr, 180, 1200), sr, 90)

    # Every attack the grid might be judged by, before the grid: the pitched ones too,
    # for a song whose only regular attacks are notes.
    bass = pick_onsets(power_env(stem["bass"], sr, 35), min_gap=0.10, sensitivity=0.18)
    note = pick_onsets(power_env(band(stem["other"], sr, 300, None), sr, 60),
                       min_gap=0.08, sensitivity=0.16)

    # --- the grid (grid.py) --------------------------------------------------------
    t_bt = time.time()
    bt = bt or grid_.tracked_beats(mix, sr)
    say(f"Beat This!: {len(bt['beats'])} beats, {len(bt['downbeats'])} downbeats  ({time.time() - t_bt:.0f}s)")
    # Only what is really playing may say where the grid is. There are no bars yet, so
    # presence is judged on 2 s windows: Demucs' leakage of absent drums has "hats" too,
    # and on Gravity without its drums they made a lattice at 124.72 BPM that 67 % of
    # them sat on (Beat This! agreed with 12 % of it).
    win = np.arange(0.0, duration, 2.0)
    drums_near = presence(stem["drums"], mix, sr, win, duration)["near"]
    other_near = presence(stem["other"], mix, sr, win, duration)["near"]
    real = lambda ev, near: near_playing(ev.t, win, near)
    hat_r, snare_r, kick_r, note_r = real(hat, drums_near), real(snare, drums_near), real(kick, drums_near), real(note, other_near)
    # (The synths' attacks were tried as a lattice for songs with no drums: 21-48 % of them
    # sit within 4 ms of the true one, and their accents did not find the beat. Not used.)
    sharp = np.sort(np.concatenate([hat.t[hat_r & (hat.amp > 0.5)], snare.t[snare_r & (snare.amp > 0.8)]]))
    lattice_from = "hats and claps"
    strong_kicks = kick.t[kick_r & (kick.amp > 0.5)]
    # Snap tracked beats only to attacks with no lag of their own - a raw kick reads
    # 7-24 ms late and would drag beats with it - unless the song has too few of them.
    if hat_r.sum() + snare_r.sum() >= 0.5 * len(bt["beats"]):
        onsets = (np.concatenate([hat.t[hat_r], snare.t[snare_r]]), np.concatenate([hat.amp[hat_r], snare.amp[snare_r]]))
    else:
        # the synths' attacks: a bass line is often off the beat, and its cluster was taken
        # for Beat This!'s lateness (-78 ms on Gravity without drums; it is late by 14-38)
        onsets = (note.t[note_r], note.amp[note_r])
    grid = grid_.find(sharp, strong_kicks, onsets, bt, duration, fix=grid_fix)
    grid["lattice_from"] = lattice_from
    beats, downbeats = grid["beats"], grid["downbeats"]
    period, meter = grid["period"], grid["meter"]
    lat = grid.get("lattice", {})
    say(f"grid: {grid['tempo']:.4f} bpm in {meter} ({grid['source']}); first beat at {1000 * grid['t0']:.1f} ms; "
        + (f"{lat['sharp_used']} of {len(sharp)} {lattice_from} within 4 ms ({lat['on_lattice']:.2f}), "
           f"Beat This! agreeing {lat.get('beat_this_agrees', float('nan')):.2f}, "
           f"{lat['sharp_residual_ms']:.2f} ms rms; drift per 30 s {lat['drift_ms_per_30s']} ms; "
           if lat else f"no lattice ({len(sharp)} {lattice_from}); ")
        + f"bar phase from {grid['bar_phase_from']} (kick {grid['bar_phase_votes']}, "
          f"Beat This! {grid['beat_this_downbeat_votes']})")
    beat_w = int(round(period * ENV_RATE))
    div = int(lat.get("div", 4))

    # A kick's low band takes a while to fill; its click does not. Time the kick by
    # how late its band reads against the lattice, measured here rather than guessed.
    # Without a lattice there is nothing to measure it against.
    on_lattice = grid["source"] == "lattice"
    kick_lag = latency(strong_kicks, beats, 1) if on_lattice else 0.0
    kick = Onsets(kick.t - kick_lag, kick.amp)
    say(f"kick band reads {1000 * kick_lag:.1f} ms late; corrected" if on_lattice
        else "kick lag not measured: no lattice")

    # --- presence: which stems are really playing, bar by bar ------------------
    bars = downbeats[(downbeats > -period) & (downbeats < duration)]
    pres = {name: presence(stem[name], mix, sr, bars, duration) for name in STEMS}
    gate = {name: bar_gate(pres[name]["near"], bars, n, period) for name in STEMS}
    n_env = env_length(len(mix), sr)
    gate_env = {name: np.interp(np.arange(n_env) / ENV_RATE, np.arange(n) / RATE, gate[name])
                for name in STEMS}
    say("playing, share of bars: " + ", ".join(f"{k} {v['playing'].mean():.2f}" for k, v in pres.items()))

    # --- sub: is there a floor under the song or not --------------------------
    sub_env = power_env(band(mix, sr, 25, 90), sr, 30)
    sub_db = db(sub_env) - db(np.percentile(sub_env, 90))
    sub_lin = np.clip((sub_db + 26.0) / 20.0, 0.0, 1.0)
    # One kick a beat keeps a trailing one-beat max up; when the sub goes, this
    # falls a beat later, and when it comes back it is back on the first kick.
    gravity = smooth(trailing_max(sub_lin, int(beat_w * 1.05)), ENV_RATE, 0.05)
    out["gravity"] = to_grid(gravity, ENV_RATE, n)
    out["sub"] = to_grid(unit(sub_env, 5, 99), ENV_RATE, n)

    # --- bass ------------------------------------------------------------------
    # Slow enough that the note's own waveform is not in it. A 49 Hz bass note
    # beats in its power envelope at 49 Hz, and at 60 frames a second that would
    # reach the screen as an 11 Hz shimmer that nothing in the music asked for.
    bass_env = power_env(stem["bass"], sr, 12)
    # Levels keep the whole song's scale - its floor is silence, which is what a quiet
    # passage should be measured against - and are shut where the stem is not playing.
    out["bass"] = to_grid(unit(bass_env, 5, 99) * gate_env["bass"][: len(bass_env)], ENV_RATE, n)
    bass_lag = latency(bass.t, beats, div) if on_lattice else 0.0
    bass = Onsets(bass.t - bass_lag, bass.amp)

    # --- voice -----------------------------------------------------------------
    vox_env = power_env(stem["vocals"], sr, 25)
    vox_unit = unit(vox_env, 20, 99) * gate_env["vocals"][: len(vox_env)]
    out["voice"] = to_grid(vox_unit, ENV_RATE, n)
    out["voice_presence"] = to_grid(smooth(trailing_max(vox_unit, 2 * beat_w), ENV_RATE, 0.6),
                                    ENV_RATE, n)
    syll = pick_onsets(power_env(stem["vocals"], sr, 40), min_gap=0.09, sensitivity=0.16)
    say(f"voice: {len(syll)} syllable attacks; bass: {len(bass)} note attacks")

    y22 = librosa.resample(stem["vocals"].astype(np.float32), orig_sr=sr, target_sr=22050)
    hop = 256
    f0, voiced, _ = librosa.pyin(y22, fmin=90, fmax=1100, sr=22050,
                                 frame_length=2048, hop_length=hop)
    f_rate = 22050 / hop
    semis = 12 * np.log2(np.where(np.isfinite(f0), f0, np.nan) / 220.0)
    good = np.isfinite(semis) & voiced
    if good.sum() > 10:
        centre = np.median(semis[good])
        idx = np.where(good, np.arange(len(semis)), 0)
        np.maximum.accumulate(idx, out=idx)
        held = semis[idx]
        held[: np.argmax(good)] = centre
        pitch = smooth(held - centre, f_rate, 0.09)
    else:
        pitch = np.zeros(len(f0))
    out["voice_pitch"] = to_grid(np.clip(pitch / 12.0, -1, 1), f_rate, n) * gate["vocals"]
    say(f"voice pitch: voiced {100 * good.mean():.0f}% of frames, "
        f"range {np.percentile(semis[good], 5):.1f}..{np.percentile(semis[good], 95):.1f} st re A3")

    # --- other: synths, pads, leads -------------------------------------------
    oth_env = power_env(stem["other"], sr, 30)
    out["other"] = to_grid(unit(oth_env, 5, 99) * gate_env["other"][: len(oth_env)], ENV_RATE, n)
    o22 = librosa.resample(stem["other"].astype(np.float32), orig_sr=sr, target_sr=22050)
    S = np.abs(librosa.stft(o22, n_fft=2048, hop_length=512))
    c_rate = 22050 / 512
    cent = librosa.feature.spectral_centroid(S=S, sr=22050)[0]
    energy = S.sum(axis=0)
    live = energy > np.percentile(energy, 25)
    logc = np.log2(np.maximum(cent, 50.0))
    idx = np.where(live, np.arange(len(logc)), 0)
    np.maximum.accumulate(idx, out=idx)
    logc = logc[idx]
    out["bright"] = to_grid(unit(smooth(logc, c_rate, 0.12), 3, 97, live), c_rate, n)

    # Where the harmony is on the circle of fifths, as an unwrapped angle. A chord
    # change moves it; a held chord holds it.
    h22 = librosa.resample((stem["other"] + stem["bass"]).astype(np.float32),
                           orig_sr=sr, target_sr=22050)
    chroma = librosa.feature.chroma_cqt(y=h22, sr=22050, hop_length=2048)
    h_rate = 22050 / 2048
    chroma = ndimage.median_filter(chroma, size=(1, int(h_rate * period * 2) | 1))
    fifths = np.exp(2j * np.pi * ((7 * np.arange(12)) % 12) / 12.0)
    z = (chroma * fifths[:, None]).sum(axis=0) / np.maximum(chroma.sum(axis=0), 1e-9)
    z = smooth(z.real, h_rate, period * 2) + 1j * smooth(z.imag, h_rate, period * 2)
    out["harmony"] = to_grid(np.unwrap(np.angle(z)), h_rate, n)
    out["harmony_clarity"] = to_grid(np.abs(z), h_rate, n)
    note_lag = latency(note.t, beats, div) if on_lattice else 0.0
    note = Onsets(note.t - note_lag, note.amp)

    # What pitch each note is: the strongest constant-Q bin in the 70 ms after its
    # attack. Not a transcription - an ordering, so that a line that climbs can be
    # seen to climb.
    C = np.abs(librosa.cqt(o22, sr=22050, hop_length=256, fmin=librosa.note_to_hz("C2"),
                           n_bins=60, bins_per_octave=12))
    q_rate = 22050 / 256
    note_pitch = np.zeros(len(note))
    for k, tn in enumerate(note.t):
        f0_, f1_ = int((tn + 0.010) * q_rate), int((tn + 0.080) * q_rate) + 1
        seg = C[:, f0_:min(f1_, C.shape[1])]
        note_pitch[k] = 36 + int(np.argmax(seg.mean(axis=1))) if seg.size else 60
    say(f"other: {len(note)} note attacks; detector lag bass {1000 * bass_lag:.1f} ms, "
        f"notes {1000 * note_lag:.1f} ms, both corrected")

    # --- the whole mix ----------------------------------------------------------
    air_env = power_env(band(mix, sr, 5000, 14000), sr, 20)
    air_db = db(air_env) - db(np.percentile(air_env, 90))
    out["air"] = to_grid(np.clip((smooth(air_db, ENV_RATE, 0.25) + 18.0) / 20.0, 0, 1), ENV_RATE, n)

    loud_env = power_env(mix, sr, 12)
    loud_db = db(loud_env) - db(np.percentile(loud_env, 95))
    out["loud"] = to_grid(np.clip((smooth(loud_db, ENV_RATE, 0.10) + 30.0) / 30.0, 0, 1), ENV_RATE, n)
    out["loud_db"] = to_grid(smooth(loud_db, ENV_RATE, 0.10), ENV_RATE, n)
    out["energy"] = to_grid(np.clip((smooth(loud_db, ENV_RATE, period * 8) + 14.0) / 14.0, 0, 1),
                            ENV_RATE, n)

    mid = mix2.mean(axis=1)
    side = (mix2[:, 0] - mix2[:, 1]) / 2.0
    width = power_env(side, sr, 8) / np.maximum(power_env(mid, sr, 8), 1e-5)
    out["width"] = to_grid(unit(smooth(width, ENV_RATE, period), 5, 95), ENV_RATE, n)

    # --- crashes: a cymbal that rings on. The top band, followed slowly; an attack
    # in *that* is something that lasted, which a hat never does.
    crash_env = power_env(band(stem["drums"], sr, 6000, None), sr, 5)
    crash = pick_onsets(crash_env, min_gap=1.5, sensitivity=0.45, rise_window=0.20, slope_ms=60)
    say(f"crashes: {len(crash)}")

    # --- what each bar sounds like, for telling sections apart --------------------
    # Timbre (MFCC of the mix) and harmony (chroma of everything pitched), averaged
    # over the bar. A section is then a run of bars that sound alike.
    m22 = librosa.resample(mix.astype(np.float32), orig_sr=sr, target_sr=22050)
    mfcc = librosa.feature.mfcc(y=m22, sr=22050, n_mfcc=14, hop_length=1024)[1:]
    chroma_bar = librosa.feature.chroma_cqt(y=h22, sr=22050, hop_length=1024)
    fr_t = np.arange(mfcc.shape[1]) * 1024 / 22050
    bar_edges = np.append(bars, duration)
    feats = []
    for b0, b1 in zip(bar_edges[:-1], bar_edges[1:]):
        sel = (fr_t >= b0) & (fr_t < b1)
        if not sel.any():
            sel = np.abs(fr_t - b0) == np.abs(fr_t - b0).min()
        feats.append(np.concatenate([mfcc[:, sel].mean(axis=1), chroma_bar[:, sel[: chroma_bar.shape[1]]].mean(axis=1)]))
    out["bar_feat"] = np.asarray(feats, dtype=np.float32)
    out["bar_t"] = bars

    # --- clocks -----------------------------------------------------------------
    t = np.arange(n) / RATE
    out["beats_elapsed"] = beat_clock(t, beats).astype(np.float32)

    events = {"kick": kick, "snare": snare, "hat": hat, "bass_note": bass,
              "syllable": syll, "note": note, "crash": crash}
    # An event is kept only where its stem is playing or about to be: Demucs' leakage
    # of an absent part has onsets too, and they are noise.
    dropped = {}
    for k, ev in events.items():
        keep = near_playing(ev.t, bars, pres[OWNER[k]]["near"])
        dropped[k] = int((~keep).sum())
        if k == "note":
            note_pitch = note_pitch[keep]
        out[f"ev_{k}_t"] = ev.t[keep].astype(np.float64)
        out[f"ev_{k}_amp"] = ev.amp[keep].astype(np.float32)
    out["ev_note_pitch"] = note_pitch.astype(np.float32)
    say("events dropped where their stem is not playing: " + ", ".join(f"{k} {v}" for k, v in dropped.items() if v))

    # --- what can play a part whose instrument is missing (cast.py) ---------------
    # A song with no drums still has a low end that lands on the beat, accents in the
    # middle and air at the top; a song with no bass still has the synths' low notes.
    spare = {
        "mixlow": pick_onsets(power_env(band(mix, sr, None, 140), sr, 45), min_gap=0.16, sensitivity=0.22),
        "mixmid": pick_onsets(power_env(band(mix, sr, 180, 4500), sr, 90), min_gap=0.11, sensitivity=0.22),
        "mixhi": pick_onsets(power_env(band(mix, sr, 7000, None), sr, 120), min_gap=0.055, sensitivity=0.10),
        "otherhi": pick_onsets(power_env(band(stem["other"], sr, 7000, None), sr, 120), min_gap=0.055, sensitivity=0.10),
    }
    # the low band fills slowly, as a kick's does: measured against the lattice, when there is one
    low_lag = latency(spare["mixlow"].t[spare["mixlow"].amp > 0.5], beats, 1) if on_lattice else 0.0
    spare["mixlow"] = Onsets(spare["mixlow"].t - low_lag, spare["mixlow"].amp)
    keep = near_playing(spare["otherhi"].t, bars, pres["other"]["near"])
    spare["otherhi"] = Onsets(spare["otherhi"].t[keep], spare["otherhi"].amp[keep])
    for k, ev in spare.items():
        out[f"ev_{k}_t"] = ev.t.astype(np.float64)
        out[f"ev_{k}_amp"] = ev.amp.astype(np.float32)
    olow = power_env(band(stem["other"], sr, None, 250), sr, 12)
    out["other_low"] = to_grid(unit(olow, 5, 99) * gate_env["other"][: len(olow)], ENV_RATE, n)
    for name in STEMS:
        out[f"present_{name}"] = pres[name]["playing"]
        out[f"near_{name}"] = pres[name]["near"]
        out[f"share_db_{name}"] = pres[name]["share_db"].astype(np.float32)
        out[f"gate_{name}"] = gate[name].astype(np.float32)
    # how bright each clap is: the top of its band against the bottom, just after it
    si = np.clip((out["ev_snare_t"] * ENV_RATE).astype(int) + 8, 0, len(snare_hi) - 1)
    out["ev_snare_bright"] = (snare_hi[si] / np.maximum(snare_hi[si] + snare_lo[si], 1e-9)).astype(np.float32)
    out["beats"] = beats
    out["downbeats"] = downbeats
    out["bt_beats"], out["bt_downbeats"] = bt["beats"], bt["downbeats"]

    meta = {"version": VERSION, "duration": duration, "rate": RATE, "n": n,
            "tempo": grid["tempo"], "period": period, "meter": meter, "grid_fix": grid_.normal_fix(grid_fix),
            "grid": {k: v for k, v in grid.items() if k not in ("beats", "downbeats")},
            "lag_ms": {"kick": 1000 * kick_lag, "bass_note": 1000 * bass_lag, "mixlow": 1000 * low_lag,
                       "note": 1000 * note_lag},
            "presence": {name: {"playing": float(pres[name]["playing"].mean()), "dropped": {
                k: v for k, v in dropped.items() if OWNER[k] == name}} for name in STEMS}}
    return {"arrays": out, "meta": meta}


# -------------------------------------------------------------------- the cache


def cache_paths(cache: Path) -> tuple[Path, Path]:
    return cache / "listen.npz", cache / "listen.json"


def save(result: dict, cache: Path) -> None:
    npz, js = cache_paths(cache)
    cache.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(npz, **result["arrays"])
    js.write_text(json.dumps(result["meta"], indent=1) + "\n")


def cached_beat_this(cache: Path) -> dict | None:
    """Beat This!'s beats from the listening kept, whatever grid was made of them."""
    npz, _ = cache_paths(cache)
    if not npz.exists():
        return None
    with np.load(npz) as z:
        if "bt_beats" not in z.files:
            return None
        return {"beats": z["bt_beats"], "downbeats": z["bt_downbeats"]}


def load_cached(cache: Path, grid_fix: dict | None = None) -> dict | None:
    """The listening kept, if it is this version's and was made with this correction of
    the grid (none, unless one is given)."""
    npz, js = cache_paths(cache)
    if not (npz.exists() and js.exists()):
        return None
    meta = json.loads(js.read_text())
    if meta.get("version") != VERSION or meta.get("grid_fix") != grid_.normal_fix(grid_fix):
        return None
    with np.load(npz) as z:
        arrays = {k: z[k] for k in z.files}
    return {"arrays": arrays, "meta": meta}
