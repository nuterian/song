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


# ---------------------------------------------------------------------------------------------
# The deep sky: every star to magnitude 7.5 with its distance and its constellation (the HYG
# database v4.1, astronexus, CC BY-SA: Hipparcos, Yale and Gliese merged), and the clusters,
# nebulae, galaxies and supernova remnants anyone has heard of (OpenNGC, CC BY-SA), each at
# its true place and its true size on the sky.
#
# One lookup texture, as before: the sphere unfolded to a square, cut into cells, each cell
# listing what could touch it, brightest first. A texel is a direction and one packed number:
#
#     stars   mag + 2  (0 .. 9.99)  + 100 x colour class (0..4) + 1000 x nearness (0..9)
#                                   + 10000 x which turn of the hats its constellation takes (0..2)
#     deep    brightness (0 .. 9.99) + 100 x 9                  + 1000 x kind (0..5)
#                                   + 10000 x size class (0..7)
#
# Nearness is what makes the depth of the sky visible. A near star is drawn crisper and a
# little larger, with glints at a fainter magnitude; a far one is a fine point. And near
# stars shift against far ones as the camera turns: there is no such parallax from inside
# the solar system (the nearest star is 270,000 times as far as the Sun), so this is art,
# not astronomy, and it is slight - a third of a degree for the very nearest.

DEEP_GRID = 96
DEEP_PER_CELL = 12
DEEP_FAINTEST = 7.5
PARALLAX = np.radians(0.34)                    # how far the very nearest star shifts, each way
KINDS = {"galaxy": 0, "open": 1, "globular": 2, "nebula": 3, "planetary": 4, "remnant": 5}
SIZE_CLASSES = np.radians(np.array([3.0, 5.0, 8.0, 13.0, 20.0, 32.0, 50.0, 75.0]) / 60.0)   # radius on the sky, per class
_NGC_KIND = {"G": "galaxy", "GPair": "galaxy", "GGroup": "galaxy", "OCl": "open", "*Ass": "open", "GCl": "globular",
             "Neb": "nebula", "HII": "nebula", "EmN": "nebula", "RfN": "nebula", "Cl+N": "nebula",
             "PN": "planetary", "SNR": "remnant"}
_ALSO = {"NGC0869", "NGC0884", "NGC5139", "NGC0104", "NGC3372", "NGC7293", "NGC6960", "NGC6992", "NGC7000",
         "NGC2070", "NGC2237", "NGC2264", "NGC0253", "NGC5128", "NGC4755", "NGC3532", "IC2602", "NGC2516", "IC0434"}


def nearness(parsecs: np.ndarray) -> np.ndarray:
    """0 (far: 300 parsecs and beyond) to 9 (the nearest few): steps of equal ratio."""
    d = np.clip(np.asarray(parsecs, dtype=np.float64), 1.3, 300.0)
    return np.round(9.0 * (1.0 - np.log(d / 1.3) / np.log(300.0 / 1.3)))


