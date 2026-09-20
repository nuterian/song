"""The same piece as a place: a star, its planets, belts, a comet, and the real sky.

Cel-shaded, and otherwise as real as it can be made. The look began as a port of
github.com/nuterian/forge's "space-age print", and what was kept from that is the
cel shading - light and shadow as two flat tones of one colour, hard terminators,
real phases, glow as clean stepped bands rather than blur. What was *not* kept,
because it was asked not to be, is the print: no dither, no grain, no noisy cells,
nothing that reads as pixel art. Surfaces are flat with a little large, slow
variation. The noise in the picture is meant to be the music's, not the texture's.

    the body        -> a star: a sphere in three flat tones, limb-darkened as stars
                       are. The kick punches it; bass and kick set how hot it runs
    the voice       -> the star's heart, white-hot and as wide as the voice is loud;
                       one thin ring standing off it, in the lyric's colour, riding
                       out and back with the melody; a strong syllable bulges it
    the satellites  -> planets: lit tone, half tone and a shadow that keeps its colour,
                       real phases, a bright sunward rim. A note flares one - it grows,
                       a band of its light stands off it, a ring is thrown
    hat ticks       -> rocks of the asteroid belts glinting in turn; stars swelling
    clap rings      -> a clean ring, which shoves the belts and the orbit lines aside
    crashes, drops  -> the big shooting stars; bar lines throw small ones; the star
                       bends every one of them as it passes
    pad brightness  -> how far the star blows a comet's two tails

Around them, what space has: moons, a ringed planet with its shadow across its rings,
an outer debris belt, a comet on a Kepler orbit, and a sky of stars as stars are -
many faint and few bright, white and blue-white and amber and red, crowded into a
lane and two clusters, with three figures of bright stars for the eye to join up -
no lines: the sky has none.

The baseline is calm and physical: the innermost planet takes half a minute to go
round and the rest follow Kepler's third law (`uOrbitSlow`); moons, spin and tumble
are slow. What is fast is what the music does. Every edge is one pixel of
anti-aliasing wide: crisp, never a staircase, never a blur.

One pass, no previous frame, the same source for GL 4.1 and WebGL2.
"""

from __future__ import annotations

from .direct import N_METEORS, N_RINGS, N_SATS, PALETTE_ROLES

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
    # the palette arrives linear; inks are flat colours on a page, so they are taken
    # to display space once, here, and everything after is mixing inks
    return "\n".join(f"    vec3 c{role} = pow(vec3(uC{role}R, uC{role}G, uC{role}B), vec3(1.0 / 2.2));"
                     for role in PALETTE_ROLES)


