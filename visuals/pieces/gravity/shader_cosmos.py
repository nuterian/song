"""The solar system, cel-shaded, seen the way an orrery is: in parallel projection.

This began as a perspective ray tracer and was taken back, because the perspective
was the problem: through a lens a sphere away from the centre of the frame is an egg,
the plane of the orbits runs off to a horizon, and everything changes size as the
camera moves. The picture that worked was orthographic - circles stay circles, orbits
are clean ellipses - so this one is too, and it is built outward from that picture:
with the camera in its fixed mode it has the same Sun, the same spacing of orbits and
the same sizes of planet as `shader_ink`.

The camera still moves, the way an orrery's does: it turns about the Sun, tilts over
the plane, rolls, zooms and slides (`uCamTurn`, `uCamTilt`, `uCamRoll`, `uCamSpan`,
`uCamX/Y`). None of that distorts anything. The sky is the one thing seen through a
lens, because it is infinitely far and has to be.

What is real: the planets' order, character and colours; their orbits - each the oval
it is, tipped out of the plane as it is, pointing where it does against the real stars,
run by Kepler's equation (`orrery`, which also says what is compressed: distance on a
log scale, years to 12:1, sizes to 4:1); gravity that falls off as the square of the
distance and travels; Pluto; Jupiter's four moons in their 1:2:4 resonance; Titan in
the plane of the rings; one light, at the origin, so phases and
terminators are where they should be; the Moon, Io and Ganymede, Titan; Saturn's
rings, tilted 26.7 degrees and fixed in space, with the planet's shadow across them;
the asteroid belt between Mars and Jupiter and the Kuiper belt beyond Neptune; five
thousand naked-eye stars from the Yale Bright Star Catalogue at their true places,
magnitudes and colours; and the Milky Way, cut in flat tones out of NASA's all-sky map
- its real bulge, its real rift, both Magellanic Clouds.

Nothing changes colour with the song. For a while the song's palette was in the
*light* - corona, ripples, the voice's ring - and a green corona is not the solar
system. The colours are the solar system's and they stay: a warm Sun and corona, light
that is gold going to white, shadow and sky the deep blue of space. The song animates.

Ripples lie in the plane of the orbits: a clap's ring, a planet's ping and pool, the
voice's ring and the re-entry's shock are circles in the ecliptic, seen as ellipses,
on the axis of the gravity they ride. No orbit is drawn; each planet leaves a short
trail that fades behind it.

Light is instant; mass is not. A flash or a ring lands on its frame. The Sun's swell,
a planet's swell and the tug on the orbits arrive *on* the hit having begun a
twentieth of a second before it (`uSunPulse`, `uSwell*`, baked with look-ahead).

Anti-aliasing is not an afterthought here, because it was the other problem. Every
edge is resolved against the size of a pixel *where that edge is*: a limb by its
distance in pixels, a terminator and a continent's coast by how much of the sphere a
pixel covers, a ring in the plane by the plane's foreshortening, a tone of the Milky
Way by the field's own gradient on screen. Nothing is thinner than about a pixel, so
nothing crawls when the camera moves.
"""

from __future__ import annotations

from . import orrery, sky
from .direct import N_METEORS, N_RINGS, N_SATS, PALETTE_ROLES

GL_HEADER = "#version 410 core\n"
WEBGL_HEADER = "#version 300 es\n"

VERTEX_BODY = """
precision highp float;
layout(location = 0) in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
"""

TEXTURES = ("uStarTex", "uGalaxyTex")
N_PLANETS = 8
# Which slot of notes (ranked low to high) lights which planet: big bodies take the low
# notes, as big things do. Mercury .. Neptune.
SLOT_TO_PLANET = (4, 5, 7, 6, 2, 1, 3, 0)
_PLANET_SLOT = [SLOT_TO_PLANET.index(i) for i in range(N_PLANETS)]
# how far out each planet sits beyond the innermost orbit; the outer four stand off
# beyond the asteroid belt. These are the spacings of the picture that worked.
# The inner four keep that picture's spacing; the giants are given room, because a
# ringed Saturn is not a dot and they have to be able to stand in a row.
# Distances, sizes and the orbits' shapes are the solar system's, compressed as `orrery` says.
ORBIT_STEP = [float(x) for x in orrery.MEAN_STEP]      # each planet's mean orbit, beyond Mercury's
PLANET_SIZE = [float(x) for x in orrery.SIZE]
# The mean colour of each planet's surface as `surface()` paints it, measured by
# `surface_means()` (a test holds the two together). A planet's trail is this colour, and
# so is the glow of its night side - Earth's is sea, land, ice and cloud together, which
# is a paler blue than its sea.
PLANET_TINT = [(0.577, 0.541, 0.511), (0.924, 0.783, 0.487), (0.426, 0.646, 0.726), (0.772, 0.384, 0.233),
               (0.820, 0.649, 0.487), (0.884, 0.764, 0.509), (0.580, 0.865, 0.900), (0.203, 0.364, 0.864)]
N_PROM = 4            # prominences in flight: the bass line's notes
N_WIND = 4            # gusts of solar wind in flight: the voice's syllables
N_FLARE = 2           # flares in flight: the corona's discharges
# (inner edge beyond Mercury's orbit, lane width, lanes). The asteroids lie from 2.1 to 3.3 AU
# in three lanes - the gaps between them are Kirkwood's, swept clear by Jupiter; the Kuiper
# belt from 39 to 48 AU.
BELTS = ((float(orrery.displayed(2.1)), float(orrery.displayed(3.3) - orrery.displayed(2.1)) / 3, 3),
         (float(orrery.displayed(39.0)), float(orrery.displayed(48.0) - orrery.displayed(39.0)) / 2, 2))


def _scalars(prefix: str, count: int, suffix: str = "") -> str:
    return "\n".join(f"uniform float {prefix}{k}{suffix};" for k in range(count))


def _gather(prefix: str, count: int, suffix: str = "") -> str:
    return f"float[{count}](" + ", ".join(f"{prefix}{k}{suffix}" for k in range(count)) + ")"


def _floats(values) -> str:
    return ", ".join(f"{float(v):.5f}" for v in values)


def _palette_uniforms() -> str:
    return "\n".join(f"uniform float uC{role}R, uC{role}G, uC{role}B;" for role in PALETTE_ROLES)


def _vec3(v) -> str:
    return "vec3(" + ", ".join(f"{float(x):.7f}" for x in v) + ")"


_G = sky.galactic_frame()

