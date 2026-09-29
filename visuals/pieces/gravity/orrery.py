"""The solar system's own numbers, and the two compromises that let it be drawn.

What is real here (J2000 elements, NASA/JPL): every planet's semi-major axis,
eccentricity, inclination to the ecliptic, the longitude of its ascending node and of
its perihelion - so each orbit is the oval it is, tipped the way it is, pointing where
it does against the real stars (the shader's plane is the ecliptic, x to the vernal
equinox, the same frame the star catalogue is in). Kepler's equation moves each planet
along its oval, quicker near the Sun. Pluto is here too: steep, lopsided, and inside
Neptune's orbit at perihelion.

What is compressed, because it has to be:

  distance   Neptune is 78 times as far out as Mercury. Drawn to scale the inner four
             are one dot. Distance is drawn on a logarithmic scale - equal ratios are
             equal steps - which keeps the true *pattern*: four close together, a wide
             gap where the asteroids are, four giants spread wide. It is applied to the
             instantaneous distance, so an orbit's eccentricity survives it.
  time       Neptune's year is 685 of Mercury's. It is drawn as 12: periods are raised
             to the power that makes it so (0.38). The order and the feel are right and
             everything still visibly moves in five minutes.
  size       Jupiter is 29 Mercuries across. Radii are raised to the power 0.40: 4 to 1.
"""

from __future__ import annotations

import numpy as np

NAMES = ("Mercury", "Venus", "Earth", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune")
#            a (AU)    e        i (deg)  node (deg) perihelion (deg)  radius (km)  year (years)
ELEMENTS = ((0.38710, 0.20563, 7.0050, 48.331, 77.456, 2439.7, 0.2408),
            (0.72333, 0.00677, 3.3947, 76.680, 131.533, 6051.8, 0.6152),
            (1.00000, 0.01671, 0.0000, 0.000, 102.947, 6371.0, 1.0000),
            (1.52366, 0.09341, 1.8506, 49.558, 336.041, 3389.5, 1.8808),
            (5.20336, 0.04839, 1.3053, 100.556, 14.753, 69911.0, 11.862),
            (9.53707, 0.05415, 2.4845, 113.715, 92.432, 58232.0, 29.457),
            (19.1913, 0.04717, 0.7699, 74.230, 170.964, 25362.0, 84.011),
            (30.0690, 0.00859, 1.7692, 131.722, 44.971, 24622.0, 164.79))
PLUTO = (39.4817, 0.24881, 17.1417, 110.303, 224.067, 1188.3, 247.94)

A, ECC, INC, NODE, PERI, RADIUS, YEAR = (np.array(col) for col in zip(*ELEMENTS))
INC, NODE, PERI = np.radians(INC), np.radians(NODE), np.radians(PERI)

SPAN = 0.440                      # how far beyond Mercury's orbit Neptune's is drawn, in frame heights
SLOWEST = 12.0                    # Neptune's year, in Mercury's
JUPITER_SIZE = 0.0300             # Jupiter's drawn radius, in frame heights at the home distance

_K = SPAN / np.log(A[-1] / A[0])


def displayed(au):
    """How far beyond Mercury's mean orbit a body `au` from the Sun is drawn."""
    return _K * np.log(np.asarray(au, dtype=np.float64) / A[0])


_TIME_POWER = np.log(SLOWEST) / np.log(YEAR[-1] / YEAR[0])


def rate(year: float | np.ndarray = YEAR) -> np.ndarray:
    """Revolutions per revolution of Mercury."""
    return (np.asarray(year) / YEAR[0]) ** -_TIME_POWER


SIZE = JUPITER_SIZE * (RADIUS / RADIUS[4]) ** 0.40
MEAN_STEP = displayed(A)          # each planet's mean orbit, beyond Mercury's
BELTS = ((2.1, 3.3), (39.0, 48.0))   # the asteroid belt and the Kuiper belt, from and to (AU)


def kepler(mean: np.ndarray, ecc: float) -> np.ndarray:
    """True anomaly from mean anomaly, continuous (it never wraps): Newton on Kepler's equation."""
    m = np.asarray(mean, dtype=np.float64)
    e_ = m + ecc * np.sin(m)
    for _ in range(10):
        e_ = e_ - (e_ - ecc * np.sin(e_) - m) / (1.0 - ecc * np.cos(e_))
    nu = 2.0 * np.arctan2(np.sqrt(1 + ecc) * np.sin(e_ / 2), np.sqrt(1 - ecc) * np.cos(e_ / 2))
    return nu + 2 * np.pi * np.round((m - nu) / (2 * np.pi))


def mean_from_true(nu: float, ecc: float) -> float:
    e_ = 2.0 * np.arctan2(np.sqrt(1 - ecc) * np.sin(nu / 2), np.sqrt(1 + ecc) * np.cos(nu / 2))
    return float(e_ - ecc * np.sin(e_))


def track(elements, mean: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Where a body is, given its mean anomaly over time: its longitude in the plane
    (radians, continuous), how far beyond Mercury's mean orbit it is drawn, and its
    height above the plane as a fraction of its drawn distance."""
    a, ecc, inc, node, peri = elements[0], elements[1], np.radians(elements[2]), np.radians(elements[3]), np.radians(elements[4])
    nu = kepler(mean, ecc)
    lon = nu + peri
    au = a * (1 - ecc * ecc) / (1 + ecc * np.cos(nu))
    return lon, displayed(au), np.sin(inc) * np.sin(lon - node)


# ---- gravity ------------------------------------------------------------------------------------
# A kick is the Sun's mass, pulsing. Its pull falls off as the square of the distance, and
# it is not felt everywhere at once: it travels. So Mercury jumps on the beat and Neptune
# stirs three-quarters of a second later, and between them the planets answer in turn.
PULL = 0.0120                      # how far Mercury is drawn in by a full kick, in frame heights
PULL_SPEED = 0.95                  # how fast the pull travels outward, frame heights a second
PULL_RISE = 0.085                  # a planet's answer peaks this long after the pull reaches it


def pull_shape(age: np.ndarray) -> np.ndarray:
    """A planet's answer to the pull, from the moment it arrives: up smoothly, back slowly."""
    x = np.maximum(np.asarray(age, dtype=np.float64), 0.0) / PULL_RISE
    return (x * np.exp(1.0 - x)) ** 2          # squared: it starts from rest, as a mass does


def pull_depth(r: np.ndarray, r_mercury: np.ndarray) -> np.ndarray:
    """How far a body drawn at r is pulled in: inverse-square, of the distances drawn."""
    return PULL * (r_mercury / np.maximum(r, 1e-6)) ** 2
