"""Headless GL to an mp4, and the same piece staged for the browser player.

Frame n is on screen from n / fps, and is drawn from the state at the *end* of its
span, (n + 1) / fps - the convention `visuals.render` already uses. So a hit at
time t first shows in the frame that is on screen when t arrives: the picture is
up to one frame early and never late, which is the side of the line the eye
forgives.
"""

from __future__ import annotations

import functools
import gzip
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import moderngl
import numpy as np

from . import ROOT, cosmos, direct, models, shader, shader_cosmos, shader_ink, sky
from .track import Track

# Which shader draws. Set once by the command line; everything that renders reads it.
STYLE = "glow"


def shader_module(style: str | None = None):
    return {"ink": shader_ink, "cosmos": shader_cosmos}.get(style or STYLE, shader)


def bake(got: dict, track: Track, sheet: dict | None = None) -> direct.Channels:
    """The channels the current style's shader reads, from the song as cast (cast.py) - and,
    given a direction sheet (sheet.py), with its decisions rather than the director's."""
    from . import cast
    from .make import modelled

    got, mod, cast_sheet = cast.apply(got, modelled(track, got, verbose=False), choose=sheet["cast"] if sheet else None)
    ch = (cosmos.bake(got, mod, sheet) if STYLE == "cosmos"
          else direct.direct(got, mod, reentries=sheet["reentries"] if sheet else None))
    ch.info = dict(ch.info or {}, cast=cast_sheet)
    ch.sheet = sheet
    return ch


CATALOGUE = ROOT / "visuals" / "cache" / "catalogues" / "bsc5.dat"


def data_textures() -> dict[str, np.ndarray]:
    """Lookup textures the current style's shader samples: (height, width, 4) float32."""
    if STYLE != "cosmos":
        return {}
    if not CATALOGUE.exists():
        raise SystemExit(f"no star catalogue at {CATALOGUE}; see the docstring of sky.py")
    galaxy = CATALOGUE.parent / "milkyway_2020_4k_gal_print.jpg"
    if not galaxy.exists():
        raise SystemExit(f"no Milky Way map at {galaxy}; see sky.milky_way")
    hyg, ngc = CATALOGUE.parent / "hyg_v41.csv", CATALOGUE.parent / "openngc.csv"
    if not hyg.exists() or not ngc.exists():
        raise SystemExit(f"no HYG / OpenNGC catalogues in {CATALOGUE.parent}; see sky.build_deep")
    return {"uStarTex": _deep_sky(hyg, ngc)["texture"], "uGalaxyTex": sky.milky_way(galaxy)[..., None]}


@functools.lru_cache(maxsize=1)
def _deep_sky(hyg: Path, ngc: Path) -> dict:
    return sky.build_deep(hyg, ngc, ngc.parent / "openngc_addendum.csv")


FULLSCREEN = np.array([-1.0, -1.0, 3.0, -1.0, -1.0, 3.0], dtype="f4")

# Which channels belong to which instrument. `solo` keeps one role live and holds
# every other channel still, which is how the separation matrix is measured.
ROLES: dict[str, tuple[str, ...]] = {
    "kick": ("uKickA",),
    "snare": tuple(f"uRingA{k}" for k in range(direct.N_RINGS)),
    "hat": ("uHatA", "uCrashA"),
    "note": tuple(f"uNoteA{k}" for k in range(direct.N_SATS)),
    "voice": ("uVoice", "uSyllA", "uPitch", "uSustain", "uTint"),
    "bass": ("uBass",),
    "drop": ("uDropA",) + tuple(f"uMetA{k}" for k in range(direct.N_METEORS)),
}
# The solar system gives mass to two of them: the kick's swell of the Sun and a note's
# swell of its planet are baked with look-ahead, as levels of their own.
ROLES["kick"] += ("uSunPulse", "uKickE") + tuple(f"uLean{k}" for k in range(8))
ROLES["note"] += tuple(f"{name}{k}" for k in range(8) for name in ("uGlow", "uBig", "uHop", "uSwing", "uSpin", "uPingA"))
ROLES["bass"] += tuple(f"uPromA{k}" for k in range(4)) + tuple(f"uFlareA{k}" for k in range(2)) + ("uCharge",)
ROLES["voice"] += tuple(f"uWindA{k}" for k in range(4)) + ("uSyllE",)
ROLES["hat"] += ("uHatE0", "uHatE1", "uHatE2", "uCrashE")
ROLES["drop"] += ("uBrace", "uOpened", "uFlashE")