FRAGMENT_BODY = f"""
precision highp float;
precision highp sampler2D;
layout(location = 0) out vec4 fragColor;

uniform vec2 uResolution;
uniform float uTime;
uniform float uSS;                 // supersampling: render pixels per output pixel, along a side (unset = 1)
uniform sampler2D uStarTex;
uniform sampler2D uGalaxyTex;

uniform float uMass, uKickT, uKickA, uBass, uSunPulse;
uniform float uHold, uSpreadSlow, uOrbitSlow;
uniform float uHatT, uHatA, uHatK;
uniform float uVoice, uPitch, uSyllT, uSyllA, uSustain;
uniform float uTint, uTintR, uTintG, uTintB;
uniform float uField, uExposure, uStars, uBeats, uRays;
uniform float uDropT, uDropA, uCrashT, uCrashA;
uniform float uCamTurn, uCamTilt, uCamRoll, uCamSpan, uCamX, uCamY;
uniform float uTall;               // 1 in the tall frame, whose camera is the wide frame's turned and 16/9 as far off (unset = 0)
uniform float uWiden;              // how many of the frame's heights the picture is high: more than 1 where it goes on round the frame (unset = 1)
{_palette_uniforms()}
{_scalars("uRingT", N_RINGS)}
{_scalars("uRingA", N_RINGS)}
{_scalars("uRingM", N_RINGS)}
{_scalars("uNoteT", N_SATS)}
{_scalars("uNoteA", N_SATS)}
{_scalars("uNoteM", N_SATS)}
{_scalars("uLean", N_PLANETS)}
{_scalars("uHop", N_PLANETS)}
{_scalars("uGlow", N_PLANETS)}
{_scalars("uBig", N_PLANETS)}
{_scalars("uSwing", N_PLANETS)}
{_scalars("uSpin", N_PLANETS)}
{_scalars("uPingT", N_PLANETS)}
{_scalars("uPingA", N_PLANETS)}
uniform float uKickE, uSyllE, uHatE0, uHatE1, uHatE2, uCrashE, uOpened, uFlashE;   // eased levels: each peaks on its sound
{_scalars("uMetT", N_METEORS)}
{_scalars("uMetA", N_METEORS)}
{_scalars("uMetS", N_METEORS)}
{_scalars("uPh", N_PLANETS)}
{_scalars("uPd", N_PLANETS)}
{_scalars("uPz", N_PLANETS)}
uniform float uPlutoPh, uPlutoD, uPlutoZ;
{_scalars("uPromT", N_PROM)}
{_scalars("uPromA", N_PROM)}
{_scalars("uPromK", N_PROM)}
{_scalars("uWindT", N_WIND)}
{_scalars("uWindA", N_WIND)}
{_scalars("uWindK", N_WIND)}
{_scalars("uFlareT", N_FLARE)}
{_scalars("uFlareA", N_FLARE)}
{_scalars("uFlareK", N_FLARE)}
uniform float uCharge;             // the corona's charge, 0..1: at 1 the next bass note on a beat discharges it
uniform float uBrace;              // the bar before a re-entry: 0 -> 1, and gone on the downbeat

const float PI = 3.14159265359;
const float TAU = 6.28318530718;
const int N_PROM = {N_PROM};
const int N_FLARE = {N_FLARE};
const int N_WIND = {N_WIND};
const int N_RINGS = {N_RINGS};
const int N_SATS = {N_SATS};
const int N_METEORS = {N_METEORS};
const int N_PLANETS = {N_PLANETS};
const int STAR_GRID = {sky.DEEP_GRID};
const int STAR_PER_CELL = {sky.DEEP_PER_CELL};
const float PARALLAX = {sky.PARALLAX:.6f};          // how far the very nearest star shifts as the camera goes round: art, not astronomy
const float DEEP_SIZE[8] = float[8]({_floats(sky.SIZE_CLASSES)});   // a deep-sky object's radius on the sky, by size class
const ivec2 GALAXY_SIZE = ivec2({sky.MILKY_WAY[1]}, {sky.MILKY_WAY[0]});
const float ORBIT_STEP[N_PLANETS] = float[{N_PLANETS}]({_floats(ORBIT_STEP)});
// each orbit's shape, for its trail: eccentricity, where its perihelion and its ascending
// node point, the sine of its inclination, and the log of its semi-latus rectum over
// Mercury's mean distance - distance is drawn on a log scale (K_MAP per e-fold)
const float ORB_ECC[N_PLANETS] = float[{N_PLANETS}]({_floats(orrery.ECC)});
const float ORB_PERI[N_PLANETS] = float[{N_PLANETS}]({_floats(orrery.PERI)});
const float ORB_NODE[N_PLANETS] = float[{N_PLANETS}]({_floats(orrery.NODE)});
const float ORB_SINI[N_PLANETS] = float[{N_PLANETS}]({_floats(__import__("numpy").sin(orrery.INC))});
const float ORB_LOGP[N_PLANETS] = float[{N_PLANETS}]({_floats(__import__("numpy").log(orrery.A * (1 - orrery.ECC ** 2) / orrery.A[0]))});
const float K_MAP = {orrery._K:.6f};
const float PULL = {orrery.PULL:.5f};
const float LEAD = {__import__("visuals.pieces.gravity.ease", fromlist=["LEAD"]).LEAD:.4f};          // held events show up this long before their sound
const float PLANET_SIZE[N_PLANETS] = float[{N_PLANETS}]({_floats(PLANET_SIZE)});
const int PLANET_SLOT[N_PLANETS] = int[{N_PLANETS}]({", ".join(str(x) for x in _PLANET_SLOT)});
const vec3 PLANET_TINT[N_PLANETS] = vec3[{N_PLANETS}]({", ".join(_vec3(c) for c in PLANET_TINT)});
// An orchestra, not a chorus: each planet answers its note in its own way. How many rings it
// throws, how far (in its own radii), how quickly they open (seconds), how wide its pool.
// Mercury flicks; Venus, all atmosphere, blooms; Earth rings twice; Mars is dry and quick;
// Jupiter rolls out three; Saturn's answer is in its rings; Uranus rings once, wide;
// Neptune is slow and far-reaching. All of it in the plane of the orbits.
const int   PING_N[N_PLANETS]     = int[{N_PLANETS}](1, 1, 2, 1, 3, 0, 1, 1);
const float PING_REACH[N_PLANETS] = float[{N_PLANETS}](2.2, 2.0, 2.6, 2.3, 2.5, 0.0, 2.8, 3.6);
const vec3 GAL_POLE = {_vec3(_G["pole"])};
const vec3 GAL_CENTRE = {_vec3(_G["centre"])};
const vec3 GAL_ACROSS = {_vec3(_G["across"])};
// Saturn's pole, in (along the plane, along the plane, up): 26.7 degrees off the
// ecliptic's and fixed in space, so the rings open and close as it goes round
const vec3 RING_POLE = vec3(0.3853, 0.2312, 0.8934);
const vec3 RING_U = normalize(cross(RING_POLE, vec3(0.0, 0.0, 1.0)));      // two directions in the plane of Saturn's rings
const vec3 RING_V = cross(RING_POLE, normalize(cross(RING_POLE, vec3(0.0, 0.0, 1.0))));
const vec3 BELT0 = vec3({BELTS[0][0]:.4f}, {BELTS[0][1]:.4f}, {BELTS[0][2]:.1f});
const vec3 BELT1 = vec3({BELTS[1][0]:.4f}, {BELTS[1][1]:.4f}, {BELTS[1][2]:.1f});
const float SKY_LENS = 1.30;                 // focal length of the sky's lens, in frame heights: about 42 degrees

// ------------------------------------------------------------- hashes and noise

float hash11(float p) {{ p = fract(p * 0.1031); p *= p + 33.33; p *= p + p; return fract(p); }}
float hash12(vec2 p) {{
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}}
vec2 hash22(vec2 p) {{
    vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.xx + p3.yz) * p3.zy);
}}
float hash13(vec3 p3) {{
    p3 = fract(p3 * 0.1031);
    p3 += dot(p3, p3.zyx + 31.32);
    return fract((p3.x + p3.y) * p3.z);
}}
float valueNoise(vec3 p) {{
    vec3 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash13(i), hash13(i + vec3(1, 0, 0)), f.x),
                   mix(hash13(i + vec3(0, 1, 0)), hash13(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(hash13(i + vec3(0, 0, 1)), hash13(i + vec3(1, 0, 1)), f.x),
                   mix(hash13(i + vec3(0, 1, 1)), hash13(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}}
// two octaves: large, slow shapes only. Nothing in this picture has fine texture.
float soft(vec3 p) {{ return (valueNoise(p) + 0.5 * valueNoise(p * 2.03 + 7.1)) / 1.5; }}

mat2 rot2(float a) {{ float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }}
float hit(float age, float tau) {{ return age < 0.0 ? 0.0 : exp(-age / tau); }}
vec3 vivid(vec3 c, float k) {{
    float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
    return clamp(mix(vec3(l), c, k), 0.0, 1.0);
}}
// Sizes are in *output* pixels - a star is as big in a frame rendered at twice the size
// and scaled down as in one rendered straight - and edges are resolved in *render*
// pixels. gAA is a render pixel, in output pixels: 1, unless supersampling.
float gAA = 1.0;
// an edge at x = at, resolved over `w` either side: w is an output pixel's worth of x
float edge(float at, float x, float w) {{ return smoothstep(at - w * gAA, at + w * gAA, x); }}
// coverage of a disc of radius rPx (or a band of half-width rPx about zero); d in output pixels
float disc(float dPx, float rPx) {{ return 1.0 - smoothstep(rPx - 0.55 * gAA, rPx + 0.55 * gAA, dPx); }}

// Nothing is instant; everything arrives on the beat. `age` is time since the sound (held
// events are shown LEAD early, so it starts negative): 0 until `lead` before it, eased up
// to 1 exactly on it, eased away to 0 by `fall` after - quick to let go, then a long tail.
// Flat at both ends and at the top: no corner anywhere.
float sstep(float x) {{ x = clamp(x, 0.0, 1.0); return x * x * x * (x * (6.0 * x - 15.0) + 10.0); }}
float arrive(float age, float lead, float fall) {{
    if (age <= -lead || age >= fall) return 0.0;
    return age < 0.0 ? sstep(1.0 + age / lead) : 1.0 - sstep(pow(age / fall, 0.62));
}}

// Light bent by a ripple of gravity: a point in the frame, pushed straight out from the
// Sun where a wavefront (one a kick's, one a re-entry's) is passing it. Amplitudes and
// radii in frame heights. What is drawn there keeps its shape; only where it is changes.
vec2 lensed(vec2 at, vec2 sun, float a1, float r1, float a2, float r2) {{
    vec2 dv = at - sun;
    float dist = length(dv) + 1e-5;
    float g1 = (dist - r1) / 0.050, g2 = (dist - r2) / 0.100;
    return at + dv / dist * (a1 * exp(-g1 * g1) + a2 * exp(-g2 * g2));
}}

// From the plane of the orbits (u, v) and height above it, to the screen and to depth
// toward the viewer; e and c are the sine and cosine of the camera's height over the plane.
vec3 toView(vec3 w, float e, float c) {{ return vec3(w.x, w.y * e + w.z * c, -w.y * c + w.z * e); }}
vec3 fromView(vec3 v, float e, float c) {{ return vec3(v.x, v.y * e - v.z * c, v.y * c + v.z * e); }}

// A circle of radius R lying in the plane, about a point whose screen offset from this
// pixel is dq: coverage of a line `halfPx` pixels wide along it. The plane is
// foreshortened by e, so a pixel is worth more of the plane up-screen than across.
float planeRing(vec2 dq, float e, float R, float halfPx, float pxScene) {{
    float rho = length(vec2(dq.x, dq.y / e));
    float grad = length(vec2(dq.x, dq.y / (e * e))) / max(rho, 1e-6);
    return disc(abs(rho - R) / (max(grad, 1e-4) * pxScene), halfPx);
}}

// ---------------------------------------------------------------------- the sky

vec2 octEncode(vec3 d) {{
    d /= abs(d.x) + abs(d.y) + abs(d.z);
    vec2 xz = d.xz;
    if (d.y < 0.0) xz = (1.0 - abs(xz.yx)) * vec2(xz.x >= 0.0 ? 1.0 : -1.0, xz.y >= 0.0 ? 1.0 : -1.0);
    return xz * 0.5 + 0.5;
}}
vec3 octDecode(vec2 uv) {{
    vec2 f = uv * 2.0 - 1.0;
    vec3 d = vec3(f.x, 1.0 - abs(f.x) - abs(f.y), f.y);
    float t = max(-d.y, 0.0);
    d.x += d.x >= 0.0 ? -t : t;
    d.z += d.z >= 0.0 ? -t : t;
    return normalize(d);
}}

// The galaxy's brightness in a direction: NASA's map, read between its samples by hand
// (so it needs no float-filtering extension), which keeps its contours smooth curves.
float galaxy(vec3 d) {{
    float b = asin(clamp(dot(d, GAL_POLE), -1.0, 1.0));
    float l = atan(dot(d, GAL_ACROSS), dot(d, GAL_CENTRE));
    vec2 uv = vec2(0.5 - l / TAU, 0.5 - b / PI) * vec2(GALAXY_SIZE) - 0.5;
    ivec2 i = ivec2(floor(uv));
    vec2 f = fract(uv);
    int w = GALAXY_SIZE.x, h = GALAXY_SIZE.y;
    int x0 = (i.x % w + w) % w, x1 = (x0 + 1) % w;
    int y0 = clamp(i.y, 0, h - 1), y1 = clamp(i.y + 1, 0, h - 1);
    return mix(mix(texelFetch(uGalaxyTex, ivec2(x0, y0), 0).r, texelFetch(uGalaxyTex, ivec2(x1, y0), 0).r, f.x),
               mix(texelFetch(uGalaxyTex, ivec2(x0, y1), 0).r, texelFetch(uGalaxyTex, ivec2(x1, y1), 0).r, f.x), f.y);
}}

vec3 starColour(float cls) {{
    vec3 c = vec3(0.72, 0.83, 1.0);                                  // blue-white
    c = mix(c, vec3(1.0, 0.98, 0.95), step(0.5, cls));                // white
    c = mix(c, vec3(1.0, 0.94, 0.78), step(1.5, cls));                // yellow-white
    c = mix(c, vec3(1.0, 0.80, 0.52), step(2.5, cls));                // amber
    c = mix(c, vec3(1.0, 0.60, 0.44), step(3.5, cls));                // red
    return c;
}}

// ------------------------------------------------------------------- the bodies

// A planet's own colours, by where on it we are: `lat` is -1..1 pole to pole, `q` a
// point on its surface turning with it, `w` how much of the sphere one pixel covers -
// every coast and band is resolved against that, so it is one pixel soft at any size.
float gDrift = 0.0;        // the slow clock, for weather: set once a frame

vec3 surface(int i, float lat, vec3 q, float w) {{
    // the gas giants do not turn as one: each band slides past its neighbours
    if (i == 4 || i == 5) q.xz = rot2(0.9 * gDrift * sin(lat * (i == 4 ? 9.0 : 8.0))) * q.xz;
    if (i == 0) return mix(vec3(0.66, 0.62, 0.58), vec3(0.48, 0.45, 0.43), edge(0.53, soft(q * 2.4), 2.0 * w));
    if (i == 1) return mix(vec3(0.96, 0.85, 0.56), vec3(0.89, 0.72, 0.42), edge(0.0, sin(lat * 7.0 + 1.5 * soft(q * 1.5)), 8.0 * w));
    if (i == 2) {{
        float land = soft(q * 1.9 + 5.0);
        vec3 c = mix(vec3(0.10, 0.34, 0.82), vec3(0.17, 0.50, 0.90), edge(0.455, land, 1.6 * w));          // deep and shallow sea
        c = mix(c, vec3(0.30, 0.66, 0.30), edge(0.54, land, 1.6 * w));
        c = mix(c, vec3(0.78, 0.68, 0.40), edge(0.65, land, 1.6 * w) * (1.0 - smoothstep(0.35, 0.6, abs(lat))));
        c = mix(c, vec3(0.97, 0.98, 1.0), edge(0.835, abs(lat) + 0.10 * land, 1.2 * w));                  // ice
        float cloud = soft(vec3(rot2(0.9 + 0.8 * gDrift) * q.xz, q.y) * 2.3 + 17.0);       // the weather moves over the land
        return mix(c, vec3(1.0), 0.85 * edge(0.615, cloud, 2.0 * w));
    }}
    if (i == 3) {{
        vec3 c = mix(vec3(0.86, 0.41, 0.22), vec3(0.57, 0.26, 0.17), edge(0.535, soft(q * 2.0 + 2.0), 1.8 * w));
        return mix(c, vec3(0.98, 0.95, 0.93), edge(0.895, abs(lat), 1.2 * w));
    }}
    if (i == 4) {{
        float t = lat * 9.0 + 0.9 * soft(q * vec3(1.2, 4.0, 1.2));
        vec3 c = mix(vec3(0.94, 0.85, 0.68), vec3(0.79, 0.56, 0.38), edge(0.0, sin(t), 10.0 * w));
        c = mix(c, vec3(0.61, 0.40, 0.28), 0.8 * edge(0.62, sin(t * 0.5 + 1.0), 5.0 * w));
        vec2 spot = vec2(atan(q.z, q.x) / 0.55, (lat + 0.37) / 0.13);                                     // the Great Red Spot
        return mix(c, vec3(0.86, 0.36, 0.24), 1.0 - edge(0.92, length(spot), 6.0 * w));
    }}
    if (i == 5) return mix(vec3(0.94, 0.84, 0.58), vec3(0.83, 0.69, 0.44), edge(0.0, sin(lat * 8.0 + 0.5 * soft(q * 1.4)), 9.0 * w));
    if (i == 6) return mix(vec3(0.62, 0.90, 0.92), vec3(0.54, 0.83, 0.88), edge(0.0, sin(lat * 3.0), 4.0 * w));
    vec3 c = mix(vec3(0.24, 0.42, 0.94), vec3(0.16, 0.30, 0.78), edge(0.0, sin(lat * 5.0 + 0.8), 6.0 * w));
    return mix(c, vec3(0.10, 0.20, 0.60), 1.0 - edge(0.90, length(vec2(atan(q.z, q.x) / 0.45, (lat + 0.32) / 0.12)), 7.0 * w));
}}

// Cel shading: a lit tone, a half tone, and a shadow that keeps its colour. `w` is a
// pixel's worth of N.L, so the terminator is a pixel soft whatever the planet's size.
vec3 cel(vec3 day, float ndl, float rimness, vec3 shade, float w) {{
    vec3 night = day * 0.20 + shade * 0.85;
    vec3 c = mix(night, mix(night, day, 0.52), edge(0.0, ndl, w));
    c = mix(c, day, edge(0.32, ndl, w));
    return mix(c, mix(day, vec3(1.0), 0.40), edge(0.82, rimness, 2.0 * w) * smoothstep(0.25, 0.45, ndl));
}}

void main() {{
    float ss = max(uSS, 1.0);
    gAA = 1.0 / ss;
    gDrift = TAU * uOrbitSlow;
    // Everything is measured in the frame's heights, and the frame is the picture, unless
    // the picture is asked to go on round it (a window of another shape, filled): then the
    // frame is in its middle, the same frame, and there is more sky and more orbit round it.
    float widen = max(uWiden, 1.0);
    float resY = uResolution.y / (ss * widen);                         // the height of the frame, in output pixels
    vec2 p = (gl_FragCoord.xy - 0.5 * uResolution) / uResolution.y * widen;

    // ---- the camera: an orrery's. It turns, tilts, rolls, zooms and slides; nothing it
    // does changes the shape of anything. ---------------------------------------------------
    float e = clamp(uCamTilt, 0.20, 0.98), c = sqrt(1.0 - e * e);
    float pxScene = uCamSpan / resY;                                   // scene units in an output pixel
    // What is sized by how close the camera is, is sized by the wide frame's camera in both
    // frames: so the tall picture is the wide one turned, and nothing in it is another size.
    float spanWide = uCamSpan * mix(1.0, 9.0 / 16.0, uTall);
    vec2 q = rot2(-uCamRoll) * (p * uCamSpan + vec2(uCamX, uCamY));   // this pixel, in the scene, unrolled
    float r = length(q);

    float amb = 0.42 + 1.00 * uExposure;
    float ev = 0.80 + 0.30 * uExposure;
    float lum = clamp(0.62 + 0.38 * amb, 0.0, 1.0);
    float kick = uKickE;                                              // eased: it peaks on the kick
    float syll = uSyllE;
    float dropAge = uTime - uDropT;
    float hatE[3] = float[3](uHatE0, uHatE1, uHatE2);                 // the hats take the stars in three turns; each turn swells and subsides
    float shimmer = uCrashE;

    vec3 white = vec3(1.0, 0.985, 0.95);
    // Nothing here changes colour with the song. This is the solar system, and it is the
    // colour it is: a warm Sun in a warm corona, light that is gold going to white, shadow
    // and sky the deep blue of space. The song moves things; it does not repaint them. (The
    // section palettes are still baked, and the other styles use them; this one does not.)
    vec3 cTint = vec3(1.0, 0.95, 0.86);
    vec3 kField = vec3(0.40, 0.46, 0.74), kFar = vec3(0.20, 0.30, 0.50), kBody = vec3(1.0, 0.56, 0.22);
    vec3 kA = vec3(1.0, 0.84, 0.54), kB = vec3(0.98, 0.93, 0.84);        // light from the Sun: gold, and a paler gold
    vec3 space = vec3(0.018, 0.023, 0.052) + kFar * 0.030;
    vec3 shade = mix(space, kField, 0.22);                            // the colour of shadow: never grey, never black
    vec3 sunlight = vec3(1.0, 0.96, 0.88);                            // sunlight

    // ---- the sky: the one thing seen through a lens, because it is infinitely far --------
    float lens = SKY_LENS / pow(spanWide, 0.18) * mix(1.0, 9.0 / 16.0, uTall);   // it answers a zoom a little, as far things do
    vec2 ps = rot2(-uCamRoll) * p;
    vec3 dPlane = fromView(normalize(vec3(ps, -lens)), e, c);         // (u, v, up), in the camera's turned frame
    vec2 uvW = rot2(-uCamTurn) * dPlane.xy;
    vec3 rd = vec3(uvW.x, dPlane.z, uvW.y);                           // world: x vernal equinox, y ecliptic north

    // The sky answers two things. A kick is mass, and mass bends light: a ripple leaves
    // the Sun and every star it passes is pushed outward a few pixels and let back - the
    // stars are moved, not brightened (their brightness is the hats'). And a re-entry:
    // through the bar before it the sky dims, holding its breath; on the downbeat it
    // opens - the galaxy's clouds a tone up, the faint stars out - and a slow, deep
    // ripple crosses it; then it settles over a couple of bars.
    vec2 sunP = -(rot2(uCamRoll) * vec2(0.0)) - vec2(uCamX, uCamY) / uCamSpan;   // the Sun, in the frame
    float sunRp = 0.078 * (0.50 + 0.80 * uMass) / uCamSpan;
    float kAge = uTime - uKickT;
    float lensKA = kAge < 0.0 ? 0.0 : 0.0036 * uKickA * exp(-kAge / 0.30) * sstep(kAge / 0.10), lensKR = sunRp + 0.95 * kAge;
    float lensDA = dropAge < 0.0 ? 0.0 : 0.0070 * uDropA * exp(-dropAge / 1.6) * sstep(dropAge / 0.20), lensDR = sunRp + 0.42 * dropAge;
    float opened = uOpened;                                           // eased open on the downbeat, and closed again over two bars
    float skyGain = (1.0 - 0.38 * uBrace) * (1.0 + 0.60 * opened);

    // the Milky Way: five flat tones cut from NASA's map along its own contours, each
    // edge a pixel wide whatever the field is doing there
    float mw = galaxy(rd);
    float wM = max(fwidth(mw), 1e-4);                                 // (a derivative is already per render pixel)
    wM *= ss;                                                          // ...so undo what edge() will do to it
    vec3 col = space * (1.0 - 0.35 * smoothstep(0.40, 1.05, length(p)));
    // Darker than a first try had it, and darker again across the stage the planets
    // move on: the clouds are there to frame the system, and a pale cloud behind a
    // planet only hides it. Out beyond the orbits they come up to full strength.
    float stage = length(vec2(q.x, q.y / e)) / ((max(0.255, 0.156 / e) + 0.46) * uSpreadSlow);
    float gM = min(mix(0.42, 1.0, smoothstep(0.55, 1.25, stage)) * skyGain, 1.0);
    col = mix(col, vec3(0.030, 0.037, 0.078) + kFar * 0.020, edge(0.14, mw, wM) * gM);
    col = mix(col, vec3(0.043, 0.051, 0.102) + kFar * 0.024, edge(0.28, mw, wM) * gM);
    col = mix(col, vec3(0.059, 0.067, 0.126) + kFar * 0.027, edge(0.45, mw, wM) * gM);
    col = mix(col, vec3(0.079, 0.084, 0.150) + kFar * 0.027, edge(0.64, mw, wM) * gM);
    col = mix(col, vec3(0.108, 0.104, 0.168) + kFar * 0.020, edge(0.86, mw, wM) * gM);       // the core of the bulge only

    float starGain = min((0.50 + 0.50 * uStars) * skyGain, 1.0);
    vec2 uvO = octEncode(rd);
    {{
        // the stars too faint for the catalogue: a hashed field, crowded where the galaxy
        // is - each one's existence decided where *it* is, not where the pixel is
        const float FAINT = 300.0;
        vec2 cell = floor(uvO * FAINT);
        vec3 fd = octDecode((cell + 0.25 + 0.5 * hash22(cell + 0.37)) / FAINT);
        if (hash12(cell + 4.1) < 0.80 * galaxy(fd) - 0.06) {{                    // (only in the Milky Way: its unresolved stars. Everywhere else the stars are the catalogue's.)
            vec3 fv = toView(vec3(rot2(uCamTurn) * fd.xz, fd.y), e, c);
            vec2 at = lensed(rot2(uCamRoll) * fv.xy / max(-fv.z, 1e-3) * lens, sunP, 0.7 * lensKA, lensKR, 0.5 * lensDA, lensDR);
            float dPx = length(p - at) * resY;
            col = mix(col, vec3(0.82, 0.86, 0.96), disc(dPx, 1.05) * min((0.22 + 0.26 * hash12(cell + 2.2)) * (1.0 + 0.6 * opened), 1.0) * starGain * step(fv.z, 0.0));
        }}
    }}
    {{
        // The real ones (HYG: every star to magnitude 7.5, with its distance and constellation),
        // and the deep sky among them (OpenNGC). A star is a hard disc whose size is its
        // magnitude; the brightest are four-pointed. Its *distance* shows three ways: a near
        // star is a little larger and crisper, takes its glints at a fainter magnitude, and
        // shifts against the far ones as the camera goes round (slightly - this is art).
        // A constellation breathes together: its stars take the same turn of the hats.
        ivec2 sc = min(ivec2(uvO * float(STAR_GRID)), ivec2(STAR_GRID - 1));
        vec3 eye = vec3(0.0, -c, e);                                   // where the camera stands, in its own turned frame
        for (int k = 0; k < STAR_PER_CELL; k++) {{
            vec4 s = texelFetch(uStarTex, ivec2(sc.x * STAR_PER_CELL + k, sc.y), 0);
            if (dot(s.xyz, s.xyz) < 0.5) break;
            float w_ = s.w;
            float grp = floor(w_ / 10000.0); w_ -= 10000.0 * grp;
            float nearD = floor(w_ / 1000.0); w_ -= 1000.0 * nearD;
            float cls = floor(w_ / 100.0);
            float mag = w_ - 100.0 * cls - 2.0;
            vec3 dT = vec3(rot2(uCamTurn) * s.xz, s.y);
            if (cls < 8.5) dT = normalize(dT - PARALLAX * (nearD / 9.0) * eye);
            vec3 sv = toView(dT, e, c);
            if (sv.z > -0.2) continue;
            vec2 d = (p - lensed(rot2(uCamRoll) * sv.xy / (-sv.z) * lens, sunP, lensKA, lensKR, lensDA, lensDR)) * resY;   // output pixels from it
            float h = hash12(s.xz * 91.7 + s.y * 13.1);
            if (cls > 8.5) {{
                // ---- the deep sky: clusters, nebulae, galaxies, remnants - flat, hard-edged, each at
                // its true size on the sky (nothing under three and a half pixels), the faintest things there are
                float rp = max(DEEP_SIZE[int(grp)] * lens * resY, 3.5);
                if (abs(d.x) > rp + 2.0 || abs(d.y) > rp + 2.0) continue;
                vec2 dr = rot2(TAU * h) * d;
                float bright = (0.45 + 0.055 * (mag + 2.0)) * starGain;
                int kind = int(nearD);
                if (kind == 0) {{                                        // a galaxy: a tilted oval of far light, and its core
                    float el = length(vec2(dr.x, dr.y / (0.34 + 0.4 * fract(h * 7.0))));
                    col = mix(col, vec3(0.62, 0.66, 0.86), disc(el, rp) * 0.26 * bright);
                    col = mix(col, vec3(0.90, 0.88, 0.92), disc(el, 0.30 * rp) * 0.55 * bright);
                }} else if (kind == 1) {{                                 // an open cluster: a handful of young blue stars
                    for (int j = 0; j < 7; j++) {{
                        vec2 at = (hash22(vec2(h * 91.0, float(j) * 3.7)) - 0.5) * 1.5 * rp;
                        col = mix(col, vec3(0.78, 0.86, 1.0), disc(length(dr - at), 0.95 + 0.7 * hash11(float(j) + h * 9.0)) * 0.80 * bright);
                    }}
                }} else if (kind == 2) {{                                 // a globular cluster: old light, packed to a core
                    col = mix(col, vec3(0.98, 0.90, 0.72), disc(length(d), rp) * 0.22 * bright);
                    col = mix(col, vec3(1.0, 0.94, 0.80), disc(length(d), 0.42 * rp) * 0.70 * bright);
                }} else if (kind == 3) {{                                 // a nebula: a cloud of glowing hydrogen, ragged-edged
                    float cloud = soft(vec3(dr / rp * 1.6, h * 9.0)) - 0.55 * length(dr) / rp;
                    col = mix(col, vec3(0.70, 0.26, 0.38), edge(0.10, cloud, 0.06) * 0.42 * bright);
                    col = mix(col, vec3(0.92, 0.50, 0.58), edge(0.34, cloud, 0.06) * 0.50 * bright);
                }} else if (kind == 4) {{                                 // a planetary nebula: a small ring, and the star that threw it
                    col = mix(col, vec3(0.42, 0.88, 0.80), disc(abs(length(d) - rp), 1.0) * 0.85 * bright);
                    col = mix(col, white, disc(length(d), 0.9) * 0.8 * bright);
                }} else {{                                                // a supernova remnant: what is left of the shell, in pieces
                    float gap = step(0.42, soft(vec3(normalize(dr + 1e-5) * 2.3, h * 5.0)));
                    col = mix(col, vec3(0.70, 0.90, 1.0), disc(abs(length(d) - rp), 1.0) * gap * 0.80 * bright);
                    col = mix(col, vec3(0.95, 0.60, 0.50), disc(abs(length(d) - 0.62 * rp), 0.8) * (1.0 - gap) * 0.50 * bright);
                }}
                continue;
            }}
            if (abs(d.x) > 26.0 || abs(d.y) > 26.0) continue;
            // a star breathes with its constellation's turn of the hats - and a little with the
            // other two, each star in its own proportion, so no two swell quite alike
            int turnK = int(grp);
            float lift = (0.75 * hatE[turnK] + 0.25 * mix(hatE[(turnK + 1) % 3], hatE[(turnK + 2) % 3], fract(h * 17.0))
                          + shimmer * (0.4 + 0.6 * hash11(h * 7.3))) * step(mag, 5.2);
            float close = nearD / 9.0;
            float rad = clamp(1.05 + 0.62 * (5.6 - mag), 0.78, 5.2) * (0.90 + 0.28 * close) * (1.0 + 0.34 * lift);
            float a = disc(length(d), rad);
            if (mag < 2.6 + 0.8 * close) {{
                float reach = rad * (2.2 + 0.45 * max(2.6 - mag, 0.0) + 0.9 * close) * (1.0 + 0.5 * lift);
                a = max(a, max(disc(abs(d.y), 0.85) * disc(abs(d.x), reach), disc(abs(d.x), 0.85) * disc(abs(d.y), reach)));
            }}
            col = mix(col, starColour(cls), a * clamp(1.12 - 0.125 * mag + 0.10 * close + 0.3 * lift, 0.26, 1.0) * starGain);
        }}
    }}

    // shooting stars: far away, so small - a thin bright scratch, never the size of a planet
    float metT[N_METEORS] = {_gather("uMetT", N_METEORS)};
    float metA[N_METEORS] = {_gather("uMetA", N_METEORS)};
    float metS[N_METEORS] = {_gather("uMetS", N_METEORS)};
    for (int i = 0; i < N_METEORS; i++) {{
        float age = uTime - metT[i];
        if (age < -LEAD || age > 1.3 || metA[i] <= 0.0) continue;
        float s = metS[i];
        float alpha = TAU * hash11(s * 7.13 + 0.3);
        vec2 start = vec2(0.78 * cos(alpha), 0.42 * sin(alpha));
        float side = hash11(s * 3.71 + 1.9) < 0.5 ? -1.0 : 1.0;
        vec2 dir = rot2(side * (0.55 + 0.35 * hash11(s * 5.3))) * normalize(-start);
        vec2 head = start + dir * (0.50 + 0.28 * hash11(s * 9.7) + 0.22 * metA[i]) * max(age, 0.0);
        vec2 d = p - head;
        float back = -dot(d, dir), off = abs(dot(d, vec2(-dir.y, dir.x))) * resY;
        float len = (0.030 + 0.070 * metA[i]) * sstep(age / 0.16) + 1e-5;
        float u = clamp(back / len, 0.0, 1.0);
        float tail = step(0.0, back) * step(back, len) * disc(off, (0.85 + 1.2 * metA[i]) * (1.0 - u) + 0.35);
        col = mix(col, mix(white, kA, smoothstep(0.25, 0.45, u)), tail * (1.0 - smoothstep(0.75, 1.1, age)) * (0.50 + 0.50 * metA[i]));
        // a small four-pointed glint where it enters: it opens onto the moment and closes after it
        vec2 g = (p - start) * resY;
        float glint = (5.0 + 9.0 * metA[i]) * arrive(age, LEAD, 0.30);
        col = mix(col, white, max(disc(abs(g.y), 0.8) * disc(abs(g.x), glint), disc(abs(g.x), 0.8) * disc(abs(g.y), glint)) * step(0.5, glint));
    }}

    // ---- the Sun's size: mass, and the beat - which it swells *into* --------------------------
    float R = 0.078 * (0.50 + 0.80 * uMass) * (1.0 + 0.22 * uSunPulse);

    // ---- waves in the plane: each clap's ring, and the re-entry's shock -----------------------
    // Where one is, whatever lies in the plane is shoved outward with it and falls back, so
    // the belts and the trails are looked up at a displaced point and the wave is seen in
    // what it moves.
    vec2 pl = vec2(q.x, q.y / e);                                     // this pixel, in the plane
    float rho = length(pl);
    float ringT[N_RINGS] = {_gather("uRingT", N_RINGS)};
    float ringA[N_RINGS] = {_gather("uRingA", N_RINGS)};
    float ringM[N_RINGS] = {_gather("uRingM", N_RINGS)};
    vec3 waveCol = vec3(0.0); float waveA = 0.0;
    float shove = 0.0;
    float flareT[N_FLARE] = {_gather("uFlareT", N_FLARE)};
    float flareA[N_FLARE] = {_gather("uFlareA", N_FLARE)};
    float flareK[N_FLARE] = {_gather("uFlareK", N_FLARE)};
    // A flare: the corona's discharge. Its front is not a ring - it is thrown one way, from
    // where its prominence stood, and fans out across the plane: fast, hot, a third of a turn wide.
    for (int i = 0; i < N_FLARE; i++) {{
        float age = uTime - flareT[i];
        if (age < 0.0 || age > 1.5 || flareA[i] <= 0.0) continue;      // (the front leaves on the beat; the tongue that throws it has been rising)
        float phiF = TAU * flareK[i] + uCamTurn;                      // thrown at a planet: its longitude, in the camera's turned frame
        float dphi = abs(mod(atan(pl.y, pl.x) - phiF + PI, TAU) - PI);
        float fan = 1.0 - smoothstep(0.42, 0.66, dphi);               // aimed: a sixth of a turn wide
        float rad = R + 0.05 + 0.95 * age;
        float a_ = planeRing(q, e, rad, 1.3 + 2.4 * exp(-age / 0.18), pxScene) * fan * flareA[i] * (1.0 - sstep((age - 0.8) / 0.7)) * sstep(age / 0.10) * ev;
        vec3 fc = mix(vec3(1.0, 0.70, 0.34), white, 0.35 + 0.45 * exp(-age / 0.2));
        waveCol = mix(waveCol, fc, step(waveA, a_)); waveA = max(waveA, a_);
    }}
    for (int i = 0; i < N_RINGS; i++) {{
        float age = uTime - ringT[i];
        // A ring goes as far as the clap was loud. The backbeat's crosses the system; a
        // ghost note's is a ripple that dies near the Sun - or the plane is never still.
        float loud = smoothstep(0.22, 0.65, ringA[i]);
        float life = mix(0.50, 2.2, loud);
        if (age < -LEAD || age > life || ringA[i] <= 0.0) continue;
        float born = sstep(1.0 + age / LEAD);                          // it comes up out of the corona over the tenth of a second before the clap
        float out_ = max(age, 0.0);
        float rad = R + 0.035 * born + 0.66 * pow(out_, 0.72);
        float g = (rho - rad) / 0.035;
        shove += 0.010 * (0.15 + 0.85 * loud) * exp(-g * g) * exp(-out_ / 0.5) * born;
        float a_ = planeRing(q, e, rad, 0.95 + 2.6 * exp(-out_ / 0.07) * born, pxScene) * (1.0 - smoothstep(0.55 * life, life, age)) * born
                   * clamp((0.40 + 0.60 * ringA[i]) * (0.95 * exp(-out_ / 0.10) + 0.75 * exp(-out_ / 0.45)), 0.0, 1.0) * ev;
        vec3 wc = mix(mix(kA, kB, ringM[i]), white, 0.15 + 0.55 * exp(-out_ / 0.10));
        waveCol = mix(waveCol, wc, step(waveA, a_)); waveA = max(waveA, a_);
    }}
    if (dropAge >= 0.0 && dropAge < 4.5) {{
        // slow enough to be watched crossing the system: it was too quick to appreciate
        float rad = R + 0.60 * pow(dropAge, 0.70);
        float g = (rho - rad) / 0.07;
        shove += 0.034 * uDropA * exp(-g * g) * exp(-dropAge / 1.3);
        for (int k = 0; k < 3; k++) {{
            float fk = float(k);
            float a_ = planeRing(q, e, rad * (1.0 - 0.09 * fk), 2.6 - 0.7 * fk, pxScene)
                       * clamp(uDropA * exp(-dropAge / 1.4) * (1.0 - 0.3 * fk), 0.0, 1.0);
            waveCol = mix(waveCol, mix(kA, white, 0.55 - 0.15 * fk), step(waveA, a_)); waveA = max(waveA, a_);
        }}
    }}
    {{
        // the voice: one thin ring in the plane, riding out and back with the melody
        float rad = R * (1.55 + 1.15 * (0.5 + 0.5 * uPitch)) + 0.012 * uSustain;
        float a_ = planeRing(q, e, rad, 0.95 + 0.6 * uSustain + 0.5 * syll, pxScene) * clamp(1.4 * uVoice + 0.9 * syll, 0.0, 1.0) * ev;
        waveCol = mix(waveCol, vivid(mix(mix(kA, white, 0.30), cTint, uTint), 1.3), step(waveA, a_)); waveA = max(waveA, a_);
    }}
    vec2 plW = pl * (1.0 - shove / max(rho, 0.02));                   // the plane, as the waves have pushed it
    float rhoW = length(plW), thW = atan(plW.y, plW.x);

    // The innermost orbit clears the Sun even at the top of a beat, however far the plane
    // is tipped: a planet behind the Sun, or across its face, is a note nobody saw.
    float a0 = max(0.255, 0.156 / e);
    float tug = uSpreadSlow;                                          // how wide the orbits stand, as this camera sees it
    // The planets are bodies (`dance`): how far each leans toward the Sun or away, and how far
    // it has hopped off the plane, are simulated - springs, driven by its notes, by the Sun's
    // pull (inverse-square, and it travels) and by its neighbours. In a close shot the
    // movement is scaled down, so it is the same small movement on screen.
    float pullGain = clamp(spanWide, 0.0, 1.0);
    float pingT[N_PLANETS] = {_gather("uPingT", N_PLANETS)};
    float pingA[N_PLANETS] = {_gather("uPingA", N_PLANETS)};
    float pLean[N_PLANETS] = {_gather("uLean", N_PLANETS)};
    float pHop[N_PLANETS] = {_gather("uHop", N_PLANETS)};
    float pGlow[N_PLANETS] = {_gather("uGlow", N_PLANETS)};
    float pBig[N_PLANETS] = {_gather("uBig", N_PLANETS)};
    float pSwing[N_PLANETS] = {_gather("uSwing", N_PLANETS)};
    float pSpin[N_PLANETS] = {_gather("uSpin", N_PLANETS)};
    float phase[N_PLANETS] = {_gather("uPh", N_PLANETS)};
    float pOff[N_PLANETS] = {_gather("uPd", N_PLANETS)};
    float pRise[N_PLANETS] = {_gather("uPz", N_PLANETS)};

    vec3 under = vec3(0.0), over = vec3(0.0);                         // what passes behind the Sun, and in front
    float underA = 0.0, overA = 0.0;

    // ---- belts: the asteroids between Mars and Jupiter, and the Kuiper belt ---------------------
    for (int bI = 0; bI < 2; bI++) {{
        float inner = a0 + (bI == 0 ? BELT0.x : BELT1.x), laneW = bI == 0 ? BELT0.y : BELT1.y;
        float li = floor((rhoW / tug - inner) / laneW);
        if (li < 0.0 || li >= (bI == 0 ? BELT0.z : BELT1.z)) continue;
        float lr = inner + (li + 0.5) * laneW;
        float count = floor((bI == 0 ? 40.0 : 44.0) + 9.0 * li);
        float turn = uOrbitSlow * pow(0.250 / (lr - a0 + 0.250), 1.5) + uCamTurn / TAU;
        float ci = floor(fract(thW / TAU - turn) * count);
        vec2 id = vec2(ci, li + 11.0 + 26.0 * float(bI));
        if (hash12(id) < (bI == 0 ? 0.34 : 0.50)) continue;
        vec2 jit = hash22(id + 2.3) - 0.5;
        float ang = TAU * ((ci + 0.5 + 0.5 * jit.x) / count + turn);
        vec2 cp = (lr + 0.30 * laneW * jit.y) * tug * vec2(cos(ang), sin(ang));
        vec2 dd = (q - vec2(cp.x, cp.y * e)) / pxScene;                // pixels from the rock
        float glint = 0.6 * hatE[int(floor(hash12(id + 9.1) * 3.0))];   // a rock catches the light with its turn of the hats - eased
        float sizePx = min(mix(bI == 0 ? 0.0022 : 0.0016, bI == 0 ? 0.0050 : 0.0032, hash12(id + 4.4)) * (1.0 + 0.9 * glint),
                           0.30 * laneW * e * tug) / pxScene;
        sizePx = max(sizePx, 1.15);
        float spin = uBeats * (0.04 + 0.10 * hash12(id + 6.1)) * (hash12(id + 8.8) < 0.5 ? -1.0 : 1.0);
        float lump = 0.80 + 0.20 * cos(3.0 * atan(dd.y, dd.x) + spin + TAU * hash12(id + 7.7));
        float rock = disc(length(dd), sizePx * lump);
        float lit = edge(-0.10, dot(normalize(dd + 1e-5), normalize(-vec2(cp.x, cp.y * e))), 1.2 / sizePx);
        vec3 tone = vec3(0.62, 0.59, 0.57) * (0.80 + 0.25 * hash12(id + 3.3)) * sunlight * lum;
        vec3 rk = mix(mix(tone * 0.26 + shade, white, 0.35 * glint), mix(tone, white, glint), lit);
        if (cp.y > 0.0) {{ under = mix(under, rk, step(underA, rock)); underA = max(underA, rock); }}
        else {{ over = mix(over, rk, step(overA, rock)); overA = max(overA, rock); }}
    }}

    // ---- a comet, on a long ellipse: Kepler's equation, five Newton steps. Small and far off.
    // Its tail streams out *behind* it, as every trail in this picture does, longer the
    // faster it is going - quick and long round the Sun, short and slow far out. (A real
    // comet's tail points away from the Sun whichever way it is travelling, and drawn that
    // way it looked like something drifting sideways with a stick on it.) ------------------------
    {{
        float ce = 0.70, ca = (a0 + 0.30) * tug;
        float M = TAU * (uOrbitSlow * 0.30 + 0.37);
        float E = M;
        for (int k = 0; k < 5; k++) E -= (E - ce * sin(E) - M) / (1.0 - ce * cos(E));
        vec2 orb = rot2(0.95 + uCamTurn) * vec2(ca * (cos(E) - ce), ca * sqrt(1.0 - ce * ce) * sin(E));
        vec2 cs = vec2(orb.x, orb.y * e);
        float closeness = clamp(ca * (1.0 - ce) / max(length(orb), 1e-3), 0.0, 1.0);
        vec2 vel = rot2(0.95 + uCamTurn) * vec2(-sin(E), sqrt(1.0 - ce * ce) * cos(E));
        float speed = length(vel) / (1.0 - ce * cos(E));                 // Kepler: 2.4 at perihelion, 0.4 at the far end
        vec2 anti = normalize(cs + 1e-6);                                // away from the Sun: the tail leans a little that way, as dust does
        vec2 away = normalize(-normalize(vec2(vel.x, vel.y * e) + 1e-6) + 0.25 * anti);
        vec2 d = q - cs;
        float back = dot(d, away);
        float len = (0.010 + 0.030 * speed) * (0.7 + 0.5 * uField);
        float u = clamp(back / len, 0.0, 1.0);
        // a fine wedge that fades to nothing along its length
        float tailA = step(0.0, back) * step(back, len) * disc(abs(dot(d, vec2(-away.y, away.x))) / pxScene, (0.55 + 0.8 * closeness) * (1.0 - 0.9 * u) + 0.2);
        vec3 cc = mix(vec3(0.96, 0.92, 0.80), white, 0.30 * (1.0 - u)); float cA = tailA * 0.50 * (1.0 - u) * (1.0 - u) * lum;
        float head = disc(length(d) / pxScene, 1.3 + 0.6 * closeness);
        cc = mix(cc, white, head); cA = max(cA, head);
        if (orb.y > 0.0) {{ under = mix(under, cc, step(underA, cA)); underA = max(underA, cA); }}
        else {{ over = mix(over, cc, step(overA, cA)); overA = max(overA, cA); }}
    }}

    // ---- the planets -------------------------------------------------------------------------------
    for (int i = 0; i < N_PLANETS; i++) {{
        float aFree = (a0 + pOff[i]) * tug;                             // where it would be, left alone
        float pulled = -pullGain * pLean[i];
        float a = aFree - pulled;
        float th = TAU * phase[i] + uCamTurn;
        vec3 sv = toView(vec3(a * cos(th), a * sin(th), a * pRise[i] + pullGain * pHop[i]), e, c);   // its orbit is tipped; and it hops
        vec2 dq = q - sv.xy;
        int slot = PLANET_SLOT[i];
        float nAge = uTime - pingT[i];                                 // since it last threw a ring (shown LEAD early: it starts negative)
        float lit = pGlow[i];                                          // its day side lifts with its playing - eased, never switched
        float size = PLANET_SIZE[i] * (1.0 + 0.22 * pBig[i]) * (1.0 + 0.10 * sv.z / max(a, 1e-3));
        float sizePx = size / pxScene;
        vec3 pc = vec3(0.0); float pA = 0.0;

        // Its trail: no orbit is drawn. A short wake that fades behind it, longer the faster it
        // goes, the mean colour of its own surface - and lying along the orbit it is actually
        // on: an oval about the Sun at one focus, tipped out of the plane. For this pixel's
        // longitude, where is that orbit? (Its height there is taken off the pixel first, so
        // the wake of a tipped orbit stays under its planet.)
        // (Only where this pixel could be on it: within the orbit's own range of distance, and
        // of height. Eight ovals' worth of trigonometry at every pixel was a third of the frame.)
        float meanR = (a0 + ORBIT_STEP[i]) * tug;
        float band = (1.2 * K_MAP * ORB_ECC[i] + (a0 + ORBIT_STEP[i]) * ORB_SINI[i] * c / e) * tug + PULL + 4.0 * pxScene / e;
        if (abs(rhoW - meanR) < band) {{
            float lonPix = thW - uCamTurn;
            float rise = ORB_SINI[i] * sin(lonPix - ORB_NODE[i]);
            float rOrb = (a0 + K_MAP * (ORB_LOGP[i] - log(1.0 + ORB_ECC[i] * cos(lonPix - ORB_PERI[i])))) * tug - pulled;
            vec2 plT = vec2(plW.x, plW.y - rOrb * rise * c / e);
            float rhoT = length(plT);
            float behind = mod(th - atan(plT.y, plT.x), TAU);
            float reach = (0.32 + 0.95 * pow(0.250 / (ORBIT_STEP[i] + 0.250), 1.5)) * (0.60 + 0.40 * uHold);
            float fade = behind < reach ? pow(1.0 - behind / reach, 1.25) : 0.0;
            float grad = length(vec2(plT.x, plT.y / e)) / max(rhoT, 1e-6);
            // it thins as it fades, as an inked line does: near the planet it is solid enough
            // to be the planet's colour and not the sky's seen through it
            float tr = disc(abs(rhoT - rOrb) / (grad * pxScene), mix(0.60, 1.20, fade)) * mix(fade, sqrt(fade), 0.5) * (0.50 + 0.36 * lum);
            vec3 tc = PLANET_TINT[i] * sunlight * lum;                 // the planet's own colour, in the planet's own light
            if (plW.y > 0.0) {{ under = mix(under, tc, step(underA, tr)); underA = max(underA, tr); }}
            else {{ over = mix(over, tc, step(overA, tr)); overA = max(overA, tr); }}
        }}

        float rel = length(dq) / max(size, 1e-5);
        if (rel < 6.8) {{
            // The outline first, so that whatever the planet gives off lies over it, not under it.
            float keyline = disc(length(dq) / pxScene, sizePx + 1.7);
            pc = space * 0.55; pA = keyline * 0.92;

            // What reaches it from the Sun. A clap's ring, the re-entry's shock and a flare's
            // front are all circles in the plane about the Sun, so each arrives at this orbit
            // at a moment that can be worked out - and at that moment the planet is *struck*:
            // its sunward side lifts and a bow wave stands off it toward the Sun - eased onto the
            // moment of arrival and away after it. (Struck by a flare it also rings: `dance` throws that ring.)
            float struck = 0.0; vec3 struckInk = white;
            for (int k = 0; k < N_RINGS; k++) {{
                float loudK = smoothstep(0.22, 0.65, ringA[k]);
                float reachAge = pow(max(a - R - 0.035, 0.0) / 0.66, 1.0 / 0.72);
                float since = uTime - ringT[k] - reachAge;
                if (ringA[k] <= 0.0 || since < -LEAD || since > 0.7 || reachAge > mix(0.50, 2.2, loudK)) continue;
                float f = (0.30 + 0.70 * loudK) * (0.30 + 0.70 * exp(-reachAge / 0.9)) * arrive(since, LEAD, 0.60);
                if (f > struck) {{ struck = f; struckInk = mix(mix(kA, kB, ringM[k]), white, 0.35); }}
            }}
            {{
                float since = dropAge - pow(max(a - R, 0.0) / 0.60, 1.0 / 0.70);
                float f = uDropA * arrive(since, 1.5 * LEAD, 1.10);
                if (f > struck) {{ struck = f; struckInk = mix(kA, white, 0.55); }}
            }}
            for (int k = 0; k < N_FLARE; k++) {{
                float since = uTime - flareT[k] - max(a - R - 0.05, 0.0) / 0.95;
                if (flareA[k] <= 0.0 || since < -LEAD || since > 1.2) continue;
                float dphi = abs(mod(th - TAU * flareK[k] - uCamTurn + PI, TAU) - PI);
                float inFan = 1.0 - smoothstep(0.42, 0.66, dphi);
                float f = 1.3 * flareA[k] * inFan * arrive(since, LEAD, 0.90);
                if (f > struck) {{ struck = f; struckInk = mix(vec3(1.0, 0.70, 0.34), white, 0.45); }}

            }}
            struck = clamp(struck, 0.0, 1.0);

            // What it gives off is its own: the colour of the planet, lifted - rings thrown from it, on the axis of the orbits. Each planet
            // in its own manner (see PING_N): this is an orchestra.
            vec3 own = mix(PLANET_TINT[i], white, 0.22) * mix(vec3(1.0), sunlight, 0.5);
            vec2 dqR = dq;                                               // everything a planet throws lies in the plane of the orbits
            // A ring is an event now, not a twitch: a planet throws one when its playing has
            // built up to it (`dance`), about once in a bar and a half. It opens over a second,
            // eased; it arrives with its note and thins away; and each planet has its own figure.
            for (int j = 0; j < 3; j++) {{
                if (j >= PING_N[i]) break;
                float ageJ = nAge - 0.16 * float(j);                     // one after another
                if (ageJ < -LEAD || ageJ > 1.6 || pingA[i] <= 0.0) continue;
                float going = clamp(ageJ / 1.6, 0.0, 1.0);
                float open = size * (1.35 + PING_REACH[i] * (1.0 - pow(1.0 - going, 2.4)));            // fast away, slowing as it opens
                float ping = planeRing(dqR, e, open, (1.15 + 0.4 * float(PING_N[i] == 1)) * (1.0 - 0.55 * going), pxScene)
                             * clamp(pingA[i], 0.0, 1.0) * arrive(ageJ, LEAD, 1.6) * (1.0 - 0.25 * float(j)) * 0.85 * ev;
                pc = mix(pc, mix(own, white, 0.30), step(pA, ping)); pA = max(pA, ping);
            }}
            if (struck > 0.02) {{
                // the bow wave: an arc in the plane, standing off the planet on the side the Sun is
                vec2 dpl = vec2(dq.x, dq.y / e);
                float sunward = dot(normalize(dpl + 1e-6), -vec2(cos(th), sin(th)));
                // a crescent: thickest on the line to the Sun, thinning and fading to nothing at its ends
                float taper = smoothstep(0.05, 1.0, sunward);
                float bow = planeRing(dq, e, size * (1.9 + 0.9 * (1.0 - struck)), (0.25 + 1.35 * struck) * taper * taper, pxScene)
                            * smoothstep(0.05, 0.55, sunward) * struck * ev;
                pc = mix(pc, struckInk, step(pA, bow)); pA = max(pA, bow);
            }}

            vec3 L = normalize(-sv);                                     // to the Sun
            // its axis: tilted as it is, fixed in space
            float tiltA = i == 2 ? 0.41 : i == 3 ? 0.44 : i == 6 ? 1.71 : i == 7 ? 0.49 : 0.05;
            vec3 axisW = i == 5 ? RING_POLE : vec3(sin(tiltA) * cos(1.1 * float(i)), sin(tiltA) * sin(1.1 * float(i)), cos(tiltA));
            vec3 axis = toView(vec3(rot2(uCamTurn) * axisW.xy, axisW.z), e, c);

            float ringA_ = 0.0; vec3 ringC = vec3(0.0); float ringFront = 0.0;
            if (i == 5) {{
                // Saturn's rings: a plane through it, tilted; an annulus in that plane with
                // the Cassini division; the planet's own shadow across the far side
                float az = abs(axis.z) < 1e-4 ? 1e-4 : axis.z;
                float zr = -(dq.x * axis.x + dq.y * axis.y) / az;
                vec3 R3 = vec3(dq, zr);
                float rk = length(R3) / size;
                float gk = length(dq - zr * axis.xy / az) / max(length(R3) * size, 1e-9) * pxScene;
                float ann = edge(1.32, rk, gk) * (1.0 - edge(2.30, rk, gk)) * (1.0 - edge(1.92, rk, gk) * (1.0 - edge(2.02, rk, gk)));
                float along = dot(R3, -L);
                float castShadow = step(0.0, along) * (1.0 - edge(size, length(R3 + L * along), pxScene));
                ringC = mix(vec3(0.91, 0.83, 0.62), vec3(0.74, 0.66, 0.50), edge(1.62, rk, gk) * (1.0 - step(1.92, rk))) * sunlight * lum;
                ringC = mix(ringC, ringC * 0.20 + shade * 0.8, castShadow);
                // Saturn's answer to its note is in its rings: a band of light runs out along them
                float runs = 1.32 + 0.98 * sstep(nAge / 0.9);
                ringC = mix(ringC, mix(vec3(1.0, 0.95, 0.80), white, 0.3), 0.8 * clamp(pingA[i], 0.0, 1.0) * arrive(nAge, LEAD, 1.2) * exp(-pow((rk - runs) / 0.20, 2.0)) * ev);
                ringA_ = ann; ringFront = step(0.0, zr);
            }}
            // Moons. The Moon, its orbit tipped five degrees. Jupiter's four: Io, Europa and
            // Ganymede go round in 1 : 2 : 4 - for every turn of Ganymede, two of Europa and four
            // of Io, and never all three in line (the Laplace resonance; their phases here keep
            // it) - with Callisto further out, keeping its own time. Titan, which goes round
            // Saturn in the plane of the rings, not the plane of the planets.
            int moons = i == 2 ? 1 : i == 4 ? 4 : i == 5 ? 1 : 0;
            vec3 moonAt[4] = vec3[4](vec3(0.0), vec3(0.0), vec3(0.0), vec3(0.0)); float moonSz[4] = float[4](0.0, 0.0, 0.0, 0.0);
            for (int m = 0; m < 4; m++) {{
                if (m >= moons) break;
                float fm = float(m);
                float turns = i == 2 ? 3.3 * uOrbitSlow
                            : i == 5 ? 2.6 * uOrbitSlow + 0.2
                            : (m == 0 ? 8.0 : m == 1 ? 4.0 : m == 2 ? 2.0 : 0.848) * uOrbitSlow + (m == 2 ? 0.25 : m == 3 ? 0.6 : 0.0);
                float ma = TAU * turns;
                float swing = 1.0 + 0.34 * pSwing[i];                    // its moons are on strings: they swing out after it, and back
                float mr = size * swing * (i == 2 ? 3.2 : i == 5 ? 3.4 : 2.1 + 0.85 * fm + 0.12 * fm * fm);
                vec3 mw = i == 5 ? mr * (cos(ma) * RING_U + sin(ma) * RING_V)
                                 : vec3(mr * cos(ma), mr * sin(ma), i == 2 ? mr * 0.089 * sin(ma - 2.18) : 0.0);
                vec3 mv = toView(vec3(rot2(uCamTurn) * mw.xy, mw.z), e, c);
                float mrel = i == 2 ? 0.27 : i == 5 ? 0.17 : (m == 0 ? 0.12 : m == 1 ? 0.10 : m == 2 ? 0.17 : 0.15);
                float msz = max(size * mrel, 1.5 * pxScene);
                moonAt[m] = mv; moonSz[m] = size * mrel;
                vec2 md = dq - mv.xy;
                float moon = disc(length(md) / pxScene, msz / pxScene);
                moon *= 1.0 - step(mv.z, 0.0) * disc(length(dq) / pxScene, sizePx);      // behind its planet
                vec3 mn = vec3(md / msz, sqrt(max(1.0 - dot(md, md) / (msz * msz), 0.0)));
                vec3 mInk = cel(vec3(0.82, 0.81, 0.82) * sunlight * lum, dot(mn, L), 1.0 - mn.z, shade, 1.2 * pxScene / msz);
                pc = mix(pc, mInk, step(pA, moon)); pA = max(pA, moon);
            }}
            if (ringA_ > 0.0 && ringFront < 0.5) {{ pc = mix(pc, ringC, step(pA, ringA_)); pA = max(pA, ringA_); }}

            if (rel < 1.0 + 1.5 / max(sizePx, 1.0)) {{
                float cover = disc(length(dq) / pxScene, sizePx);
                vec3 n = vec3(dq / size, sqrt(max(1.0 - rel * rel, 0.0)));
                float w = 1.0 / max(sizePx, 1.0);                         // how much of the sphere a pixel covers
                float lat = dot(n, axis);
                vec3 e1 = normalize(cross(axis, vec3(0.31, 0.95, 0.10))), e2 = cross(axis, e1);
                vec3 sq = vec3(rot2(uOrbitSlow * (2.2 + 0.6 * float(i)) + pSpin[i]) * vec2(dot(n, e1), dot(n, e2)), lat).xzy;
                // (the kick does not light a planet: the planets are the notes'. But as the corona
                // charges, the daylight out here dims a little - and comes back with the discharge.)
                vec3 day = surface(i, lat, sq, w) * sunlight * lum * (1.0 - 0.10 * uCharge);
                // a note is the planet catching light: its day flares, its night glows its own colour
                day = mix(day, mix(day, white, 0.28), clamp(lit, 0.0, 1.0));
                float ndl = dot(n, L);
                vec3 globe = cel(day, ndl, 1.0 - n.z, shade, 1.4 * w);
                globe += PLANET_TINT[i] * 0.22 * lit * (1.0 - smoothstep(-0.02, 0.10, ndl));
                // Shadows that fall on it. A moon passing between it and the Sun puts a small
                // hard spot on its day side, which crosses as the moon does (Io's, on Jupiter);
                // and Saturn's rings lay a dark band across Saturn.
                vec3 P = n * size;
                float dark = 0.0;
                for (int m = 0; m < 4; m++) {{
                    if (moonSz[m] <= 0.0) continue;
                    vec3 toMoon = moonAt[m] - P;
                    float sunward = dot(toMoon, L);
                    dark = max(dark, step(0.0, sunward) * (1.0 - edge(moonSz[m], length(toMoon - L * sunward), pxScene)));
                }}
                if (i == 5) {{
                    float sRing = -dot(P, axis) / (dot(L, axis) + (dot(L, axis) < 0.0 ? -1e-4 : 1e-4));
                    float rkS = length(P + L * sRing) / size;
                    dark = max(dark, step(0.0, sRing) * step(1.32, rkS) * step(rkS, 2.30) * (1.0 - step(1.92, rkS) * step(rkS, 2.02)));
                }}
                globe = mix(globe, globe * 0.22 + shade * 0.75, dark * smoothstep(-0.05, 0.10, ndl));
                globe = mix(globe, mix(day, struckInk, 0.50), 0.45 * struck * smoothstep(0.15, 0.60, ndl));      // struck: its sunward side flashes
                if (i == 2) globe = mix(globe, vec3(0.48, 0.72, 1.0), 0.50 * edge(0.80, 1.0 - n.z, 2.0 * w) * smoothstep(-0.1, 0.3, ndl));   // air
                pc = mix(pc, globe, cover); pA = max(pA, cover);
            }}
            if (ringA_ > 0.0 && ringFront > 0.5) {{ pc = mix(pc, ringC, ringA_); pA = max(pA, ringA_); }}
        }}
        if (sv.z < 0.0) {{ under = mix(under, pc, pA); underA = max(underA, pA); }}
        else {{ over = mix(over, pc, pA); overA = max(overA, pA); }}
    }}

    // ---- Pluto: small, far, and on an orbit like no planet's - tipped seventeen degrees and so
    // lopsided that at perihelion it is inside Neptune's. With Charon, half its size and close by.
    {{
        float a = (a0 + uPlutoD) * tug;
        float th = TAU * uPlutoPh + uCamTurn;
        vec3 sv = toView(vec3(a * cos(th), a * sin(th), a * uPlutoZ), e, c);
        vec2 dq = q - sv.xy;
        float size = {orrery.JUPITER_SIZE * (orrery.PLUTO[5] / orrery.RADIUS[4]) ** 0.40:.5f};
        if (length(dq) < 4.0 * size + 3.0 * pxScene) {{
            vec3 L = normalize(-sv);
            float pA = disc(length(dq) / pxScene, size / pxScene + 1.5) * 0.92; vec3 pc = space * 0.55;
            vec2 cd = dq - size * 2.3 * vec2(cos(TAU * 6.0 * uOrbitSlow), e * sin(TAU * 6.0 * uOrbitSlow));
            float csz = max(0.52 * size, 1.3 * pxScene);
            vec3 cn = vec3(cd / csz, sqrt(max(1.0 - dot(cd, cd) / (csz * csz), 0.0)));
            float charon = disc(length(cd) / pxScene, csz / pxScene);
            pc = mix(pc, cel(vec3(0.62, 0.60, 0.60) * sunlight * lum, dot(cn, L), 1.0 - cn.z, shade, 1.2 * pxScene / csz), charon); pA = max(pA, charon);
            vec3 n = vec3(dq / size, sqrt(max(1.0 - dot(dq, dq) / (size * size), 0.0)));
            float heart = edge(0.52, soft(n * 2.1 + 3.0), 2.0 * pxScene / size);              // the pale plain
            vec3 day = mix(vec3(0.74, 0.58, 0.47), vec3(0.93, 0.87, 0.80), heart) * sunlight * lum;
            float cover = disc(length(dq) / pxScene, size / pxScene);
            pc = mix(pc, cel(day, dot(n, L), 1.0 - n.z, shade, 1.4 * pxScene / size), cover); pA = max(pA, cover);
            if (sv.z < 0.0) {{ under = mix(under, pc, pA); underA = max(underA, pA); }}
            else {{ over = mix(over, pc, pA); overA = max(overA, pA); }}
        }}
    }}

    // ---- put it together: the far half of the plane's waves, what is behind the Sun, the
    // corona, the Sun, then the near half and what is in front ---------------------------------------
    float farHalf = step(0.0, pl.y);
    col = mix(col, waveCol, waveA * farHalf);
    col = mix(col, under, clamp(underA, 0.0, 1.0));

    // The voice's ring wears each syllable: three short strokes stand out from it, along
    // the plane, the moment the syllable lands, and draw back in over a quarter of a
    // second - a crown that flickers with the words. Hard-edged; they go by getting shorter.
    {{
        float windT[N_WIND] = {_gather("uWindT", N_WIND)};
        float windA[N_WIND] = {_gather("uWindA", N_WIND)};
        float windK[N_WIND] = {_gather("uWindK", N_WIND)};
        float ringR = R * (1.55 + 1.15 * (0.5 + 0.5 * uPitch)) + 0.012 * uSustain;      // the voice's ring, where it is now
        vec3 windInk = vivid(mix(mix(kA, white, 0.45), cTint, 0.6 * uTint), 1.2);
        for (int i = 0; i < N_WIND; i++) {{
            float age = uTime - windT[i];
            if (age < -LEAD || age > 0.70 || windA[i] <= 0.0) continue;
            float out1 = (0.35 + 0.65 * windA[i]) * R * 0.62 * arrive(age, LEAD, 0.70);
            if (out1 < 1.5 * pxScene) continue;
            for (int k = 0; k < 3; k++) {{
                float phi = TAU * (windK[i] + float(k) / 3.0) + uCamTurn;
                vec2 dir = vec2(cos(phi), e * sin(phi));                // a radius of the plane, as the screen sees it
                float along = dot(q, dir) / dot(dir, dir);              // how far out along it this pixel is, in the plane
                if (along < ringR || along > ringR + out1) continue;
                float perp = length(q - along * dir) / pxScene;
                float u = (along - ringR) / out1;                        // 0 on the ring, 1 at the tip
                col = mix(col, windInk, disc(perp, (0.9 + 1.3 * windA[i]) * (1.0 - 0.75 * u)) * ev);
            }}
        }}
    }}

    float promT[N_PROM] = {_gather("uPromT", N_PROM)};
    float promA[N_PROM] = {_gather("uPromA", N_PROM)};
    float promK[N_PROM] = {_gather("uPromK", N_PROM)};

    // the corona: one band, in the song's colour, darker than the Sun - a rim of light,
    // not a second, bigger sun
    float out_ = r - R;
    if (out_ > -2.0 * pxScene && out_ < 0.30 + R) {{
        float flow = soft(vec3(normalize(q + 1e-5) * 1.3, 0.030 * uBeats));
        float reach = (0.012 + 0.020 * uBass + 0.014 * uRays * uHold + 0.008 * uSunPulse + 0.04 * uFlashE
                       + 0.020 * uCharge) * (0.80 + 0.40 * flow);             // ...and it stands further out as it charges
        // Where a prominence stands the corona stands out with it, a tongue of flame: the bass
        // line is in the Sun's silhouette, against the dark. Each tongue has a hot core. And a
        // discharge is one great tongue, there on its frame and drawn back in a fifth of a second.
        float around = atan(q.x, q.y);
        float tongue = 0.0;
        for (int i = 0; i < N_PROM; i++) {{
            float age = uTime - promT[i];
            if (age < -LEAD || age > 0.70 || promA[i] <= 0.0) continue;
            float dth = abs(mod(around - TAU * promK[i] + PI, TAU) - PI);
            // a swell of the rim, not a spike: broad, blunt-topped, a third as high as it is wide
            tongue += R * (0.09 + 0.30 * promA[i]) * exp(-pow(dth / 0.34, 2.6)) * arrive(age, LEAD, 0.70);        // it swells onto its note and sinks back
        }}
        float burst = 0.0;
        for (int i = 0; i < N_FLARE; i++) {{
            float age = uTime - flareT[i];
            if (age < -1.6 * LEAD || age > 0.9 || flareA[i] <= 0.0) continue;
            float phiF = TAU * flareK[i] + uCamTurn;                  // where on the limb that direction in the plane leaves from
            float dth = abs(mod(around - atan(cos(phiF), e * sin(phiF)) + PI, TAU) - PI);
            burst += R * 0.80 * flareA[i] * exp(-pow(dth / 0.40, 2.6)) * arrive(age, 1.6 * LEAD, 0.80);
        }}
        tongue = 0.50 * R * (1.0 - exp(-tongue / (0.50 * R)));         // the same note played again and again does not pile up into a spike
        reach += tongue + burst;
        vec3 rim = mix(vec3(0.80, 0.40, 0.15), vec3(0.95, 0.52, 0.19), uCharge);                       // always warm; hotter as it charges
        // the song's colour, plainly: this rim is where a section's palette is most seen
        col = mix(col, rim, disc(out_ / pxScene, reach / pxScene) * 0.92 * (0.70 * lum + 0.30 * ev));
        // The core of a tongue is the limb itself standing out: the limb's own tone, running
        // on from it with no seam, and tapering to nothing at its ends instead of being cut.
        float core = 0.52 * tongue + 0.70 * burst;
        vec3 limbTone = mix(vec3(1.0, 0.57, 0.19), vec3(1.0, 0.80, 0.42), clamp(0.32 + 0.45 * uBass * amb + 0.85 * kick * ev, 0.0, 1.0));
        col = mix(col, mix(limbTone, white, 0.55 * clamp(burst / R, 0.0, 1.0)), disc(out_ / pxScene, core / pxScene) * smoothstep(0.0, 2.0 * pxScene, core));
    }}
    if (r < R + 2.0 * pxScene) {{
        float mu = sqrt(max(1.0 - (r * r) / (R * R), 0.0));          // 1 at the centre of the disc, 0 at the limb
        float w = pxScene / R;
        // the bass warms the whole face; the kick flashes the limb - the middle of the face is the voice's
        float heat = clamp(0.32 + 0.45 * uBass * amb, 0.0, 1.0);
        vec3 surf = mix(vec3(1.0, 0.82, 0.40), vec3(1.0, 0.94, 0.72), heat);
        float discharge = 0.0;
        for (int i = 0; i < N_FLARE; i++) discharge = max(discharge, flareA[i] * arrive(uTime - flareT[i], LEAD, 0.50));
        vec3 limb = mix(vec3(1.0, 0.57, 0.19), vec3(1.0, 0.80, 0.42), clamp(heat + 0.85 * kick * ev, 0.0, 1.0));
        limb = mix(limb, white, 0.75 * discharge * ev);
        // limb darkening, as a real star has, in one clean step
        vec3 s = mix(limb, surf, disc(r / pxScene, 0.86 * R / pxScene));
        vec3 n = vec3(q / R, mu);
        float cells = soft(vec3(rot2(0.006 * uBeats) * n.xz, n.y).xzy * 1.7 + vec3(0.0, 0.0, 0.010 * uBeats));
        s = mix(s, mix(s, white, 0.12), edge(0.575, cells, 2.5 * w) * smoothstep(0.30, 0.60, mu));
        s = mix(s, s * vec3(0.95, 0.91, 0.88), (1.0 - edge(0.285, cells, 2.5 * w)) * smoothstep(0.45, 0.70, mu));
        // sunspots: a few, in the two belts they keep to, carried round by the Sun's slow turn -
        // an umbra and a penumbra, two flat tones
        {{
            float turn = 0.004 * uBeats;
            for (int k = 0; k < 4; k++) {{
                float fk = float(k);
                float latS = (mod(fk, 2.0) < 0.5 ? 0.30 : -0.24) + 0.08 * hash11(fk * 5.7);
                float lon = turn * (1.0 - 0.9 * sin(latS) * sin(latS)) + 1.7 * fk + 0.6 * hash11(fk * 3.1 + 0.2);   // it is not solid: its equator laps its higher latitudes
                vec3 at = vec3(cos(latS) * sin(lon), sin(latS), cos(latS) * cos(lon));
                if (at.z < 0.15) continue;                                // round the back, or too near the limb to draw cleanly
                float ang = acos(clamp(dot(n, at), -1.0, 1.0));
                float big = 0.050 + 0.035 * hash11(fk * 9.3 + 1.1);
                s = mix(s, s * vec3(0.86, 0.74, 0.62), 1.0 - edge(big, ang, 1.2 * w));
                s = mix(s, s * vec3(0.62, 0.42, 0.30), 1.0 - edge(0.45 * big, ang, 1.2 * w));
            }}
        }}
        // the voice is its heart: white-hot, as wide as the voice is loud
        float heart = R * (0.10 + 0.50 * uVoice + 0.22 * syll) * step(0.02, uVoice + syll);
        vec3 heartInk = mix(mix(white, cTint, 0.30 * uTint), vec3(1.0), 0.25);
        s = mix(s, mix(surf, heartInk, clamp(0.62 + 0.60 * syll, 0.0, 1.0)), disc(r / pxScene, heart / pxScene));
        col = mix(col, s, disc(r / pxScene, R / pxScene));
    }}
    col = mix(col, waveCol, waveA * (1.0 - farHalf));
    col = mix(col, over, clamp(overA, 0.0, 1.0));

    // a re-entry lifts the whole sky for a moment: one flat wash, and it goes slowly
    col = mix(col, mix(vec3(1.0, 0.72, 0.40), white, 0.45), 0.12 * uFlashE);
    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}}
"""


