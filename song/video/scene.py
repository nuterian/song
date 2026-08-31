"""The picture: generated from the analysis this project already computes.

Not supplied footage and not a still image. Everything on screen is derived
from the track itself - the mix envelope, the vocal envelope, the tracked beat
and the section list - so the visuals move on the same structure the lyrics do
and cannot drift out of agreement with them.

Four layers, back to front:

    wash     a two-tone vertical gradient, hue chosen per section
    bloom    a soft radial glow that kicks on every beat and opens with the voice
    ribbon   a scrolling +/- 6 s window of the mix waveform along the bottom
    grain    a few thousandths of noise, which is what stops the gradient banding

The lyrics are a fifth layer and libass draws them; see karaoke.py.

Frames are generated at a fraction of the output size and scaled up by ffmpeg.
Every layer here is a smooth field, so upscaling costs nothing visible, while
rendering a quarter of the pixels costs a quarter of the time - and the text,
burned after the scale, is still drawn at full resolution.
"""

from __future__ import annotations

import colorsys
import re
import zlib

import numpy as np

from ..project import Project

WIDTH, HEIGHT = 640, 360

# Hue per section, keyed on the name rather than the index so every chorus is
# the same colour and the picture repeats when the song does. "Chorus" and
# "Final Chorus" are the same room; the eye learns that in one listen.
HUES = {
    "intro": 202,
    "pre": 268,     # before "chorus", so "Pre-Chorus" is its own colour
    "chorus": 336,
    "hook": 344,
    "drop": 350,
    "refrain": 330,
    "verse": 214,
    "bridge": 168,
    "break": 186,
    "outro": 196,
}

RIBBON_SECONDS = 6.0     # half-width of the scrolling waveform window
RIBBON_BASE = 0.885      # its centre line, in fractions of frame height
RIBBON_HEIGHT = 0.085    # peak deflection either side
GRAIN = 0.008            # dither amplitude
GRAIN_FIELDS = 8         # cycled so the noise moves instead of sitting still


def _hue(name: str) -> float:
    key = re.sub(r"[^a-z]+", " ", name.lower())
    for token, hue in HUES.items():
        if token in key:
            return float(hue)
    # An unheard-of section name still needs a stable colour, and it has to be
    # stable across processes - Python's hash() is salted per run, so the same
    # track would come out a different colour every render.
    return (zlib.crc32(key.encode()) * 137.508) % 360.0


def _rgb(hue: float, sat: float, val: float) -> np.ndarray:
    r, g, b = colorsys.hsv_to_rgb((hue % 360.0) / 360.0, sat, val)
    return np.array([r, g, b], dtype=np.float32)