# clocks: frozen in a solo, so that only the soloed instrument moves anything
CLOCKS = ("uOrbit", "uOrbitSlow", "uDrift", "uBeats") + tuple(f"uPh{i}" for i in range(8))
SILENT_IN_SOLO = ("uVoice", "uSustain", "uTint", "uPump")


# What a section decides. With only these live - every hit silenced, every follower
# of the audio held still, the clocks running - any step in the picture is a step
# in a decision, and there should not be one.
SECTION_LEVEL = tuple(f"uC{role}{c}" for role in direct.PALETTE_ROLES for c in "RGB") + (
    "uRays", "uBands", "uStars", "uTilt", "uIncl") + cosmos.CAMERA_UNIFORMS


def sections_only(ch: direct.Channels) -> direct.Channels:
    data = ch.data.copy()
    sizes = {name for names in ROLES.values() for name in names}
    for c, (name, kind) in enumerate(zip(ch.names, ch.kinds)):
        if name in SECTION_LEVEL or name in CLOCKS:
            continue
        if kind == direct.HOLD:
            if name in sizes:
                data[:, c] = 0.0
        elif name in SILENT_IN_SOLO:
            data[:, c] = 0.0
        else:
            data[:, c] = np.median(ch.data[:, c])
    return direct.Channels(ch.names, ch.kinds, data, ch.drops, ch.duration, ch.sections, ch.info)


