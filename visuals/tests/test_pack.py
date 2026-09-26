"""The compact bundle (render.pack) and the player's reader of it (player/bundle.js)."""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess

import numpy as np
import pytest

from visuals.pieces.gravity import ROOT, render

BUNDLE_JS = ROOT / "visuals" / "player" / "bundle.js"
FRAMES = 1001                     # odd, so a float16 column leaves the next one unaligned
node = pytest.mark.skipif(shutil.which("node") is None, reason="no node to run the player's reader")


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    """A small bundle in `export`'s form: levels, a clock, the times of hits, negatives and a
    texture - the kinds of values a real one holds - and the audio as a link."""
    out = tmp_path_factory.mktemp("out")
    rng = np.random.default_rng(7)
    t = np.arange(FRAMES) / 120.0
    cols = {
        "uLevel": rng.random(FRAMES),                                 # 0..1: float16 holds it
        "uSigned": np.sin(t * 3.0) * 0.9,                              # negative too
        "uBeats": t * 2.07,                                            # a clock, past 2: not float16
        "uKickT": np.maximum.accumulate(np.where(rng.random(FRAMES) < 0.02, t, 0.0)) + 280.0,
        "uFar": np.full(FRAMES, 1e6),                                  # beyond float16 altogether
        "uZero": np.zeros(FRAMES),
    }
    names = list(cols)
    data = np.stack([cols[n] for n in names], axis=1).astype("<f4")
    texture = rng.normal(size=(4, 6, 4)).astype("<f4")
    (out / "frames.bin").write_bytes(data.tobytes())
    (out / "uTex.bin").write_bytes(texture.tobytes())
    audio = out.parent / "mix-source.m4a"
    audio.write_bytes(b"not really audio")
    (out / "mix.m4a").symlink_to(audio)
    plan = {"grid": {"rate": 120, "frames": FRAMES,
                     "features": [{"name": n, "kind": "hold" if n == "uKickT" else "lerp"} for n in names]},
            "frames_file": "frames.bin", "audio_file": "mix.m4a",
            "textures": [{"name": "uTex", "file": "uTex.bin", "width": 6, "height": 4, "channels": 4}]}
    (out / "plan.json").write_text(json.dumps(plan))
    dest = render.pack(out, tmp_path_factory.mktemp("packed") / "song")
    return out, dest, data, texture


def _read(dest):
    """The packed bundle read back, the way the plan describes it."""
    plan = json.loads((dest / "plan.json").read_text())
    raw = gzip.decompress((dest / plan["frames_file"]).read_bytes())
    frames, at, cols = plan["grid"]["frames"], 0, []
    for dtype in plan["frames_dtype"]:
        size = 2 if dtype == "f16" else 4
        chunk = np.frombuffer(raw[at:at + frames * size], dtype=np.uint8).reshape(size, frames)
        cols.append(np.ascontiguousarray(chunk.T).view("<f2" if size == 2 else "<f4")[:, 0].astype("<f4"))
        at += frames * size
    assert at == len(raw)
    return plan, np.stack(cols, axis=1)


def test_each_channel_is_kept_as_narrow_as_holds_it(bundle):
    _, dest, _, _ = bundle
    plan, _ = _read(dest)
    assert plan["frames_file"].endswith(".gz") and plan["frames_packing"] == "planes"
    assert plan["frames_dtype"] == ["f16", "f16", "f32", "f32", "f32", "f16"]


def test_the_packed_frames_read_back_exactly_or_within_a_half_step(bundle):
    _, dest, data, _ = bundle
    plan, back = _read(dest)
    for c, dtype in enumerate(plan["frames_dtype"]):
        if dtype == "f32":
            assert np.array_equal(back[:, c], data[:, c])        # the clocks and hit times, exact
        else:
            assert np.abs(back[:, c] - data[:, c]).max() <= render.HALF_ERROR


def test_textures_audio_and_the_plan(bundle):
    out, dest, _, texture = bundle
    plan = json.loads((dest / "plan.json").read_text())
    spec = plan["textures"][0]
    assert spec["file"] == "uTex.bin.gz" and spec["dtype"] == "f32" and spec["packing"] == "planes"
    raw = np.frombuffer(gzip.decompress((dest / spec["file"]).read_bytes()), dtype=np.uint8)
    assert np.array_equal(np.ascontiguousarray(raw.reshape(4, -1).T).view("<f4")[:, 0], texture.ravel())
    assert not (dest / "mix.m4a").is_symlink() and (dest / "mix.m4a").read_bytes() == b"not really audio"
    # the local form is left as it was: the studio and the player on this machine read it
    assert json.loads((out / "plan.json").read_text())["frames_file"] == "frames.bin"


def test_packing_again_gives_the_same_bytes(bundle, tmp_path):
    out, dest, _, _ = bundle
    again = render.pack(out, tmp_path / "again")
    for name in ("frames.bin.gz", "uTex.bin.gz", "plan.json"):
        assert (again / name).read_bytes() == (dest / name).read_bytes(), name


def _node(tmp_path, body: str) -> str:
    script = f'import * as B from {json.dumps(BUNDLE_JS.as_uri())};\nimport {{ readFileSync }} from "node:fs";\n{body}'
    (tmp_path / "check.mjs").write_text(script)
    return subprocess.run(["node", str(tmp_path / "check.mjs")], capture_output=True, text=True, check=True).stdout


@node
def test_the_players_float16_is_numpys(tmp_path):
    rng = np.random.default_rng(3)
    values = np.concatenate([
        [0.0, -0.0, 1.0, -1.0, 1000.0, -1000.0, 0.5, 65504.0, -65504.0, 6e-8, -6e-8, 1e-5, np.inf, -np.inf],
        rng.uniform(-1, 1, 200), rng.uniform(-2000, 2000, 100), rng.uniform(0, 1e-4, 50)]).astype("<f2")
    bits = values.view("<u2").tolist()
    got = json.loads(_node(tmp_path, f"""
const bits = {json.dumps(bits)};
const out = B.halves(Uint16Array.from(bits));
console.log(JSON.stringify(Array.from(out, (v, i) => [v === Infinity ? "inf" : v === -Infinity ? "-inf" : v,
  Object.is(v, -0), B.halfToFloat(bits[i]) === v || (Number.isNaN(v) && Number.isNaN(B.halfToFloat(bits[i])))])));
"""))
    want = values.astype(np.float64)
    assert len(got) == len(want) > 300
    for (v, negzero, agrees), w in zip(got, want):
        assert agrees
        assert (float(v) if not isinstance(v, str) else float(v.replace("inf", "Infinity"))) == w
        assert negzero == (w == 0 and np.signbit(w))


@node
def test_the_player_reads_the_packed_bundle_as_python_does(bundle, tmp_path):
    _, dest, _, texture = bundle
    plan, back = _read(dest)
    got = json.loads(_node(tmp_path, f"""
const dir = {json.dumps(str(dest))};
const plan = JSON.parse(readFileSync(dir + "/plan.json", "utf8"));
const bytes = (name) => {{ const b = readFileSync(dir + "/" + name); return b.buffer.slice(b.byteOffset, b.byteOffset + b.length); }};
const grid = B.gridValues(await B.inflate(bytes(plan.frames_file)), plan);
const spec = plan.textures[0];
const tex = B.textureValues(await B.inflate(bytes(spec.file)), spec);
console.log(JSON.stringify({{ grid: Array.from(grid), tex: Array.from(tex) }}));
"""))
    assert np.array_equal(np.array(got["grid"], dtype="<f4").reshape(back.shape), back)
    assert np.array_equal(np.array(got["tex"], dtype="<f4"), texture.ravel())