def read_hyg(path: Path) -> dict[str, np.ndarray]:
    import csv

    ra, dec, mag, ci, dist, con = [], [], [], [], [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["id"] == "0" or not row["mag"] or float(row["mag"]) > DEEP_FAINTEST:
                continue
            ra.append(np.radians(15.0 * float(row["ra"]))); dec.append(np.radians(float(row["dec"])))
            mag.append(float(row["mag"])); ci.append(float(row["ci"]) if row["ci"] else 0.6)
            d = float(row["dist"]) if row["dist"] else 1e5
            dist.append(d if d < 9e4 else 1e5)                      # 100000 is the catalogue's "unknown": far
            con.append(row["con"])
    return {"ra": np.array(ra), "dec": np.array(dec), "mag": np.array(mag), "bv": np.array(ci),
            "dist": np.array(dist), "con": np.array(con)}


def read_openngc(*paths: Path) -> list[dict]:
    """The objects worth drawing: everything Messier catalogued, anything brighter than
    magnitude 7, and a short list of famous southern and faint ones he never saw."""
    import csv

    out = []
    for path in paths:
        if not path.exists():
            continue
        with open(path, newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                kind = _NGC_KIND.get(row["Type"])
                if kind is None or not row["RA"] or not row["Dec"]:
                    continue
                vmag = float(row["V-Mag"]) if row["V-Mag"] else (float(row["B-Mag"]) if row["B-Mag"] else 99.0)
                if not (row["M"] or vmag <= 7.0 or row["Name"] in _ALSO):
                    continue
                h, m, sec = (float(x) for x in row["RA"].split(":"))
                sign = -1.0 if row["Dec"].startswith("-") else 1.0
                d, dm, ds = (float(x) for x in row["Dec"].lstrip("+-").split(":"))
                major = float(row["MajAx"]) if row["MajAx"] else 4.0
                out.append({"name": row["Name"], "kind": kind, "ra": np.radians(15 * (h + m / 60 + sec / 3600)),
                            "dec": sign * np.radians(d + dm / 60 + ds / 3600), "mag": min(vmag, 9.5),
                            "radius": np.radians(0.5 * major / 60.0), "messier": row["M"], "common": row["Common names"]})
    return out


def _ring_of(d: np.ndarray, reach: float, points: int = 8) -> list[np.ndarray]:
    a = np.cross(d, [0.0, 1.0, 0.0] if abs(d[1]) < 0.9 else [1.0, 0.0, 0.0])
    a /= np.linalg.norm(a)
    b = np.cross(d, a)
    return [d] + [np.cos(reach) * d + np.sin(reach) * (np.cos(t) * a + np.sin(t) * b)
                  for t in np.linspace(0, 2 * np.pi, points, endpoint=False)]


def build_deep(hyg: Path, *ngc: Path) -> dict:
    stars = read_hyg(hyg)
    dirs = equatorial_to_ecliptic(stars["ra"], stars["dec"])
    colour = np.digitize(stars["bv"], [0.0, 0.45, 0.9, 1.4]).astype(np.float64)
    near = nearness(stars["dist"])
    names = sorted(set(stars["con"]))
    turn = np.array([(names.index(c) * 7 + 1) % 3 for c in stars["con"]], dtype=np.float64)     # a constellation twinkles together
    packed = (stars["mag"] + 2.0) + 100.0 * colour + 1000.0 * near + 10000.0 * turn
    # how far from its centre anything of a star's can be: its disc and arms, and its parallax
    reach = np.where(stars["mag"] < 2.6, np.radians(0.75), np.where(stars["mag"] < 5.0, np.radians(0.28), np.radians(0.10))) \
        + PARALLAX * near / 9.0
    entries = [(stars["mag"][i], dirs[i], packed[i], reach[i]) for i in range(len(packed))]

    deep = read_openngc(*ngc)
    for o in deep:
        d = equatorial_to_ecliptic(np.array([o["ra"]]), np.array([o["dec"]]))[0]
        size = int(np.argmin(np.abs(np.log(SIZE_CLASSES / max(o["radius"], SIZE_CLASSES[0])))))
        o["size_class"] = size
        entries.append((o["mag"] - 6.0,                        # listed ahead of the faint stars of its cell
                        d, (9.99 - min(max(o["mag"], 0.0), 9.99)) + 100.0 * 9 + 1000.0 * KINDS[o["kind"]] + 10000.0 * size,
                        float(SIZE_CLASSES[size]) * 1.25))

    tex = np.zeros((DEEP_GRID, DEEP_GRID * DEEP_PER_CELL, 4), dtype=np.float32)
    filled = np.zeros((DEEP_GRID, DEEP_GRID), dtype=int)
    dropped = 0
    for rank, d, w, r in sorted(entries, key=lambda e_: e_[0]):
        pts = np.array(_ring_of(d, r, 8) + (_ring_of(d, 0.5 * r, 6)[1:] if r > np.radians(0.6) else []))
        cells = np.minimum((oct_encode(pts) * DEEP_GRID).astype(int), DEEP_GRID - 1)
        for cx, cy in {(int(c[0]), int(c[1])) for c in cells}:
            k = filled[cy, cx]
            if k >= DEEP_PER_CELL:
                dropped += 1
                continue
            tex[cy, cx * DEEP_PER_CELL + k] = (*d, w)
            filled[cy, cx] = k + 1
    return {"texture": tex, "stars": len(packed), "deep": deep, "dropped_listings": dropped,
            "fullest_cell": int(filled.max()), "mean_listed": float(filled.mean())}

