"""The solar system, in three dimensions, cel-shaded, through a moving camera.

One fragment shader still. A ray leaves the camera for every pixel and is tested
against the things that are there: the Sun and the eight planets and their moons are
spheres, Saturn's rings and the plane of the ecliptic are planes, and whatever the ray
hits nothing of is the sky. No meshes, no previous frame; any frame can be drawn cold.

Why three dimensions, when the look is flat: because it puts things where they
belong. A clap's ripple, a planet's ping and the voice's ring are circles *in the
plane of the orbits* and are seen in perspective, on the axis of the gravity they
ride - not circles facing the viewer. A shooting star is small because it is far. And
the camera can go somewhere, which is how the song's acts are told.

What is real: the planets' order, character, colours and relative periods; phases and
terminators from one light at the origin; Saturn's rings, tilted and fixed in space,
with the planet's shadow across them; the Moon; the asteroid belt between Mars and
Jupiter and the Kuiper belt beyond Neptune; five thousand naked-eye stars from the
Yale Bright Star Catalogue at their true positions, magnitudes and colours; the Milky
Way where it is, crossing the ecliptic at sixty degrees, brightest toward Sagittarius
with the dark rift down it. What is not: distances and sizes are compressed, as in any
orrery; and everything answers the music.

The song's palette is in the *light* - the corona, the ripples, the trails, the
voice's ring, the lyric's tint - and never repaints a planet.

Light is instant, mass is not: flashes and rings land on their frame; the swelling of
the Sun and of a planet arrives *on* the hit, having begun a twentieth of a second
before it (`uSunPulse`, `uSwell*`, baked with look-ahead in `cosmos.py`).

Every edge is about one pixel of anti-aliasing: crisp, never a staircase, never a blur.
"""

from __future__ import annotations

from . import cosmos, sky
from .direct import N_METEORS, N_RINGS, N_SATS, PALETTE_ROLES

GL_HEADER = "#version 410 core\n"
WEBGL_HEADER = "#version 300 es\n"

VERTEX_BODY = """
precision highp float;
layout(location = 0) in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
"""

TEXTURES = ("uStarTex",)


def _scalars(prefix: str, count: int, suffix: str = "") -> str:
    return "\n".join(f"uniform float {prefix}{k}{suffix};" for k in range(count))


def _gather(prefix: str, count: int, suffix: str = "") -> str:
    return f"float[{count}](" + ", ".join(f"{prefix}{k}{suffix}" for k in range(count)) + ")"


def _palette_uniforms() -> str:
    return "\n".join(f"uniform float uC{role}R, uC{role}G, uC{role}B;" for role in PALETTE_ROLES)


def _palette_locals() -> str:
    return "\n".join(f"    vec3 c{role} = pow(vec3(uC{role}R, uC{role}G, uC{role}B), vec3(1.0 / 2.2));"
                     for role in PALETTE_ROLES)


def _vec3(v) -> str:
    return "vec3(" + ", ".join(f"{float(x):.7f}" for x in v) + ")"


_G = sky.galactic_frame()
_PLANET_SLOT = [cosmos.SLOT_TO_PLANET.index(i) for i in range(cosmos.N_PLANETS)]