def _palette(hue: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One section's three colours: the floor, the lit top, and what the bloom adds.

    All of them dark. The words are white and they have to win, so the picture
    is lit from behind rather than in front of them.
    """
    return (
        _rgb(hue + 8, 0.78, 0.045),
        _rgb(hue - 14, 0.60, 0.24),
        _rgb(hue - 30, 0.34, 1.00),
    )


def _envelope(peaks: list[float], rate: int, seconds: float) -> np.ndarray:
    """Smooth an amplitude track and rescale it so its loud parts reach 1.

    The peaks are normalized against the single loudest sample in the file, so
    a track with one clipped transient reads as quiet everywhere. The 95th
    percentile is the level the song actually spends its time near.
    """
    values = np.asarray(peaks, dtype=np.float32)
    if values.size == 0:
        return np.zeros(1, dtype=np.float32)
    width = max(1, int(round(seconds * rate)))
    if width > 1:
        kernel = np.hanning(width + 2)[1:-1].astype(np.float32)
        values = np.convolve(values, kernel / kernel.sum(), mode="same")
    loud = float(np.percentile(values, 95)) or 1.0
    return np.clip(values / loud, 0.0, 1.0).astype(np.float32)


class Scene:
    def __init__(
        self,
        project: Project,
        analysis: dict,
        beats: dict,
        width: int = WIDTH,
        height: int = HEIGHT,
    ):
        self.w, self.h = width, height
        self.duration = float(project.duration)

        self.rate = int(analysis.get("rate", 120))
        self.mix = _envelope(analysis.get("mix_peaks", []), self.rate, 0.16)
        self.voice = _envelope(analysis.get("vocal_peaks", []), self.rate, 0.10)
        # Un-smoothed, for the ribbon: the whole point of it is the detail.
        self.raw_mix = np.asarray(analysis.get("mix_peaks", [0.0]), dtype=np.float32)

        self._load_beats(beats)
        self._load_sections(project)
        self._precompute()

    # ------------------------------------------------------------- setup

    def _load_beats(self, beats: dict) -> None:
        times = np.asarray(beats.get("beats", []), dtype=np.float32)
        if times.size < 2:
            # Nothing tracked - a spoken word track, or a fade with no drums in
            # it. Weight zero, so the picture is driven by the envelopes alone
            # rather than by one invented tempo that is wrong for the whole song.
            self.beat_times = np.array([0.0, max(self.duration, 1.0)], dtype=np.float32)
            self.beat_gap = np.ones(2, dtype=np.float32)
            self.beat_weight = np.zeros(2, dtype=np.float32)
            return
        self.beat_times = times
        self.beat_gap = np.diff(times, append=times[-1] + float(np.median(np.diff(times))))
        meter = int(beats.get("meter", 4)) or 4
        phase = int(beats.get("phase", 0))
        index = np.arange(times.size)
        # A bar start hits harder than the three beats after it - that is the
        # difference between motion that has a pulse and motion that ticks.
        self.beat_weight = np.where((index - phase) % meter == 0, 1.0, 0.55).astype(
            np.float32
        )

    def _load_sections(self, project: Project) -> None:
        """Where the colour changes, and to what.

        A section's colour arrives on the last downbeat before its first line
        rather than on the line itself, so the change lands with the music
        instead of a beat and a half after it.
        """
        self.section_at: list[float] = []
        self.section_colour: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []

        starts = {ln.index: ln.start for ln in project.lines if ln.end > ln.start}
        for section in project.sections:
            times = [starts[i] for i in section.line_indices if i in starts]
            if not times:
                continue
            first = min(times)
            earlier = self.beat_times[self.beat_times <= first - 0.5]
            self.section_at.append(float(earlier[-1]) if earlier.size else first)
            self.section_colour.append(_palette(_hue(section.name)))

        if not self.section_colour:
            self.section_at = [0.0]
            self.section_colour = [_palette(HUES["verse"])]
        # The intro belongs to whatever comes first; there is nothing else it
        # could belong to, and fading up from black would waste a verse of it.
        self.section_at[0] = 0.0

    def _precompute(self) -> None:
        w, h = self.w, self.h
        aspect = w / h
        xs = np.linspace(0.0, 1.0, w, dtype=np.float32)
        ys = np.linspace(0.0, 1.0, h, dtype=np.float32)

        self.ax = ((xs - 0.5) * aspect)[None, :]          # (1, w)
        self.ay = (ys - 0.5)[:, None]                     # (h, 1)
        # Lit toward the top, dark at the floor where the ribbon runs. Kept as
        # a column and broadcast at use: the gradient is constant across a row,
        # so storing it width times over would be h*w floats of the same number.
        self.wash = ((1.0 - ys) ** 1.5)[:, None].astype(np.float32)

        radius = self.ax ** 2 + self.ay ** 2
        self.vignette = (1.0 - 0.62 * np.clip(radius / 0.62, 0, 1) ** 1.25).astype(
            np.float32
        )

        self.rib_y = ys[:, None]
        # "Now" is the middle column, so brighten it and let the rest fall off.
        self.rib_x = np.exp(-(((xs - 0.5) / 0.085) ** 2)).astype(np.float32)[None, :]
        # Where in the mix envelope each ribbon column samples from, as an
        # offset in seconds from the playhead.
        self.rib_offsets = np.linspace(
            -RIBBON_SECONDS, RIBBON_SECONDS, w, dtype=np.float32
        )

        self._grain = 0
        rng = np.random.default_rng(0xB3A7)
        self.grain = (
            rng.random((GRAIN_FIELDS, h, w), dtype=np.float32) - 0.5
        ) * GRAIN

    # ------------------------------------------------------------- sampling

    def _at(self, track: np.ndarray, t: float) -> float:
        i = int(t * self.rate)
        return float(track[min(max(i, 0), track.size - 1)])

    def _pulse(self, t: float) -> float:
        """How recently a beat landed, 1 at the hit and decaying to ~0 by the next."""
        i = int(np.searchsorted(self.beat_times, t, side="right")) - 1
        if i < 0:
            return 0.0
        i = min(i, self.beat_times.size - 1)
        gap = float(self.beat_gap[i]) or 0.5
        phase = (t - float(self.beat_times[i])) / gap
        return float(np.exp(-3.4 * phase)) * float(self.beat_weight[i])

    def _colours(self, t: float):
        """Section colours at time t, crossfaded across the boundary."""
        i = 0
        for k, at in enumerate(self.section_at):
            if t >= at - 0.6:
                i = k
        if i == 0:
            return self.section_colour[0]
        edge = self.section_at[i]
        mix = float(np.clip((t - (edge - 0.6)) / 1.2, 0.0, 1.0))
        # smoothstep: a linear crossfade shows its two corners.
        mix = mix * mix * (3.0 - 2.0 * mix)
        previous, current = self.section_colour[i - 1], self.section_colour[i]
        return tuple(a + (b - a) * mix for a, b in zip(previous, current))

    def _ribbon(self, t: float) -> np.ndarray:
        """Antialiased mask of the scrolling mix waveform. (h, w) in 0..1."""
        idx = np.clip(
            ((t + self.rib_offsets) * self.rate).astype(np.int32),
            0,
            self.raw_mix.size - 1,
        )
        heights = self.raw_mix[idx] * RIBBON_HEIGHT
        # Nothing sampled beyond the ends of the track: a ribbon that keeps
        # drawing the last frame of audio for six seconds reads as frozen.
        live = (t + self.rib_offsets >= 0) & (
            t + self.rib_offsets <= self.raw_mix.size / self.rate
        )
        heights = np.where(live, heights, 0.0).astype(np.float32)[None, :]
        distance = np.abs(self.rib_y - RIBBON_BASE)
        return np.clip((heights - distance) * (self.h * 0.9), 0.0, 1.0)

    # ------------------------------------------------------------- the frame

    def frame(self, t: float) -> np.ndarray:
        deep, mid, glow = self._colours(t)
        voice = self._at(self.voice, t)
        energy = self._at(self.mix, t)
        pulse = self._pulse(t)

        column = deep[None, None, :] + (mid - deep)[None, None, :] * self.wash[:, :, None]
        img = np.broadcast_to(column, (self.h, self.w, 3)).copy()

        # The bloom drifts on two periods that do not divide into each other, so
        # it never visibly loops back to where it started.
        cx = 0.16 * np.sin(t * 0.21) + 0.05 * np.sin(t * 0.53)
        cy = -0.04 + 0.10 * np.sin(t * 0.13 + 1.2)
        spread = 0.19 * (1.0 + 0.55 * energy) * (1.0 + 0.30 * pulse)
        falloff = ((self.ax - cx) ** 2 + (self.ay - cy) ** 2) / (spread + 1e-4)
        strength = 0.10 + 0.34 * voice + 0.30 * pulse * (0.4 + 0.6 * energy)
        img += glow[None, None, :] * (np.exp(-falloff) * strength)[:, :, None]

        ribbon = self._ribbon(t) * (0.34 + 0.66 * self.rib_x)
        img += (mid * 1.6 + 0.22)[None, None, :] * ribbon[:, :, None]

        img *= self.vignette[:, :, None]
        self._grain = (self._grain + 1) % GRAIN_FIELDS
        img += self.grain[self._grain][:, :, None]
        return (np.clip(img, 0.0, 1.0) * 255.0).astype(np.uint8)
