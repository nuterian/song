// The same score, the same shaders and the same uniforms as the mp4, in WebGL2.
//
// There is deliberately no signal processing here. Everything that varies over
// time - the followed routes, the section levels, the transition envelope - was
// baked to a 120 Hz grid by the Python side and shipped as frames.bin. This file
// interpolates that grid and sets uniforms from it. That is the whole reason the
// browser and the mp4 cannot drift: there is no second implementation to drift.
//
// The shaders are the identical source, under `#version 300 es` instead of
// `#version 410 core`.

import { decoded } from "./bundle.js";
import { lyricInk, lyricOpacity, seating } from "./lyrics.js";

const params = new URLSearchParams(location.search);
if (params.get("embed")) document.body.classList.add("embed");
if (params.get("bare")) document.body.classList.add("bare");
const canvas = document.getElementById("gl");
const audio = document.getElementById("audio");
const playBtn = document.getElementById("play");
const seek = document.getElementById("seek");
const readout = document.getElementById("readout");
const errorBox = document.getElementById("error");
// A browser may hold an older index.html than the player.js it has just fetched. The
// controls this script owns are made here if the page does not have them.
function own(id) {
  let el = document.getElementById(id);
  if (!el) { el = document.createElement("span"); el.id = id; document.getElementById("bar").appendChild(el); }
  return el;
}
const choicesBox = own("choices");
const fpsBox = own("fps");
// the clock: made here, first in the bar after the play button, so that it is there
// whichever index.html the browser has
const clock = (() => {
  let el = document.getElementById("clock");
  if (!el) {
    el = document.createElement("span"); el.id = "clock";
    el.style.cssText = "color:#f2f0ff;font-variant-numeric:tabular-nums;white-space:nowrap;min-width:15ch;cursor:pointer";
    playBtn.after(el);
  }
  el.title = "click to copy a link to this moment";
  return el;
})();
const mmss = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;

// The mp4 is rendered at 60, and frame feedback decays once per frame, so the
// player steps at 60 too. Left to the display's own rate a 120 Hz screen would
// decay the trails twice as fast and the two would not look alike.
const STEP = 1 / 60;

function fail(message) {
  errorBox.hidden = false;
  errorBox.textContent = message;
  readout.textContent = "failed";
  throw new Error(message);
}

// Where the bundles are: beside visuals/player/ in visuals/out/, unless the page says
// otherwise (the demo keeps them beside itself, and names the song it opens on).
const bundles = document.body.dataset.bundles || "../out/";

async function pickTrack() {
  const named = params.get("track") || document.body.dataset.track;
  if (named) return named;
  // No ?track=, so guess from the directory listing the static server hands back.
  const res = await fetch("../out/");
  if (!res.ok) fail("no ?track=<name> given, and ../out/ could not be listed.");
  const html = await res.text();
  const names = [...html.matchAll(/href="([^"/]+)\/"/g)].map((m) => m[1]);
  if (!names.length) fail("nothing staged in ../out/. Run:  python -m visuals render <song-workdir>");
  return names[0];
}

function compile(gl, type, source, label) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, source);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    fail(`${label} did not compile:\n${gl.getShaderInfoLog(sh)}`);
  }
  return sh;
}

function link(gl, vertexSource, fragmentSource, label) {
  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, vertexSource, `${label} vertex`));
  gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, fragmentSource, `${label} fragment`));
  gl.bindAttribLocation(prog, 0, "aPos");
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    fail(`${label} did not link:\n${gl.getProgramInfoLog(prog)}`);
  }
  return prog;
}

function makeTarget(gl, width, height) {
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const fbo = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  gl.clearColor(0, 0, 0, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);
  return { tex, fbo };
}

/* The grid, read the way each channel's kind says: a level is interpolated
   between samples, an index is held. This mirrors Timeline.window in listen.py. */
