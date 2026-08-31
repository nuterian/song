"""The picture: generated from the analysis this project already computes.

Not supplied footage and not a still image. Everything on screen is derived
from the track itself - the mix envelope, the vocal envelope, the tracked beat
and the section list - so the visuals move on the same structure the lyrics do
and cannot drift out of agreement with them.

Four layers, back to front:

    wash     a lit vertical gradient, tinted by the section
    lobes    four drifting fields of light - a pool, a column, a band, a spot -
             each answering a different part of the track
    page     a wide soft lift under the corner the words sit in
    trace    three zigzag lines low on the right: bass, mix and air
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
# Four fields, and no two the same shape or driven by the same thing. Three
# ellipses of similar proportion answering one envelope between them read as
# blobs drifting about; a pool, a column, a band and a spot, each with its own
# part of the track under it, read as weather.
#
#   hue offset, saturation, half-width, half-height, strength,
#   x drift, y drift, which signal
LOBES = (
    (   0.0, 0.30, 0.52, 0.40, 0.40, (0.041, 0.017), (0.029, 0.011), "mix"),
    (  52.0, 0.42, 0.15, 0.62, 0.26, (0.023, 0.053), (0.037, 0.019), "high"),
    ( -44.0, 0.38, 0.78, 0.13, 0.30, (0.013, 0.031), (0.007, 0.023), "low"),
    (  22.0, 0.34, 0.24, 0.22, 0.22, (0.037, 0.011), (0.019, 0.043), "voice"),
)

# A wide, soft lightening under the words, so dark type has something to be dark
# against however the picture moves. The alternative is an outline around every
# glyph, which is the ugly way to solve the same problem. Wide and soft enough
# that there is no edge anywhere to notice - it reads as light falling on that
# corner rather than as a panel put there to hold text.
PAGE_X, PAGE_Y = 0.24, 0.92     # its centre, in fractions of the frame
PAGE_W, PAGE_H = 0.50, 0.30     # and how far it reaches
PAGE_LIGHT = 0.34               # how far toward white it lifts

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
TRACE_X = 0.744          # its centre, in fractions of frame width
TRACE_BASE = 0.866       # its rest height, in fractions of frame height
TRACE_REACH = 0.246      # half-length of the visible stroke
TRACE_FADE = 0.072       # how much of each end is spent fading out
TRACE_SPAN = 0.200       # half-width of the part that actually zigzags
TRACE_EDGE = 0.16        # the fraction of each end that ramps into the flat line
TRACE_GAMMA = 0.90       # opens the quiet detail a little, without flattening loud

# Three lines, stacked rather than overlaid, because a peak envelope cannot tell
# a kick from a hi-hat and the difference is most of what a song sounds like.
# Air is fast and fine and sits on top; the mix is the one you read; bass is
# slow and broad and sits underneath. On one shared baseline they were a tangle
# - three zigzags of similar height through each other, legible as none of them.
#
# Teeth are spaced in time rather than in beats, so a faster passage puts more
# of them in front of you. That is where the tempo is.
#
#   signal, teeth, seconds per tooth, offset from the baseline,
#   deflection, stroke px, opacity
TRACES = (
    ("high", 104, 1.0 / 56, -0.055, 0.026, 0.9, 0.55),
    ("mix",   76, 1.0 / 40,  0.000, 0.046, 1.4, 1.00),
    ("low",   28, 1.0 / 13, +0.058, 0.040, 2.4, 0.46),
)

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
    # The fields are light tints and the picture is composited *toward* them,
    # never added to. Adding a saturated colour to a nearly-white area darkens
    # some channel of it, which is where the dark patches drifting around the
    # frame were coming from - they were the pools, doing the opposite of what
    # a pool of light should do.
    rows += [_rgb(hue + off, sat, 0.97) for off, sat, *_ in LOBES]
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


def _running_max(values: np.ndarray, width: int) -> np.ndarray:
    """Peak-hold over `width` samples.

    A tooth stands for more than one analysis bucket, and picking one of them
    and dropping the rest means a transient lands on a tooth in one frame and
    between two in the next - the line crawls. Holding the peak over what each
    tooth covers means nothing can fall between them.
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
        # Barely smoothed. Long windows made the picture answer a bar late,
        # which reads as decoration running alongside the song rather than as
        # something the song is doing. Everything these drive is shallow, so
        # the responsiveness costs no calm.
        self.mix = _envelope(analysis.get("mix_peaks", []), self.rate, 0.05)
        self.voice = _envelope(analysis.get("vocal_peaks", []), self.rate, 0.045)
        # Everything anything here reads, by name. The lines read peaks rather
        # than envelopes - the fields want the average, the lines want what
        # actually happened - and each is peak-held to whatever one of its own
        # teeth covers, so no transient can fall between two of them.
        peaks = _envelope(analysis.get("mix_peaks", []), self.rate, 0.0)
        self.signal = {"mix": self.mix, "voice": self.voice}
        self.detail = {}
        for name, _, lag, *_ in TRACES:
            raw = {"mix": peaks}.get(name)
            if raw is None:
                raw = self._band(beats, name)
            self.signal.setdefault(name, _envelope(raw.tolist(), self.rate, 0.06))
            self.detail[name] = _running_max(
                raw, max(1, round(lag * self.rate))) ** TRACE_GAMMA

        self._load_beats(beats)
        self._load_sections(project)
        self._precompute()

    # ------------------------------------------------------------- setup

    def _band(self, beats: dict, name: str) -> np.ndarray:
        """One of the cached frequency bands, or silence if the cache predates them.

        A beats.json written before the bands existed is still a valid beat
        grid, and a picture with no bass layer is better than a render that
        refuses to start.
        """
        values = np.asarray(beats.get(name, []), dtype=np.float32)
        if values.size:
            return values
        return np.zeros(max(1, int(self.duration * self.rate)), dtype=np.float32)

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

        # --- the traces
        # Only the rows the lines can reach are ever touched. The band is a
        # seventh of the frame, and a stroke computed over the whole picture is
        # six sevenths wasted - which is what makes three of them affordable
        # where one was already the second most expensive thing in the frame.
        top = min(off - height for *_, off, height, _, _ in TRACES)
        bottom = max(off + height for *_, off, height, _, _ in TRACES)
        top = int((TRACE_BASE + top) * h) - 3
        floor = int((TRACE_BASE + bottom) * h) + 3
        self.band = slice(max(0, top), min(h, floor))
        self.band_y = (ys[self.band] * h)[:, None].astype(np.float32)
        self.columns = xs * w
        # How much of the stroke is drawn at each column: solid across the
        # middle, easing to nothing over the last stretch at either end. This is
        # what gives the lines no ends to notice.
        edge = np.clip((TRACE_REACH - np.abs(xs - TRACE_X)) / TRACE_FADE, 0.0, 1.0)
        self.trace_alpha = (edge * edge * (3.0 - 2.0 * edge)).astype(np.float32)[None, :]

        self.teeth = {}
        for name, count, lag, *_ in TRACES:
            # Full height across the middle and ramping only at the very ends,
            # so the outline of a line is its waveform rather than a spindle the
            # waveform has been poured into.
            ramp = np.clip(
                np.minimum(np.linspace(0.0, 1.0, count, dtype=np.float32),
                           np.linspace(1.0, 0.0, count, dtype=np.float32))
                / TRACE_EDGE, 0.0, 1.0)
            taper = ramp * ramp * (3.0 - 2.0 * ramp)
            self.teeth[name] = (
                np.linspace(TRACE_X - TRACE_SPAN, TRACE_X + TRACE_SPAN,
                            count, dtype=np.float32) * w,
                # Alternating, which is what makes it a zigzag rather than a curve.
                (taper * np.where(np.arange(count) % 2, 1.0, -1.0)).astype(np.float32),
                # Each tooth reads a little further back than the one before it,
                # so the shape ripples left to right instead of moving as one.
                ((np.arange(count, dtype=np.float32) - count / 2.0) * lag),
            )
        self.env_index = np.arange(self.detail["mix"].size, dtype=np.float32)

        # Static, so it is built once. Separable like a lobe: a column of light
        # times a row of it.
        self.page = (
            np.exp(-(((ys - PAGE_Y) / PAGE_H) ** 2))[:, None]
            * np.exp(-(((xs - PAGE_X) / PAGE_W) ** 2))[None, :]
        ).astype(np.float32) * PAGE_LIGHT

        # Reused every frame. At output resolution these are 2.6 MB apiece and
        # allocating them 8574 times is pure garbage-collector work.
        self._img = np.empty((h, w, 3), dtype=np.float32)
        self._lobe = np.empty((h, w), dtype=np.float32)
        self._tint = np.empty((h, w), dtype=np.float32)
        self._band_tint = np.empty((self.band.stop - self.band.start, w), np.float32)

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

    def _trace(self, t: float, name: str, offset: float, height: float,
               weight: float) -> np.ndarray:
        """One thin zigzag line, over the band rows only. (band, w) in 0..1.

        Drawn as a stroke rather than a filled shape, and fixed in place rather
        than scrolling: what it shows is the song right now, not a window of its
        history sliding past.
        """
        at, shape, lag = self.teeth[name]
        track = self.detail[name]
        teeth = np.interp((t + lag) * self.rate,
                          self.env_index[:track.size], track).astype(np.float32)
        path = np.interp(self.columns, at, teeth * shape * (height * self.h))
        path = path.astype(np.float32) + (TRACE_BASE + offset) * self.h

        # A steep segment is longer than the column it crosses, so measuring the
        # distance to it vertically would draw it thinner. Dividing by the slope
        # term measures perpendicular instead, and the stroke keeps one weight
        # all the way along.
        slope = np.gradient(path)
        stroke = np.abs(self.band_y - path[None, :])
        stroke /= (weight * np.sqrt(1.0 + slope * slope))[None, :]
        np.subtract(1.0, stroke, out=stroke)
        np.clip(stroke, 0.0, 1.0, out=stroke)
        stroke *= self.trace_alpha
        return stroke

    # ------------------------------------------------------------- the frame

    def frame(self, t: float) -> np.ndarray:
        energy = self._at(self.mix, t)
        pulse = self._pulse(t)

        # Colour answers the mix directly. Sliding between two palettes a few
        # degrees apart is what makes the room feel lit by the track rather
        # than painted once per section.
        quiet, loud = self._colours(t)
        palette = quiet + (loud - quiet) * energy
        deep, mid, fields, trace = palette[0], palette[1], palette[2:6], palette[6]

        img, field, tint = self._img, self._lobe, self._tint
        # The floor, lifted toward the top. Written as a column and broadcast:
        # the gradient is constant across a row.
        img[:] = deep + (mid - deep) * self.wash[:, :, None]

        # Each field drifts on two periods that share no common multiple, so the
        # arrangement never visibly returns to one you have seen. The depths are
        # small deliberately - the signals underneath are barely smoothed, so a
        # large depth on top of them would twitch rather than breathe.
        shiver = SHIVER * energy
        for (_, _, rx, ry, gain, drift_x, drift_y, name), colour in zip(LOBES, fields):
            level = self._at(self.signal[name], t)
            breathe = 1.0 + 0.16 * level + 0.07 * pulse
            cx = 0.30 * math.sin(t * drift_x[0] * TAU) + 0.13 * math.sin(t * drift_x[1] * TAU)
            cy = 0.20 * math.sin(t * drift_y[0] * TAU + 1.1) + 0.09 * math.sin(t * drift_y[1] * TAU)
            cx += shiver * math.sin(t * SHIVER_RATE * TAU + rx * 40.0)
            cy += shiver * math.cos(t * SHIVER_RATE * TAU * 0.83 + ry * 40.0)
            ex = np.exp(-(((self.ax - cx) / (rx * breathe)) ** 2))
            ey = np.exp(-(((self.ay - cy) / (ry * breathe)) ** 2))
            np.multiply(ey[:, None], ex[None, :], out=field)
            field *= gain * (0.42 + 0.58 * level)
            # Toward the field's colour, never added to it: adding a saturated
            # colour to a nearly-white area darkens some channel of it, and the
            # dark patches drifting round the frame were the pools themselves.
            for channel in range(3):
                np.subtract(colour[channel], img[:, :, channel], out=tint)
                tint *= field
                img[:, :, channel] += tint

        # Toward white rather than added, so the lift under the words is the
        # same amount of contrast wherever the picture happens to be bright.
        for channel in range(3):
            np.subtract(1.0, img[:, :, channel], out=tint)
            tint *= self.page
            img[:, :, channel] += tint

        # Composited, not added. The lines are darker than the picture they sit
        # on and adding a dark colour to a light one lightens it: the trace was
        # drawn correctly and invisibly for a while on that mistake.
        band = img[self.band]
        for name, _, _, offset, height, weight, opacity in TRACES:
            # Every line brightens on the beat, harder on the first of the bar.
            # That is where the tempo is: the rate at which they flicker.
            stroke = self._trace(t, name, offset, height, weight)
            stroke *= opacity * (0.62 + 0.30 * self._at(self.signal[name], t)
                                 + 0.24 * pulse)
            for channel in range(3):
                np.multiply(stroke, band[:, :, channel] - trace[channel],
                            out=self._band_tint)
                band[:, :, channel] -= self._band_tint

        self._grain = (self._grain + 1) % GRAIN_FIELDS
        img += self.grain[self._grain][:, :, None]
        np.clip(img, 0.0, 1.0, out=img)
        img *= 255.0
        return img.astype(np.uint8)
