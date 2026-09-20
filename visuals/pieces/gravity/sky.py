"""The real sky, in a form a fragment shader can look things up in.

The stars are the Yale Bright Star Catalogue (public domain; 9,110 stars to about
magnitude 6.5 - everything a dark site shows the naked eye), fetched once to
`visuals/cache/catalogues/bsc5.dat` from tdc-www.harvard.edu/catalogs/bsc5.dat.gz.

They are not drawn into a picture of the sky. A picture would be sampled, and a
sampled star is a blurred star. Each star stays a direction, a magnitude and a
colour, and the shader draws it as a hard-edged disc wherever the camera happens to
be looking. To find the few stars near a pixel's ray without visiting nine thousand,
the sphere is unfolded onto a square (an octahedral map), the square is cut into
cells, and each cell lists the stars whose discs could touch it. A star near a cell's
edge is listed in both cells - which is the lesson of the star that was cut in half:
whatever draws a star must be able to draw all of it.

World axes are ecliptic: x to the vernal equinox, y to the ecliptic's north pole, so
the solar system lies in y = 0 and the Milky Way crosses it at the angle it does.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

GRID = 64            # cells along each side of the unfolded sphere
PER_CELL = 14        # stars a cell can list: the Milky Way's cells are crowded
FAINTEST = 6.0       # naked-eye limit under a good sky
REACH = np.radians(0.7)   # how far from its centre a star's disc and arms can extend

OBLIQUITY = np.radians(23.4393)


def equatorial_to_ecliptic(ra: np.ndarray, dec: np.ndarray) -> np.ndarray:
    """Unit vectors, world axes: x vernal equinox, y ecliptic north, z completing."""
    x = np.cos(dec) * np.cos(ra)
    y = np.cos(dec) * np.sin(ra)
    z = np.sin(dec)
    ce, se = np.cos(OBLIQUITY), np.sin(OBLIQUITY)
    ye = ce * y + se * z             # equatorial -> ecliptic: rotate about x
    ze = -se * y + ce * z
    return np.stack([x, ze, -ye], axis=-1)       # ecliptic north to world y; right-handed


def galactic_frame() -> dict[str, list[float]]:
    """The galaxy's north pole and the direction of its centre, in world axes (J2000)."""
    pole = equatorial_to_ecliptic(np.radians([192.85948]), np.radians([27.12825]))[0]
    centre = equatorial_to_ecliptic(np.radians([266.40499]), np.radians([-28.93617]))[0]
    centre = centre - pole * float(centre @ pole)
    centre /= np.linalg.norm(centre)
    return {"pole": pole.tolist(), "centre": centre.tolist(), "across": np.cross(pole, centre).tolist()}


def read_bsc(path: Path) -> dict[str, np.ndarray]:
    """Right ascension and declination (J2000, radians), V magnitude, B-V colour."""
    ra, dec, mag, bv = [], [], [], []
    for line in path.read_text(errors="replace").splitlines():
        if len(line) < 107 or not line[75:77].strip() or not line[102:107].strip():
            continue                 # the catalogue keeps a few entries that are not stars
        h, m, s = float(line[75:77]), float(line[77:79]), float(line[79:83])
        sign = -1.0 if line[83] == "-" else 1.0
        d, dm, ds = float(line[84:86]), float(line[86:88]), float(line[88:90])
        ra.append(np.radians(15.0 * (h + m / 60.0 + s / 3600.0)))
        dec.append(sign * np.radians(d + dm / 60.0 + ds / 3600.0))
        mag.append(float(line[102:107]))
        colour = line[109:114].strip()
        bv.append(float(colour) if colour else 0.6)
    return {"ra": np.array(ra), "dec": np.array(dec), "mag": np.array(mag), "bv": np.array(bv)}


def oct_encode(d: np.ndarray) -> np.ndarray:
    """Unit vectors to the unit square. The shader has the same function."""
    d = d / np.abs(d).sum(axis=-1, keepdims=True)
    xz = d[..., [0, 2]]
    lower = d[..., 1] < 0
    folded = (1.0 - np.abs(xz[..., ::-1])) * np.where(xz >= 0, 1.0, -1.0)
    xz = np.where(lower[..., None], folded, xz)
    return xz * 0.5 + 0.5


