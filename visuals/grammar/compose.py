"""Assembling a score into the one shader that draws the whole song.

There is exactly one program per song, and that is the design rather than an
optimisation. Only song-level choices - the palette family, the motif, how the
motion feels, the symmetry - become constants in the source. Everything a section
decides resolves to numbers, the numbers are ramped from section to section, and
so the picture is always somewhere on a continuous path. Nothing is ever swapped
for anything, which is why there is no cut to hide.

The source is dialect-neutral. `GL_HEADER` puts it on desktop GL 4.10 core for the
headless renderer; `WEBGL_HEADER` puts the same body on GLSL ES 3.00 for WebGL2.
Nothing below the header differs between the two.
"""

from __future__ import annotations

from .. import schema
from ..uniforms import uniform_names
from . import blocks

# macOS tops out at desktop GL 4.1, and a core-profile context there will not
# accept `#version 300 es` at all - it is a different language as far as the
# compiler is concerned. So the version line is the shim, and the body is written
# to the intersection of the two dialects. See DESIGN.md.
GL_HEADER = "#version 410 core\n"
WEBGL_HEADER = "#version 300 es\n"

# Compile-time loop bounds, which is what makes per-frame cost bounded.
LIMITS = {"ORBIT_MAX": 8}

# How the song's motion character shows up, once, in the coordinate. Song-level,
# so it is a constant and never has to be transitioned between - and measured in
# beats rather than seconds, like everything else that moves on its own.
MOTION: dict[str, str] = {
    "drift": "    p += 0.06 * vec2(sin(uBeats * 0.030), cos(uBeats * 0.026));",
    "pulse": "    p /= 1.0 + 0.055 * sin(uBarPhase * TAU);",
    "sweep": "    p = rot2(uBeats * (TAU / 256.0)) * p;",
    "churn": "    p += 0.06 * vec2(sin(uBeats * 0.075 + p.y * 1.7),\n"
             "                     cos(uBeats * 0.065 + p.x * 1.6));",
    "still": "",
}

VERTEX_BODY = """
precision highp float;
in vec2 aPos;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""


def _need(score: schema.Score, tier: str, name: str, group: int = 0) -> str:
    v = score.value(tier, name, group)
    if v is None:
        where = tier if tier == "song" else f"{tier} {group}"
        raise ValueError(
            f"cannot compile: {where}.{name} is masked. Fill the score first "
            f"(Score.filled(seed) does it legally)."
        )
    return str(v)


def program_key(score: schema.Score) -> str:
    """What a song's one program is keyed on: its song-level choices, and only those."""
    return "/".join([
        _need(score, "song", "palette_family"),
        _need(score, "song", "motif"),
        _need(score, "song", "motion_character"),
        _need(score, "song", "symmetry"),
    ])


def check_sections(score: schema.Score) -> None:
    """Every section's scene has to be one the song's block set admits.

    The compiler no longer discovers this - all four layers are compiled either
    way - so it is checked here, where the error can still name the section.
    """
    block_set = _need(score, "song", "block_set")
    legal = schema.BLOCK_SET_SCENES[block_set]
    for i in range(score.shape.n_sections):
        scene = _need(score, "section", "scene", i)
        if scene not in legal:
            raise ValueError(
                f"section {i}: scene {scene!r} is not in block set "
                f"{block_set!r} ({', '.join(legal)})"
            )


def vertex_source(header: str = GL_HEADER) -> str:
    return header + VERTEX_BODY.lstrip("\n")


def fragment_source(score: schema.Score, header: str = GL_HEADER) -> str:
    """The fragment shader for a whole song."""
    check_sections(score)
    family = _need(score, "song", "palette_family")
    motif = _need(score, "song", "motif")
    motion = _need(score, "song", "motion_character")
    symmetry = _need(score, "song", "symmetry")

    defines = "\n".join(f"#define {k} {v}" for k, v in LIMITS.items())
    decls = "\n".join(f"uniform float {n};" for n in uniform_names())

    return "".join([
        header,
        "precision highp float;\n\n",
        f"/* {program_key(score)} */\n",
        defines, "\n\n",
        "uniform vec2 uResolution;\n",
        "uniform sampler2D uPrev;\n",
        decls, "\n\n",
        "layout(location = 0) out vec4 fragColor;\n",
        blocks.COMMON,
        blocks.palette_block(family),
        blocks.motif_block(motif),
        blocks.symmetry_block(symmetry),
        blocks.warp_blocks(),
        blocks.layer_blocks(),
        blocks.POST,
        _main(motion),
    ])


def _main(motion: str) -> str:
    """The frame, in the fixed order every score is drawn in.

    The order is part of the grammar: shake and the camera move the frame,
    symmetry folds it, the warps bend it, the four layers draw into it at their
    weights, the tonemap bounds it, post works on the result, grain lands last.
    """
    return f"""
void main() {{
    vec2 uv = gl_FragCoord.xy / uResolution;
    vec2 p = (gl_FragCoord.xy * 2.0 - uResolution) / uResolution.y;

    /* A routed shake jitters per output frame, not per second, so it reads as a
       shake rather than as a wobble. */
    float tick = floor(uTime * 60.0);
    p += (vec2(hash21(vec2(tick, 1.0)), hash21(vec2(2.0, tick))) - 0.5)
         * uShake * 0.06;

{MOTION[motion]}
    p = rot2(uSpinPhase * 0.7) * p;
    p /= 1.0 + 0.60 * uScale;
    p = symmetry(p);

    /* The warps, by weight. Each is the identity at zero and each is blended
       toward rather than switched to, so a section half way between two of them
       bends space half way between them. uWarp is what a bar routes at the lot. */
    float bend = clamp(0.85 + 0.6 * uWarp, 0.0, 2.0);
    vec2 q = p;
    q += uWarpSwirl * bend * (warpSwirl(p) - p);
    q += uWarpRipple * bend * (warpRipple(p) - p);
    q += uWarpStretch * bend * (warpStretch(p) - p);

    /* The four layers, always all of them, at their weights. A scene is these
       four numbers; a transition is these four numbers moving. */
    vec3 c = vec3(0.0);
    c += uLayerWash * layerWash(q);
    c += uLayerOrbits * layerOrbits(q);
    c += uLayerBands * layerBands(q);
    c += uLayerHalo * layerHalo(q);

    /* Brightness scales the picture rather than being added to it. Adding lifts
       the empty parts of the frame as much as the drawn parts, and a routed
       brightness then reads as a flat colour wash over everything. */
    c *= 0.28 + 1.05 * uEnergy + 0.70 * uBright;

    /* Reinhard, then a mild gamma. Together they mean no routed value can drive
       the frame past white, which is one of the automatic filters milestone 3
       leans on. It happens before post because uPrev holds a finished frame. */
    c = max(c, 0.0);
    c = c / (1.0 + c);
    c = pow(c, vec3(1.0 / 1.8));

    c = post(c, uv);
    c += (hash21(gl_FragCoord.xy + tick) - 0.5) * uGrain * 0.09;

    fragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
}}
"""