def vertex_source(header: str = GL_HEADER) -> str:
    return header + VERTEX_BODY.lstrip("\n")


def fragment_source(header: str = GL_HEADER) -> str:
    return header + FRAGMENT_BODY.lstrip("\n")


def surface_means(turns: int = 24):
    """Each planet's surface, averaged over the disc we see and a full rotation: the
    shader's own `surface()` drawn on eight spheres side by side. Needs a GL context."""
    import re

    import moderngl
    import numpy as np

    src = fragment_source()
    head = src[:src.index("void main()")]
    out = re.search(r"out vec4 (\w+);", head).group(1)
    main = """
void main() {
    gAA = 1.0;
    vec2 uv = gl_FragCoord.xy / uResolution;
    int i = int(floor(uv.x * 8.0));
    vec2 d = vec2(fract(uv.x * 8.0), uv.y) * 2.0 - 1.0;
    float r2 = dot(d, d);
    if (r2 > 1.0) { OUT = vec4(0.0); return; }
    vec3 n = vec3(d, sqrt(1.0 - r2));
    vec3 axis = vec3(0.0, 1.0, 0.0);
    float lat = dot(n, axis);
    vec3 e1 = normalize(cross(axis, vec3(0.31, 0.95, 0.10))), e2 = cross(axis, e1);
    vec3 sq = vec3(rot2(uTime) * vec2(dot(n, e1), dot(n, e2)), lat).xzy;
    OUT = vec4(surface(i, lat, sq, 0.01), 1.0);
}
""".replace("OUT", out)
    ctx = moderngl.create_standalone_context(require=330)
    try:
        prog = ctx.program(vertex_shader=vertex_source(), fragment_shader=head + main)
        quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1], dtype="f4").tobytes())
        vao = ctx.vertex_array(prog, [(quad, "2f", "aPos")])
        side = 256
        fbo = ctx.framebuffer([ctx.texture((8 * side, side), 4, dtype="f4")])
        fbo.use()
        prog["uResolution"].value = (8.0 * side, float(side))
        total = np.zeros((8, 3))
        for a in np.linspace(0.0, 2 * np.pi, turns, endpoint=False):
            prog["uTime"].value = float(a)
            vao.render(moderngl.TRIANGLES)
            img = np.frombuffer(fbo.read(components=4, dtype="f4"), dtype=np.float32).reshape(side, 8 * side, 4)
            for i in range(8):
                tile = img[:, i * side:(i + 1) * side]
                total[i] += tile[tile[..., 3] > 0.5][:, :3].mean(axis=0)
        return total / turns
    finally:
        ctx.release()
