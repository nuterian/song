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

const params = new URLSearchParams(location.search);
const canvas = document.getElementById("gl");
const audio = document.getElementById("audio");
const playBtn = document.getElementById("play");
const seek = document.getElementById("seek");
const readout = document.getElementById("readout");
const errorBox = document.getElementById("error");

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

async function pickTrack() {
  const named = params.get("track");
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
  constructor(header, buffer) {
    this.rate = header.rate;
    this.frames = header.frames;
    this.names = header.features.map((f) => f.name);
    this.kinds = header.features.map((f) => f.kind);
    this.stride = this.names.length;
    this.data = new Float32Array(buffer);
    const want = this.frames * this.stride;
    if (this.data.length !== want) {
      fail(`frames.bin holds ${this.data.length} floats, plan.json says ${want}`);
    }
  }

  read(t, out) {
    const x = Math.min(Math.max(t * this.rate, 0), this.frames - 1);
    const i = Math.floor(x);
    const j = Math.min(i + 1, this.frames - 1);
    const f = x - i;
    for (let c = 0; c < this.stride; c++) {
      const a = this.data[i * this.stride + c];
      out[c] = this.kinds[c] === "lerp" ? a + (this.data[j * this.stride + c] - a) * f : a;
    }
    return out;
  }
}

async function main() {
  const track = await pickTrack();
  const base = `../out/${encodeURIComponent(track)}/`;
  const planRes = await fetch(base + "plan.json");
  if (!planRes.ok) fail(`no plan for "${track}". Run:  python -m visuals render <song-workdir>`);
  const plan = await planRes.json();
  const grid = new Grid(plan.grid, await (await fetch(base + plan.frames_file)).arrayBuffer());

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
    const raw = new Float32Array(await (await fetch(base + spec.file)).arrayBuffer());
    const tex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE1 + unit);
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, spec.width, spec.height, 0, gl.RGBA, gl.FLOAT, raw);
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

  const W = canvas.width;
  const H = canvas.height;
  const targets = [makeTarget(gl, W, H), makeTarget(gl, W, H)];
  let front = 0;

  audio.src = base + plan.audio_file;
  seek.max = String(plan.duration);

  const values = new Float32Array(grid.stride);
  const perFrame = new Set(plan.per_frame);
  let lastDrawn = -1;

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
      const loc = uniforms[grid.names[c]];
      if (loc) gl.uniform1f(loc, values[c]);
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

    const morph = values[grid.names.indexOf("uMorph")];
    readout.textContent =
      `${plan.track}  ${t.toFixed(2)}s / ${plan.duration.toFixed(0)}s  ` +
      `${section.name}  ${section.scene}` +
      (morph < 0.999 ? `  morphing ${(morph * 100).toFixed(0)}%` : "");
  }

  function tick() {
    const t = audio.currentTime;
    if (lastDrawn < 0 || t < lastDrawn || t - lastDrawn >= STEP) {
      if (lastDrawn >= 0 && (t < lastDrawn || t - lastDrawn > 0.5)) clearFeedback();
      draw(t);
      lastDrawn = t;
      if (document.activeElement !== seek) seek.value = String(t);
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

  draw(0);
  readout.textContent =
    `${plan.track}  ${plan.duration.toFixed(0)}s  ${plan.tempo.toFixed(1)} bpm  ` +
    `${plan.sections.length} sections  one program  - press play`;
  requestAnimationFrame(tick);
}

main().catch((e) => {
  if (!errorBox.hidden) return;
  errorBox.hidden = false;
  errorBox.textContent = String(e && e.stack ? e.stack : e);
});