FRAGMENT_BODY = f"""
precision highp float;
precision highp sampler2D;
layout(location = 0) out vec4 fragColor;

uniform vec2 uResolution;
uniform float uTime;
uniform sampler2D uStarTex;

uniform float uMass, uKickT, uKickA, uBass, uSunPulse;
uniform float uHold, uSpreadSlow, uYears;
uniform float uHatT, uHatA, uHatK;
uniform float uVoice, uPitch, uSyllT, uSyllA, uSustain;
uniform float uTint, uTintR, uTintG, uTintB;
uniform float uField, uExposure, uStars, uBeats;
uniform float uDropT, uDropA, uCrashT, uCrashA;
uniform float uCamX, uCamY, uCamZ, uTgtX, uTgtY, uTgtZ, uFov;
uniform float uCometX, uCometZ;
{_palette_uniforms()}
{_scalars("uRingT", N_RINGS)}
{_scalars("uRingA", N_RINGS)}
{_scalars("uRingM", N_RINGS)}
{_scalars("uNoteT", N_SATS)}
{_scalars("uNoteA", N_SATS)}
{_scalars("uNoteM", N_SATS)}
{_scalars("uSwell", N_SATS)}
{_scalars("uMetT", N_METEORS)}
{_scalars("uMetA", N_METEORS)}
{_scalars("uMetS", N_METEORS)}
{_scalars("uP", cosmos.N_PLANETS, "X")}
{_scalars("uP", cosmos.N_PLANETS, "Z")}

const float PI = 3.14159265359;
const float TAU = 6.28318530718;
const int N_RINGS = {N_RINGS};
const int N_SATS = {N_SATS};
const int N_METEORS = {N_METEORS};
const int N_PLANETS = {cosmos.N_PLANETS};
const int STAR_GRID = {sky.GRID};
const int STAR_PER_CELL = {sky.PER_CELL};
const float SUN_R = {cosmos.SUN_RADIUS:.5f};
const float PLANET_R[N_PLANETS] = float[{cosmos.N_PLANETS}]({", ".join(f"{r:.5f}" for r in cosmos.RADIUS)});
const float PLANET_PERIOD[N_PLANETS] = float[{cosmos.N_PLANETS}]({", ".join(f"{x:.5f}" for x in cosmos.PERIOD)});
const int PLANET_SLOT[N_PLANETS] = int[{cosmos.N_PLANETS}]({", ".join(str(x) for x in _PLANET_SLOT)});
const vec3 PLANET_TINT[N_PLANETS] = vec3[8](vec3(0.64, 0.60, 0.56), vec3(0.95, 0.84, 0.56), vec3(0.16, 0.48, 0.88),
    vec3(0.84, 0.40, 0.22), vec3(0.90, 0.76, 0.58), vec3(0.93, 0.83, 0.58), vec3(0.62, 0.89, 0.91), vec3(0.24, 0.42, 0.92));
const vec3 GAL_POLE = {_vec3(_G["pole"])};
const vec3 GAL_CENTRE = {_vec3(_G["centre"])};
const vec3 GAL_ACROSS = {_vec3(_G["across"])};
// Saturn's pole: 26.7 degrees off the ecliptic's, and fixed in space, so its rings
// open and close to the Sun as it goes round
const vec3 RING_POLE = vec3(0.3853, 0.8934, 0.2312);

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
// a band of constant width in *pixels* around f = 0, whatever f's units: the gradient
// of f across the screen says how many of its units a pixel is
float line(float f, float grad, float halfPx) {{
    float d = abs(f) / max(grad, 1e-6);
    return 1.0 - smoothstep(halfPx - 0.5, halfPx + 0.5, d);
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

// The Milky Way's brightness in a direction, 0..1. Not a stripe: a ragged river of
// light on the galactic equator, fat at the bulge toward the centre and thin opposite
// it, clotted into clouds, and split along much of its length by the dark rift.
float milkyWay(vec3 d) {{
    float b = degrees(asin(clamp(dot(d, GAL_POLE), -1.0, 1.0)));
    float l = degrees(atan(dot(d, GAL_ACROSS), dot(d, GAL_CENTRE)));
    float big = soft(d * 1.7 + 3.0), mid = soft(d * 4.3 + 9.0);
    float toCentre = exp(-(l * l) / (55.0 * 55.0));
    float width = (3.5 + 11.0 * toCentre) * (0.55 + 0.95 * big);      // the edge wanders by half its own width
    float centreLine = 3.0 * (big - 0.5) + 1.5 * sin(radians(l) * 1.7);
    float glow = exp(-pow((b - centreLine) / width, 2.0)) * (0.34 + 0.66 * toCentre + 0.20 * exp(-pow((abs(l) - 80.0) / 25.0, 2.0)));
    glow *= 0.45 + 1.10 * mid;                                        // clouds, and gaps between them
    float riftAt = centreLine + 1.0 + 3.0 * (soft(d * 3.1 + 21.0) - 0.5);
    float rift = exp(-pow((b - riftAt) / (1.0 + 2.2 * mid), 2.0)) * (1.0 - smoothstep(55.0, 95.0, abs(l)));
    return clamp(glow * (1.0 - 0.85 * rift), 0.0, 1.0);
}}

vec3 starColour(float cls) {{
    vec3 c = vec3(0.72, 0.83, 1.0);                                  // blue-white
    c = mix(c, vec3(1.0, 0.98, 0.95), step(0.5, cls));                // white
    c = mix(c, vec3(1.0, 0.94, 0.78), step(1.5, cls));                // yellow-white
    c = mix(c, vec3(1.0, 0.80, 0.52), step(2.5, cls));                // amber
    c = mix(c, vec3(1.0, 0.60, 0.44), step(3.5, cls));                // red
    return c;
}}

// A star: a hard disc whose size in *pixels* is its magnitude, so it is as sharp
// through a long lens as a wide one; the brightest few are four-pointed.
vec4 drawStar(vec3 rd, vec3 sd, float mag, float cls, vec3 right, vec3 upv, float pxAngle,
              float tick, float which, float shimmer) {{
    vec3 dv = sd - rd;
    vec2 px = vec2(dot(dv, right), dot(dv, upv)) / pxAngle;           // offset from the star, in pixels
    float h = hash12(sd.xz * 91.7 + sd.y * 13.1);
    float mine = 1.0 - min(abs(floor(h * 3.0) - which), 1.0);
    float lift = (tick * mine + shimmer * (0.4 + 0.6 * hash11(h * 7.3))) * step(mag, 5.0);
    float rad = clamp(0.80 + 0.60 * (5.8 - mag), 0.80, 5.0) * (1.0 + 0.55 * lift);
    float a = 1.0 - smoothstep(rad - 0.5, rad + 0.5, length(px));
    if (mag < 1.6) {{
        float reach = rad * (2.4 + 0.5 * (1.6 - mag)) * (1.0 + 0.8 * lift);
        float armX = (1.0 - smoothstep(0.4, 1.3, abs(px.y))) * (1.0 - smoothstep(reach - 0.5, reach + 0.5, abs(px.x)));
        float armY = (1.0 - smoothstep(0.4, 1.3, abs(px.x))) * (1.0 - smoothstep(reach - 0.5, reach + 0.5, abs(px.y)));
        a = max(a, max(armX, armY));
    }}
    float level = clamp(1.10 - 0.125 * mag + 0.5 * lift, 0.30, 1.0);
    return vec4(starColour(cls), a * level);
}}

vec3 skyColour(vec3 rd, vec3 right, vec3 upv, float pxAngle, vec3 space, vec3 kFar,
               float tick, float which, float shimmer, float starGain) {{
    // the galaxy, in three flat tones with clean edges
    float mw = milkyWay(rd);
    vec3 col = space;
    col = mix(col, vec3(0.034, 0.040, 0.082) + kFar * 0.020, smoothstep(0.150, 0.165, mw));
    col = mix(col, vec3(0.056, 0.060, 0.112) + kFar * 0.028, smoothstep(0.330, 0.345, mw));
    col = mix(col, vec3(0.088, 0.086, 0.140) + kFar * 0.032, smoothstep(0.540, 0.555, mw));
    col = mix(col, vec3(0.140, 0.126, 0.160) + kFar * 0.030, smoothstep(0.760, 0.775, mw));

    // the stars too faint for the catalogue: a hashed field, crowded where the galaxy
    // is - each one's existence decided where *it* is, not where the pixel is
    vec2 uv = octEncode(rd);
    const float FAINT = 380.0;
    vec2 cell = floor(uv * FAINT);
    vec2 at = 0.2 + 0.6 * hash22(cell + 0.37);
    vec3 fd = octDecode((cell + at) / FAINT);
    if (hash12(cell + 4.1) < 0.05 + 0.85 * milkyWay(fd)) {{
        vec3 dv = fd - rd;
        float dpx = length(vec2(dot(dv, right), dot(dv, upv))) / pxAngle;
        float rad = 0.70 + 0.35 * hash12(cell + 8.8);
        col = mix(col, vec3(0.80, 0.84, 0.95), (1.0 - smoothstep(rad - 0.5, rad + 0.5, dpx)) * (0.30 + 0.30 * hash12(cell + 2.2)) * starGain);
    }}

    // the real ones
    ivec2 c = min(ivec2(uv * float(STAR_GRID)), ivec2(STAR_GRID - 1));
    for (int k = 0; k < STAR_PER_CELL; k++) {{
        vec4 s = texelFetch(uStarTex, ivec2(c.x * STAR_PER_CELL + k, c.y), 0);
        if (dot(s.xyz, s.xyz) < 0.5) break;
        float cls = floor((s.w + 2.0) / 100.0);
        vec4 st = drawStar(rd, s.xyz, s.w - 100.0 * cls, cls, right, upv, pxAngle, tick, which, shimmer);
        col = mix(col, st.rgb, st.a * starGain);
    }}
    return col;
}}

// ------------------------------------------------------------------- the bodies

float sphere(vec3 ro, vec3 rd, vec3 c, float r) {{
    vec3 oc = ro - c;
    float b = dot(oc, rd), h = b * b - (dot(oc, oc) - r * r);
    return h < 0.0 ? -1.0 : -b - sqrt(h);
}}

// A planet's own colours, by where on it we are: `lat` is -1..1 pole to pole, `q` a
// point on its surface turning with it. Flat tones, large shapes, clean edges.
vec3 surface(int i, float lat, vec3 q) {{
    if (i == 0) return mix(vec3(0.64, 0.60, 0.56), vec3(0.47, 0.44, 0.42), smoothstep(0.52, 0.55, soft(q * 2.4)));
    if (i == 1) return mix(vec3(0.95, 0.84, 0.56), vec3(0.88, 0.72, 0.42), smoothstep(-0.05, 0.05, sin(lat * 7.0 + 1.5 * soft(q * 1.5))));
    if (i == 2) {{
        float land = soft(q * 1.9 + 5.0);
        vec3 c = mix(vec3(0.10, 0.34, 0.80), vec3(0.16, 0.48, 0.88), smoothstep(0.44, 0.47, land));      // deep and shallow sea
        c = mix(c, vec3(0.30, 0.64, 0.30), smoothstep(0.53, 0.55, land));
        c = mix(c, vec3(0.76, 0.66, 0.40), smoothstep(0.64, 0.66, land) * (1.0 - smoothstep(0.35, 0.6, abs(lat))));
        c = mix(c, vec3(0.97, 0.98, 1.0), smoothstep(0.82, 0.85, abs(lat) + 0.10 * land));                // ice
        float cloud = soft(vec3(rot2(0.9) * q.xz, q.y) * 2.3 + 17.0);
        return mix(c, vec3(1.0), 0.85 * smoothstep(0.60, 0.63, cloud));
    }}
    if (i == 3) {{
        vec3 c = mix(vec3(0.84, 0.40, 0.22), vec3(0.56, 0.26, 0.17), smoothstep(0.52, 0.55, soft(q * 2.0 + 2.0)));
        return mix(c, vec3(0.98, 0.95, 0.93), smoothstep(0.88, 0.91, abs(lat)));
    }}
    if (i == 4) {{
        float w = lat * 9.0 + 0.9 * soft(q * vec3(1.2, 4.0, 1.2));
        vec3 c = mix(vec3(0.93, 0.84, 0.68), vec3(0.78, 0.56, 0.38), smoothstep(-0.10, 0.10, sin(w)));
        c = mix(c, vec3(0.60, 0.40, 0.28), smoothstep(0.55, 0.70, sin(w * 0.5 + 1.0)) * 0.8);
        vec2 spot = vec2(atan(q.z, q.x) / 0.55, (lat + 0.37) / 0.13);                                     // the Great Red Spot
        return mix(c, vec3(0.84, 0.36, 0.24), 1.0 - smoothstep(0.85, 1.0, length(spot)));
    }}
    if (i == 5) return mix(vec3(0.93, 0.83, 0.58), vec3(0.82, 0.69, 0.44), smoothstep(-0.10, 0.10, sin(lat * 8.0 + 0.5 * soft(q * 1.4))));
    if (i == 6) return mix(vec3(0.62, 0.89, 0.91), vec3(0.54, 0.82, 0.87), smoothstep(-0.1, 0.1, sin(lat * 3.0)));
    vec3 c = mix(vec3(0.24, 0.42, 0.92), vec3(0.16, 0.30, 0.76), smoothstep(-0.10, 0.10, sin(lat * 5.0 + 0.8)));
    return mix(c, vec3(0.10, 0.20, 0.58), 1.0 - smoothstep(0.80, 1.0, length(vec2(atan(q.z, q.x) / 0.45, (lat + 0.32) / 0.12))));
}}

// Cel shading: a lit tone, a half tone, and a shadow that keeps its colour.
vec3 cel(vec3 day, float ndl, float rimness, vec3 space) {{
    vec3 night = day * 0.13 + space * 0.9;
    vec3 c = mix(night, mix(night, day, 0.50), smoothstep(-0.015, 0.015, ndl));
    c = mix(c, day, smoothstep(0.30, 0.33, ndl));
    c = mix(c, mix(day, vec3(1.0), 0.40), smoothstep(0.80, 0.83, rimness) * smoothstep(0.30, 0.50, ndl));
    // seen from behind, a world is a dark disc with a thin bright edge on the side the Sun is
    return mix(c, mix(day, vec3(1.0), 0.55), smoothstep(0.90, 0.93, rimness) * smoothstep(-0.30, -0.05, ndl) * (1.0 - smoothstep(0.0, 0.30, ndl)));
}}

void main() {{
    vec2 pixel = gl_FragCoord.xy;
    vec2 p = (pixel - 0.5 * uResolution) / uResolution.y;

    // ---- the camera -------------------------------------------------------------------
    vec3 ro = vec3(uCamX, uCamY, uCamZ);
    vec3 fwd = normalize(vec3(uTgtX, uTgtY, uTgtZ) - ro);
    vec3 right = normalize(cross(fwd, vec3(0.0, 1.0, 0.0)));
    vec3 upv = cross(right, fwd);
    float focal = 0.5 / tan(radians(uFov) * 0.5);
    vec3 rd = normalize(fwd * focal + p.x * right + p.y * upv);
    float pxAngle = 1.0 / (uResolution.y * focal);                   // radians a pixel subtends

    float amb = 0.42 + 1.00 * uExposure;
    float ev = 0.80 + 0.30 * uExposure;
    float lum = clamp(0.66 + 0.34 * amb, 0.0, 1.0);
    float kick = uKickA * hit(uTime - uKickT, 0.105);                 // as light: instant
    float syll = uSyllA * hit(uTime - uSyllT, 0.14);
    float dropAge = uTime - uDropT;

{_palette_locals()}
    vec3 white = vec3(1.0, 0.985, 0.95);
    vec3 cTint = pow(vec3(uTintR, uTintG, uTintB), vec3(1.0 / 2.2));
    vec3 kFar = vivid(cFar, 1.4), kBody = vivid(cBody, 1.8);
    vec3 kA = vivid(cAccent, 1.6), kB = vivid(cAccent2, 1.6);
    vec3 space = vec3(0.016, 0.020, 0.046) + kFar * 0.022;
    // the Sun's light, faintly the section's colour: the song is in the light
    vec3 sunlight = mix(vec3(1.0, 0.97, 0.90), kBody, 0.14);

    float tick = uHatA * hit(uTime - uHatT, 0.060);
    float shimmer = uCrashA * hit(uTime - uCrashT, 1.6);

    // ---- the sky, and what crosses it ---------------------------------------------------
    vec3 col = skyColour(rd, right, upv, pxAngle, space, kFar, tick, uHatK, shimmer, 0.45 + 0.55 * uStars);

    // shooting stars: far away, so small - a thin bright scratch, never the size of a planet
    float metT[N_METEORS] = {_gather("uMetT", N_METEORS)};
    float metA[N_METEORS] = {_gather("uMetA", N_METEORS)};
    float metS[N_METEORS] = {_gather("uMetS", N_METEORS)};
    for (int i = 0; i < N_METEORS; i++) {{
        float age = uTime - metT[i];
        if (age < 0.0 || age > 1.3 || metA[i] <= 0.0) continue;
        float s = metS[i];
        float alpha = TAU * hash11(s * 7.13 + 0.3);
        vec2 start = vec2(0.78 * cos(alpha), 0.42 * sin(alpha));
        float side = hash11(s * 3.71 + 1.9) < 0.5 ? -1.0 : 1.0;
        vec2 dir = rot2(side * (0.55 + 0.35 * hash11(s * 5.3))) * normalize(-start);
        float speed = 0.55 + 0.30 * hash11(s * 9.7) + 0.25 * metA[i];
        vec2 head = start + dir * speed * age;
        vec2 d = p - head;
        float back = -dot(d, dir), off = abs(dot(d, vec2(-dir.y, dir.x))) * uResolution.y;
        float len = (0.035 + 0.075 * metA[i]) * min(age / 0.08, 1.0);
        float u = clamp(back / len, 0.0, 1.0);
        float live = 1.0 - smoothstep(0.75, 1.1, age);
        float w = (0.9 + 1.3 * metA[i]) * (1.0 - u);
        float tail = step(0.0, back) * step(back, len) * (1.0 - smoothstep(w - 0.5, w + 0.5, off));
        col = mix(col, mix(white, kA, smoothstep(0.25, 0.45, u)), tail * live * (0.55 + 0.45 * metA[i]));
    }}

    // ---- the Sun ---------------------------------------------------------------------------
    float Rs = SUN_R * (0.82 + 0.22 * uMass) * (1.0 + 0.15 * uSunPulse);
    float dSun = length(ro);
    vec3 sunDir = -ro / dSun;
    float tSun = sphere(ro, rd, vec3(0.0), Rs);

    // ---- the planets, their moons, Saturn's rings: the nearest thing the ray meets --------
    float swell[N_SATS] = {_gather("uSwell", N_SATS)};
    float noteT[N_SATS] = {_gather("uNoteT", N_SATS)};
    float noteA[N_SATS] = {_gather("uNoteA", N_SATS)};
    float noteM[N_SATS] = {_gather("uNoteM", N_SATS)};
    float px_[N_PLANETS] = {_gather("uP", cosmos.N_PLANETS, "X")};
    float pz_[N_PLANETS] = {_gather("uP", cosmos.N_PLANETS, "Z")};

    float tNear = 1e9;
    vec3 nearCol = vec3(0.0);
    if (tSun > 0.0) tNear = tSun;                                     // shaded below, once the winner is known
    int winner = tSun > 0.0 ? -1 : -2;                                // -1 Sun, -2 nothing, >= 0 a planet, 100+ a moon

    vec3 moonC = vec3(0.0); float moonR = 0.0; vec3 moonHost = vec3(0.0);
    for (int i = 0; i < N_PLANETS; i++) {{
        vec3 c = vec3(px_[i], 0.0, pz_[i]);
        int slot = PLANET_SLOT[i];
        float dist = length(c - ro);
        // an orrery's licence: a body is never drawn smaller than a few pixels
        float r = max(PLANET_R[i] * (1.0 + 0.20 * swell[slot]), 4.2 * pxAngle * dist);
        float t = sphere(ro, rd, c, r);
        if (t > 0.0 && t < tNear) {{ tNear = t; winner = i; }}
        // moons: the Moon; Io and Ganymede; Titan
        int moons = i == 2 ? 1 : i == 4 ? 2 : i == 5 ? 1 : 0;
        for (int m = 0; m < 2; m++) {{
            if (m >= moons) break;
            float fm = float(m);
            float mper = i == 2 ? 0.0748 : i == 4 ? 0.055 + 0.060 * fm : 0.085;
            float ma = TAU * (uYears / mper + 0.31 * float(i) + 0.57 * fm);
            float mr = r * (i == 2 ? 3.4 : 2.3 + 1.0 * fm);
            vec3 mc = c + mr * vec3(cos(ma), (i == 5 ? 0.45 : 0.08) * sin(ma), sin(ma));
            float rr = max(r * (i == 2 ? 0.27 : 0.16), 1.6 * pxAngle * dist);
            float tm = sphere(ro, rd, mc, rr);
            if (tm > 0.0 && tm < tNear) {{ tNear = tm; winner = 100 + i; moonC = mc; moonR = rr; moonHost = c; }}
        }}
    }}

    // Saturn's rings: a plane through Saturn, an annulus in it, a gap, and the planet's
    // own shadow lying across the far side
    float tRing = -1.0; vec3 ringCol = vec3(0.0); float ringA = 0.0;
    {{
        vec3 c = vec3(px_[5], 0.0, pz_[5]);
        float dist = length(c - ro);
        float r = max(PLANET_R[5] * (1.0 + 0.20 * swell[PLANET_SLOT[5]]), 4.2 * pxAngle * dist);
        float denom = dot(rd, RING_POLE);
        float t = dot(c - ro, RING_POLE) / (abs(denom) < 1e-5 ? 1e-5 : denom);
        vec3 q = ro + t * rd - c;
        float rho = length(q) / r;
        float g = max(length(vec2(dFdx(rho), dFdy(rho))), 1e-6);      // ring-radii per pixel
        float inside = smoothstep(-0.5, 0.5, (rho - 1.30) / g) * (1.0 - smoothstep(-0.5, 0.5, (rho - 2.30) / g));
        float gap = smoothstep(-0.5, 0.5, (rho - 1.92) / g) * (1.0 - smoothstep(-0.5, 0.5, (rho - 2.02) / g));
        vec3 toSun = normalize(-c);
        float along = dot(q, -toSun);
        float castShadow = step(0.0, along) * (1.0 - smoothstep(r * 0.98, r * 1.02, length(q + toSun * along)));
        vec3 inkR = mix(vec3(0.90, 0.82, 0.62), vec3(0.72, 0.64, 0.48), smoothstep(-0.5, 0.5, (rho - 1.62) / g) * (1.0 - step(1.92, rho)));
        ringCol = mix(inkR * sunlight * lum, inkR * 0.14 + space, castShadow);
        ringA = t > 0.0 ? inside * (1.0 - gap) * 0.95 : 0.0;
        tRing = t;
    }}

    // ---- the plane of the ecliptic: ripples, trails, belts - what gravity holds -----------
    float tPlane = -ro.y / (abs(rd.y) < 1e-5 ? 1e-5 : rd.y);
    vec3 Q = ro + tPlane * rd;
    float rho = length(Q.xz);
    float gRho = max(length(vec2(dFdx(rho), dFdy(rho))), 1e-6);        // world units per pixel, radially
    // Toward the horizon a pixel covers more and more of the plane, until a line a pixel
    // wide means nothing and everything reads as "on the line". The plane fades out
    // before that happens.
    float planeOK = step(0.0, tPlane) * (1.0 - smoothstep(30.0, 45.0, tPlane)) * (1.0 - smoothstep(0.05, 0.16, gRho));
    vec3 planeCol = vec3(0.0); float planeA = 0.0;

    // a wave passing: a clap's ring, a re-entry's. Where it is, what lies in the plane is
    // pushed outward with it and falls back; the belts are looked up at that displaced point
    float ringT[N_RINGS] = {_gather("uRingT", N_RINGS)};
    float ringA_[N_RINGS] = {_gather("uRingA", N_RINGS)};
    float ringM[N_RINGS] = {_gather("uRingM", N_RINGS)};
    float shove = 0.0;
    for (int i = 0; i < N_RINGS; i++) {{
        float age = uTime - ringT[i];
        if (age < 0.0 || age > 2.4 || ringA_[i] <= 0.0) continue;
        float rad = Rs + 0.10 + 2.2 * pow(age, 0.72);
        float g = (rho - rad) / 0.12;
        shove += 0.030 * (0.4 + 0.6 * ringA_[i]) * exp(-g * g) * exp(-age / 0.6);
        float wpx = 1.2 + 3.2 * exp(-age / 0.08);
        float a_ = line(rho - rad, gRho, wpx) * clamp((0.40 + 0.60 * ringA_[i]) * (0.9 * exp(-age / 0.12) + 0.75 * exp(-age / 0.55)), 0.0, 1.0);
        vec3 c = mix(mix(kA, kB, ringM[i]), white, 0.15 + 0.55 * exp(-age / 0.10));
        planeCol = mix(planeCol, c, step(planeA, a_ * ev)); planeA = max(planeA, a_ * ev);
    }}
    if (dropAge >= 0.0 && dropAge < 5.0) {{
        // the re-entry's shock: three rings, and slow enough to be watched crossing the system
        float rad = Rs + 1.9 * pow(dropAge, 0.70);
        float g = (rho - rad) / 0.22;
        shove += 0.085 * uDropA * exp(-g * g) * exp(-dropAge / 1.4);
        for (int k = 0; k < 3; k++) {{
            float fk = float(k);
            float a_ = line(rho - rad * (1.0 - 0.10 * fk), gRho, 3.0 - 0.8 * fk)
                       * clamp(uDropA * exp(-dropAge / 1.5) * (1.0 - 0.3 * fk), 0.0, 1.0);
            vec3 c = mix(kA, white, 0.55 - 0.15 * fk);
            planeCol = mix(planeCol, c, step(planeA, a_)); planeA = max(planeA, a_);
        }}
    }}
    // the voice: one thin ring in the plane, riding out and back with the melody
    {{
        float rad = Rs * (1.55 + 1.25 * (0.5 + 0.5 * uPitch)) + 0.05 * uSustain;
        float a_ = line(rho - rad, gRho, 0.9 + 0.7 * uSustain + 0.6 * syll) * clamp(1.4 * uVoice + 0.9 * syll, 0.0, 1.0) * ev;
        vec3 c = vivid(mix(mix(kA, white, 0.30), cTint, uTint), 1.3);
        planeCol = mix(planeCol, c, step(planeA, a_)); planeA = max(planeA, a_);
    }}

    vec2 Qw = Q.xz * (1.0 - shove / max(rho, 0.05));
    float rhoW = length(Qw);
    float thQ = atan(Qw.y, Qw.x);

    // trails: no orbit is drawn. Each planet leaves a short wake that fades behind it,
    // longer the faster it goes - its colour, warmed by the song's
    for (int i = 0; i < N_PLANETS; i++) {{
        vec2 c = vec2(px_[i], pz_[i]);
        float a = length(c);
        float behind = mod(atan(c.y, c.x) - thQ, TAU);
        float reach = clamp(1.25 * pow(PLANET_PERIOD[i], -0.42), 0.10, 1.7) * (0.55 + 0.45 * uHold);
        float fade = behind < reach ? pow(1.0 - behind / reach, 1.6) : 0.0;
        float a_ = line(rhoW - a, gRho, 0.9) * fade * (0.30 + 0.45 * lum);
        vec3 tc = mix(PLANET_TINT[i], kA, 0.40);
        planeCol = mix(planeCol, mix(tc, white, 0.25), step(planeA, a_)); planeA = max(planeA, a_);

        // a note: a ring thrown off the planet, lying in the plane with everything else
        int slot = PLANET_SLOT[i];
        float nAge = uTime - noteT[slot];
        float dP = length(Q.xz - c);
        float gP = max(length(vec2(dFdx(dP), dFdy(dP))), 1e-6);
        float r = max(PLANET_R[i], 4.2 * pxAngle * length(vec3(c.x, 0.0, c.y) - ro));
        float pingR = r * (1.6 + 3.2 * (1.0 - exp(-max(nAge, 0.0) / 0.16)));
        float ping = line(dP - pingR, gP, 1.0) * clamp(noteA[slot], 0.0, 1.0) * hit(nAge, 0.22) * step(0.0, nAge) * ev;
        vec3 pc = mix(mix(kA, kB, noteM[slot]), white, 0.35);
        planeCol = mix(planeCol, pc, step(planeA, ping)); planeA = max(planeA, ping);
    }}

    // belts: the asteroids between Mars and Jupiter, and the Kuiper belt beyond Neptune.
    // Lanes at Keplerian rates, rocks two-toned and lit from the Sun; hats make them glint.
    for (int bI = 0; bI < 2; bI++) {{
        float inner = bI == 0 ? 1.30 : 3.45, laneW = bI == 0 ? 0.075 : 0.16;
        float lanes = bI == 0 ? 3.0 : 2.0, count0 = bI == 0 ? 56.0 : 70.0;
        float pr = rhoW / uSpreadSlow;
        float li = floor((pr - inner) / laneW);
        if (li < 0.0 || li >= lanes) continue;
        float lr = inner + (li + 0.5) * laneW;
        float count = floor(count0 + 12.0 * li);
        float turn = uYears / pow(lr, 1.5 / {cosmos.DISTANCE_POWER:.3f});
        float ci = floor(fract(thQ / TAU - turn) * count);
        vec2 id = vec2(ci, li + 11.0 + 23.0 * float(bI));
        if (hash12(id) < (bI == 0 ? 0.30 : 0.55)) continue;
        vec2 jit = hash22(id + 2.3) - 0.5;
        float ang = TAU * ((ci + 0.5 + 0.45 * jit.x) / count + turn);
        vec3 rc = (lr + 0.28 * laneW * jit.y) * uSpreadSlow * vec3(cos(ang), 0.0, sin(ang));
        vec3 v = rc - ro;
        float zc = dot(v, fwd);
        if (zc < 0.05) continue;
        vec2 sC = vec2(dot(v, right), dot(v, upv)) * focal / zc;        // the rock, on screen
        float mine = 1.0 - min(abs(floor(hash12(id + 9.1) * 3.0) - uHatK), 1.0);
        float glint = tick * mine;
        float rw = mix(0.006, 0.014, hash12(id + 4.4)) * (bI == 0 ? 1.0 : 0.8);
        float rpx = clamp(rw * focal / zc * uResolution.y, 1.1, 0.30 * laneW * uSpreadSlow / gRho) * (1.0 + 0.8 * glint);
        vec2 dd = (p - sC) * uResolution.y;
        float spin = uBeats * (0.04 + 0.10 * hash12(id + 6.1)) * (hash12(id + 8.8) < 0.5 ? -1.0 : 1.0);
        float lump = 0.78 + 0.22 * cos(3.0 * atan(dd.y, dd.x) + spin + TAU * hash12(id + 7.7));
        float rock = 1.0 - smoothstep(rpx * lump - 0.5, rpx * lump + 0.5, length(dd));
        vec3 vs = -ro; float zs = max(dot(vs, fwd), 0.05);
        vec2 toSun = normalize(vec2(dot(vs, right), dot(vs, upv)) * focal / zs - sC + 1e-6);
        float lit = smoothstep(-0.16, -0.04, dot(normalize(dd + 1e-5), toSun));
        vec3 tone = vec3(0.60, 0.57, 0.55) * (0.80 + 0.25 * hash12(id + 3.3)) * sunlight * lum;
        vec3 rk = mix(mix(tone * 0.22 + space, white, 0.35 * glint), mix(tone, white, glint), lit);
        planeCol = mix(planeCol, rk, step(planeA, rock)); planeA = max(planeA, rock);
    }}
    planeA *= planeOK;

    // ---- a comet: small, far, its tails always away from the Sun ---------------------------
    vec3 cometCol = vec3(0.0); float cometA = 0.0; float tComet = 1e9;
    {{
        vec3 cc = vec3(uCometX, 0.0, uCometZ);
        vec3 v = cc - ro; float zc = dot(v, fwd);
        if (zc > 0.05) {{
            vec2 sC = vec2(dot(v, right), dot(v, upv)) * focal / zc;
            float closeness = clamp(0.9 / max(length(cc), 0.3), 0.0, 1.0);
            vec3 tipW = cc + normalize(cc) * (0.10 + 0.55 * closeness * closeness) * (0.55 + 0.75 * uField);
            vec3 vt = tipW - ro; float zt = max(dot(vt, fwd), 0.05);
            vec2 sT = vec2(dot(vt, right), dot(vt, upv)) * focal / zt;
            vec2 axis = sT - sC; float len = max(length(axis), 1e-5); axis /= len;
            vec2 d = p - sC;
            float back = dot(d, axis), off = abs(dot(d, vec2(-axis.y, axis.x))) * uResolution.y;
            float u = clamp(back / len, 0.0, 1.0);
            float w = (1.0 + 2.2 * closeness) * (1.0 - 0.85 * u);
            float dust = step(0.0, back) * step(back, len) * (1.0 - smoothstep(w - 0.5, w + 0.5, off));
            cometCol = mix(kB, white, 0.30 * (1.0 - u)); cometA = dust * (0.70 - 0.45 * u) * lum;
            float head = 1.0 - smoothstep(1.6 - 0.5, 1.6 + 0.5, length(d) * uResolution.y);
            cometCol = mix(cometCol, white, head); cometA = max(cometA, head);
            tComet = length(v);
        }}
    }}

    // ---- put it together, nearest last ----------------------------------------------------
    // the corona first: two... no - one band, in the song's colour, darker than the Sun,
    // and hidden by anything that stands in front of it
    float gamma = acos(clamp(dot(rd, sunDir), -1.0, 1.0));
    float alphaS = asin(clamp(Rs / dSun, 0.0, 1.0));
    float flow = soft(vec3(normalize(p + 1e-5) * 1.3, 0.030 * uBeats));
    float reach = (0.16 + 0.26 * uBass + 0.42 * uSunPulse + 0.50 * uDropA * hit(dropAge, 0.8)) * (0.80 + 0.40 * flow);
    float corona = 1.0 - smoothstep(-0.5, 0.5, (gamma - alphaS * (1.0 + reach)) / pxAngle);
    vec3 coronaInk = mix(vec3(1.0, 0.62, 0.24), kBody, 0.50) * 0.62;
    col = mix(col, coronaInk, corona * 0.85 * (0.70 * lum + 0.30 * ev));

    float tSolid = tNear;
    vec3 solid = vec3(0.0); float solidA = 0.0;
    if (winner == -1) {{
        vec3 n = normalize(ro + tSun * rd);
        float mu = dot(n, -rd);                                       // 1 at the centre of the disc, 0 at the limb
        float heat = clamp(0.30 + 0.45 * uBass * amb + 0.55 * kick * ev, 0.0, 1.0);
        vec3 surf = mix(vec3(1.0, 0.80, 0.38), vec3(1.0, 0.93, 0.70), heat);
        vec3 limb = mix(vec3(1.0, 0.56, 0.18), vec3(1.0, 0.70, 0.30), heat);
        vec3 c = mix(limb, surf, smoothstep(0.50, 0.53, mu));
        float cells = soft(vec3(rot2(0.006 * uBeats) * n.xz, n.y).xzy * 1.7 + vec3(0.0, 0.0, 0.010 * uBeats));
        c = mix(c, mix(c, white, 0.12), smoothstep(0.56, 0.59, cells) * smoothstep(0.30, 0.60, mu));
        c = mix(c, c * vec3(0.95, 0.91, 0.88), smoothstep(0.30, 0.27, cells) * smoothstep(0.45, 0.70, mu));
        // the voice is its heart: white-hot, as wide as the voice is loud
        float heart = (0.10 + 0.50 * uVoice + 0.22 * syll) * step(0.02, uVoice + syll);
        float fromCentre = sqrt(max(1.0 - mu * mu, 0.0));
        float gH = pxAngle * dSun / Rs;                                  // (no derivative here: this is inside a branch)
        vec3 heartInk = mix(mix(white, cTint, 0.30 * uTint), vec3(1.0), 0.25);
        c = mix(c, mix(surf, heartInk, clamp(0.62 + 0.60 * syll, 0.0, 1.0)), 1.0 - smoothstep(-0.5, 0.5, (fromCentre - heart) / gH));
        solid = c; solidA = 1.0;
    }} else if (winner >= 100) {{
        vec3 n = normalize(ro + tNear * rd - moonC);
        vec3 L = normalize(-moonC);
        // a moon in its planet's shadow goes dark: an eclipse, seen from outside
        vec3 toHost = moonHost - moonC; float al = dot(toHost, L);
        float hidden = step(0.0, al) * step(length(toHost - L * al), PLANET_R[winner - 100]);
        solid = cel(vec3(0.80, 0.79, 0.80) * sunlight * lum, dot(n, L) * (1.0 - hidden) - hidden, 1.0 - dot(n, -rd), space);
        solidA = 1.0;
    }} else if (winner >= 0) {{
        int i = winner;
        vec3 c0 = vec3(px_[i], 0.0, pz_[i]);
        vec3 n = normalize(ro + tNear * rd - c0);
        vec3 L = normalize(-c0);
        // its own axis, tilted as it is, and its day turning under it
        float tiltA = i == 2 ? 0.41 : i == 3 ? 0.44 : i == 5 ? 0.466 : i == 6 ? 1.71 : i == 7 ? 0.49 : 0.05;
        vec3 axis = i == 5 ? RING_POLE : normalize(vec3(sin(tiltA) * cos(1.1 * float(i)), cos(tiltA), sin(tiltA) * sin(1.1 * float(i))));
        vec3 e1 = normalize(cross(axis, vec3(0.31, 0.0, 0.95))), e2 = cross(axis, e1);
        float lat = dot(n, axis);
        float spin = uYears * (i < 4 ? 9.0 : 16.0) + float(i);
        vec3 q = vec3(rot2(spin) * vec2(dot(n, e1), dot(n, e2)), lat).xzy;
        int slot = PLANET_SLOT[i];
        float lit = noteA[slot] * (0.72 * hit(uTime - noteT[slot], 0.055) + 0.28 * hit(uTime - noteT[slot], 0.26));
        vec3 day = surface(i, lat, q) * sunlight * lum * (1.0 + 0.16 * kick * ev);
        // a note is the planet catching light: its day flares, its night glows its own colour
        day = mix(day, mix(day, white, 0.62), clamp(1.2 * lit, 0.0, 1.0));
        float ndl = dot(n, L);
        // Saturn wears its rings' shadow as a thin dark line
        if (i == 5) {{
            vec3 hp = ro + tNear * rd - c0;
            float tr = dot(-hp, RING_POLE) / max(abs(dot(L, RING_POLE)), 1e-4) * sign(dot(L, RING_POLE));
            float rr = length(hp + L * tr) / max(PLANET_R[5], 1e-5);
            ndl = (tr > 0.0 && rr > 1.30 && rr < 2.30 && !(rr > 1.92 && rr < 2.02)) ? min(ndl, -0.2) : ndl;
        }}
        vec3 c = cel(day, ndl, 1.0 - dot(n, -rd), space);
        c += surface(i, lat, q) * 0.55 * lit * (1.0 - smoothstep(-0.02, 0.10, ndl));
        if (i == 2) c = mix(c, vec3(0.45, 0.70, 1.0), 0.55 * smoothstep(0.78, 0.82, 1.0 - dot(n, -rd)) * smoothstep(-0.1, 0.3, ndl));   // air
        solid = c; solidA = 1.0;
    }}

    // nearest last: whichever of the solid body, the rings and the plane is farthest goes down first
    bool ringFirst = tRing > tSolid || winner == -2;
    bool planeBehind = tPlane > tSolid && winner != -2;
    if (planeBehind) col = mix(col, planeCol, planeA);
    if (ringFirst && tRing > 0.0) col = mix(col, ringCol, ringA);
    col = mix(col, solid, solidA);
    if (!ringFirst && tRing > 0.0) col = mix(col, ringCol, ringA);
    if (!planeBehind) col = mix(col, planeCol, planeA);
    if (tComet < tSolid || winner == -2) col = mix(col, cometCol, cometA);

    // a re-entry lifts the whole sky for a moment: one flat wash, and it goes slowly
    col = mix(col, mix(coronaInk, white, 0.4), 0.16 * uDropA * hit(dropAge, 0.45));

    col *= 1.0 - 0.30 * smoothstep(0.45, 1.05, length(p));
    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}}
"""


def vertex_source(header: str = GL_HEADER) -> str:
    return header + VERTEX_BODY.lstrip("\n")


def fragment_source(header: str = GL_HEADER) -> str:
    return header + FRAGMENT_BODY.lstrip("\n")
