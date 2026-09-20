"""The GLSL blocks, written from scratch.

Every block is a fragment of source with a fixed signature, so the composer can
put them together without knowing what any of them does. They are written in the
intersection of GLSL ES 3.00 and desktop GLSL 4.10 core - which is to say: an
explicit `out`, `texture()` rather than `texture2D()`, a `precision` statement,
constant loop bounds, and no integer-to-float slop - so that one body compiles
under both version headers. `compose.py` supplies the header.

Two rules shape everything here.

**Simple things, well modulated.** Four layers: a gradient wash, a few orbiting
discs, a set of soft bands, one ring. That is the entire vocabulary of form. What
makes a frame worth watching is not how much is in it, it is how precisely what is
in it moves with the music - so the effort goes into giving every layer a handful
of inputs that read at a glance (size, distance, softness, hue, brightness) rather
than into drawing more.

**Nothing is a switch.** Every layer is always compiled and always evaluated, at a
weight. A scene is a set of weights; a warp is a set of weights; a post chain is a
set of weights. Any two of them therefore have a straight line between them, and a
section boundary is a place where those numbers start moving rather than a place
where one picture is swapped for another. One shader draws the whole song, and
there is no cut anywhere in it.

The techniques are the standard public ones: signed distance fields, smooth
gradients, cosine palettes, polar folding, frame feedback. None of this source is
derived from Shadertoy or any other CC-licensed collection; the repo is MIT and
stays that way.

Bounded cost is a rule, not a hope: every loop here has a compile-time constant
bound, so a frame's worst case is known once the program is built.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

COMMON = """
const float TAU = 6.2831853;

float hash11(float x) {
    return fract(sin(x * 41.7 + uSeed * 0.031) * 43758.5453);
}

float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21) + uSeed * 0.013);
    p += dot(p, p + 34.56);
    return fract(p.x * p.y);
}

mat2 rot2(float a) {
    float c = cos(a);
    float s = sin(a);
    return mat2(c, -s, s, c);
}

float sdCircle(vec2 p, float r) { return length(p) - r; }

/* A regular n-gon. The hex, triangle and star motifs are all this. */
float sdPoly(vec2 p, float r, float n) {
    float a = atan(p.y, p.x);
    float seg = TAU / n;
    float k = cos(floor(0.5 + a / seg) * seg - a);
    return length(p) * k - r;
}

/* A capsule: the two motifs that point somewhere rather than folding. */
float sdCapsule(vec2 p, float r, float half_len) {
    p.x -= clamp(p.x, -half_len, half_len);
    return length(p) - r;
}

/* One soft edge, and the only place softness is interpreted.

   `soft` runs from a hard line to a pure gradient. At the hard end this is a step
   with an antialiased edge; at the soft end the shape has no edge left at all and
   is only a falloff - which is what lets a section built from exactly the same
   shapes feel like a different piece of music. */
float shade(float d, float soft) {
    float w = 0.004 + soft * soft * 0.85;
    return smoothstep(w, -w * 0.15, d);
}

/* The light a shape throws past its own edge. Wider as the shape softens, so
   softening never just means dimmer. */