FRAGMENT_BODY = f"""
precision highp float;
layout(location = 0) out vec4 fragColor;

uniform vec2 uResolution;
uniform float uTime;

uniform float uMass, uKickT, uKickA, uBass;
uniform float uSpread, uOrbitSlow, uHold, uTilt, uIncl;
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
{_scalars("uMetT", N_METEORS)}
{_scalars("uMetA", N_METEORS)}
{_scalars("uMetS", N_METEORS)}

const float PI = 3.14159265359;
const float TAU = 6.28318530718;
const int N_RINGS = {N_RINGS};
const int N_SATS = {N_SATS};
const int N_METEORS = {N_METEORS};

// ------------------------------------------------------------- hashes and noise

float hash11(float p) {{
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}}

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

// Value noise: it bands more cleanly under posterisation than gradient noise does.
float valueNoise(vec3 p) {{
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float n000 = hash13(i);
    float n100 = hash13(i + vec3(1.0, 0.0, 0.0));
    float n010 = hash13(i + vec3(0.0, 1.0, 0.0));
    float n110 = hash13(i + vec3(1.0, 1.0, 0.0));
    float n001 = hash13(i + vec3(0.0, 0.0, 1.0));
    float n101 = hash13(i + vec3(1.0, 0.0, 1.0));
    float n011 = hash13(i + vec3(0.0, 1.0, 1.0));
    float n111 = hash13(i + vec3(1.0, 1.0, 1.0));
    return mix(mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y),
               mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y), f.z);
}}

float fbm(vec3 p, int octaves, float lacunarity, float gain) {{
    float sum = 0.0, amp = 0.5, norm = 0.0;
    for (int i = 0; i < 6; i++) {{
        if (i >= octaves) break;
        sum += amp * valueNoise(p);
        norm += amp;
        p *= lacunarity;
        amp *= gain;
    }}
    return sum / max(norm, 1e-4);
}}

// -------------------------------------------------------------------- the inks

float posterize(float x, float steps) {{
    return min(floor(clamp(x, 0.0, 1.0) * steps), steps - 1.0) / max(steps - 1.0, 1.0);
}}

// keeps a hair of gradient inside each band, so a boundary that is moving moves
// rather than hops
float posterizeSoft(float x, float steps, float softness) {{
    float scaled = clamp(x, 0.0, 1.0) * steps;
    float band = floor(scaled);
    float smoothed = smoothstep(0.5 - softness, 0.5 + softness, scaled - band);
    return min((band + smoothed) / max(steps - 1.0, 1.0), 1.0);
}}

// Light and shadow are two inks. N.L is clamped at zero before it is banded, so
// the whole night side stays in the shadow ink and the terminator is where it is.
vec3 inkShade(vec3 shadowInk, vec3 lightInk, float ndl, float steps, float softness) {{
    float lit = posterizeSoft(clamp(ndl, 0.0, 1.0), steps, softness);
    lit = lit <= 0.001 ? 0.0 : mix(0.62, 1.0, lit);
    return mix(shadowInk, lightInk, lit);
}}

mat2 rot2(float a) {{
    float c = cos(a), s = sin(a);
    return mat2(c, -s, s, c);
}}

// An event that happened `age` seconds ago, decaying over `tau`. Nothing before it.
float hit(float age, float tau) {{
    return age < 0.0 ? 0.0 : exp(-age / tau);
}}

// push a colour away from its own grey: inks are meant to be inks
vec3 vivid(vec3 c, float k) {{
    float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
    return clamp(mix(vec3(l), c, k), 0.0, 1.0);
}}

// ink laid over what is there: opaque where `a` is 1
vec3 lay(vec3 under, vec3 ink, float a) {{
    return mix(under, ink, clamp(a, 0.0, 1.0));
}}

// ---------------------------------------------------------------------- the sky

// star colour, as stars are: most white, some blue-white, some amber, a few red
vec3 starTint(float h) {{
    vec3 c = vec3(1.0, 0.97, 0.92);
    c = mix(c, vec3(0.72, 0.84, 1.0), step(0.62, h));
    c = mix(c, vec3(1.0, 0.80, 0.52), step(0.84, h));
    c = mix(c, vec3(1.0, 0.58, 0.46), step(0.955, h));
    return c;
}}

// How crowded the sky is at a point: one broad lane across it, and two clusters.
// Analytic and smooth - the sky's texture is its stars, not a pattern under them.
float crowding(vec2 sky) {{
    vec2 sp = rot2(0.5) * sky;
    float lane = 1.0 - smoothstep(0.05, 0.30, abs(sp.y + 0.10 * sin(sp.x * 1.7)));
    vec2 k1 = sky - vec2(-0.55, 0.26), k2 = sky - vec2(0.62, -0.24);
    return 0.50 * lane + exp(-dot(k1, k1) / 0.010) + 0.8 * exp(-dot(k2, k2) / 0.006);
}}

// One layer of stars: hard-edged discs on a jittered grid. Magnitudes fall off the way
// they do in the sky - many faint, few bright. A third answer each hat in turn: they
// grow, they do not blur.
//
// Whether a star exists is decided once, from how crowded the sky is *where the star
// is* - not where the pixel is. Decided per pixel, a star that straddles the edge of a
// cluster exists on one side of it and not the other, and is drawn cut in half.
vec4 starLayer(vec2 p, vec2 shift, vec2 skyPan, float sc, vec2 offset, float cell,
               float baseDensity, float crowdGain, float size, float sparkle,
               float tick, float which, float shimmer, float aa) {{
    vec2 g = ((p + shift) / sc + offset) / cell;
    vec2 id = floor(g);
    // ...and it is drawn by the cell it is in, so all of it - arms, and the swell a hat
    // gives it - has to fit inside that cell
    float margin = sparkle > 0.0 ? 0.36 : 0.26;
    vec2 at = margin + hash22(id + 1.7) * (1.0 - 2.0 * margin);
    vec2 centre = ((id + at) * cell - offset) * sc - shift;          // where it is on screen
    if (hash12(id) > baseDensity + crowdGain * crowding(centre + skyPan)) return vec4(0.0);
    // A four-pointed star's arms are a pixel wide. Left where it falls, an arm that
    // lands across two rows prints as two dim rows and its twin as one bright column;
    // so the star is seated on the pixel grid, and every arm is a whole pixel.
    if (sparkle > 0.0) {{
        vec2 px = centre * uResolution.y + 0.5 * uResolution;
        centre = (floor(px) + 0.5 - 0.5 * uResolution) / uResolution.y;
    }}
    vec2 delta = (p - centre) / sc;
    size /= sc; aa /= sc;
    float m = hash12(id + 5.3);
    float magnitude = m * m * m;                              // few bright ones
    float mine = 1.0 - min(abs(floor(hash12(id + 9.1) * 3.0) - which), 1.0);
    float lift = tick * mine * step(0.35, m) + shimmer * (0.4 + 0.6 * hash12(id + 1.9));
    float radius = size * (0.55 + 0.75 * magnitude) * (1.0 + 0.70 * lift);
    float star = smoothstep(radius + aa, radius - aa, length(delta));
    if (sparkle > 0.0 && magnitude > 0.35) {{
        float thin = max(radius * 0.22, 0.75 * aa);
        float reach = min(radius * sparkle * (0.8 + 0.6 * magnitude) * (1.0 + 1.0 * lift), 0.33 * cell);
        float armX = smoothstep(thin + aa, thin - aa, abs(delta.y)) * smoothstep(reach + aa, reach - aa, abs(delta.x));
        float armY = smoothstep(thin + aa, thin - aa, abs(delta.x)) * smoothstep(reach + aa, reach - aa, abs(delta.y));
        star = max(star, max(armX, armY));
    }}
    float level = clamp(0.30 + 0.70 * magnitude + 0.60 * lift, 0.0, 1.0);
    return vec4(starTint(hash12(id + 3.9)), star * level);
}}

// A constellation is a figure the eye finds in a few bright stars. Nothing joins them
// up: the sky has no lines in it. Returns the stars' colour and coverage.
vec4 constellation(vec2 p, vec2 origin, float scale, float lean, vec2 pts[6], float aa) {{
    vec2 q = rot2(-lean) * (p - origin) / scale;
    if (abs(q.x) > 1.6 || abs(q.y) > 1.6) return vec4(0.0);
    vec4 found = vec4(0.0);
    for (int i = 0; i < 6; i++) {{
        float h = hash11(float(i) * 3.1 + origin.x * 9.0);
        float rad = 0.022 + 0.020 * h;
        float star = smoothstep(rad + aa / scale, rad - aa / scale, length(q - pts[i]));
        found = star > found.a ? vec4(starTint(hash11(h * 7.7 + 0.2)), star) : found;
    }}
    return found;
}}

// A belt of rock: lanes turning at their own Keplerian rates, each rock tumbling,
// two tones, lit from the star. A third of them answer each hat. Returns coverage.
float belt(vec2 pw, float inner, float lanes, float laneW, float count0, float sizeLo, float sizeHi,
           float seed, float tug, float tick, vec3 shadeTone, vec3 litTone, vec3 hotTone, float aa,
           out vec3 rockInk, out float front) {{
    rockInk = vec3(0.0);
    front = 0.0;
    vec2 q = rot2(-uIncl) * pw;
    vec2 pl = vec2(q.x, q.y / uTilt);
    float pr = length(pl) / tug;
    float li = floor((pr - inner) / laneW);
    if (li < 0.0 || li >= lanes) return 0.0;
    float lr = inner + (li + 0.5) * laneW;
    float count = floor(count0 + 9.0 * li);
    float turn = uOrbitSlow * pow(0.250 / lr, 1.5);
    float ci = floor(fract(atan(pl.y, pl.x) / TAU - turn) * count);
    vec2 id = vec2(ci, li + seed);
    if (hash12(id) < 0.34) return 0.0;
    vec2 jit = hash22(id + 2.3) - 0.5;
    float ang = TAU * ((ci + 0.5 + 0.5 * jit.x) / count + turn);
    float rr = (lr + 0.30 * laneW * jit.y) * tug;            // well inside its lane: see `size`
    vec2 centre = rot2(uIncl) * vec2(rr * cos(ang), rr * uTilt * sin(ang));
    vec2 dd = pw - centre;
    float mine = 1.0 - min(abs(floor(hash12(id + 9.1) * 3.0) - uHatK), 1.0);
    float glint = tick * mine;
    // a rock, glinting and lumpy, must still fit in the lane that draws it - the lane
    // is foreshortened by the tilt - or it is cropped at the lane's edge
    float size = min(mix(sizeLo, sizeHi, hash12(id + 4.4)) * (1.0 + 0.90 * glint), 0.30 * laneW * uTilt * tug);
    float spin = uBeats * (0.04 + 0.10 * hash12(id + 6.1)) * (hash12(id + 8.8) < 0.5 ? -1.0 : 1.0);
    float lump = 0.78 + 0.22 * cos(3.0 * atan(dd.y, dd.x) + spin + TAU * hash12(id + 7.7));
    float rock = smoothstep(size * lump + aa, size * lump - aa, length(dd));
    // one hard terminator across the rock, facing the star
    float ndl = dot(normalize(dd + 1e-5), normalize(-centre));
    float lit = smoothstep(-0.10 - 0.06, -0.10 + 0.06, ndl);
    vec3 tone = litTone * (0.80 + 0.20 * hash12(id + 3.3));
    rockInk = mix(mix(shadeTone, hotTone, 0.35 * glint), mix(tone, hotTone, glint), lit);
    front = sin(ang) > 0.0 ? 0.0 : 1.0;
    return rock;
}}

void main() {{
    vec2 pixel = gl_FragCoord.xy;
    vec2 p = (pixel - 0.5 * uResolution) / uResolution.y;
    // One pixel of anti-aliasing on every edge: crisp, and not a staircase.
    float aa = 1.0 / uResolution.y;

    // The shock of a re-entry pushes the frame in and lets go; a kick nudges it.
    float dropAge = uTime - uDropT;
    float shock = uDropA * hit(dropAge, 0.30);
    float kick = uKickA * hit(uTime - uKickT, 0.105);
    p *= 1.0 - 0.085 * shock - 0.010 * kick;
    float r = length(p);

    // Loudness is how much light there is: in a quiet passage the colours sit a
    // little deeper. A hit arrives at its own strength regardless.
    float amb = 0.42 + 1.00 * uExposure;
    float ev = 0.80 + 0.30 * uExposure;
    float lum = clamp(0.62 + 0.38 * amb, 0.0, 1.0);

{_palette_locals()}
    vec3 white = vec3(1.0, 0.985, 0.95);
    vec3 cTint = pow(vec3(uTintR, uTintG, uTintB), vec3(1.0 / 2.2));
    // flat, clean colour: the section's palette, pushed away from grey
    vec3 kField = vivid(cField, 1.5), kFar = vivid(cFar, 1.4);
    vec3 kBody = vivid(cBody, 1.9), kA = vivid(cAccent, 1.6), kB = vivid(cAccent2, 1.6);
    vec3 space = vec3(0.020, 0.026, 0.060) + kFar * 0.045;      // deep, and a breath of the section's hue
    vec3 shade = mix(space, kField, 0.30);                      // the colour of shadow: never grey, never black

    // ---- the star's size: mass, and the kick ---------------------------------------
    float R = 0.078 * (0.50 + 0.80 * uMass) * (1.0 + 0.26 * kick);

    // ---- waves passing through: the shock, and each clap's ring -----------------------
    // Where a ring is, whatever lies in the plane is shoved outward with it and falls
    // back: the belts and the orbit lines are looked up at a displaced point.
    float ringT[N_RINGS] = {_gather("uRingT", N_RINGS)};
    float ringA[N_RINGS] = {_gather("uRingA", N_RINGS)};
    float ringM[N_RINGS] = {_gather("uRingM", N_RINGS)};
    float shove = 0.0;
    for (int i = 0; i < N_RINGS; i++) {{
        float age = uTime - ringT[i];
        if (age < 0.0 || age > 2.0 || ringA[i] <= 0.0) continue;
        float g = (r - (R + 0.030 + 0.62 * pow(age, 0.72))) / 0.030;
        shove += 0.0085 * (0.4 + 0.6 * ringA[i]) * exp(-g * g) * exp(-age / 0.5);
    }}
    if (dropAge >= 0.0 && dropAge < 3.0) {{
        float g = (r - (R + 1.35 * pow(dropAge, 0.62))) / 0.060;
        shove += 0.030 * uDropA * exp(-g * g) * exp(-dropAge / 0.7);
    }}
    vec2 pw = p * (1.0 - shove / max(r, 0.02));

    // ---- the sky ------------------------------------------------------------------------
    // The camera drifts a hair, on the bars; each layer of sky moves by how far away
    // it is, which is all that depth is.
    vec2 pan = 0.030 * vec2(sin(0.021 * uBeats), cos(0.017 * uBeats + 1.0));
    vec3 col = space * (1.0 - 0.45 * smoothstep(0.35, 1.05, r));
    float tick = uHatA * hit(uTime - uHatT, 0.060);
    float shimmer = uCrashA * hit(uTime - uCrashT, 1.6);

    // Faint and middling stars drift - a riser draws them outward, two copies an octave
    // apart cross-faded, so it can go on for ever - and the bright ones, the clusters
    // and the figures stay where the sky keeps them.
    vec2 skyPan = 0.30 * pan;
    float z0 = fract(uDrift), z1 = fract(uDrift + 0.5);
    for (int k = 0; k < 2; k++) {{
        float zz = k == 0 ? z0 : z1;
        float w = smoothstep(0.0, 0.35, sin(PI * zz));
        vec4 far = starLayer(p, 0.25 * pan, skyPan, exp2(zz), vec2(float(k) * 7.7), 0.034, 0.22, 0.55, 0.00135, 0.0, tick, uHatK, shimmer, aa);
        vec4 mid = starLayer(p, 0.50 * pan, skyPan, exp2(zz), vec2(3.1 + float(k) * 5.3), 0.070, 0.20, 0.50, 0.00190, 0.0, tick, uHatK, shimmer, aa);
        col = mix(col, far.rgb, far.a * w * 0.60 * (0.35 + 0.65 * uStars));
        col = mix(col, mid.rgb, mid.a * w * 0.85 * (0.35 + 0.65 * uStars));
    }}
    vec4 knot = starLayer(p, skyPan, skyPan, 1.0, vec2(2.3), 0.022, -0.35, 1.30, 0.00170, 0.0, tick, uHatK, shimmer, aa);
    vec4 bright = starLayer(p, skyPan, skyPan, 1.0, vec2(5.9), 0.150, 0.34, 0.45, 0.00290, 3.4, tick, uHatK, shimmer, aa);
    col = mix(col, knot.rgb, knot.a * 0.9);
    col = mix(col, bright.rgb, bright.a);
    {{
        vec2 cp = p + 0.30 * pan;
        vec2 c1[6] = vec2[6](vec2(-1.0, 0.2), vec2(-0.45, 0.55), vec2(0.05, 0.25), vec2(0.45, 0.60), vec2(1.0, 0.30), vec2(0.75, -0.45));
        vec2 c2[6] = vec2[6](vec2(-0.9, -0.5), vec2(-0.35, -0.1), vec2(0.0, 0.45), vec2(0.35, -0.1), vec2(0.9, -0.5), vec2(0.0, -0.75));
        vec2 c3[6] = vec2[6](vec2(-1.0, -0.3), vec2(-0.5, 0.1), vec2(0.0, -0.15), vec2(0.4, 0.35), vec2(0.7, 0.9), vec2(1.05, 0.55));
        vec4 a1 = constellation(cp, vec2(0.52, 0.30), 0.105, 0.30, c1, aa);
        vec4 a2 = constellation(cp, vec2(-0.66, -0.26), 0.090, -0.45, c2, aa);
        vec4 a3 = constellation(cp, vec2(-0.20, 0.40), 0.080, 1.10, c3, aa);
        col = mix(col, a1.rgb, a1.a);
        col = mix(col, a2.rgb, a2.a);
        col = mix(col, a3.rgb, a3.a);
    }}

    // ---- shooting stars: crashes and re-entries throw the big ones, the bar line the
    // small ones; the star bends each as it passes ----------------------------------------
    float metT[N_METEORS] = {_gather("uMetT", N_METEORS)};
    float metA[N_METEORS] = {_gather("uMetA", N_METEORS)};
    float metS[N_METEORS] = {_gather("uMetS", N_METEORS)};
    for (int i = 0; i < N_METEORS; i++) {{
        float age = uTime - metT[i];
        if (age < 0.0 || age > 1.6 || metA[i] <= 0.0) continue;
        float s = metS[i];
        float alpha = TAU * hash11(s * 7.13 + 0.3);
        vec2 start = vec2(0.80 * cos(alpha), 0.44 * sin(alpha));
        float side = hash11(s * 3.71 + 1.9) < 0.5 ? -1.0 : 1.0;
        vec2 dir = rot2(side * (0.42 + 0.30 * hash11(s * 5.3))) * normalize(-start);
        float speed = 1.05 + 0.5 * hash11(s * 9.7);
        vec2 across = vec2(-dir.y, dir.x) * -side;
        vec2 head = start + dir * speed * age + across * 0.34 * age * age;
        vec2 along = normalize(dir * speed + across * 0.68 * age);
        vec2 d = p - head;
        float back = -dot(d, along);
        float off = abs(dot(d, vec2(-along.y, along.x)));
        float len = (0.07 + 0.19 * metA[i]) * min(age / 0.10, 1.0);
        float u = clamp(back / len, 0.0, 1.0);
        float live = 1.0 - smoothstep(1.0, 1.25, age);
        // a clean tapering wedge, in two tones: white near the head, the accent behind
        float width = 0.0040 * (0.5 + 0.5 * metA[i]) * (1.0 - u);
        float tail = step(0.0, back) * step(back, len) * smoothstep(width + aa, width - aa, off);
        col = mix(col, mix(white, kA, smoothstep(0.30, 0.34, u)), tail * live);
        float hr = 0.0058 * (0.5 + 0.5 * metA[i]) * (1.0 + 0.8 * hit(age, 0.08));
        col = mix(col, white, smoothstep(hr + aa, hr - aa, length(d)) * live);
    }}

    // ---- the corona: two clean bands, their edge a slow, large undulation -----------
    // The voice is a thin band standing off it - the lyric's colour, reaching with the
    // melody, swelling on a held note; a strong syllable throws a prominence.
    float syll = uSyllA * hit(uTime - uSyllT, 0.14);
    float out_ = r - R;
    if (out_ > 0.0 && out_ < 0.46) {{
        vec2 dirv = p / max(r, 1e-4);
        float flow = fbm(vec3(dirv * 1.3, 0.030 * uBeats), 2, 2.0, 0.5);
        float pa = TAU * hash11(uSyllT * 13.7);
        float arc = smoothstep(0.80, 1.0, dot(dirv, vec2(cos(pa), sin(pa))));
        float prominence = 0.10 * arc * arc * max(uSyllA - 0.55, 0.0) * hit(uTime - uSyllT, 0.30);
        float reachV = 0.050 + 0.085 * (0.5 + 0.5 * uPitch) + 0.020 * uSustain + prominence;
        // one thin ring, a true circle but for the prominence, riding out and back
        // with the melody; a held note thickens it a little, a syllable brightens it
        float wV = 0.0016 + 0.0012 * uSustain + 0.0010 * syll;
        float ringV = smoothstep(wV + aa, wV - aa, abs(out_ - reachV));
        vec3 cAura = vivid(mix(mix(kA, white, 0.30), cTint, uTint), 1.3);
        col = mix(col, cAura, ringV * clamp(1.4 * uVoice + 0.9 * syll, 0.0, 1.0) * ev);
        // a corona is a rim of light, not a second, bigger sun: it stays close
        float reach = (0.012 + 0.022 * uBass + 0.016 * uRays * uHold + 0.034 * kick + 0.07 * shock) * (0.80 + 0.40 * flow);
        // one band: a sun drawn as a stack of rings is a target, not a sun
        col = mix(col, mix(space, kBody, 0.50), smoothstep(reach + aa, reach - aa, out_) * 0.85 * (0.70 * lum + 0.30 * ev));
    }}

    // ---- what is in the plane: belts, a comet, orbits, planets, moons ------------------
    float noteT[N_SATS] = {_gather("uNoteT", N_SATS)};
    float noteA[N_SATS] = {_gather("uNoteA", N_SATS)};
    float noteM[N_SATS] = {_gather("uNoteM", N_SATS)};
    // The innermost orbit clears the star even at the top of a kick, however far the
    // plane is tipped: a planet behind the star, or across its face, is a note unseen.
    float a0 = max(0.255, 0.156 / uTilt);
    float tug = uSpread * (1.0 - 0.045 * kick);
    float depth = sqrt(max(1.0 - uTilt * uTilt, 0.0));
    float trail = 0.35 + 1.30 * uHold;

    vec3 overInk = vec3(0.0);
    float overA = 0.0;

    {{
        vec3 rk; float fr;
        vec3 rockLit = mix(vec3(0.62, 0.60, 0.66), kField, 0.35) * lum;
        float b = belt(pw, a0 + 0.158, 3.0, 0.0175, 40.0, 0.0022, 0.0050, 11.0, tug, tick,
                       mix(space, rockLit, 0.30), rockLit, white, aa, rk, fr);
        if (fr < 0.5) col = mix(col, rk, b); else {{ overInk = mix(overInk, rk, b); overA = max(overA, b); }}
        b = belt(pw, a0 + 0.405, 2.0, 0.030, 44.0, 0.0016, 0.0032, 37.0, tug, tick,
                 mix(space, rockLit, 0.25), rockLit * 0.85, white, aa, rk, fr);
        if (fr < 0.5) col = mix(col, rk, b); else {{ overInk = mix(overInk, rk, b); overA = max(overA, b); }}
    }}

    {{
        // A comet on a long ellipse: Kepler's equation, five Newton steps. Its tails
        // point away from the star, always, and grow as it falls inward; how far the
        // star blows them is how bright the pad is.
        float ce = 0.70, ca = (a0 + 0.30) * tug;
        float M = TAU * (uOrbitSlow * 0.30 + 0.37);
        float E = M;
        for (int k = 0; k < 5; k++) E -= (E - ce * sin(E) - M) / (1.0 - ce * cos(E));
        vec2 orb = rot2(0.95) * vec2(ca * (cos(E) - ce), ca * sqrt(1.0 - ce * ce) * sin(E));
        vec2 cs = rot2(uIncl) * vec2(orb.x, orb.y * uTilt);
        float near = clamp(ca * (1.0 - ce) / max(length(orb), 1e-3), 0.0, 1.0);
        vec2 away = normalize(cs);
        vec2 d = p - cs;
        float back = dot(d, away);
        float len = (0.035 + 0.22 * near * near) * (0.55 + 0.75 * uField);
        float u = clamp(back / len, 0.0, 1.0);
        float wDust = 0.0080 * (1.0 - 0.85 * u) * (0.6 + 0.6 * near);
        float dustTail = step(0.0, back) * step(back, len) * smoothstep(wDust + aa, wDust - aa, abs(dot(d, vec2(-away.y, away.x))));
        vec3 cInk = mix(kB, white, 0.25 * (1.0 - u)); float cA = dustTail * (0.80 - 0.45 * u) * lum;
        vec2 ionDir = rot2(0.16) * away;
        float ib = dot(d, ionDir);
        float ion = step(0.0, ib) * step(ib, len * 1.35) * smoothstep(0.0012 + aa, 0.0012 - aa, abs(dot(d, vec2(-ionDir.y, ionDir.x))));
        cInk = mix(cInk, mix(kA, white, 0.5), step(cA, ion * 0.8)); cA = max(cA, ion * 0.8 * lum);
        float coma = smoothstep(0.0080 + aa, 0.0080 - aa, length(d));
        cInk = mix(cInk, mix(kB, white, 0.55), coma); cA = max(cA, coma);
        float nucleus = smoothstep(0.0040 + aa, 0.0040 - aa, length(d));
        cInk = mix(cInk, white, nucleus); cA = max(cA, nucleus);
        if (orb.y > 0.0) col = mix(col, cInk, cA); else {{ overInk = mix(overInk, cInk, cA); overA = max(overA, cA); }}
    }}

    for (int i = 0; i < N_SATS; i++) {{
        float fi = float(i);
        float a_rest = a0 + 0.038 * fi + (i >= 4 ? 0.070 : 0.0);      // the outer four stand off beyond the belt
        float a = a_rest * tug;
        float e = uTilt;
        float inc = uIncl + 0.035 * sin(fi * 2.399 + 0.6);
        vec2 q = rot2(-inc) * pw;
        // Kepler's third law: the period goes as the orbit's size to the three-halves
        float th = TAU * (uOrbitSlow * pow(0.250 / (a_rest - a0 + 0.250), 1.5) + fi * 0.618);
        vec2 s = vec2(a * cos(th), a * e * sin(th));
        float z = -sin(th);

        // the trace: a hairline, brighter just behind the planet
        float k = length(vec2(q.x / a, q.y / (a * e)));
        float dl = abs(k - 1.0) * a * mix(e, 1.0, abs(q.x) / max(length(q), 1e-4));
        float behindIt = mod(th - atan(q.y / (a * e), q.x / a), TAU);
        float lineA = smoothstep(0.0009 + aa, 0.0009 - aa, dl) * (0.16 + 0.55 * exp(-behindIt / trail)) * (0.55 + 0.45 * lum);

        float nAge = uTime - noteT[i];
        float lit = noteA[i] * (0.72 * hit(nAge, 0.055) + 0.28 * hit(nAge, 0.26));
        float base = i == 0 ? 0.0080 : i == 1 ? 0.0102 : i == 2 ? 0.0128 : i == 3 ? 0.0106
                   : i == 4 ? 0.0225 : i == 5 ? 0.0190 : i == 6 ? 0.0150 : 0.0130;
        float size = base * (1.0 + 0.22 * z) * (1.0 + 0.42 * lit);
        vec2 dq = (rot2(-inc) * p) - s;
        float ds = length(dq);
        vec3 pInk = vec3(0.0);
        float pA = 0.0;
        if (ds < size * 4.4) {{
            vec3 note = vivid(mix(cAccent, cAccent2, noteM[i]), 1.6);
            vec3 L = normalize(-vec3(s.x, s.y, z * a * depth));   // to the star
            // A note is the planet flaring: it grows, one clean band of its own light
            // stands off it for as long as the pop lasts, and a hard ring is thrown.
            float pop = clamp(noteA[i], 0.0, 1.0) * hit(nAge, 0.075);
            float haloR = size * (1.35 + 1.1 * pop);
            float halo = smoothstep(haloR + aa, haloR - aa, ds) * step(0.03, pop);
            pInk = mix(note, white, 0.45);
            pA = halo * clamp(2.5 * pop, 0.0, 0.85) * ev;
            float pingR = size * (1.35 + 2.3 * (1.0 - exp(-nAge / 0.11)));
            float ping = smoothstep(0.0012 + aa, 0.0012 - aa, abs(ds - pingR))
                         * clamp(noteA[i], 0.0, 1.0) * hit(nAge, 0.16) * step(0.0, nAge);
            pInk = mix(pInk, mix(note, white, 0.5), step(pA, ping * ev)); pA = max(pA, ping * ev);

            if (i == 4) {{
                // rings in the plane of the orbits, two tones and a gap, and the planet's
                // own shadow lying across them on the side away from the star
                vec2 rd = vec2(dq.x, dq.y / max(e, 0.2));
                float rk = length(rd) / size;
                float w_ = aa / size * 2.0;
                float annulus = smoothstep(1.45 - w_, 1.45 + w_, rk) * smoothstep(2.35 + w_, 2.35 - w_, rk)
                                * (1.0 - smoothstep(1.90 - w_, 1.90 + w_, rk) * smoothstep(2.00 + w_, 2.00 - w_, rk));
                float hidden = step(0.0, dq.y) * step(ds, size);
                vec2 awayP = normalize(vec2(s.x, s.y / max(e, 0.2)));
                float castShadow = step(0.0, dot(rd, awayP)) * smoothstep(size + aa, size - aa, abs(dot(rd, vec2(-awayP.y, awayP.x))));
                vec3 ringInk = mix(mix(note, white, 0.35), mix(note, white, 0.10), step(2.0, rk)) * lum;
                ringInk = mix(ringInk, mix(shade, note, 0.18), castShadow);
                float ra = annulus * (1.0 - hidden);
                pInk = mix(pInk, ringInk, step(pA, ra)); pA = max(pA, ra);
            }}
            if (i == 4 || i == 5) {{
                for (int m = 0; m < 2; m++) {{
                    if (i == 5 && m == 1) break;
                    float fm = float(m);
                    float mr = size * (i == 4 ? 3.0 + 0.9 * fm : 2.5);
                    float mth = TAU * (uOrbitSlow * (5.5 - 2.0 * fm) + 0.3 * fi + 0.55 * fm);
                    vec2 mp = vec2(mr * cos(mth), mr * e * sin(mth));
                    float msz = size * (0.20 - 0.05 * fm);
                    vec2 md = dq - mp;
                    float moon = smoothstep(msz + aa, msz - aa, length(md));
                    moon *= 1.0 - step(0.0, sin(mth)) * step(ds, size);
                    float mlit = smoothstep(-0.04, 0.04, dot(normalize(vec3(md, msz * 0.6)), L));
                    vec3 mInk = mix(mix(shade, vec3(0.7), 0.15), vec3(0.86, 0.85, 0.88) * lum, mlit);
                    pInk = mix(pInk, mInk, moon); pA = max(pA, moon);
                }}
            }}
            if (ds < size + aa) {{
                vec3 n = vec3(dq / size, sqrt(max(1.0 - (ds * ds) / (size * size), 0.0)));
                float ndl = dot(n, L);
                float spin = uOrbitSlow * (2.2 + 0.6 * fi);
                vec3 o = vec3(rot2(spin) * n.xz, n.y).xzy;
                // flat, with a little variation: a gas giant wears a few clean bands, a
                // rocky world a few large shapes. Two tones of one colour, no texture.
                float mark = i == 4 || i == 5 || i == 7
                    ? smoothstep(-0.06, 0.06, sin(o.y * (5.0 + fi) + 0.8 * sin(o.x * 2.0 + fi)))
                    : smoothstep(0.50, 0.54, fbm(o * 1.6 + fi * 3.7, 2, 2.0, 0.5));
                vec3 day = mix(note, mix(note, white, 0.38), mark) * lum;
                day = mix(day, mix(note, white, 0.78), clamp(1.2 * lit, 0.0, 1.0));
                // cel shading: a lit tone, a half tone, and a shadow that keeps its colour
                vec3 night = mix(mix(shade, note * 0.30, 0.55), note, 0.70 * lit);
                vec3 half_ = mix(night, day, 0.55);
                vec3 globe = mix(night, half_, smoothstep(-0.02, 0.02, ndl));
                globe = mix(globe, day, smoothstep(0.30, 0.34, ndl));
                // a thin bright rim on the sunward limb
                globe = mix(globe, mix(day, white, 0.45), smoothstep(0.80, 0.84, 1.0 - n.z) * smoothstep(0.25, 0.45, ndl));
                float disc = smoothstep(size + aa, size - aa, ds);
                pInk = mix(pInk, globe, disc); pA = max(pA, disc);
            }}
        }}

        vec3 lineCol = mix(white, vivid(mix(cAccent, cAccent2, noteM[i]), 1.6), 0.45);
        if (q.y > 0.0) col = mix(col, lineCol, lineA);
        else {{ overInk = mix(overInk, lineCol, lineA); overA = max(overA, lineA); }}
        if (s.y > 0.0) col = mix(col, pInk, pA);
        else {{ overInk = mix(overInk, pInk, pA); overA = max(overA, pA); }}
    }}

    // ---- the star: a sphere in three flat tones ---------------------------------------
    if (r < R + aa) {{
        float mu = sqrt(max(1.0 - (r * r) / (R * R), 0.0));       // 1 at the centre, 0 at the limb
        vec3 n = vec3(p / R, mu);
        vec3 o = vec3(rot2(0.006 * uBeats) * n.xz, n.y).xzy;
        // how hot it runs: the bass under it, the kick through it
        float heat = clamp(0.35 + 0.45 * uBass * amb + 0.55 * kick * ev, 0.0, 1.0);
        vec3 surface = mix(kBody, mix(kBody, white, 0.45), heat);
        // limb darkening, as a real star has, in one clean step
        vec3 limb = mix(kBody * 0.72, kBody, heat * 0.6);
        vec3 c = mix(limb, surface, smoothstep(0.50, 0.54, mu));
        // a little variation: a few large, slow, slightly brighter cells, and a spot or two
        float cells = fbm(o * 1.7 + vec3(0.0, 0.0, 0.010 * uBeats), 2, 2.0, 0.5);
        c = mix(c, mix(c, white, 0.16), smoothstep(0.56, 0.60, cells) * smoothstep(0.30, 0.60, mu));
        c = mix(c, c * 0.90, smoothstep(0.30, 0.27, cells) * smoothstep(0.45, 0.70, mu));
        // The voice is the star's heart: white-hot, as wide as the voice is loud, with a
        // brighter centre where a syllable has just landed.
        float heart = R * (0.10 + 0.50 * uVoice + 0.22 * syll) * step(0.02, uVoice + syll);
        vec3 heartInk = mix(mix(white, cTint, 0.30 * uTint), vec3(1.0), 0.25);
        c = mix(c, mix(surface, heartInk, clamp(0.62 + 0.60 * syll, 0.0, 1.0)), smoothstep(heart + aa, heart - aa, r));
        col = mix(col, c * (0.80 + 0.20 * lum), smoothstep(R + aa, R - aa, r));
    }}

    col = mix(col, overInk, clamp(overA, 0.0, 1.0));

    // ---- the waves themselves: clean rings -----------------------------------------------
    for (int i = 0; i < N_RINGS; i++) {{
        float age = uTime - ringT[i];
        if (age < 0.0 || age > 2.0 || ringA[i] <= 0.0) continue;
        float rad = R + 0.030 + 0.62 * pow(age, 0.72);
        float w = 0.0014 + 0.0060 * exp(-age / 0.07);
        float amp = 0.40 + 0.60 * ringA[i];
        float a_ = smoothstep(w + aa, w - aa, abs(r - rad)) * clamp(amp * (0.95 * exp(-age / 0.10) + 0.75 * exp(-age / 0.42)), 0.0, 1.0);
        vec3 c = mix(vivid(mix(cAccent, cAccent2, ringM[i]), 1.6), white, 0.15 + 0.55 * exp(-age / 0.10));
        col = mix(col, c, a_ * ev);
    }}
    if (dropAge >= 0.0 && dropAge < 3.0) {{
        float rad = R + 1.35 * pow(dropAge, 0.62);
        for (int k = 0; k < 3; k++) {{
            float fk = float(k);
            float w = (0.0070 - 0.0022 * fk) * (1.0 + 2.0 * dropAge);
            float a_ = smoothstep(w + aa, w - aa, abs(r - rad * (1.0 - 0.085 * fk)))
                       * clamp(uDropA * exp(-dropAge / 0.55) * (1.0 - 0.3 * fk), 0.0, 1.0);
            col = mix(col, mix(kA, white, 0.55 - 0.15 * fk), a_);
        }}
        // the whole sky lifts for an instant: one flat wash, gone in a fifth of a second
        col = mix(col, mix(kBody, white, 0.5), 0.22 * uDropA * exp(-dropAge / 0.18));
    }}

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}}
"""


def vertex_source(header: str = GL_HEADER) -> str:
    return header + VERTEX_BODY.lstrip("\n")


def fragment_source(header: str = GL_HEADER) -> str:
    return header + FRAGMENT_BODY.lstrip("\n")
