"""The picture: generated from the analysis this project already computes.

Not supplied footage and not a still image. Everything on screen is derived
from the track itself - the mix envelope, the vocal envelope, the tracked beat
and the section list - so the visuals move on the same structure the lyrics do
and cannot drift out of agreement with them.

Four layers, back to front:

    wash     a near-black vertical gradient, tinted by the section
    lobes    three drifting pools of light, hues spread around the section's,
             breathing with the mix and kicking on the beat
    ribbon   a scrolling +/- 6 s window of the mix waveform along the bottom
    grain    a few thousandths of noise, which is what stops the gradient banding

The lyrics are a fifth layer and libass draws them; see karaoke.py.

Generated at output resolution. Half size and let ffmpeg scale was the first
try, on the theory that every layer is a smooth field - but the ribbon is not:
it samples a 120 Hz envelope, and at half width each column had to stand for
two and a bit buckets, which is exactly the condition for aliasing. It crawled.
Full size costs about 20 ms a frame against an encoder that wants 30, so it is
free in wall time, and it fixed the crawl.
"""

from __future__ import annotations

import colorsys
import math
import re
import zlib

import numpy as np

from ..project import Project

WIDTH, HEIGHT = 1280, 720
TAU = 2.0 * math.pi

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

# Three pools of light rather than one. A single radial glow centred in the
# frame is a flat blob however it is animated - it reads as a gradient someone
# reached for, not as a picture. Spread across the frame at different sizes,
# hues and drift periods, they overlap into something with depth, and each one
# can answer to a different part of the track.
#
#   hue offset, saturation, value, half-width, half-height, x drift, y drift
LOBES = (
    (  0.0, 0.66, 0.50, 0.40, 0.30, (0.041, 0.017), (0.029, 0.011)),
    ( 44.0, 0.76, 0.34, 0.26, 0.20, (0.023, 0.053), (0.037, 0.019)),
    (-38.0, 0.70, 0.26, 0.62, 0.13, (0.013, 0.031), (0.007, 0.023)),
)

RIBBON_SECONDS = 6.0     # half-width of the scrolling waveform window
RIBBON_BASE = 0.885      # its centre line, in fractions of frame height
RIBBON_HEIGHT = 0.080    # peak deflection either side
GRAIN = 0.010            # dither amplitude
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


def _palette(hue: float) -> np.ndarray:
    """A section's colours: floor, lit top, then one row per lobe.

    All of them dark. The words are white and they have to win, so the picture
    is lit from behind them rather than in front.
    """
    rows = [_rgb(hue + 10, 0.85, 0.035), _rgb(hue - 10, 0.70, 0.115)]
    rows += [_rgb(hue + off, sat, val) for off, sat, val, *_ in LOBES]
    return np.stack(rows)