float bleed(float d, float soft) {
    float w = 0.05 + soft * 0.75;
    return exp(-max(d, 0.0) / w);
}
"""

# --------------------------------------------------------------------------- #
# Palettes
# --------------------------------------------------------------------------- #

# Cosine palettes: colour = a + b * cos(2pi * (c * t + d)). Four vec3s per family,
# chosen by eye. `mono` has zero chroma, which is why the schema forbids rotating
# it - there would be nothing to rotate.
PALETTES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "ember":   ((0.50, 0.26, 0.18), (0.46, 0.28, 0.16), (1.00, 1.00, 1.00), (0.00, 0.10, 0.20)),
    "ice":     ((0.36, 0.48, 0.60), (0.26, 0.30, 0.36), (1.00, 1.00, 1.00), (0.60, 0.55, 0.45)),
    "neon":    ((0.48, 0.30, 0.54), (0.52, 0.42, 0.58), (1.00, 1.10, 0.90), (0.20, 0.55, 0.85)),
    "mono":    ((0.55, 0.55, 0.55), (0.45, 0.45, 0.45), (1.00, 1.00, 1.00), (0.00, 0.00, 0.00)),
    "verdant": ((0.32, 0.46, 0.36), (0.24, 0.38, 0.24), (1.00, 1.00, 1.00), (0.35, 0.28, 0.55)),
    "dusk":    ((0.42, 0.32, 0.50), (0.36, 0.26, 0.42), (1.00, 0.95, 1.05), (0.85, 0.70, 0.35)),
    "rust":    ((0.46, 0.29, 0.22), (0.40, 0.25, 0.18), (1.00, 0.90, 0.80), (0.10, 0.25, 0.55)),
    "coral":   ((0.56, 0.40, 0.44), (0.40, 0.32, 0.34), (0.95, 1.05, 1.00), (0.15, 0.40, 0.70)),
}


def palette_block(family: str) -> str:
    a, b, c, d = PALETTES[family]
    v = lambda t: f"vec3({t[0]:.4f}, {t[1]:.4f}, {t[2]:.4f})"  # noqa: E731
    return f"""
/* Cosine palette, family "{family}". uPaletteShift places the song in it,
   uPaletteRotate walks it over the song, uHue is whatever a bar routes at it.
   Because uPaletteRotate is ramped rather than stepped, the colour arc is a
   drift through this function and never a change of colour. */
vec3 palette(float t) {{
    t += uPaletteShift + uPaletteRotate + uHue * 0.22;
    return {v(a)} + {v(b)} * cos(TAU * ({v(c)} * t + {v(d)}));
}}
"""


# --------------------------------------------------------------------------- #
# Motif: the one shape a song keeps returning to
# --------------------------------------------------------------------------- #

MOTIFS: dict[str, str] = {
    "circle": "    return sdCircle(p, r);",
    "hex": "    return sdPoly(p, r, 6.0);",
    "triangle": "    return sdPoly(p, r, 3.0);",
    "star": "    return min(sdPoly(p, r, 5.0),\n"
            "               sdPoly(rot2(0.6283) * p, r * 0.62, 5.0));",
    "slot": "    return sdCapsule(p, r * 0.55, r * 0.9);",
    "bar": "    return sdCapsule(p, r * 0.28, r * 1.7);",
}


def motif_block(kind: str) -> str:
    return "float motif(vec2 p, float r) {\n" + MOTIFS[kind].strip("\n") + "\n}\n"


# --------------------------------------------------------------------------- #
# Symmetry, applied once, before anything is drawn. Song-level, so it never has
# to transition.
# --------------------------------------------------------------------------- #

SYMMETRY: dict[str, str] = {
    "none": "    return p;",
    "mirror_x": "    p.x = abs(p.x);\n    return p;",
}
for _n in (3, 5, 6, 8):
    SYMMETRY[f"kaleido_{_n}"] = f"""
    float r = length(p);
    float a = atan(p.y, p.x);
    float seg = TAU / {float(_n):.1f};
    a = mod(a, seg);
    a = abs(a - seg * 0.5);
    return vec2(cos(a), sin(a)) * r;"""


def symmetry_block(kind: str) -> str:
    return "vec2 symmetry(vec2 p) {\n" + SYMMETRY[kind].strip("\n") + "\n}\n"


# --------------------------------------------------------------------------- #
# Warps. Each returns a displaced coordinate, and the composer blends toward it by
# weight - so every one of them has to be the identity at weight zero, and a
# section half way between two warps is a coordinate half way between them.
# --------------------------------------------------------------------------- #

WARPS: dict[str, str] = {
    "swirl": """
vec2 warpSwirl(vec2 p) {
    float r = length(p);
    return rot2(1.5 * exp(-r * 1.3)) * p;
}
""",
    "ripple": """
