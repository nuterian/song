"""Nothing is instant; everything arrives on the beat.

The piece used to say "light is instant": a flash or a ring appeared whole on its frame.
On its frame it was - and it strobed. Because every channel is baked from a song that is
already known, a movement can *begin before* its sound and *peak on* it: eased in, eased
out, with no corner anywhere. That is smoother and no less tight - the eye takes the peak
for the moment, and the peak is where the sound is.

    bezier(x1, y1, x2, y2)   a CSS-style cubic Bezier easing curve, as a function on 0..1
    envelope(...)            a level: for each event, ease up over `lead` to peak on it,
                             ease down over `fall`; overlapping events take the larger
    advance(...)             make held event channels (time, size, ...) show up early, so
                             a shader that knows an event's true time can ease toward it
    smooth(...)              take the corners off a level without moving it in time
"""

from __future__ import annotations

import numpy as np

from .direct import RATE

LEAD = 0.090          # how long before its sound a drawn event begins to arrive, seconds


def bezier(x1: float, y1: float, x2: float, y2: float):
    """The easing curve through (0,0), (x1,y1), (x2,y2), (1,1): y as a function of x."""
    s = np.linspace(0.0, 1.0, 2049)
    bx = 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s ** 2 * x2 + s ** 3
    by = 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s ** 2 * y2 + s ** 3

    def ease(x):
        return np.interp(np.clip(x, 0.0, 1.0), bx, by)
    return ease


# The house curves. Both ends of each are flat, so joined end to end they have no corner.
EASE_IN = bezier(0.45, 0.0, 0.55, 1.0)          # arriving: slow off the mark, slow onto the peak
EASE_OUT = bezier(0.12, 0.0, 0.30, 1.0)         # leaving: lets go of the peak gently, then goes, then a long tail
EASE_SLOW = bezier(0.35, 0.0, 0.25, 1.0)        # a large, heavy thing


def envelope(times, amps, n: int, lead: float, fall: float, rise=EASE_IN, fade=EASE_OUT, soften: float = 0.040) -> np.ndarray:
    """A level at RATE. Each event eases up over `lead` seconds to `amp` exactly at its
    time, then eases down to nothing over `fall`. Where events overlap, the larger - and
    where one event's rise overtakes another's fall there would be a corner, so the whole
    is softened over `soften` seconds (centred: nothing is delayed)."""
    out = np.zeros(n)
    k_up, k_down = max(int(round(lead * RATE)), 1), max(int(round(fall * RATE)), 1)
    shape = np.concatenate([rise(np.arange(k_up + 1) / k_up), 1.0 - fade(np.arange(1, k_down + 1) / k_down)])
    # Softening a shape that rises faster than it falls moves its top a sample or so later.
    # It is measured, and the shape set that much earlier: the top is on the event.
    late = int(np.argmax(_soften(np.pad(shape, 4 * k_up), soften))) - 4 * k_up - k_up if soften > 0 else 0
    k_up += late
    for t, a in zip(np.asarray(times, dtype=np.float64), np.asarray(amps, dtype=np.float64)):
        i0 = int(round(t * RATE)) - k_up
        lo, hi = max(i0, 0), min(i0 + len(shape), n)
        if hi > lo:
            out[lo:hi] = np.maximum(out[lo:hi], a * shape[lo - i0:hi - i0])
    return _soften(out, soften) if soften > 0 else out


def _soften(x: np.ndarray, seconds: float) -> np.ndarray:
    k = max(int(seconds * RATE / 2), 1)
    box = np.ones(k) / k
    y = np.pad(x, 2 * k, mode="edge")
    return np.convolve(np.convolve(y, box, mode="same"), box, mode="same")[2 * k:len(x) + 2 * k]


def advance(data: np.ndarray, columns: list[int], lead: float = LEAD) -> None:
    """Held event channels, in place: every change in them happens `lead` seconds sooner.
    The *values* are untouched - an event's time is still its true time - so a shader sees
    an event coming (its age is negative) and can ease toward it."""
    k = int(round(lead * RATE))
    for c in columns:
        data[:-k, c] = data[k:, c]


def smooth(x: np.ndarray, seconds: float) -> np.ndarray:
    """A box filter run twice, centred: corners become curves; nothing is delayed."""
    k = max(int(seconds * RATE / 2), 1)
    box = np.ones(k) / k
    y = np.pad(np.asarray(x, dtype=np.float64), 2 * k, mode="edge")
    return np.convolve(np.convolve(y, box, mode="same"), box, mode="same")[2 * k:-2 * k]