def _running_max(values: np.ndarray, width: int) -> np.ndarray:
    """Peak-hold over `width` samples.

    The ribbon resamples a 120 Hz envelope onto one column per pixel. Wherever a
    column has to stand for more than one bucket, picking one and dropping the
    rest means a transient lands in a column on one frame and between two
    columns on the next, and the whole waveform crawls sideways. Holding the
    peak over what each column covers means nothing can fall between them.
    """
    if width <= 1 or values.size < width:
        return values
    pad = width // 2
    padded = np.pad(values, (pad, width - 1 - pad), mode="edge")
    return np.lib.stride_tricks.sliding_window_view(padded, width).max(axis=1)


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

        # Kept one-dimensional. A lobe is a Gaussian, and a Gaussian is
        # separable: exp(-(dx^2 + dy^2)) is exp(-dx^2) times exp(-dy^2). So a
        # pool of light costs two exponentials over w and h values and one
        # outer product, instead of an exponential over every pixel - which is
        # what makes three of them affordable where one squared-distance field
        # was already the most expensive thing in the frame.
        self.ax = (xs - 0.5) * aspect                     # (w,)
        self.ay = ys - 0.5                                # (h,)
        # Lit toward the top, dark at the floor where the ribbon runs. Kept as
        # a column and broadcast at use: the gradient is constant across a row,
        # so storing it width times over would be h*w floats of the same number.
        self.wash = ((1.0 - ys) ** 1.5)[:, None].astype(np.float32)

        radius = self.ax[None, :] ** 2 + self.ay[:, None] ** 2
        self.vignette = (1.0 - 0.58 * np.clip(radius / 0.66, 0, 1) ** 1.25).astype(
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
        # Peak-held to whatever one column covers, then read back with linear
        # interpolation: held so no transient can hide between two columns,
        # interpolated so the shape slides smoothly instead of stepping a column
        # at a time as the window scrolls.
        per_column = self.rate * 2.0 * RIBBON_SECONDS / w
        self.rib_track = _running_max(self.raw_mix, int(round(per_column)))
        self.rib_index = np.arange(self.rib_track.size, dtype=np.float32)

        # Reused every frame. At output resolution these are 2.6 MB apiece and
        # allocating them 8574 times is pure garbage-collector work.
        self._img = np.empty((h, w, 3), dtype=np.float32)
        self._lobe = np.empty((h, w), dtype=np.float32)
        self._tint = np.empty((h, w), dtype=np.float32)

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

    def _colours(self, t: float) -> np.ndarray:
        """The section's colour rows at time t, crossfaded across the boundary."""
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
        return previous + (current - previous) * mix

    def _ribbon(self, t: float) -> np.ndarray:
        """Antialiased mask of the scrolling mix waveform. (h, w) in 0..1."""
        seconds = t + self.rib_offsets
        heights = np.interp(
            seconds * self.rate, self.rib_index, self.rib_track
        ).astype(np.float32) * RIBBON_HEIGHT
        # Nothing sampled beyond the ends of the track: a ribbon that keeps
        # drawing the last six seconds of audio reads as frozen, and np.interp
        # holds its end values rather than running out.
        live = (seconds >= 0.0) & (seconds <= self.rib_track.size / self.rate)
        heights = np.where(live, heights, 0.0)[None, :]
        distance = np.abs(self.rib_y - RIBBON_BASE)
        # Scaled by frame height, so the edge is one pixel of ramp whatever the
        # output size - the whole point of an antialiased edge is that it is a
        # pixel wide, not a fixed fraction of the picture.
        return np.clip((heights - distance) * self.h, 0.0, 1.0)

    # ------------------------------------------------------------- the frame

    def frame(self, t: float) -> np.ndarray:
        palette = self._colours(t)
        deep, mid, lobes = palette[0], palette[1], palette[2:]
        voice = self._at(self.voice, t)
        energy = self._at(self.mix, t)
        pulse = self._pulse(t)

        img, field, tint = self._img, self._lobe, self._tint
        # The floor, lifted toward the top. Written as a column and broadcast:
        # the gradient is constant across a row.
        img[:] = deep + (mid - deep) * self.wash[:, :, None]

        # Each lobe drifts on two periods that share no common multiple, so the
        # field never visibly returns to an arrangement you have already seen.
        # Sizes answer to the mix and the beat; brightness to the voice, which
        # is why the picture opens where the words are.
        breathe = 1.0 + 0.22 * energy + 0.30 * pulse
        light = 0.50 + 0.26 * voice + 0.30 * pulse * (0.4 + 0.6 * energy)
        for (_, _, _, rx, ry, drift_x, drift_y), colour in zip(LOBES, lobes):
            cx = 0.30 * math.sin(t * drift_x[0] * TAU) + 0.13 * math.sin(t * drift_x[1] * TAU)
            cy = 0.20 * math.sin(t * drift_y[0] * TAU + 1.1) + 0.09 * math.sin(t * drift_y[1] * TAU)
            ex = np.exp(-(((self.ax - cx) / (rx * breathe)) ** 2))
            ey = np.exp(-(((self.ay - cy) / (ry * breathe)) ** 2))
            np.multiply(ey[:, None], ex[None, :], out=field)
            for channel in range(3):
                np.multiply(field, colour[channel] * light, out=tint)
                img[:, :, channel] += tint

        ribbon = self._ribbon(t)
        ribbon *= 0.34 + 0.66 * self.rib_x
        for channel in range(3):
            np.multiply(ribbon, mid[channel] * 3.4 + 0.30, out=tint)
            img[:, :, channel] += tint

        img *= self.vignette[:, :, None]
        self._grain = (self._grain + 1) % GRAIN_FIELDS
        img += self.grain[self._grain][:, :, None]
        np.clip(img, 0.0, 1.0, out=img)
        img *= 255.0
        return img.astype(np.uint8)