vec2 warpRipple(vec2 p) {
    float r = length(p) + 1e-4;
    /* On the bar, not only on the clock: a ripple that breathes once a bar is the
       cheapest way for the frame to feel like it knows where it is. */
    float w = sin(r * 7.0 - uBeats * (TAU / 4.0));
    return p * (1.0 + 0.10 * w / r);
}
""",
    "stretch": """
vec2 warpStretch(vec2 p) {
    float r = length(p) + 1e-4;
    float a = atan(p.y, p.x);
    return vec2(cos(a), sin(a)) * pow(r, 0.62);
}
""",
}

WARP_ORDER = ("swirl", "ripple", "stretch")


def warp_blocks() -> str:
    return "".join(WARPS[k] for k in WARP_ORDER)


# --------------------------------------------------------------------------- #
# Layers. Signature: vec3 layerX(vec2 p)
#
# All four are always compiled and always evaluated, at a weight. Each is one
# simple idea, and each takes the routed modulations, so the music reaches every
# layer rather than only the one a section happens to favour.
# --------------------------------------------------------------------------- #

LAYERS: dict[str, str] = {
    # One large gradient across the frame, on an axis that turns slowly. This is
    # the mood, and on its own it is a whole section's worth of picture.
    "wash": """
vec3 layerWash(vec2 p) {
    /* One turn every sixty-four beats, not every so many seconds. */
    float a = uBeats * (TAU / 128.0) + uSpinPhase * 0.25;
    vec2 dir = vec2(cos(a), sin(a));
    float g = dot(p, dir) * (0.45 + 0.40 * uDensity) + 0.5;
    /* Two gradients crossed: one along that axis, one out from the middle. The
       second is what the routed radius gets to move. */
    float r = length(p) * (1.0 - 0.35 * uRadius);
    float fall = smoothstep(1.85, 0.05, r);
    vec3 c = palette(g * 0.55) * fall;
    return c * (0.55 + 0.45 * smoothstep(0.0, 0.6, 1.0 - abs(g - 0.5) * 1.4));
}
""",
    # A few soft discs on slow orbits. The count is the density; the size and the
    # orbit are routed; each carries its own colour out of the palette.
    "orbits": """
vec3 layerOrbits(vec2 p) {
    /* The count is a real number, not an integer, and the last disc fades in
       across the fractional part. Rounding it would mean a whole disc appearing
       in a single frame as the density ramps past a threshold - which is the one
       kind of cut a design with no cuts can still produce by accident. */
    float count = 2.0 + uDensity * 5.99;
    float soft = uSoftness;
    vec3 c = vec3(0.0);
    for (int i = 0; i < ORBIT_MAX; i++) {
        float fi = float(i);
        if (fi >= count) break;
        float w = clamp(count - fi, 0.0, 1.0);
        float k = fi / count;
        float seed = hash11(fi + 3.0);
        float spin = mix(-1.0, 1.0, step(0.5, seed));
        /* A disc completes a turn every eight to thirty-two beats, so the whole
           layer is in phase with the song rather than merely near it. */
        float turns = uBeats / mix(64.0, 16.0, seed) * spin;
        float ang = turns * TAU + k * TAU + uSpinPhase;
        float orbit = (0.22 + 0.62 * k) * (1.0 + 0.45 * uRadius);
        vec2 o = vec2(cos(ang), sin(ang)) * orbit;
        float rad = (0.085 + 0.13 * (1.0 - k)) * (1.0 + 0.55 * uRadius);
        float d = motif(p - o, rad);
        vec3 tint = palette(k * 0.6 + 0.15);
        c += tint * w * (shade(d, soft) + 0.5 * bleed(d, soft));
    }
    return c / sqrt(count);
}
""",
    # Soft parallel bands, travelling. Sines rather than edges, because the point
    # of this layer is to be a gradient that moves.
    "bands": """