class Grid {
  constructor(header, data, piece = 0) {
    this.rate = header.rate;
    this.frames = header.frames;
    this.names = header.features.map((f) => f.name);
    this.kinds = header.features.map((f) => f.kind);
    this.stride = this.names.length;
    this.data = data;
    const want = this.frames * this.stride;
    if (this.data.length !== want) {
      fail(`the frames hold ${this.data.length} floats, plan.json says ${want}`);
    }
    // In pieces of `piece` frames (the demo's bundle), which come one by one: `have` says
    // which are here, `wanted` which was last found missing.
    this.piece = piece;
    this.have = piece ? new Uint8Array(Math.ceil(this.frames / piece)) : null;
    this.wanted = -1;
  }

  put(k, values) {
    this.data.set(values, k * this.piece * this.stride);
    this.have[k] = 1;
  }

  // the frame that is here and nearest to frame i, whose piece is not
  nearest(i) {
    const k = Math.floor(i / this.piece);
    for (let d = 1; d < this.have.length; d++) {
      if (this.have[k - d]) return (k - d + 1) * this.piece - 1;
      if (this.have[k + d]) return (k + d) * this.piece;
    }
    return i;
  }

  read(t, out) {
    const x = Math.min(Math.max(t * this.rate, 0), this.frames - 1);
    let i = Math.floor(x);
    let j = Math.min(i + 1, this.frames - 1);
    let f = x - i;
    if (this.have) {
      // a moment whose piece has not come is drawn as the nearest that has, and asked for next
      const pi = Math.floor(i / this.piece), pj = Math.floor(j / this.piece);
      if (!this.have[pi]) { this.wanted = pi; i = j = this.nearest(i); f = 0; }
      else if (!this.have[pj]) { this.wanted = pj; j = i; }
    }
    for (let c = 0; c < this.stride; c++) {
      const a = this.data[i * this.stride + c];
      out[c] = this.kinds[c] === "lerp" ? a + (this.data[j * this.stride + c] - a) * f : a;
    }
    return out;
  }
}

// ---------------------------------------------------------------------------- lyrics
// Set over the picture, not in it: real type, crisp at any size. What each word looks
// like at a moment is lyrics.js's to say - a copy of visuals/pieces/gravity/lyrics.py's,
// held to it by a test; here they are only placed and drawn.