def solo_channels(ch: direct.Channels, role: str) -> direct.Channels:
    if role == "sections":
        return sections_only(ch)
    if role not in ROLES:
        raise SystemExit(f"--solo takes one of {sorted(ROLES)}")
    data = ch.data.copy()
    live = set(ROLES[role])
    sizes = {name for names in ROLES.values() for name in names}
    for c, (name, kind) in enumerate(zip(ch.names, ch.kinds)):
        if name in live:
            continue
        if name in CLOCKS:
            data[:, c] = ch.data[len(ch.data) // 2, c]
        elif kind == direct.HOLD:
            if name in sizes:
                data[:, c] = 0.0                  # an event's size: no size, no event
        elif name in SILENT_IN_SOLO:
            data[:, c] = 0.0
        else:
            data[:, c] = np.median(ch.data[:, c])  # every level, palette included, held still
    return direct.Channels(ch.names, ch.kinds, data, ch.drops, ch.duration)


class Renderer:
    def __init__(self, width: int, height: int, supersample: int = 1) -> None:
        """`supersample` says these pixels are that many to an output pixel along a side:
        the frame is meant to be scaled down by it afterwards. A shader that knows about
        it (`uSS`) keeps its sizes in output pixels, so the scaled-down frame is the same
        picture with its edges resolved from more samples."""
        self.size = (width, height)
        self.ctx = moderngl.create_standalone_context(require=330)
        sh = shader_module()
        self.prog = self.ctx.program(vertex_shader=sh.vertex_source(),
                                     fragment_shader=sh.fragment_source())
        quad = self.ctx.buffer(FULLSCREEN.tobytes())
        self.vao = self.ctx.vertex_array(self.prog, [(quad, "2f", "aPos")])
        self.tex = self.ctx.texture((width, height), 4, dtype="f1")
        self.fbo = self.ctx.framebuffer(color_attachments=[self.tex])
        self.prog["uResolution"].value = (float(width), float(height))
        if "uSS" in self.prog:
            self.prog["uSS"].value = float(supersample)
        self.textures = []
        for unit, (name, arr) in enumerate(data_textures().items()):
            tex = self.ctx.texture((arr.shape[1], arr.shape[0]), arr.shape[2], arr.astype("f4").tobytes(), dtype="f4")
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            tex.use(unit)
            if name in self.prog:
                self.prog[name].value = unit
            self.textures.append(tex)
        self.fbo.use()

    def bind(self, names: list[str], feeds: dict[str, str] | None = None, shape: str = "wide") -> None:
        """Look each uniform up once. One the compiler dropped is simply not set. `feeds`
        re-points uniforms to other channels, as the player's variants do: a camera is
        {"uCamSpan": "uCamSpan.cinematic", ...}. In the tall frame the camera is the one
        the channels give, turned (cosmos.turned)."""
        feeds = feeds or {}
        self.slots = [(names.index(feeds.get(n, n)), self.prog[n]) for n in names if n in self.prog]
        self.turned = [names.index(feeds.get(n, n)) for n in cosmos.TURNED] if shape == "tall" else None
        if "uTall" in self.prog:
            self.prog["uTall"].value = 1.0 if shape == "tall" else 0.0

    def frame(self, t: float, row: np.ndarray) -> np.ndarray:
        self.prog["uTime"].value = float(t)
        for c, u in self.slots:
            u.value = float(row[c])
        if self.turned:
            for name, value in zip(cosmos.TURNED, cosmos.turned(*(float(row[c]) for c in self.turned))):
                if name in self.prog:
                    self.prog[name].value = float(value)
        self.vao.render(moderngl.TRIANGLES)
        buf = np.frombuffer(self.fbo.read(components=3), dtype=np.uint8)
        return buf.reshape(self.size[1], self.size[0], 3)[::-1]

    def release(self) -> None:
        self.ctx.release()


def frame_times(start: float, duration: float, fps: int) -> np.ndarray:
    n = max(1, int(round(duration * fps)))
    return start + (np.arange(n, dtype=np.float64) + 1.0) / fps


def mp4_name(track: Track, camera: str | None = "static", words: bool = True, clip: float | None = None,
             solo: str | None = None, shape: str = "wide") -> str:
    """What an mp4 is called: the song and its camera in the cosmos style (whether it is
    tall, and whether it has the words), "piece" in the others; a clip or a solo says so,
    and where it starts."""
    stem = "piece" if camera is None else (f"{track.slug}-{camera}" + ("-tall" if shape == "tall" else "")
                                           + ("" if words else "-no-lyrics"))
    return f"{stem}.mp4" if clip is None and not solo else f"{stem}-{solo or 'clip'}-{clip or 0:.0f}s.mp4"


def render(got: dict, track: Track, out_dir: str | Path, start: float = 0.0, duration: float | None = None,
           size: tuple[int, int] = (1920, 1080), fps: int = 60, crf: int = 17,
           solo: str | None = None, quiet: bool = False, camera: str = "static", words: bool = True,
           ch: direct.Channels | None = None, progress=None, shape: str = "wide") -> Path:
    """The mp4: the picture frame by frame, with the song under it. `shape` "tall" is the
    same picture for a screen held upright: `size` with its sides changed over (1080 x 1920
    for 1920 x 1080), the camera turned, the words set for it.

    In the cosmos style it is what the player shows: baked from the song's direction sheet
    (`make.directed`), unless the channels are given (`ch`, the studio's own bake), seen
    through one of the three cameras, with the words burned in (burn.py) unless `words` is
    False. A solo is for measuring one instrument, so it has no words. `progress(done, total)`
    is told as the frames go."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cosmic = STYLE == "cosmos"
    if shape not in cosmos.SHAPES or (shape == "tall" and not cosmic):
        raise ValueError(f"no shape {shape!r}: the solar system is wide or tall")
    if shape == "tall" and size[0] > size[1]:
        size = (size[1], size[0])
    baked_here = ch is None
    if ch is None:
        if cosmic:
            from .make import directed
            ch = directed(track, got)[0]
        else:
            ch = bake(got, track)
    feeds = {}
    if cosmic:
        choices = ch.variants["camera"]["choices"]
        if camera not in choices:
            raise ValueError(f"no camera {camera!r}: the cameras are {', '.join(choices)}")
        feeds = choices[camera]
    lines = None
    if cosmic and words and not solo:
        from . import lyrics
        from .burn import Words
        spec = lyrics.layout(track, ch, (getattr(ch, "sheet", None) or {}).get("lyrics"))
        lines = Words(spec, camera, size, shape) if spec else None
    if solo:
        ch = solo_channels(ch, solo)
    total = ch.duration - start if duration is None else min(duration, ch.duration - start)

    whole = start == 0.0 and duration is None and not solo
    out_path = out_dir / mp4_name(track, camera if cosmic else None, words or bool(solo), None if whole else start, solo, shape)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}",
           "-r", str(fps), "-i", "-",
           "-ss", f"{start:.6f}", "-i", str(track.audio),
           "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "256k",
           "-t", f"{total:.6f}",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None

    r = Renderer(*size)
    t0 = time.perf_counter()
    times = frame_times(start, total, fps)
    rows = ch.rows(times)
    r.bind(ch.names, feeds, shape)
    try:
        for k, (t, row) in enumerate(zip(times, rows)):
            frame = np.ascontiguousarray(r.frame(float(t), row))
            if lines is not None:
                lines.draw(frame, float(t))              # a frame with no line up is left as it is
            proc.stdin.write(frame.tobytes())
            if progress is not None and (k % 30 == 29 or k == len(times) - 1):
                progress(k + 1, len(times))
    except BrokenPipeError:
        proc.wait()
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.read().decode()[:800]}") from None
    finally:
        r.release()
    proc.stdin.close()
    err = proc.stderr.read().decode()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg exited {proc.returncode}: {err[:800]}")
    dt = time.perf_counter() - t0
    if not quiet:
        print(f"{len(times)} frames in {dt:.1f}s ({len(times) / dt:.0f} fps)")

    if whole and baked_here:                          # the player's bundle, the same bake (the studio has its own)
        export(got, ch, track, out_dir)
    return out_path


def canvas_name(track: Track, camera: str = "static") -> str:
    return f"{track.slug}-{camera}-canvas.mp4"


def canvas(got: dict, track: Track, out_dir: str | Path, camera: str = "static", ch: direct.Channels | None = None,
           size: tuple[int, int] = (1080, 1920), fps: int = 60, crf: int = 17, progress=None, at: float | None = None):
    """A loop for Spotify's Canvas (loop.py): a few bars of the song where the most is
    played (or from the bar the moment `at` is in), tall, made to run round without a
    seam; no sound and no words. Returns the mp4 and the bars it is of."""
    from . import loop

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if ch is None:
        from .make import directed
        ch = directed(track, got)[0]
    choices = ch.variants["camera"]["choices"]
    if camera not in choices:
        raise ValueError(f"no camera {camera!r}: the cameras are {', '.join(choices)}")
    w = loop.window(ch, got, camera, at=at)
    times, rows = loop.rows(ch, w, fps)
    out_path = out_dir / canvas_name(track, camera)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    r = Renderer(*size)
    r.bind(ch.names, choices[camera], "tall")
    try:
        for k, (t, row) in enumerate(zip(times, rows)):
            proc.stdin.write(np.ascontiguousarray(r.frame(float(t), row)).tobytes())
            if progress is not None and (k % 30 == 29 or k == len(times) - 1):
                progress(k + 1, len(times))
    except BrokenPipeError:
        proc.wait()
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.read().decode()[:800]}") from None
    finally:
        r.release()
    proc.stdin.close()
    err = proc.stderr.read().decode()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg exited {proc.returncode}: {err[:800]}")
    return out_path, w


def stage(got: dict, track: Track, out_dir: str | Path, ch: direct.Channels | None = None) -> Path:
    """Only what the browser player needs - the shader and the baked channels - and
    no mp4. Seconds rather than minutes, which is what trying a look wants."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    Renderer(64, 36).release()              # compile it here first: a GLSL error is better read now
    export(got, bake(got, track) if ch is None else ch, track, out_dir)
    return out_dir


def heard(ch: direct.Channels) -> dict:
    """What was heard, as the moments themselves: every kick, every note of the bass line,
    every note a planet plays, every syllable. They are read back out of the baked channels
    (and the planets' parts), so they are the very moments the picture moves to, not a
    second opinion. For a page to draw beside the picture (player/heard.js).

    Each part is {"t": seconds, "a": sizes 0..1, "k": which of several}: for the notes `k`
    is the planet, Mercury 0 to Neptune 7."""
    col = {name: ch.data[:, c] for c, name in enumerate(ch.names)}

    def held(time: str, size: str, slots: int | None = None) -> list[tuple[float, float, int]]:
        out = []
        for k in range(slots or 1):
            t, a = col[f"{time}{'' if slots is None else k}"], col[f"{size}{'' if slots is None else k}"]
            first = np.flatnonzero(np.diff(t, prepend=np.float32(-1000.0)) != 0)
            out += [(float(t[i]), float(a[i]), k) for i in first if t[i] > -100]
        return out

    def part(events) -> dict:
        events = sorted(events)
        return {"t": [round(t, 3) for t, _, _ in events], "a": [round(min(max(a, 0.0), 1.0), 2) for _, a, _ in events],
                "k": [k for _, _, k in events]}

    notes = [(float(t), float(a), planet) for planet, (tt, aa) in enumerate(getattr(ch, "planet_notes", None) or [])
             for t, a in zip(tt, aa)]
    return {"kick": part(held("uKickT", "uKickA")),
            "bass": part(held("uPromT", "uPromA", shader_cosmos.N_PROM)),
            "notes": part(notes),
            "voice": part(held("uWindT", "uWindA", shader_cosmos.N_WIND))}


def shipped(ch: direct.Channels) -> list[int]:
    """Which of the channels the player is sent. In the cosmos style, those the shader declares
    a uniform for, under its own name or as one camera's (uCamX.cinematic, which the player
    feeds uCamX from): the cosmos bake also holds `direct`'s channels for the other styles'
    shaders, and ones it reads itself while baking (uNoteT, uTilt), which nothing reads after.
    The player reads no channel by name but these, and the measuring reads the bake itself.
    The other styles are sent every channel."""
    if STYLE != "cosmos":
        return list(range(len(ch.names)))
    declared = set(re.findall(r"\bu[A-Z]\w*", " ".join(re.findall(r"^uniform [^;]*", shader_cosmos.FRAGMENT_BODY, re.M))))
    return [c for c, name in enumerate(ch.names) if name.split(".")[0] in declared]


def export(got: dict, ch: direct.Channels, track: Track, out_dir: Path) -> None:
    """plan.json + frames.bin + audio, in the format visuals/player already reads: of the
    channels, what the player is sent (`shipped`)."""
    bad = [name for name, col in zip(ch.names, ch.data.T) if not np.isfinite(col).all()]
    if bad:
        raise ValueError(f"channels that are not finite, which the player would draw as nothing: {bad}")
    meta = got["meta"]
    bar = int(meta.get("meter", 4)) * meta["period"]
    edges = [0.0] + [d["t"] for d in ch.drops if d["t"] > bar] + [ch.duration]
    sections = [{"index": i, "name": f"from bar {int(round(a / bar))}", "start": a, "end": b,
                 "scene": "gravity"} for i, (a, b) in enumerate(zip(edges[:-1], edges[1:]))]
    sent = shipped(ch)
    grid = ch.header()
    grid["features"] = [grid["features"][c] for c in sent]
    plan = {
        "version": 1, "track": track.slug, "duration": ch.duration, "tempo": meta["tempo"],
        "meter": int(meta.get("meter", 4)), "seed": 0, "grid": grid, "per_frame": ["uTime"],
        "sections": sections,
        "program": {"key": f"{track.slug}-{STYLE}",
                    "fragment": shader_module().fragment_source(shader.WEBGL_HEADER)},
        "vertex": shader_module().vertex_source(shader.WEBGL_HEADER),
        "frames_file": "frames.bin", "audio_file": "mix.m4a",
        "drops": ch.drops,
        "plan": [{"bars": [s.bar0, s.bar1], "state": s.state, "hue": s.hue, "axes": s.axes}
                 for s in (ch.sections or [])],
    }
    plan["textures"] = []
    for name, arr in data_textures().items():
        file = f"{name}.bin"
        (out_dir / file).write_bytes(arr.astype("<f4").tobytes())
        plan["textures"].append({"name": name, "file": file, "width": int(arr.shape[1]),
                                 "height": int(arr.shape[0]), "channels": int(arr.shape[2])})
    if getattr(ch, "variants", None):
        plan["variants"] = ch.variants
    if getattr(ch, "acts", None):
        plan["acts"] = [{"start": a.start, "end": a.end, "function": a.function,
                         "subject": a.subject if a.subject >= 0 else None} for a in ch.acts]
    if STYLE == "cosmos":
        from . import lyrics
        words = lyrics.layout(track, ch, (getattr(ch, "sheet", None) or {}).get("lyrics"))
        if words:
            plan["lyrics"] = words
        plan["heard"] = heard(ch)
    (out_dir / "frames.bin").write_bytes(ch.data[:, sent].astype("<f4").tobytes())
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    src, dst = track.mix_m4a, out_dir / "mix.m4a"
    if src.exists():
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        try:
            os.symlink(src, dst)
        except OSError:
            shutil.copy2(src, dst)


# ---------------------------------------------------------------- the compact form
# A bundle as `export` writes it is float32, frame by frame, uncompressed: 34 MB of frames
# for a 4:45 song, which is right on this machine and too much to put on a web page. `pack`
# writes the same bundle compact, for a static host (the demo on GitHub Pages).
#
# Plain float16 is not enough. Half the channels are levels between 0 and 1, where it is
# exact to 0.0005, but the rest are clocks and the times of the last hits (uKickT is the
# moment of the last kick, up to the song's length): at 280 s a float16 is 0.25 s coarse, so
# a hit would land an eighth of a second off and the orbits would step. So each channel is
# stored as float16 only if that holds it to within HALF_ERROR, and as float32 otherwise.
#
# And a planet's phase (where it is along its orbit, in revolutions) is float32 whatever
# float16 would hold: HALF_ERROR is fine for a level and too coarse for a place. Saturn's
# phase is 0.0005 coarse in float16, about 7 pixels in its close shot, so Saturn went in
# steps some six times a second while the camera, which follows its true path, went
# smoothly (seen on Jugal's telephone, 2026-09-28). It is rounded to PHASE_STEP first,
# 0.06 pixels of Saturn there, so that its lowest bits, noise gzip cannot fold, are zeros:
# 132 KB more for Gravity, where plain float32 would be 369 KB. What else says where things
# are (distances, the camera) is a pixel or less coarse in float16, and stays so.
#
# Each column is written as byte planes (every value's first byte, then every second
# byte...), because neighbouring values share their high bytes and gzip then finds them.
#
# And the frames are cut into pieces of PIECE_SECONDS, each a file of its own, so that a
# page draws as soon as it has the piece under the moment it starts at, and has the rest
# come while it plays. On Gravity: twenty pieces, 3.0 MB in all and 0.18 MB the largest
# wait. (When it was 3.3 MB: 2.9 MB in one, 5.1 MB for plain float16, 14.7 MB for float32,
# gzipped.)

PIECE_SECONDS = 15.0

# half of float16's step between 1 and 2: whatever it holds this well is as good as exact
HALF_ERROR = 2.0 ** -11


def narrowest(values: np.ndarray) -> str:
    """"f16" if float16 holds these values to within HALF_ERROR, else "f32"."""
    with np.errstate(over="ignore", invalid="ignore"):
        back = values.astype("<f2").astype("<f4")
    ok = np.isfinite(back).all() and np.abs(back - values).max(initial=0.0) <= HALF_ERROR
    return "f16" if ok else "f32"


PHASES = ("uPh", "uPlutoPh")
PHASE_STEP = 2.0 ** -18


def phase(name: str) -> bool:
    """Whether the channel `name` is a planet's phase (uPh5, uPlutoPh)."""
    return name.split(".")[0].rstrip("0123456789") in PHASES


def planes(values: np.ndarray, dtype: str) -> bytes:
    """The values at `dtype`, little-endian, as byte planes."""
    a = np.ascontiguousarray(values, dtype="<f2" if dtype == "f16" else "<f4")
    return a.view(np.uint8).reshape(-1, a.itemsize).T.tobytes()


def _gzip(path: Path, data: bytes) -> None:
    # mtime 0: the same bundle packs to the same bytes, so a rebuild is not a change in git
    path.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))


