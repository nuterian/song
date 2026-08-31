"""The picture: generated from the analysis this project already computes.

Not supplied footage and not a still image. Everything on screen is derived
from the track itself - the mix envelope, the vocal envelope, the tracked beat
and the section list - so the visuals move on the same structure the lyrics do
and cannot drift out of agreement with them.

Four layers, back to front:

    wash     a lit vertical gradient, tinted by the section
    lobes    three drifting pools of light, hues spread around the section's
    trace    one thin zigzag line low on the right, deflecting with the amplitude
    grain    a few thousandths of noise, which is what stops the gradient banding

Lit to the corners, and lit throughout. There is no vignette and no dark floor:
both are how you make a frame look like a spotlight in a black room, and this
wants to look like daylight through frosted glass. The base is already a colour
you could read against; the pools shade and warm it rather than rescuing it.

Sensitive, and quiet with it. The envelopes are barely smoothed, so the picture
answers the track within a frame or two of a transient - but every depth it
drives is small, so what you see is a room breathing rather than anything
flashing. Colour moves the same way: each section carries two palettes a few
degrees and a little brightness apart, and the mix envelope slides between
them.

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
    (  0.0, 0.34, 0.26, 0.50, 0.40, (0.041, 0.017), (0.029, 0.011)),
    ( 46.0, 0.44, 0.19, 0.34, 0.26, (0.023, 0.053), (0.037, 0.019)),
    (-40.0, 0.40, 0.15, 0.74, 0.18, (0.013, 0.031), (0.007, 0.023)),
)

# A fast, tiny wobble on top of the slow drift, its size set by how loud the
# track is right now. A couple of pixels at most: not a movement you watch, a
# movement you would only notice if it stopped.
SHIVER = 0.011
SHIVER_RATE = 9.7

# How far the loud palette is from the quiet one. Small on purpose: the point is
# that the colour is never quite still, not that it changes.
HUE_LIFT = 14.0
VALUE_LIFT = 1.30

# One line, low and to the right, opposite the words. It has no ends: the stroke
# fades out into the picture well before it would reach an edge, so it reads as
# an instrument sitting in the frame rather than as a rule drawn across it.
TRACE_X = 0.752          # its centre, in fractions of frame width
TRACE_BASE = 0.866       # its rest height, in fractions of frame height
TRACE_HEIGHT = 0.062     # deflection at full amplitude
TRACE_REACH = 0.222      # half-length of the visible stroke
TRACE_FADE = 0.070       # how much of each end is spent fading out
TRACE_SPAN = 0.176       # half-width of the part that actually zigzags
# One tooth per two analysis buckets, off an envelope smoothed at 12 ms - close
# enough to the peaks themselves that the line has the track's texture in it and
# not a rolling average of it. Coarser teeth over a wider lag made a spindle:
# regular, symmetrical and the same shape in every loud passage.
TRACE_TEETH = 62
TRACE_LAG = 0.0166       # seconds between one tooth's sample and the next
TRACE_WEIGHT = 1.7       # stroke, in pixels

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
    rows = [_rgb(hue + 12, 0.50, 0.360), _rgb(hue - 8, 0.36, 0.545)]
    rows += [_rgb(hue + off, sat, val) for off, sat, val, *_ in LOBES]
    rows.append(_rgb(hue + 6, 0.55, 0.22))       # the trace, darker than its ground
    return np.stack(rows)


def _palettes(hue: float) -> np.ndarray:
    """The quiet and loud versions of one section, stacked.

    Two whole palettes rather than a hue shift applied at render time, because
    the crossfade between sections has to interpolate colours and it is much
    easier to be sure of that when there is only ever one kind of colour to
    interpolate.
    """
    return np.stack([_palette(hue), _palette(hue + HUE_LIFT) * VALUE_LIFT])


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
        # Barely smoothed. Long windows made the picture answer a bar late,
        # which reads as decoration running alongside the song rather than as
        # something the song is doing. Everything these drive is shallow, so
        # the responsiveness costs no calm.
        self.mix = _envelope(analysis.get("mix_peaks", []), self.rate, 0.05)
        self.voice = _envelope(analysis.get("vocal_peaks", []), self.rate, 0.045)
        # The trace reads its own, barely-smoothed copy: the field wants an
        # envelope, the line wants the detail.
        self.detail = _envelope(analysis.get("mix_peaks", []), self.rate, 0.012)

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
        self.section_colour: list[np.ndarray] = []

        starts = {ln.index: ln.start for ln in project.lines if ln.end > ln.start}
        for section in project.sections:
            times = [starts[i] for i in section.line_indices if i in starts]
            if not times:
                continue
            first = min(times)
            earlier = self.beat_times[self.beat_times <= first - 0.5]
            self.section_at.append(float(earlier[-1]) if earlier.size else first)
            self.section_colour.append(_palettes(_hue(section.name)))

        if not self.section_colour:
            self.section_at = [0.0]
            self.section_colour = [_palettes(HUES["verse"])]
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
        # Lit toward the top, a little deeper along the floor. Gentle, because
        # the whole frame is meant to read as lit. Kept as a column and broadcast
        # at use: the gradient is constant across a row, so storing it width
        # times over would be h*w floats of the same number.
        self.wash = ((1.0 - ys) ** 0.85)[:, None].astype(np.float32)

        # --- the trace
        self.pixel_y = (ys * h)[:, None].astype(np.float32)
        self.columns = xs * w
        # How much of the stroke is drawn at each column: solid across the
        # middle, easing to nothing over the last stretch at either end. This is
        # what gives it no ends to notice.
        edge = (TRACE_REACH - np.abs(xs - TRACE_X)) / TRACE_FADE
        edge = np.clip(edge, 0.0, 1.0)
        self.trace_alpha = (edge * edge * (3.0 - 2.0 * edge)).astype(np.float32)[None, :]
        # Where each tooth sits, and how far its deflection is allowed to go.
        # A raised cosine, so the zigzag grows out of the flat line and settles
        # back into it rather than starting and stopping at a corner.
        self.teeth_x = np.linspace(
            TRACE_X - TRACE_SPAN, TRACE_X + TRACE_SPAN, TRACE_TEETH, dtype=np.float32
        )
        taper = 0.5 - 0.5 * np.cos(
            np.linspace(0.0, 2.0 * np.pi, TRACE_TEETH, dtype=np.float32)
        )
        # Alternating, which is what makes it a zigzag rather than a curve.
        self.teeth_shape = (taper * np.where(np.arange(TRACE_TEETH) % 2, 1.0, -1.0)
                            ).astype(np.float32)
        # Each tooth reads the envelope a little further back than the one
        # before it, so the shape ripples left to right instead of every tooth
        # moving as one.
        self.teeth_lag = (np.arange(TRACE_TEETH, dtype=np.float32)
                          - TRACE_TEETH / 2.0) * TRACE_LAG
        self.teeth_pixels = self.teeth_x * w
        self.env_index = np.arange(self.detail.size, dtype=np.float32)

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

    def _trace(self, t: float) -> np.ndarray:
        """One thin zigzag line across the frame. (h, w) in 0..1.

        Drawn as a stroke rather than a filled band, and fixed in place rather
        than scrolling: the shape is the amplitude of the song right now, not
        six seconds of its history sliding past.
        """
        teeth = np.interp(
            (t + self.teeth_lag) * self.rate, self.env_index, self.detail
        ).astype(np.float32)
        deflection = teeth * self.teeth_shape * (TRACE_HEIGHT * self.h)
        # The path, one y per pixel column, straight between teeth.
        path = np.interp(self.columns, self.teeth_pixels, deflection).astype(np.float32)
        path += TRACE_BASE * self.h

        # A steep segment is longer than the column it crosses, so measuring the
        # distance to it vertically would draw it thinner. Dividing by the slope
        # term measures perpendicular instead, and the stroke keeps one weight
        # all the way along.
        slope = np.gradient(path)
        weight = TRACE_WEIGHT * np.sqrt(1.0 + slope * slope)

        stroke = np.abs(self.pixel_y - path[None, :])
        stroke /= weight[None, :]
        np.subtract(1.0, stroke, out=stroke)
        np.clip(stroke, 0.0, 1.0, out=stroke)
        stroke *= self.trace_alpha
        return stroke

    # ------------------------------------------------------------- the frame

    def frame(self, t: float) -> np.ndarray:
        voice = self._at(self.voice, t)
        energy = self._at(self.mix, t)
        pulse = self._pulse(t)

        # Colour answers the mix directly. Sliding between two palettes a few
        # degrees apart is what makes the room feel lit by the track rather
        # than painted once per section.
        quiet, loud = self._colours(t)
        palette = quiet + (loud - quiet) * energy
        deep, mid, lobes, trace = palette[0], palette[1], palette[2:5], palette[5]

        img, field, tint = self._img, self._lobe, self._tint
        # The floor, lifted toward the top. Written as a column and broadcast:
        # the gradient is constant across a row.
        img[:] = deep + (mid - deep) * self.wash[:, :, None]

        # Each lobe drifts on two periods that share no common multiple, so the
        # field never visibly returns to an arrangement you have already seen.
        # The depths are small deliberately - the envelopes underneath are
        # barely smoothed, so a large depth on top of them would twitch.
        breathe = 1.0 + 0.10 * energy + 0.07 * pulse
        shiver = SHIVER * energy
        light = 0.72 + 0.16 * voice + 0.12 * pulse * (0.4 + 0.6 * energy)
        for (_, _, _, rx, ry, drift_x, drift_y), colour in zip(LOBES, lobes):
            cx = 0.30 * math.sin(t * drift_x[0] * TAU) + 0.13 * math.sin(t * drift_x[1] * TAU)
            cy = 0.20 * math.sin(t * drift_y[0] * TAU + 1.1) + 0.09 * math.sin(t * drift_y[1] * TAU)
            cx += shiver * math.sin(t * SHIVER_RATE * TAU + rx * 40.0)
            cy += shiver * math.cos(t * SHIVER_RATE * TAU * 0.83 + ry * 40.0)
            ex = np.exp(-(((self.ax - cx) / (rx * breathe)) ** 2))
            ey = np.exp(-(((self.ay - cy) / (ry * breathe)) ** 2))
            np.multiply(ey[:, None], ex[None, :], out=field)
            for channel in range(3):
                np.multiply(field, colour[channel] * light, out=tint)
                img[:, :, channel] += tint

        # Composited, not added. The line is darker than the picture it sits on
        # and adding a dark colour to a light one lightens it: the trace was
        # drawn correctly and invisibly for a while on that mistake.
        stroke = self._trace(t)
        stroke *= 0.55 + 0.45 * energy
        for channel in range(3):
            np.multiply(stroke, img[:, :, channel] - trace[channel], out=tint)
            img[:, :, channel] -= tint

        self._grain = (self._grain + 1) % GRAIN_FIELDS
        img += self.grain[self._grain][:, :, None]
        np.clip(img, 0.0, 1.0, out=img)
        img *= 255.0
        return img.astype(np.uint8)