vec3 layerBands(vec2 p) {
    float a = 0.35 + uSpinPhase * 0.35 + uBeats * (TAU / 256.0);
    vec2 dir = vec2(cos(a), sin(a));
    float k = 1.2 + 5.5 * uDensity;
    /* One band passes any given point every two beats. */
    float s = dot(p, dir) * k - uBeats * 0.25;
    float band = 0.5 + 0.5 * sin(s * TAU);
    /* Softness is the exponent, so the same bands go from a broad gradient to
       narrow stripes without any of them appearing or disappearing. */
    band = pow(band, 1.0 + 7.0 * (1.0 - uSoftness));
    vec3 c = palette(s * 0.13 + 0.35) * band;
    return c * smoothstep(1.9, 0.2, length(p) * (1.0 - 0.3 * uRadius));
}
""",
    # One ring, breathing. The simplest thing in the vocabulary, and the one that
    # reads a kick most clearly.
    "halo": """
vec3 layerHalo(vec2 p) {
    float r = (0.30 + 0.32 * uDensity) * (1.0 + 0.55 * uRadius);
    float d = motif(p, r);
    float soft = uSoftness;
    float ring = shade(abs(d) - 0.004 - 0.10 * soft, soft * 0.6 + 0.02);
    vec3 c = palette(0.10 + length(p) * 0.35) * ring;
    /* Inside it, a gradient toward the middle rather than a fill: a fill turns to
       mud as soon as the tonemap has had it. */
    c += palette(0.55) * smoothstep(0.0, -0.5, d) * smoothstep(0.0, 0.7, length(p))
         * (0.12 + 0.22 * uDensity);
    c += palette(0.25) * bleed(abs(d), soft) * 0.32;
    return c;
}
""",
}

LAYER_ORDER = ("wash", "orbits", "bands", "halo")


def layer_blocks() -> str:
    return "".join(LAYERS[k] for k in LAYER_ORDER)


# --------------------------------------------------------------------------- #
# Post. Every stage takes a weight and leaves the frame alone at zero, so a post
# chain is a point in a four-dimensional space and two chains have a line between
# them.
#
# All of it runs on a tonemapped frame, in 0..1, which is also what uPrev holds.
# Running it before the tonemap would mean mixing a linear colour with a
# display-space one, and the feedback stages would drift bright and stay there.
# --------------------------------------------------------------------------- #

POST = """
vec3 post(vec3 c, vec2 uv) {
    /* Bloom: four taps on the finished previous frame, which is already a blurred
       copy of roughly what is being drawn now. Total gain well under one, or it
       settles into a flat haze. */
    if (uPostBloom > 0.001) {
        vec3 b = texture(uPrev, uv + vec2(0.0045, 0.0)).rgb
               + texture(uPrev, uv - vec2(0.0045, 0.0)).rgb
               + texture(uPrev, uv + vec2(0.0, 0.0080)).rgb
               + texture(uPrev, uv - vec2(0.0, 0.0080)).rgb;
        c += b * 0.10 * uPostBloom * (0.5 + 0.5 * uEnergy);
    }
    /* Trails: the previous frame, zoomed a hair and decayed, so motion smears
       outward instead of sitting still and never clearing. */
    if (uPostTrails > 0.001) {
        vec2 z = (uv - 0.5) * (1.0 - 0.009 - 0.010 * uScale) + 0.5;
        vec3 prev = texture(uPrev, z).rgb * (0.74 + 0.14 * uEnergy);
        c = mix(c, max(c, prev), uPostTrails);
    }
    /* A radial chromatic split, widening with whatever is routed at it.

       Weighted by uPostSplit rather than merely offset by it. Every stage here
       has to be the identity at weight zero, or a section whose post chain ramps
       this weight down to nothing crosses the branch below and the stage switches
       off in one frame - which is a cut, in a design that has no others. */
    if (uPostSplit > 0.001) {
        vec2 d = (uv - 0.5) * (0.004 + 0.018 * uSplit);
        float rr = texture(uPrev, uv + d).r;
        float bb = texture(uPrev, uv - d).b;
        vec3 split = vec3(max(c.r, rr * 0.75), c.g, max(c.b, bb * 0.75));
        c = mix(c, split, uPostSplit);
    }
    float v = 1.0 - 0.70 * uPostVignette * dot(uv - 0.5, uv - 0.5) * 2.2;
    return c * clamp(v, 0.0, 1.0);
}
"""