def faststart(src: Path, dst: Path) -> None:
    """The audio copied, with its index (the `moov` atom) before its samples if it was
    after them: a page that starts a song in its middle then finds where in one request,
    not after reading to the end of the file. Nothing is encoded again."""
    data = src.read_bytes()
    at, order = 0, []
    while at + 8 <= len(data):
        size, kind = int.from_bytes(data[at:at + 4], "big"), data[at + 4:at + 8]
        if size == 1 and at + 16 <= len(data):
            size = int.from_bytes(data[at + 8:at + 16], "big")
        if size < 8:
            break
        order.append(kind)
        at += size
    late = b"moov" in order and b"mdat" in order and order.index(b"moov") > order.index(b"mdat")
    if late and shutil.which("ffmpeg"):
        done = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-c", "copy",
                               "-fflags", "+bitexact", "-movflags", "+faststart", "-f", "mp4", str(dst)])
        if done.returncode == 0:
            return
    dst.write_bytes(data)                                        # follows a link: a copy


def pack(out_dir: str | Path, dest: str | Path) -> Path:
    """The bundle in `out_dir`, written compact into `dest`: the frames in pieces, channel by
    channel, each at the narrowest precision that holds it, as byte planes, gzipped; the
    textures the same way, whole; the audio copied (never linked); and a plan that says so.
    The player reads either form (player/bundle.js)."""
    out_dir, dest = Path(out_dir), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    plan = json.loads((out_dir / "plan.json").read_text())
    stride = len(plan["grid"]["features"])
    data = np.frombuffer((out_dir / plan["frames_file"]).read_bytes(), dtype="<f4").reshape(-1, stride)
    names = [f["name"] for f in plan["grid"]["features"]]
    if any(phase(name) for name in names):
        data = data.copy()
        for c, name in enumerate(names):
            if phase(name):
                data[:, c] = np.round(data[:, c].astype(np.float64) / PHASE_STEP) * PHASE_STEP
    dtypes = ["f32" if phase(name) else narrowest(col) for name, col in zip(names, data.T)]
    piece = int(round(PIECE_SECONDS * plan["grid"]["rate"]))
    files = [f"frames-{k:03d}.bin.gz" for k in range(-(-len(data) // piece))]
    for old in dest.glob("frames*.bin.gz"):                      # an earlier packing's, longer or whole
        if old.name not in files:
            old.unlink()
    for k, name in enumerate(files):
        part = data[k * piece:(k + 1) * piece]
        _gzip(dest / name, b"".join(planes(col, dt) for col, dt in zip(part.T, dtypes)))
    del plan["frames_file"]
    plan.update(frames_files=files, frames_piece=piece, frames_packing="planes", frames_dtype=dtypes)
    for spec in plan.get("textures", []):
        values = np.frombuffer((out_dir / spec["file"]).read_bytes(), dtype="<f4")
        dtype = narrowest(values)
        _gzip(dest / f"{spec['name']}.bin.gz", planes(values, dtype))
        spec.update(file=f"{spec['name']}.bin.gz", packing="planes", dtype=dtype)
    audio = out_dir / plan["audio_file"]
    if audio.exists():
        faststart(audio, dest / plan["audio_file"])
    (dest / "plan.json").write_text(json.dumps(plan, separators=(",", ":")) + "\n")
    return dest