function makeLyrics(spec, canvas, bar, camera) {
  let st = spec.style;
  // The canvas and the words share one frame, so they cannot come apart: the words are
  // placed in percentages of it and sized in its height (container units), by CSS alone.
  const frame = document.createElement("div");
  frame.id = "frame";
  canvas.parentElement.insertBefore(frame, canvas);
  frame.appendChild(canvas);
  const layer = document.createElement("div");
  layer.id = "lyrics";
  layer.style.setProperty("--size", String(st.size));
  frame.appendChild(layer);
  const els = new Map();                           // line index -> its element, made when first needed
  let on = params.get("lyrics") !== "off";

  const toggle = document.createElement("span");
  toggle.className = "choice";
  toggle.innerHTML = "<span>lyrics</span>";
  let fading = 0;
  const turn = (name) => {
    on = name === "on";
    for (const x of toggle.querySelectorAll("button")) x.classList.toggle("on", x.dataset.name === name);
    const url = new URL(location.href); url.searchParams.set("lyrics", name); history.replaceState(null, "", url);
    // they fade, they are not switched: shown for as long as the fade out takes
    clearTimeout(fading);
    layer.hidden = false;
    layer.style.opacity = on ? "1" : "0";
    if (!on) fading = setTimeout(() => { if (!on) layer.hidden = true; }, 700);
  };
  for (const name of ["on", "off"]) {
    const b = document.createElement("button");
    b.textContent = name; b.dataset.name = name;
    b.addEventListener("click", () => turn(name));
    toggle.appendChild(b);
  }
  toggle.querySelector(`button[data-name="${on ? "on" : "off"}"]`).classList.add("on");
  layer.hidden = !on;
  layer.style.opacity = on ? "1" : "0";
  bar.appendChild(toggle);

  function element(k) {
    if (!els.has(k)) {
      const line = spec.lines[k];
      const el = document.createElement("div");
      el.className = "line";
      for (const [text] of line.words) {
        const w = document.createElement("span");
        w.textContent = text;
        el.appendChild(w);
        el.appendChild(document.createTextNode(" "));
      }
      layer.appendChild(el);
      els.set(k, el);
    }
    return els.get(k);
  }

  function put(el, region) {
    const r = spec.regions[region];                  // frame heights from the middle, y up
    el.style.left = `${50 + (100 * r.x * 9) / 16}%`;
    el.style.top = `${50 - 100 * r.y}%`;
    el.style.transform = `translate(${r.align === "center" ? "-50%" : r.align === "right" ? "-100%" : "0"}, -50%)`;
    el.style.textAlign = r.align;
  }

  // A line is set where it belongs the moment it appears and stays there until it has gone
  // (lyrics.js, `seating`). It once slid there from the corner every line began in: a
  // transition on its position, meant for camera switches, which is not allowed back.
  let seat = seating();
  const placed = new Map();                          // line index -> the region its element is in
  return {
    get on() { return on; },
    setOn(v) { turn(v ? "on" : "off"); },
    // a new bake's words (the studio's edits): set afresh, where the new layout puts them
    respec(next) {
      spec = next || { ...spec, lines: [] };
      st = spec.style;
      layer.style.setProperty("--size", String(st.size));
      for (const el of els.values()) el.remove();
      els.clear(); placed.clear();
      seat = seating();
    },
    show(t) {
      if (layer.hidden) return;
      const cam = camera() || "static";
      spec.lines.forEach((line, k) => {
        const region = seat(k, line, t, cam);
        if (region === null) {
          if (els.has(k)) els.get(k).style.opacity = "0";
          placed.delete(k);
          return;
        }
        const el = element(k);
        if (placed.get(k) !== region) { put(el, region); placed.set(k, region); }
        el.style.opacity = String(lyricOpacity(t, line));
        line.words.forEach(([, start, end], i) => {
          el.children[i].style.opacity = String(lyricInk(t, start, end, st));
        });
      });
    },
  };
}

// The grid of a plan: whole, as this machine stages it, or in pieces, as the demo has it.
// In pieces it is ready as soon as the one under `t` is here; the rest come after it (and
// after `before`, if given: what the first picture is waiting for), from there to the song's
// end and then from its beginning; or on from a piece found missing, if the song is moved.
async function gridOf(plan, base, t, options, before) {
  if (!plan.frames_files) {
    return new Grid(plan.grid, await decoded(base + plan.frames_file, plan.frames_file, "grid", plan, options));
  }
  const files = plan.frames_files, piece = plan.frames_piece, frames = plan.grid.frames;
  const grid = new Grid(plan.grid, new Float32Array(frames * plan.grid.features.length), piece);
  const bring = async (k) => {
    const spec = { frames_packing: plan.frames_packing, frames_dtype: plan.frames_dtype, frames: Math.min(piece, frames - k * piece) };
    grid.put(k, await decoded(base + files[k], files[k], "grid", spec, options));
  };
  const first = Math.min(Math.max(Math.floor((t * plan.grid.rate) / piece), 0), files.length - 1);
  await bring(first);
  (async () => {
    if (before) await before.catch(() => {});
    const rest = files.map((_, d) => (first + 1 + d) % files.length).filter((k) => k !== first);
    let failed = 0;
    while (rest.length) {
      const asked = rest.indexOf(grid.wanted);      // the song has been moved there: on from there
      if (asked > 0) rest.push(...rest.splice(0, asked));
      const k = rest.shift();
      try { await bring(k); }
      catch (e) {                                    // a piece that did not come is asked for again, a few times
        if (++failed > 6) return;
        rest.push(k);
        await new Promise((done) => setTimeout(done, 1500));
      }
    }
  })();
  return grid;
}

