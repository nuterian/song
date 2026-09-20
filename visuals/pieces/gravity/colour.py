"""Colour, chosen and moved in OKLCH, handed to the shader as linear RGB.

A palette is a few roles - field, far field, body, accent, second accent - each a
lightness, a chroma and a hue. Hue is an angle, so a ramp between two palettes
goes the short way round it, at constant-ish lightness, and never through grey:
that is what OKLCH buys over lerping RGB, where blue to orange passes through mud.

Everything here is a level on the 120 Hz grid, low-passed before it is baked, so
no palette change can be a step however abrupt the decision behind it was.
"""

from __future__ import annotations

import numpy as np

ROLES = ("field", "far", "body", "accent", "accent2")


def oklch_to_linear_rgb(L: np.ndarray, C: np.ndarray, h: np.ndarray) -> np.ndarray:
    """OKLCH (h in turns) to linear sRGB, gamut-clipped by pulling chroma in."""
    L, C, h = (np.asarray(v, dtype=np.float64) for v in np.broadcast_arrays(L, C, h))

    def convert(chroma):
        a = chroma * np.cos(2 * np.pi * h)
        b = chroma * np.sin(2 * np.pi * h)
        l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
        m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
        s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
        return np.stack([
            4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
            -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
            -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
        ], axis=-1)

    # Out of gamut: keep the hue and the lightness, give up chroma. Eight halvings
    # of a bisection is closer than a screen can show.
    lo, hi = np.zeros_like(C), C.copy()
    rgb = convert(C)
    bad = (rgb.min(axis=-1) < -1e-4) | (rgb.max(axis=-1) > 1.0 + 1e-4)
    if bad.any():
        for _ in range(10):
            mid = 0.5 * (lo + hi)
            test = convert(mid)
            out = (test.min(axis=-1) < -1e-4) | (test.max(axis=-1) > 1.0 + 1e-4)
            hi = np.where(bad & out, mid, hi)
            lo = np.where(bad & ~out, mid, lo)
        rgb = np.where(bad[..., None], convert(lo), rgb)
    return np.clip(rgb, 0.0, 1.0)


def unwrap_turns(h: np.ndarray) -> np.ndarray:
    """A hue track in turns, made continuous so that smoothing goes the short way."""
    return np.unwrap(np.asarray(h, dtype=np.float64) * 2 * np.pi) / (2 * np.pi)


def hold_then_ramp(values: np.ndarray, starts: np.ndarray, n: int, rate: float,
                   ramp_seconds: float, circular: bool = False) -> np.ndarray:
    """Piecewise-constant decisions, turned into a track with no steps in it.

    `values[k]` holds from `starts[k]`. The steps are then low-passed twice with a
    box of `ramp_seconds`, which makes each change an S-curve centred on the
    boundary - it starts moving before the bar line and arrives after it, the way a
    lighting change is called. Hues are unwrapped first so red to violet does not go
    round through green.
    """
    from scipy import ndimage

    v = np.asarray(values, dtype=np.float64)
    if circular:
        v = unwrap_turns(v)
    idx = np.clip(np.searchsorted(np.asarray(starts) * rate, np.arange(n), side="right") - 1,
                  0, len(v) - 1)
    track = v[idx]
    w = max(1, int(ramp_seconds * rate / 2))
    for _ in range(2):
        track = ndimage.uniform_filter1d(track, w, mode="nearest")
    return track
