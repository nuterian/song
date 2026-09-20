"""The picture: one body, eight satellites on tilted orbits, a field, thrown rings.

Written, like the grammar, to the intersection of GLSL ES 3.00 and desktop GLSL
4.10 core, so the version line is the only difference between the mp4 and the
browser. It reads no previous frame. Every moving thing is a function of `uTime`
and of numbers that were baked from the audio, so any frame can be drawn cold.
"""

from __future__ import annotations

from .direct import N_RINGS, N_SATS

GL_HEADER = "#version 410 core\n"
WEBGL_HEADER = "#version 300 es\n"

VERTEX_BODY = """
precision highp float;
layout(location = 0) in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
"""


def _scalars(prefix: str, count: int) -> str:
    return "\n".join(f"uniform float {prefix}{k};" for k in range(count))


def _gather(prefix: str, count: int) -> str:
    return f"float[{count}](" + ", ".join(f"{prefix}{k}" for k in range(count)) + ")"


FRAGMENT_BODY = f"""
precision highp float;
layout(location = 0) out vec4 fragColor;

uniform vec2 uResolution;
uniform float uTime;

uniform float uMass, uKickT, uKickA, uBass;
uniform float uSpread, uOrbit;
uniform float uHatT, uHatA;
uniform float uSynth;
uniform float uVoice, uPresence, uPitch, uSyllT, uSyllA;
uniform float uField, uAir, uHue, uWarm, uExposure;
uniform float uDropT, uDropA;
{_scalars("uRingT", N_RINGS)}
{_scalars("uRingA", N_RINGS)}
{_scalars("uNoteT", N_SATS)}
{_scalars("uNoteA", N_SATS)}

const float TAU = 6.28318530718;
const int N_RINGS = {N_RINGS};
const int N_SATS = {N_SATS};

vec3 hue(float h) {{
    return 0.5 + 0.5 * cos(TAU * (h - vec3(0.0, 0.3333, 0.6667)));
}}

mat2 rot2(float a) {{
    float c = cos(a), s = sin(a);
    return mat2(c, -s, s, c);
}}

// An event that happened `age` seconds ago, decaying over `tau`. Nothing before it.
float hit(float age, float tau) {{
    return age < 0.0 ? 0.0 : exp(-age / tau);
}}

float hash(vec2 p) {{
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}}

void main() {{
    vec2 p = (gl_FragCoord.xy - 0.5 * uResolution) / uResolution.y;

    // The shock of a re-entry: the frame is pushed in and lets go.
    float dropAge = uTime - uDropT;
    float shock = uDropA * hit(dropAge, 0.30);
    p *= 1.0 - 0.085 * shock;

    float r = length(p);

    // Loudness sets how much light there is to stand in. A hit brings its own: it
    // already carries its own size, and a clap in a quiet bar is still a clap.
    float amb = 0.30 + 1.10 * uExposure;
    float ev = 0.80 + 0.30 * uExposure;

    vec3 cBody  = mix(hue(uHue), vec3(1.0, 0.86, 0.70), 0.18 + 0.30 * uWarm);
    vec3 cField = hue(uHue - 0.07);
    vec3 cSat   = mix(hue(uHue + 0.13), vec3(1.0), 0.35);
    vec3 cRing  = mix(hue(uHue + 0.05), vec3(1.0), 0.55);
    vec3 cVoice = vec3(1.0, 0.95, 0.88);

    // ---- the body: mass sets its size, the kick punches it ---------------------
    float kick = uKickA * hit(uTime - uKickT, 0.105);
    float R = 0.078 * (0.50 + 0.80 * uMass) * (1.0 + 0.26 * kick);

    // ---- the field: how far the pad reaches -------------------------------------
    float reach = 0.22 + 0.40 * uField;
    float field = exp(-(r * r) / (2.0 * reach * reach));
    // The pad's brightness opens the field out; how much light is in it is the
    // song's loudness (exposure, below) and the body's own pulse.
    vec3 col = cField * field * (0.030 + 0.028 * uField + 0.020 * uAir) * (amb + 0.9 * kick * ev);
    col += cField * 0.0045 * amb;

    // ---- orbits and satellites ---------------------------------------------------
    float noteT[N_SATS] = {_gather("uNoteT", N_SATS)};
    float noteA[N_SATS] = {_gather("uNoteA", N_SATS)};
    float tick = uHatA * hit(uTime - uHatT, 0.055);

    vec3 behind = vec3(0.0);
    vec3 before = vec3(0.0);
    for (int i = 0; i < N_SATS; i++) {{
        float fi = float(i);
        // every kick tugs the whole system inward for an instant
        // The innermost orbit clears the body even at the top of a kick, seen from
        // this angle: a note lights a satellite, and a satellite behind the body, or
        // in front of its glare, is a note nobody saw.
        float a = (0.250 + 0.038 * fi) * uSpread * (1.0 - 0.045 * kick);
        // one plane, seen from a little above and a little askew: concentric
        // ellipses, not a tangle
        float e = 0.56 + 0.020 * sin(fi * 1.7 + 0.4);
        float inc = -0.24 + 0.05 * sin(fi * 2.399 + 0.6);
        vec2 q = rot2(-inc) * p;

        // the line: distance to the ellipse, near enough for a hairline
        float k = length(vec2(q.x / a, q.y / (a * e)));
        float d = abs(k - 1.0) * a * mix(e, 1.0, abs(q.x) / max(length(q), 1e-4));
        float line = exp(-(d * d) / (0.0015 * 0.0015)) * (0.030 * amb + 0.85 * tick * ev);

        // the satellite: Kepler, inner ones quicker
        float th = TAU * (uOrbit * pow(0.250 / (0.250 + 0.038 * fi), 1.5) * 2.2 + fi * 0.618);
        vec2 s = vec2(a * cos(th), a * e * sin(th));
        float z = -sin(th);
        // a pop and a short tail, so the next note a sixteenth later is still news
        float nAge = uTime - noteT[i];
        float lit = noteA[i] * (0.72 * hit(nAge, 0.055) + 0.28 * hit(nAge, 0.26));
        float size = 0.0070 * (1.0 + 0.30 * z) * (1.0 + 1.1 * lit);
        float ds = length(q - s);
        float dot_ = smoothstep(size, size * 0.55, ds);
        float glow = exp(-ds / (size * 2.8)) * (0.10 + 1.9 * lit);
        float sat = (dot_ * ((0.14 + 0.30 * uSynth) * amb + 3.2 * lit * ev)
                     + glow * ((0.08 + 0.20 * uSynth) * amb + 1.1 * lit * ev))
                    * (0.75 + 0.25 * z);

        // the line is split by which half of the ellipse this pixel is on, the
        // satellite by which half it is on: the far half goes behind the body
        vec3 cl = cSat * line * 0.8;
        vec3 cs = cSat * sat;
        if (q.y > 0.0) behind += cl; else before += cl;
        if (s.y > 0.0) behind += cs; else before += cs;
    }}
    col += behind;

    // ---- the body over what is behind it ----------------------------------------
    float disc = smoothstep(R + 0.0015, R - 0.0015, r);
    // a lit solid, always brighter than its own glow, so its edge is always an edge
    float shade = 0.78 + 0.22 * sqrt(max(1.0 - (r * r) / (R * R), 0.0));
    vec3 body = cBody * shade * ((0.17 + 0.30 * uBass) * amb + 0.34 * kick * ev);
    // the voice is the light inside it
    float syll = uSyllA * hit(uTime - uSyllT, 0.14);
    // kept well inside the body: at the rim it must not wash the edge out, because
    // the edge is how the kick is seen, and the voice and the kick play together
    float core = exp(-(r * r) / (2.0 * pow(R * (0.24 + 0.30 * uVoice), 2.0)));
    body += cVoice * core * (0.60 * uVoice + 0.40 * syll) * ev;
    col = mix(col, body, disc);

    // glow off the body: bass makes it breathe, the voice makes it reach
    float out_ = max(r - R, 0.0);
    col += cBody * exp(-out_ / (0.014 + 0.040 * uBass)) * ((0.03 + 0.10 * uBass) * amb + 0.12 * kick * ev) * (1.0 - disc);
    // the voice's aura: a soft band that stands off the surface and moves out and
    // back with the melody. It peaks away from the rim, so the rim stays an edge.
    float standoff = 0.030 + 0.085 * (0.5 + 0.5 * uPitch);
    float av = (out_ - standoff) / 0.028;
    float aura = exp(-av * av) * (1.0 - disc);
    col += mix(hue(uHue + 0.04), cVoice, 0.40) * aura * (0.24 * uVoice + 0.24 * syll) * ev;
    col += mix(cBody, cVoice, 0.5) * exp(-out_ / 0.16) * 0.07 * uVoice * ev * (1.0 - disc);

    col += before;

    // ---- rings: one per clap, thrown from the surface ----------------------------
    float ringT[N_RINGS] = {_gather("uRingT", N_RINGS)};
    float ringA[N_RINGS] = {_gather("uRingA", N_RINGS)};
    for (int i = 0; i < N_RINGS; i++) {{
        float age = uTime - ringT[i];
        if (age < 0.0 || age > 2.0) continue;
        // born thick and bright just off the surface, so the clap itself is seen,
        // then thinning as it travels
        float rad = R + 0.030 + 0.62 * pow(age, 0.72);
        float w = 0.0040 + 0.010 * exp(-age / 0.09) + 0.012 * age;
        float g = (r - rad) / w;
        // a quiet clap is a smaller ring, but never no ring
        float amp = ringA[i] > 0.0 ? 0.40 + 0.60 * ringA[i] : 0.0;
        col += cRing * exp(-g * g) * amp * ev * (1.50 * exp(-age / 0.10) + 0.60 * exp(-age / 0.38));
    }}

    // ---- the shock ring, and its light --------------------------------------------
    if (dropAge >= 0.0 && dropAge < 3.0) {{
        float rad = R + 1.35 * pow(dropAge, 0.62);
        float w = 0.010 + 0.060 * dropAge;
        float g = (r - rad) / w;
        col += mix(cRing, vec3(1.0), 0.4) * exp(-g * g) * uDropA * 2.0 * exp(-dropAge / 0.55);
        col += cBody * field * uDropA * 0.36 * exp(-dropAge / 0.20);
    }}

    // ---- light, then the screen ------------------------------------------------------
    col *= 1.0 - 0.45 * smoothstep(0.30, 1.05, r);
    col = 1.0 - exp(-col * 1.5);
    col = pow(col, vec3(1.0 / 2.2));
    col += (hash(gl_FragCoord.xy) - 0.5) / 255.0;
    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}}
"""


def vertex_source(header: str = GL_HEADER) -> str:
    return header + VERTEX_BODY.lstrip("\n")


def fragment_source(header: str = GL_HEADER) -> str:
    return header + FRAGMENT_BODY.lstrip("\n")