async function main() {
  const track = await pickTrack();
  const base = `${bundles}${encodeURIComponent(track)}/`;
  const planRes = await fetch(base + "plan.json");
  if (!planRes.ok) fail(`no plan for "${track}". Run:  python -m visuals render <song-workdir>`);
  let plan = await planRes.json();
  // Everything the picture needs is asked for at once, and is on its way while the shader
  // is compiled: the frames under the moment it starts at, the sky, the song.
  const startAt = Number(params.get("t")) > 0 && Number(params.get("t")) < plan.duration ? Number(params.get("t")) : 0;
  const texturesComing = (plan.textures || []).map((spec) => decoded(base + spec.file, spec.file, "texture", spec));
  const gridComing = gridOf(plan, base, startAt, undefined, Promise.all(texturesComing));
  for (const coming of [gridComing, ...texturesComing]) coming.catch(() => {});   // said where they are awaited
  audio.src = base + plan.audio_file;
  if (startAt) audio.currentTime = startAt;

  const gl = canvas.getContext("webgl2", { antialias: false, preserveDrawingBuffer: false });
  if (!gl) fail("this browser has no WebGL2.");

  // One program, for the whole song. Nothing is ever swapped, because nothing a
  // section decides is a switch - the section's choices are numbers in the grid
  // below, and they arrive already ramped.
  const prog = link(gl, plan.vertex, plan.program.fragment, plan.program.key);
  const uniforms = {};
  {
    const n = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    for (let k = 0; k < n; k++) {
      const name = gl.getActiveUniform(prog, k).name;
      uniforms[name] = gl.getUniformLocation(prog, name);
    }
  }

  // Lookup textures a program samples - a star catalogue, say. Float, unfiltered, read
  // with texelFetch, so what the shader gets is exactly what Python wrote.
  const dataTextures = [];
  for (const [unit, spec] of (plan.textures || []).entries()) {
    const raw = await texturesComing[unit];
    const tex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE1 + unit);
    gl.bindTexture(gl.TEXTURE_2D, tex);
    if ((spec.channels || 4) === 1) gl.texImage2D(gl.TEXTURE_2D, 0, gl.R32F, spec.width, spec.height, 0, gl.RED, gl.FLOAT, raw);
    else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, spec.width, spec.height, 0, gl.RGBA, gl.FLOAT, raw);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    dataTextures.push({ name: spec.name, unit: 1 + unit, tex });
  }
  // back to unit 0: everything after this binds its textures to the active unit, and
  // would otherwise bind a render target over the top of the lookup
  gl.activeTexture(gl.TEXTURE0);

  // A full-screen triangle, same as the renderer's.
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

  // The canvas is drawn at the display's own resolution, not at a fixed size stretched
  // to fit: on a dense screen a stretched 720p canvas is every pixel made four, and no
  // shader can look sharp through that. Capped, so a 5K window does not ask for 5K.
  let W = 0, H = 0, targets = [], front = 0, quality = 1;
  function fit() {
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    let w = Math.round(canvas.clientWidth * dpr * quality), h = Math.round(canvas.clientWidth * dpr * quality * 9 / 16);
    const cap = Number(params.get("maxheight")) || 1440;
    if (h > cap * quality) { h = Math.round(cap * quality); w = Math.round(h * 16 / 9); }
    if (!w || (w === W && h === H)) return;
    for (const old of targets) { gl.deleteFramebuffer(old.fbo); gl.deleteTexture(old.tex); }
    W = canvas.width = w; H = canvas.height = h;
    gl.activeTexture(gl.TEXTURE0);
    targets = [makeTarget(gl, W, H), makeTarget(gl, W, H)];
    front = 0;
    lastDrawn = -1;
  }

  let grid = await gridComing;
  seek.max = String(plan.duration);

  let values = new Float32Array(grid.stride);
  const perFrame = new Set(plan.per_frame);
  let lastDrawn = -1;
  fit();
  new ResizeObserver(fit).observe(canvas);

  // Variants: the same piece with some uniforms fed from other channels - three cameras,
  // say, all baked into the one grid. Choosing one re-points those uniforms and nothing
  // else, so it can be done while the song plays.
  const feeds = new Map();                         // uniform name -> the channel that feeds it, if not its own
  // A change of camera is a move, not a cut: for `seconds` each uniform goes from what the
  // camera left would have given it to what the one taken gives it, eased, by the clock on
  // the wall (so it moves while the song is paused too). Angles go the short way round; the
  // zoom goes by ratio, as a zoom is felt.
  const leaving = new Map();                       // uniform name -> the channel of the camera being left
  let move = null;                                 // {t0, seconds} while a move is on
  const easeInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2);
  function fed(name, c) {
    const to = feeds.has(name) && feeds.get(name) >= 0 ? values[feeds.get(name)] : values[c];
    if (!move || !leaving.has(name) || leaving.get(name) < 0) return to;
    const w = easeInOut(Math.min((performance.now() - move.t0) / (1000 * move.seconds), 1));
    const from = values[leaving.get(name)];
    if (/Turn|Roll/.test(name)) {
      const d = Math.atan2(Math.sin(to - from), Math.cos(to - from));
      return from + d * w;
    }
    if (/Span/.test(name) && from > 0 && to > 0) return from * (to / from) ** w;
    return from + (to - from) * w;
  }
  const chosen = {};                               // variant kind -> the name picked (the camera, say)
  const pickers = {};                              // variant kind -> how to pick one (again, after a new bake)
  for (const [kind, spec] of Object.entries(plan.variants || {})) {
    const group = document.createElement("span");
    group.className = "choice";
    group.innerHTML = `<span>${kind}</span>`;
    const pick = (name, seconds = 0) => {
      if (seconds > 0 && chosen[kind] && chosen[kind] !== name && !move) {
        for (const uniform of Object.keys(spec.choices[name])) leaving.set(uniform, feeds.get(uniform));
        move = { t0: performance.now(), seconds };
      }
      chosen[kind] = name;
      for (const [uniform, channel] of Object.entries(spec.choices[name])) feeds.set(uniform, grid.names.indexOf(channel));
      for (const b of group.querySelectorAll("button")) b.classList.toggle("on", b.dataset.name === name);
      const url = new URL(location.href); url.searchParams.set(kind, name); history.replaceState(null, "", url);
      lastDrawn = -1;
    };
    for (const name of Object.keys(spec.choices)) {
      const b = document.createElement("button");
      b.textContent = name; b.dataset.name = name;
      b.addEventListener("click", () => pick(name, 1.2));
      group.appendChild(b);
    }
    choicesBox.appendChild(group);
    pickers[kind] = pick;
    pick(spec.choices[params.get(kind)] ? params.get(kind) : spec.default);
  }

  let words = plan.lyrics ? makeLyrics(plan.lyrics, canvas, choicesBox, () => chosen.camera) : null;

  function sectionAt(t) {
    for (const s of plan.sections) if (t >= s.start && t < s.end) return s;
    return plan.sections[plan.sections.length - 1];
  }

  function clearFeedback() {
    for (const target of targets) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
      gl.clear(gl.COLOR_BUFFER_BIT);
    }
  }

  function draw(t) {
    // A page loaded where it has no width yet (a hidden pane, a tab in the background) has
    // nothing to draw into; the first frame waits for `fit`, which the resize brings.
    if (!targets.length) { lastDrawn = -1; return; }
    const section = sectionAt(t);
    grid.read(t, values);

    const src = targets[front];
    const dst = targets[1 - front];
    gl.bindFramebuffer(gl.FRAMEBUFFER, dst.fbo);
    gl.viewport(0, 0, W, H);
    gl.useProgram(prog);
    gl.bindVertexArray(vao);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, src.tex);
    if (uniforms.uPrev) gl.uniform1i(uniforms.uPrev, 0);
    if (uniforms.uResolution) gl.uniform2f(uniforms.uResolution, W, H);
    for (let c = 0; c < grid.stride; c++) {
      const name = grid.names[c];
      const loc = uniforms[name];
      if (loc) gl.uniform1f(loc, fed(name, c));
    }
    for (const d of dataTextures) {
      gl.activeTexture(gl.TEXTURE0 + d.unit);
      gl.bindTexture(gl.TEXTURE_2D, d.tex);
      if (uniforms[d.name]) gl.uniform1i(uniforms[d.name], d.unit);
    }
    gl.activeTexture(gl.TEXTURE0);
    if (uniforms.uTime) gl.uniform1f(uniforms.uTime, t);
    if (uniforms.uSeed) gl.uniform1f(uniforms.uSeed, plan.seed);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    front = 1 - front;

    // Straight to the canvas. A copy shader would be a second place for the two
    // renderers to disagree, and WebGL2 can blit.
    gl.bindFramebuffer(gl.READ_FRAMEBUFFER, dst.fbo);
    gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, null);
    gl.blitFramebuffer(0, 0, W, H, 0, 0, W, H, gl.COLOR_BUFFER_BIT, gl.NEAREST);
    if (words) words.show(t);

    const morph = values[grid.names.indexOf("uMorph")];
    const act = (plan.acts || []).find((a) => t >= a.start && t < a.end);
    clock.textContent = `${mmss(t)} / ${mmss(plan.duration)}`;
    readout.textContent =
      `${t.toFixed(2)}s  ` + (act ? `act ${(plan.acts.indexOf(act) + 1)} ${act.function}  ` : "") +
      `${section.name}  ${section.scene}` +
      (morph < 0.999 ? `  morphing ${(morph * 100).toFixed(0)}%` : "");
  }

  // The scrubber follows the song except while it is being dragged. (It used to defer to
  // the scrubber whenever it had *focus* - and it keeps focus after one click, so from
  // then on it never moved again.)
  let scrubbing = false;
  seek.addEventListener("pointerdown", () => (scrubbing = true));
  for (const ev of ["pointerup", "pointercancel", "change", "blur"]) seek.addEventListener(ev, () => (scrubbing = false));
  window.addEventListener("pointerup", () => (scrubbing = false));

  // frames actually drawn per second, and the slowest gap between two of them
  let shown = 0, slowest = 0, lastTick = performance.now(), windowStart = lastTick;
  // The song's clock, made even. `audio.currentTime` moves in steps of its own (a few
  // milliseconds in one browser, tens in another), and a picture drawn from it skips a frame
  // whenever two steps fall close together. Between its steps the time is carried forward
  // by the clock on the wall, and set by the audio's again only if the two come 50 ms apart.
  let sync = { wall: performance.now(), t: audio.currentTime };
  function songTime(now) {
    const real = audio.currentTime;
    if (audio.paused || audio.seeking) { sync = { wall: now, t: real }; return real; }
    const carried = sync.t + ((now - sync.wall) / 1000) * audio.playbackRate;
    if (Math.abs(carried - real) > 0.05) { sync = { wall: now, t: real }; return real; }
    return Math.min(carried, plan.duration);
  }

  // ?adapt=1: a machine that cannot keep 60 frames a second at this size is given fewer
  // pixels, a step at a time, and never more again (a size that comes and goes is worse).
  const adapt = Boolean(params.get("adapt"));
  let slow = 0;

  function tick() {
    const now = performance.now();
    slowest = Math.max(slowest, now - lastTick); lastTick = now;
    if (now - windowStart >= 1000) {
      const fps = Math.round(shown * 1000 / (now - windowStart));
      fpsBox.textContent = audio.paused ? `${W}x${H}` : `${fps} fps  ${slowest.toFixed(0)} ms`;
      if (adapt && !audio.paused && !document.hidden && lastDrawn >= 0) {
        slow = fps < 52 ? slow + 1 : 0;
        if (slow >= 2 && quality > 0.5) { quality = Math.max(0.5, quality * 0.85); slow = 0; fit(); }
      }
      shown = 0; slowest = 0; windowStart = now;
    }
    if (move) {
      if (now - move.t0 >= 1000 * move.seconds) { move = null; leaving.clear(); }
      lastDrawn = -1;                                // a camera on its way is drawn every frame, song playing or not
    }
    const t = songTime(now);
    if (lastDrawn < 0 || t < lastDrawn || t - lastDrawn >= STEP - 0.002) {
      if (lastDrawn >= 0 && (t < lastDrawn || t - lastDrawn > 0.5)) clearFeedback();
      draw(t);
      shown++;                                       // frames drawn, not frames asked for
      lastDrawn = t;
      if (!scrubbing) seek.value = String(t);
    }
    requestAnimationFrame(tick);
  }

  playBtn.addEventListener("click", () => {
    if (audio.paused) audio.play();
    else audio.pause();
  });
  audio.addEventListener("play", () => (playBtn.textContent = "pause"));
  audio.addEventListener("pause", () => (playBtn.textContent = "play"));
  seek.addEventListener("input", () => {
    audio.currentTime = Number(seek.value);
    clearFeedback();
  });
  // space plays and pauses; the arrows step five seconds (one with shift); a link carries the moment
  window.addEventListener("keydown", (e) => {
    if (e.target instanceof HTMLButtonElement && e.code === "Space") return;
    if (e.code === "Space") { e.preventDefault(); audio.paused ? audio.play() : audio.pause(); }
    if (e.code === "ArrowLeft" || e.code === "ArrowRight") {
      e.preventDefault();
      const step = (e.shiftKey ? 1 : 5) * (e.code === "ArrowLeft" ? -1 : 1);
      audio.currentTime = Math.min(Math.max(audio.currentTime + step, 0), plan.duration - 0.05);
      clearFeedback();
    }
  });
  clock.addEventListener("click", () => {
    const url = new URL(location.href); url.searchParams.set("t", audio.currentTime.toFixed(1));
    history.replaceState(null, "", url);
    if (navigator.clipboard) navigator.clipboard.writeText(url.href).catch(() => {});
  });
  if (startAt) seek.value = String(startAt);

  // The studio (visuals/studio/) edits the sheet and bakes it again; it hands the new bake
  // to this page here, and the song plays on. Only what a bake makes is read again - the
  // channels, the acts, the words; the shader and the sky are the same.
  window.player = {
    audio,
    get chosen() { return { ...chosen }; },
    variants(kind) { return Object.keys(((plan.variants || {})[kind] || {}).choices || {}); },
    choose(kind, name, seconds = 0) { if (pickers[kind]) pickers[kind](name, seconds); },
    // the song's clock as the picture has it, and the moments heard in it (render.heard)
    time() { return songTime(performance.now()); },
    get heard() { return plan.heard || null; },
    get drops() { return (plan.drops || []).map((d) => d.t); },
    get duration() { return plan.duration; },
    get lyrics() { return words ? words.on : null; },
    setLyrics(v) { if (words) words.setOn(v); },
    async reload() {
      const next = await (await fetch(base + "plan.json", { cache: "no-store" })).json();
      grid = await gridOf(next, base, audio.currentTime, { cache: "no-store" });
      if (values.length !== grid.stride) values = new Float32Array(grid.stride);
      plan = next;
      for (const [kind, pick] of Object.entries(pickers)) {
        const spec = (plan.variants || {})[kind];
        pick(spec && spec.choices[chosen[kind]] ? chosen[kind] : spec ? spec.default : chosen[kind]);
      }
      if (words) words.respec(plan.lyrics);
      else if (plan.lyrics) words = makeLyrics(plan.lyrics, canvas, choicesBox, () => chosen.camera);
      clearFeedback();
      lastDrawn = -1;
    },
  };

  draw(startAt);
  readout.textContent =
    `${plan.track}  ${plan.duration.toFixed(0)}s  ${plan.tempo.toFixed(1)} bpm  ` +
    `${plan.sections.length} sections  one program  - press play`;
  document.body.classList.add("ready");
  // ?play=1: start at once, if the browser allows it (it may not without a click here)
  // ?muted=1: silent until asked, which is what lets a page start it without a click
  if (params.get("muted")) audio.muted = true;
  if (params.get("play")) audio.play().catch(() => {});
  requestAnimationFrame(tick);
}

main().catch((e) => {
  if (!errorBox.hidden) return;
  errorBox.hidden = false;
  errorBox.textContent = String(e && e.stack ? e.stack : e);
});