def build(catalogue: Path) -> dict:
    """The lookup texture: (GRID, GRID * PER_CELL, 4) float32 - direction, and the
    magnitude with the colour class folded in - and the numbers the shader needs."""
    stars = read_bsc(catalogue)
    keep = stars["mag"] <= FAINTEST
    dirs = equatorial_to_ecliptic(stars["ra"][keep], stars["dec"][keep])
    mag, bv = stars["mag"][keep], stars["bv"][keep]
    # colour classes, as the eye sorts them: blue-white, white, yellow-white, amber, red
    colour = np.digitize(bv, [0.0, 0.45, 0.9, 1.4]).astype(np.float64)

    # every cell a star's reach could touch: its centre and a ring of points round it
    ring = []
    for d in dirs:
        a = np.cross(d, [0.0, 1.0, 0.0] if abs(d[1]) < 0.9 else [1.0, 0.0, 0.0])
        a /= np.linalg.norm(a)
        b = np.cross(d, a)
        pts = [d] + [np.cos(REACH) * d + np.sin(REACH) * (np.cos(t) * a + np.sin(t) * b)
                     for t in np.linspace(0, 2 * np.pi, 8, endpoint=False)]
        ring.append(pts)
    cells = np.minimum((oct_encode(np.array(ring)) * GRID).astype(int), GRID - 1)      # (stars, 9, 2)

    tex = np.zeros((GRID, GRID * PER_CELL, 4), dtype=np.float32)
    tex[..., 3] = 99.0                                   # an empty slot: too faint to be anything
    filled = np.zeros((GRID, GRID), dtype=int)
    dropped = 0
    for s in np.argsort(mag):                            # brightest first, so a full cell loses its faintest
        for cx, cy in {(int(c[0]), int(c[1])) for c in cells[s]}:
            k = filled[cy, cx]
            if k >= PER_CELL:
                dropped += 1
                continue
            tex[cy, cx * PER_CELL + k] = (*dirs[s], mag[s] + 100.0 * colour[s])
            filled[cy, cx] = k + 1
    return {"texture": tex, "stars": int(keep.sum()), "dropped_listings": dropped,
            "fullest_cell": int(filled.max()), "galaxy": galactic_frame(),
            "grid": GRID, "per_cell": PER_CELL}


MILKY_WAY = (512, 1024)       # rows (galactic latitude, +90 at the top), columns (longitude, 0 in the middle, increasing leftward)


def milky_way(image: Path) -> np.ndarray:
    """The galaxy's brightness over the whole sky, 0..1, as a smooth field.

    From NASA's Deep Star Maps 2020 (svs.gsfc.nasa.gov/4851, public domain), the
    Milky-Way-only layer in galactic coordinates: the real bulge, the real rift, both
    Magellanic Clouds. It is blurred a little and kept smooth on purpose. The picture
    is not drawn from it - a sampled photograph would be soft - the shader cuts flat
    tones out of it along its contours, so the edges are its own and as sharp as the
    screen, and the shape is the sky's.
    """
    import subprocess

    from scipy import ndimage

    h, w = MILKY_WAY
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(image), "-vf", f"scale={w}:{h}:flags=area",
                          "-pix_fmt", "gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    img = np.frombuffer(raw, dtype=np.uint8).reshape(h, w).astype(np.float64) / 255.0
    # longitude wraps; latitude does not
    img = ndimage.gaussian_filter(img, sigma=(1.6, 1.6), mode=("nearest", "wrap"))
    lo, hi = np.percentile(img, 35), np.percentile(img, 99.7)
    return np.clip((img - lo) / (hi - lo), 0.0, 1.0).astype(np.float32) ** 0.85


def galactic_lb(direction: np.ndarray) -> tuple[float, float]:
    """Galactic longitude and latitude, degrees, of a world-axes direction."""
    g = galactic_frame()
    d = np.asarray(direction, dtype=float)
    b = np.degrees(np.arcsin(np.clip(d @ np.array(g["pole"]), -1, 1)))
    l = np.degrees(np.arctan2(d @ np.array(g["across"]), d @ np.array(g["centre"]))) % 360.0
    return float(l), float(b)
