"""The picture: one body, eight satellites on tilted orbits, a field, thrown rings.

Written, like the grammar, to the intersection of GLSL ES 3.00 and desktop GLSL
4.10 core, so the version line is the only difference between the mp4 and the
browser. It reads no previous frame. Every moving thing is a function of `uTime`
and of numbers that were baked from the audio, so any frame can be drawn cold.

Colour arrives as a palette of five roles in linear RGB - field, far field, body,
accent, second accent - already chosen, and already ramped, by `direct`. The
shader never picks a hue; it only decides which role a thing is, and for a note or
a ring, where between the two accents it sits.

The layers that come and go - rays, bands, stars - are always drawn, at a weight.
A weight of zero is the identity, so nothing can switch on.
"""

from __future__ import annotations

from .direct import N_RINGS, N_SATS, PALETTE_ROLES

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


def _palette_uniforms() -> str:
    return "\n".join(f"uniform float uC{role}R, uC{role}G, uC{role}B;" for role in PALETTE_ROLES)


def _palette_locals() -> str:
    return "\n".join(f"    vec3 c{role} = vec3(uC{role}R, uC{role}G, uC{role}B);"
                     for role in PALETTE_ROLES)


FRAGMENT_BODY = f"""
precision highp float;
layout(location = 0) out vec4 fragColor;

uniform vec2 uResolution;
uniform float uTime;

uniform float uMass, uKickT, uKickA, uBass;
uniform float uSpread, uOrbit, uHold, uTilt, uIncl;
uniform float uHatT, uHatA, uHatK;
uniform float uSynth, uPump;
uniform float uVoice, uPitch, uSyllT, uSyllA, uSustain;
uniform float uTint, uTintR, uTintG, uTintB;
uniform float uField, uAir, uExposure;
uniform float uRays, uBands, uStars, uDrift, uBeats;
uniform float uDropT, uDropA, uCrashT, uCrashA;
{_palette_uniforms()}
{_scalars("uRingT", N_RINGS)}
{_scalars("uRingA", N_RINGS)}
{_scalars("uRingM", N_RINGS)}
{_scalars("uNoteT", N_SATS)}
{_scalars("uNoteA", N_SATS)}
{_scalars("uNoteM", N_SATS)}

const float TAU = 6.28318530718;
const int N_RINGS = {N_RINGS};
const int N_SATS = {N_SATS};

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

vec2 hash2(vec2 p) {{
    return vec2(hash(p), hash(p + 17.31));
}}

// One layer of stars on a grid: a point per cell, a third of them answering each
// hat in turn, all of them ringing on after a crash.
float starLayer(vec2 p, float cell, float tick, float which, float shimmer) {{
    vec2 g = p / cell;
    vec2 id = floor(g);
    vec2 f = fract(g) - 0.5;
    vec2 o = (hash2(id) - 0.5) * 0.7;
    float keep = step(0.45, hash(id + 3.7));
    float d = length(f - o) * cell;
    float mine = 1.0 - min(abs(floor(hash(id + 9.1) * 3.0) - which), 1.0);
    float size = 0.0016 + 0.0012 * hash(id + 5.3);
    float b = 0.10 + 0.90 * tick * mine + shimmer * (0.4 + 0.6 * hash(id + 1.9));
    return keep * exp(-(d * d) / (size * size)) * b;
}}

void main() {{
    vec2 p = (gl_FragCoord.xy - 0.5 * uResolution) / uResolution.y;

    // The shock of a re-entry pushes the frame in and lets go; a kick nudges it.
    float dropAge = uTime - uDropT;
    float shock = uDropA * hit(dropAge, 0.30);
    float kick = uKickA * hit(uTime - uKickT, 0.105);
    p *= 1.0 - 0.085 * shock - 0.010 * kick;

    float r = length(p);
    float ang = atan(p.y, p.x);

    // Loudness sets how much light there is to stand in. A hit brings its own: it
    // already carries its own size, and a clap in a quiet bar is still a clap.
    float amb = 0.42 + 1.00 * uExposure;
    float ev = 0.80 + 0.30 * uExposure;

{_palette_locals()}
    vec3 cream = vec3(1.0, 0.95, 0.88);
    vec3 cTint = vec3(uTintR, uTintG, uTintB);
    // the light inside the body keeps most of its white, so a syllable stays a
    // flash of light; the aura round it takes the lyric's colour whole
    vec3 cVoice = mix(cream, cTint, 0.45 * uTint);
    vec3 cAura = mix(mix(cAccent, cream, 0.25), cTint, uTint);

    // ---- the body: mass sets its size, the kick punches it ---------------------
    float R = 0.078 * (0.50 + 0.80 * uMass) * (1.0 + 0.26 * kick);

    // ---- the far field: a slow two-colour sky, and the bands that drift in it ----
    float sky = 0.5 + 0.5 * sin(1.9 * p.y + 0.8 * p.x + 0.11 * uBeats);
    vec3 col = mix(cFar, cField, 0.25 + 0.5 * sky) * 0.0160 * amb;
    float band = 0.5 + 0.5 * sin(TAU * (1.35 * p.y + 0.22 * sin(1.3 * p.x + 0.045 * uBeats)
                                        + 0.021 * uBeats));
    band = band * band * (0.35 + 0.65 * smoothstep(0.10, 0.55, r));
    col += mix(cFar, cAccent2, 0.40) * band * uBands * (0.040 + 0.070 * uPump) * amb;

    // ---- the field: how far the pad reaches -------------------------------------
    float reach = 0.22 + 0.40 * uField;
    float field = exp(-(r * r) / (2.0 * reach * reach));
    col += cField * field * (0.030 + 0.028 * uField + 0.020 * uAir + 0.030 * uPump)
           * (amb + 0.9 * kick * ev);

    // ---- rays: the body's own light, fanned, turning with the bars ----------------
    float fan = 0.5 + 0.5 * cos(ang * 9.0 + 0.19 * uBeats);
    float fan2 = 0.5 + 0.5 * cos(ang * 5.0 - 0.13 * uBeats + 1.3);
    float rays = (0.65 * fan * fan * fan + 0.35 * fan2 * fan2) * exp(-r / 0.42)
                 * smoothstep(R, R + 0.10, r);
    col += mix(cBody, cAccent, 0.45) * rays * uRays * (0.050 * amb + 0.110 * kick * ev);

    // ---- stars: hats pick them out, a crash leaves them ringing, a riser draws ----
    // them outward. Two layers an octave apart, cross-faded, so the drift never ends.
    float tick = uHatA * hit(uTime - uHatT, 0.055);
    float shimmer = uCrashA * hit(uTime - uCrashT, 1.6);
    float z0 = fract(uDrift), z1 = fract(uDrift + 0.5);
    float stars = starLayer(p / exp2(z0), 0.085, tick, uHatK, shimmer) * sin(3.14159 * z0)
                + starLayer(p / exp2(z1) + 7.7, 0.085, tick, uHatK, shimmer) * sin(3.14159 * z1);
    col += mix(cAccent2, vec3(1.0), 0.35) * stars * uStars * (0.55 * amb + 1.3 * (tick + shimmer) * ev)
           * smoothstep(R + 0.02, R + 0.12, r);

    // ---- orbits and satellites ---------------------------------------------------
    float noteT[N_SATS] = {_gather("uNoteT", N_SATS)};
    float noteA[N_SATS] = {_gather("uNoteA", N_SATS)};
    float noteM[N_SATS] = {_gather("uNoteM", N_SATS)};

    // The innermost orbit clears the body even at the top of a kick, however far
    // the plane is tipped: a note lights a satellite, and a satellite behind the
    // body, or in front of its glare, is a note nobody saw.
    float a0 = max(0.250, 0.142 / uTilt);
    float tail = 0.25 + 1.10 * uHold;

    vec3 behind = vec3(0.0);
    vec3 before = vec3(0.0);
    for (int i = 0; i < N_SATS; i++) {{
        float fi = float(i);
        // every kick tugs the whole system inward for an instant
        float a = (a0 + 0.038 * fi) * uSpread * (1.0 - 0.045 * kick);
        float e = uTilt + 0.020 * sin(fi * 1.7 + 0.4);
        float inc = uIncl + 0.05 * sin(fi * 2.399 + 0.6);
        vec2 q = rot2(-inc) * p;

        // the line: distance to the ellipse, near enough for a hairline
        float k = length(vec2(q.x / a, q.y / (a * e)));
        float d = abs(k - 1.0) * a * mix(e, 1.0, abs(q.x) / max(length(q), 1e-4));
        float hair = exp(-(d * d) / (0.0015 * 0.0015));
        float line = hair * (0.030 * amb + 0.85 * tick * ev);

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

        // its wake: the stretch of orbit it has just been along, longer the harder
        // the body holds. It is the orbit's speed, made visible.
        float phi = atan(q.y / (a * e), q.x / a);
        float back = mod(th - phi, TAU);
        float wake = exp(-(d * d) / (0.0026 * 0.0026)) * exp(-back / tail)
                     * ((0.10 + 0.22 * uSynth) * amb + 0.9 * lit * ev);

        // a note's colour is where it sits between the two accents
        vec3 cNote = mix(cAccent, cAccent2, noteM[i]);
        vec3 cl = mix(cAccent, vec3(1.0), 0.15) * line * 0.8;
        vec3 cs = mix(cNote, vec3(1.0), 0.10 + 0.30 * lit) * sat + cNote * wake;
        // the line is split by which half of the ellipse this pixel is on, the
        // satellite by which half it is on: the far half goes behind the body
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
    // back with the melody, and swells while a note is held. It peaks away from the
    // rim, so the rim stays an edge.
    float standoff = 0.030 + 0.085 * (0.5 + 0.5 * uPitch);
    float av = (out_ - standoff) / (0.026 + 0.022 * uSustain);
    float aura = exp(-av * av) * (1.0 - disc);
    col += cAura * aura * (0.26 * uVoice + 0.24 * syll + 0.10 * uSustain) * ev;
    col += mix(cBody, cVoice, 0.5) * exp(-out_ / 0.16) * 0.07 * uVoice * ev * (1.0 - disc);

    col += before;

    // ---- rings: one per clap, thrown from the surface ----------------------------
    float ringT[N_RINGS] = {_gather("uRingT", N_RINGS)};
    float ringA[N_RINGS] = {_gather("uRingA", N_RINGS)};
    float ringM[N_RINGS] = {_gather("uRingM", N_RINGS)};
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
        // white when it is born, its own colour by the time it has travelled
        vec3 cRing = mix(mix(cAccent, cAccent2, ringM[i]), vec3(1.0), 0.08 + 0.40 * exp(-age / 0.10));
        col += cRing * exp(-g * g) * amp * ev * (1.50 * exp(-age / 0.10) + 0.60 * exp(-age / 0.38));
    }}

    // ---- the shock ring, and its light --------------------------------------------
    if (dropAge >= 0.0 && dropAge < 3.0) {{
        float rad = R + 1.35 * pow(dropAge, 0.62);
        float w = 0.010 + 0.060 * dropAge;
        float g = (r - rad) / w;
        col += mix(cAccent, vec3(1.0), 0.30) * exp(-g * g) * uDropA * 2.0 * exp(-dropAge / 0.55);
        col += mix(cBody, cAccent, 0.3) * field * uDropA * 0.36 * exp(-dropAge / 0.20);
    }}

    // ---- light, then the screen ------------------------------------------------------
    col *= 1.0 - 0.45 * smoothstep(0.30, 1.05, r);
    // Tone-map the brightness, not each channel: an exponential per channel pulls
    // every bright colour toward white, which is where the colour was going. Most of
    // the curve is applied to luminance and the colour is carried through it; a
    // little per-channel is kept so that a true overload still whitens.
    float lum = dot(col, vec3(0.2126, 0.7152, 0.0722));
    vec3 byLum = col * ((1.0 - exp(-lum * 1.5)) / max(lum, 1e-5));
    vec3 byChannel = 1.0 - exp(-col * 1.5);
    col = mix(byChannel, min(byLum, vec3(1.0)), 0.72);
    col = pow(col, vec3(1.0 / 2.2));
    col += (hash(gl_FragCoord.xy) - 0.5) / 255.0;
    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}}
"""


def vertex_source(header: str = GL_HEADER) -> str:
    return header + VERTEX_BODY.lstrip("\n")


def fragment_source(header: str = GL_HEADER) -> str:
    return header + FRAGMENT_BODY.lstrip("\n")
