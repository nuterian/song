// The studio page: one screen, as an editing suite is - the picture, an inspector beside
// it, the song along the bottom on a timeline in bars. Every change is sent to the server
// as edits in the direction sheet's own vocabulary (timeline.js makes them from gestures;
// the local model makes them from words). The server checks, bakes and keeps; the player
// takes the new bake without stopping.

import { barOf, timeOf, edgeEdits, spanEdit, momentEdits, changedActs, changedMoments, sectionEdgeEdits } from "./timeline.js";
import { icon, PLANET_INK } from "./icons.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const mmss = (t) => `${Math.floor(Math.max(t, 0) / 60)}:${String(Math.floor(Math.max(t, 0) % 60)).padStart(2, "0")}`;
const clockOf = (t) => `${Math.floor(Math.max(t, 0) / 60)}:${(Math.max(t, 0) % 60).toFixed(1).padStart(4, "0")}`;
const cap = (s) => s[0].toUpperCase() + s.slice(1);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const SHOT = { approach: "Approach", wide: "Wide", intimate: "Two-shot", eclipse: "Close", alignment: "Alignment", pullback: "Pull back" };
const DIAL = {
  flares_every_bars: ["Flares", "bars apart"], planet_rings_every_bars: ["Planet rings", "bars apart"],
  camera_move_bars: ["Camera moves", "bars"], hybrid_turn_bars: ["Hybrid turn", "bars"], orbits_breathe: ["Orbits breathe", ""],
  size: ["Size", ""], unsung: ["Before", ""], peak: ["Sung", ""], sung: ["After", ""],
};
const TABS = [["sel", "cursor", "Selection"], ["feel", "sliders", "Feel"], ["cast", "mic", "Cast"], ["words", "text", "Words"],
  ["grid", "metronome", "Grid"], ["log", "clock", "History"]];
const NAMES = ["Intro", "Verse", "Pre-chorus", "Chorus", "Bridge", "Drop", "Break", "Outro"];

let song = null, sheet = null, N = 0;
let history = [], at = 0;          // the server's history of changes (every one, a hand's or the AI's), and where we are in it
let busy = false, selected = null, proposal = null;
let tab = "sel", zoom = 1, spanPlanet = "earth";

// A selected shot is held by a bar inside it, not by its place in the list: an edit can
// split, join or move acts, and the selection should stay on the one that is there.
const actAt = (acts, bar) => acts.findIndex((a) => a.bars[0] <= bar && bar < a.bars[1]);
const isSelAct = (acts, i) => selected && selected.kind === "act" && actAt(acts, selected.bar) === i;

const P = (b) => `${(b / N) * 100}%`;
const W = (a, b) => `calc(${((b - a) / N) * 100}% - 2px)`;
const tOf = (b) => timeOf(song.bar_t, song.duration, b);
const bOf = (t) => barOf(song.bar_t, song.duration, t);
const needs = (shot) => song.vocabulary.needs_subject.includes(shot);

// ---------------------------------------------------------------------------- the server

async function call(path, body) {
  const res = await fetch(`${path}?track=${encodeURIComponent(song.slug)}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return res.json();
}

function status(text, kind = "") {
  $("status").textContent = text;
  $("status").className = kind;
}

let toastTimer = 0;
function toast(lines, kind = "bad") {
  const t = $("toast");
  t.innerHTML = `<div class="pop ${kind}" style="position:static;width:auto"><ul>${lines.map((x) =>
    `<li>${icon(kind === "bad" ? "x" : "check", 14)}<span>${esc(x)}</span></li>`).join("")}</ul></div>`;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 7000);
}

// Every change goes through here: edits in, a new bake out, the player told.
async function change(path, body, relisten = false) {
  if (busy) { status("baking…", "busy"); return null; }
  busy = true;
  status(relisten ? "listening again… (a few minutes the first time)" : "baking…", "busy");
  let r;
  try { r = await call(path, body); } catch (e) { r = { ok: false, refused: [String(e)] }; }
  busy = false;
  if (r.history) { history = r.history; at = r.at; }
  if (!r.ok) { status("not changed", "bad"); toast(r.refused); return null; }
  if (!r.changed) { status("no change"); return r; }
  const picture = JSON.stringify({ ...r.sheet, heard: { ...r.sheet.heard, sections: 0 } }) !==
    JSON.stringify({ ...sheet, heard: { ...sheet.heard, sections: 0 } });
  sheet = r.sheet;
  if (r.song) { song = r.song; N = song.bar_t.length; showFacts(); }       // a new grid: new bars
  status(`${r.seconds.toFixed(1)} s`);
  if (player() && (picture || r.song)) await player().reload();
  return r;
}

async function edit(edits, source = "hand", request = null) {
  if (!edits.length) { draw(); return null; }
  const r = await change("/api/edit", { edits, source, request }, edits.some((e) => e.op === "grid"));
  draw();
  if (r && r.changed) flashHistory();
  return r;
}

// Undo, redo, and going back to any step: moving along the one history. A step that
// changed the grid is listened to again (at once if that grid was heard before).
async function goTo(k) {
  if (k < 0 || k >= history.length || k === at) return;
  const [lo, hi] = k < at ? [k + 1, at] : [at + 1, k];
  const relisten = history.slice(lo, hi + 1).some((h) => h.changes.some((c) => c.kind === "grid"));
  await change("/api/goto", { to: k }, relisten);
  draw();
}

function flashHistory() {
  const b = document.querySelector(`#tabs .ib[title="History"]`);
  if (!b || tab === "log") return;
  b.animate([{ color: "var(--accent)" }, { color: "" }], { duration: 900 });
}

// ---------------------------------------------------------------------------- the player

const frame = $("player");
const player = () => frame.contentWindow && frame.contentWindow.player;
const now = () => (player() ? player().audio.currentTime : 0);
const seek = (t) => { if (player()) player().audio.currentTime = Math.min(Math.max(t, 0), song.duration - 0.05); };
const playPause = () => { const a = player() && player().audio; if (a) a.paused ? a.play() : a.pause(); };

function drawTransport() {
  const cams = $("cams");
  cams.innerHTML = "";
  const p = player();
  if (!p) return;
  for (const name of p.variants("camera")) {
    const b = document.createElement("button");
    b.textContent = cap(name);
    b.dataset.name = name;
    b.addEventListener("click", () => { p.choose("camera", name); syncTransport(); });
    cams.appendChild(b);
  }
  // the frame: wide, or tall for a screen held upright; kept from one visit to the next
  const shapes = $("shapes");
  shapes.innerHTML = "";
  for (const [name, title] of [["wide", "Wide, 16:9"], ["tall", "Tall, 9:16: for a screen held upright"]]) {
    const b = document.createElement("button");
    b.innerHTML = icon(`frame${name}`, 16);
    b.dataset.name = name;
    b.title = title;
    b.setAttribute("aria-label", title);
    b.addEventListener("click", () => {
      p.setShape(name);
      try { localStorage.setItem("studio.shape", name); } catch (e) { /* private window */ }
      syncTransport();
    });
    shapes.appendChild(b);
  }
  try { if (localStorage.getItem("studio.shape") === "tall") p.setShape("tall"); } catch (e) { /* private window */ }
  $("lyr").hidden = p.lyrics === null;
  syncTransport();
}

function syncTransport() {
  const p = player();
  if (!p) return;
  const cam = p.chosen.camera;
  for (const b of $("cams").children) b.classList.toggle("on", b.dataset.name === cam);
  for (const b of $("shapes").children) b.classList.toggle("on", b.dataset.name === p.shape);
  $("lyr").innerHTML = icon(p.lyrics ? "eye" : "eyeoff", 18);
  $("lyr").classList.toggle("on", !!p.lyrics);
}

// ---------------------------------------------------------------------------- the mp4
// The whole song as it is shown now: this camera, this frame, the words on or off. Where it will be
// written is said before it starts; the server writes it in the background and says how far
// it has got, and the finished file is offered in the status.

let exportTimer = 0;
const exportUrl = (q = "") => `/api/export?track=${encodeURIComponent(song.slug)}${q}`;

async function openExport() {
  const p = player(), box = $("exportpop");
  if (!p || !box.hidden) { box.hidden = true; return; }
  const camera = p.chosen.camera || "static", lyrics = !!p.lyrics, shape = p.shape || "wide";
  const q = await (await fetch(exportUrl(`&camera=${encodeURIComponent(camera)}&lyrics=${lyrics ? 1 : 0}&shape=${shape}`))).json();
  if (q.job && q.job.state === "running") { watchExport(q.job); return; }
  const size = shape === "tall" ? "tall, 1080 by 1920" : "wide, 1920 by 1080";
  box.innerHTML = `<div class="said">${icon("download", 14)}<span>The whole song, ${size}, the ${esc(camera)} camera, ${lyrics ? "with" : "without"} the words, to</span></div>` +
    `<div class="path">${esc(q.path)}</div>` +
    `<div class="acts"><button class="pill" id="exno">Cancel</button><button class="pill go" id="exgo">${icon("download", 14)}Export</button></div>`;
  box.hidden = false;
  $("exno").addEventListener("click", () => (box.hidden = true));
  $("exgo").addEventListener("click", async () => {
    box.hidden = true;
    const r = await call("/api/export", { camera, lyrics, shape });
    if (!r.ok) { status("Not exported", "bad"); toast(r.refused); return; }
    watchExport(r);
  });
}

function watchExport(job) {
  clearTimeout(exportTimer);
  const name = job.path.split("/").pop();
  $("status").title = job.path;
  if (job.state === "running") {
    const frames = job.total ? `${job.done.toLocaleString()} / ${job.total.toLocaleString()} frames` : "preparing";
    const left = job.remaining === null ? "" : `, about ${mmss(job.remaining)} left`;
    status(`Exporting: ${frames}, ${mmss(job.elapsed)}${left}`, "busy");
    exportTimer = setTimeout(async () => {
      const q = await (await fetch(exportUrl())).json();
      if (q.job) watchExport(q.job);
    }, 1000);
  } else if (job.state === "done") {
    $("status").className = "";
    $("status").innerHTML = `<a href="${esc(job.url)}" download="${esc(name)}">${icon("download", 14)}${esc(name)}</a>`;
  } else {
    status("Export failed", "bad");
    toast([job.error]);
  }
}

// ---------------------------------------------------------------------------- the timeline

function draw() {
  const shown = proposal && proposal.proposal ? proposal.proposal : sheet;
  $("tracks").style.width = `${zoom * 100}%`;
  drawRuler();
  drawSections();
  drawEnergy();
  drawShots(shown);
  drawMoments(shown);
  drawWords();
  drawSelection();
  drawPane();
  $("undo").disabled = at <= 0;
  $("redo").disabled = at >= history.length - 1;
}

function drawRuler() {
  const el = $("ruler");
  el.innerHTML = "";
  const width = $("tracks").clientWidth || 800;
  const every = [1, 2, 4, 8, 16, 32, 64].find((k) => (k / N) * width >= 64) || 64;
  for (let b = 0; b < N; b += every) {
    const d = document.createElement("div");
    d.className = "tick";
    d.style.left = P(b);
    d.textContent = `${b}  ${mmss(tOf(b))}`;
    el.appendChild(d);
  }
  if ((width / N) / song.meter >= 7) {                   // close enough to see the beats: a mark on each
    for (const t of song.beats) {
      const d = document.createElement("div");
      d.className = "bt";
      d.style.left = P(bOf(t));
      el.appendChild(d);
    }
  }
}

function block(parent, cls, a, b, html, title) {
  const d = document.createElement("div");
  d.className = `blk ${cls}`;
  d.style.left = P(a);
  d.style.width = W(a, b);
  d.innerHTML = html;
  if (title) d.title = title;
  parent.appendChild(d);
  return d;
}

const secAt = (bar) => sheet.heard.sections.findIndex((x) => x.bars[0] <= bar && bar < x.bars[1]);

function drawSections() {
  const el = $("lane-song");
  el.innerHTML = "";
  const shown = proposal && proposal.proposal ? proposal.proposal : sheet;
  shown.heard.sections.forEach((s, i) => {
    const [a, b] = s.bars;
    const on = !proposal && selected && selected.kind === "section" && secAt(selected.bar) === i;
    const d = block(el, "sec" + (on ? " sel" : ""), a, b, esc(s.name), `${s.name} · bars ${a}–${b} · ${mmss(tOf(a))}`);
    d.addEventListener("pointerdown", (e) => e.stopPropagation());
    d.addEventListener("click", () => { select({ kind: "section", bar: a }); seek(tOf(a)); });
    if (proposal) return;
    for (const side of ["start", "end"]) {
      const e = document.createElement("div");
      e.className = "sedge";
      e.style.left = P(side === "start" ? a : b);
      e.addEventListener("pointerdown", (ev) => dragSectionEdge(ev, e, s, side));
      el.appendChild(e);
    }
  });
}

function drawEnergy() {
  const c = $("env");
  const w = c.clientWidth, h = c.clientHeight, dpr = window.devicePixelRatio || 1;
  if (!w) return;
  c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  const css = getComputedStyle(document.documentElement);
  const ink = { drive: css.getPropertyValue("--drive"), float: css.getPropertyValue("--float"), void: css.getPropertyValue("--void"), silent: "transparent" };
  const n = song.loud.length;
  for (let x = 0; x < w; x++) {
    const t = tOf((x / w) * N);                                    // the strip is in bars; the envelope in time
    const k = Math.min(n - 1, Math.max(0, Math.floor((t / song.duration) * n)));
    const bar = Math.min(N - 1, Math.floor(bOf(t)));
    const bh = Math.max(1, song.loud[k] * (h - 6));
    g.fillStyle = ink[song.energy[bar]] || ink.void;
    g.fillRect(x, (h - bh) / 2, 1, bh);
  }
}

function drawShots(shown) {
  const el = $("lane-shots");
  el.innerHTML = "";
  el.classList.toggle("proposed", !!(proposal && proposal.proposal));
  const changed = proposal && proposal.proposal ? new Set(changedActs(sheet.acts, shown.acts)) : new Set();
  shown.acts.forEach((a, i) => {
    const [b0, b1] = a.bars;
    const cls = "act" + (a.shot === "alignment" ? " climax" : "") + (changed.has(i) ? " changed" : "") +
      (!proposal && isSelAct(shown.acts, i) ? " sel" : "");
    const label = SHOT[a.shot] + (a.subject ? ` · ${cap(a.subject)}` : "");
    const dot = a.subject ? `<span style="width:7px;height:7px;border-radius:50%;flex:none;background:${PLANET_INK[a.subject]}"></span>` : "";
    const d = block(el, cls, b0, b1, `${icon(a.shot, 14)}${dot}<span>${esc(label)}</span>`,
      `${label} · bars ${b0}–${b1}\n${song.vocabulary.shots[a.shot]}`);
    if (!proposal) d.addEventListener("click", () => { select({ kind: "act", bar: b0 }); });
  });
  if (proposal) return;
  for (let i = 0; i < shown.acts.length - 1; i++) {
    const e = document.createElement("div");
    e.className = "edge";
    e.style.left = P(shown.acts[i].bars[1]);
    e.addEventListener("pointerdown", (ev) => dragEdge(ev, e, i));
    el.appendChild(e);
  }
}

function drawMoments(shown) {
  const el = $("lane-moments");
  el.innerHTML = "";
  const diff = proposal && proposal.proposal ? changedMoments(sheet.reentries, shown.reentries) : { added: [], removed: [], changed: [] };
  const mark = (r, cls) => {
    const d = document.createElement("div");
    d.className = `mk ${cls}`;
    d.style.left = P(r.bar + 0.5);
    d.style.height = `${4 + r.strength * 18}px`;
    d.title = `bar ${r.bar} · ${mmss(tOf(r.bar))} · ${Math.round(r.strength * 100)}%`;
    el.appendChild(d);
    return d;
  };
  for (const r of shown.reentries) {
    const cls = (diff.added.includes(r.bar) || diff.changed.includes(r.bar) ? "changed" : "") +
      (!proposal && selected && selected.kind === "moment" && selected.bar === r.bar ? " sel" : "");
    const d = mark(r, cls);
    if (!proposal) d.addEventListener("pointerdown", (ev) => dragMoment(ev, d, r));
  }
  for (const bar of diff.removed) mark(sheet.reentries.find((r) => r.bar === bar), "gone changed");
}

function drawWords() {
  const el = $("lane-words");
  el.innerHTML = "";
  song.lines.forEach((ln, k) => {
    const a = bOf(ln.in), b = bOf(ln.out);
    const d = document.createElement("div");
    d.className = "line" + (selected && selected.kind === "line" && selected.k === k ? " sel" : "");
    d.style.left = P(a);
    d.style.width = W(a, b);
    d.title = ln.text;
    d.addEventListener("click", () => { select({ kind: "line", k }); seek(ln.in); });
    el.appendChild(d);
  });
}

function drawSelection() {
  const band = $("selband");
  const on = selected && selected.kind === "span";
  band.hidden = !on;
  if (on) { band.style.left = P(selected.a); band.style.width = `${((selected.b - selected.a) / N) * 100}%`; }
}

// ---------------------------------------------------------------------------- the inspector

function select(s) {
  selected = s;
  tab = "sel";
  draw();
}

function drawTabs() {
  const nav = $("tabs");
  nav.innerHTML = "";
  for (const [name, ic, title] of TABS) {
    const b = document.createElement("button");
    b.className = "ib" + (tab === name ? " on" : "");
    b.innerHTML = icon(ic, 18);
    b.title = title;
    b.setAttribute("aria-label", title);
    b.addEventListener("click", () => { tab = name; drawPane(); });
    nav.appendChild(b);
  }
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function drawPane() {
  drawTabs();
  const pane = $("pane");
  pane.innerHTML = "";
  ({ sel: paneSelection, feel: paneFeel, cast: paneCast, words: paneWords, grid: paneGrid, log: paneLog })[tab](pane);
}

function shotTiles(current, onPick) {
  const grid = el(`<div class="shots"></div>`);
  for (const shot of Object.keys(song.vocabulary.shots)) {
    const t = el(`<button class="tile${shot === current ? " on" : ""}" title="${esc(song.vocabulary.shots[shot])}">${icon(shot, 22)}<span>${SHOT[shot]}</span></button>`);
    t.addEventListener("click", () => onPick(shot));
    grid.appendChild(t);
  }
  return grid;
}

function planetDots(current, onPick, enabled = true) {
  const row = el(`<div class="planets${enabled ? "" : " dim"}"></div>`);
  for (const p of song.vocabulary.planets) {
    const d = el(`<button class="dot${p === current ? " on" : ""}" title="${cap(p)}" aria-label="${cap(p)}" style="background:${PLANET_INK[p]}"></button>`);
    d.addEventListener("click", () => onPick(p));
    row.appendChild(d);
  }
  return row;
}

function paneSelection(pane) {
  if (proposal) {
    pane.appendChild(el(`<div class="empty">${icon("spark", 28)}<span>Proposal open</span></div>`));
    return;
  }
  if (!selected) {
    pane.appendChild(el(`<div class="empty">${icon("cursor", 28)}<span>Select on the timeline</span></div>`));
    return;
  }
  if (selected.kind === "act") {
    const a = sheet.acts[actAt(sheet.acts, selected.bar)];
    if (!a) { selected = null; return paneSelection(pane); }
    pane.appendChild(el(`<div class="h">${icon(a.shot, 18)}${SHOT[a.shot]}<span class="sub">${a.bars[0]}–${a.bars[1]} · ${mmss(tOf(a.bars[0]))}</span></div>`));
    const give = (shot, planet) => edit([spanEdit(a.bars[0], a.bars[1], shot, needs(shot) ? planet : null)]);
    pane.appendChild(shotTiles(a.shot, (shot) => give(shot, a.subject || spanPlanet)));
    pane.appendChild(planetDots(a.subject, (p) => give(a.shot, p), needs(a.shot)));
    return;
  }
  if (selected.kind === "section") {
    const sec = sheet.heard.sections[secAt(selected.bar)];
    if (!sec) { selected = null; return paneSelection(pane); }
    const [a, b] = sec.bars;
    pane.appendChild(el(`<div class="h">${icon("song", 18)}${esc(sec.name)}<span class="sub">${a}–${b} · ${mmss(tOf(a))}</span></div>`));
    pane.appendChild(nameField(sec.name, (name) => edit([{ op: "section", bars: [a, b], name }])));
    pane.appendChild(el(`<div class="label">Shot for these bars</div>`));
    pane.appendChild(shotTiles(null, (shot) => edit([spanEdit(a, b, shot, needs(shot) ? spanPlanet : null)])));
    pane.appendChild(planetDots(spanPlanet, (p) => { spanPlanet = p; drawPane(); }));
    const del = el(`<button class="pill" style="margin-top:14px">${icon("trash", 14)}Unname</button>`);
    del.addEventListener("click", () => edit([{ op: "section", bars: [a, b], name: "" }]).then((r) => { if (r && r.changed) { selected = null; draw(); } }));
    pane.appendChild(del);
    return;
  }
  if (selected.kind === "span") {
    const { a, b } = selected;
    pane.appendChild(el(`<div class="h">${icon("song", 18)}Bars<span class="sub">${a}–${b} · ${mmss(tOf(a))}</span></div>`));
    pane.appendChild(nameField("", (name) => edit([{ op: "section", bars: [a, b], name }]).then((r) => { if (r && r.changed) select({ kind: "section", bar: a }); })));
    pane.appendChild(el(`<div class="label">Shot</div>`));
    pane.appendChild(shotTiles(null, (shot) => edit([spanEdit(a, b, shot, needs(shot) ? spanPlanet : null)]).then((r) => { if (r && r.changed) { selected = null; draw(); } })));
    pane.appendChild(planetDots(spanPlanet, (p) => { spanPlanet = p; drawPane(); }));
    return;
  }
  if (selected.kind === "moment") {
    const r = sheet.reentries.find((x) => x.bar === selected.bar);
    if (!r) { selected = null; return paneSelection(pane); }
    pane.appendChild(el(`<div class="h">${icon("bolt", 18)}Bar ${r.bar}<span class="sub">${mmss(tOf(r.bar))}</span></div>`));
    const d = el(`<div class="dial"><div class="top"><span>Strength</span><b>${Math.round(r.strength * 100)}%</b></div>
      <input type="range" min="0.05" max="1" step="0.05" value="${r.strength}" aria-label="Strength"></div>`);
    const s = d.querySelector("input");
    s.addEventListener("input", () => (d.querySelector("b").textContent = `${Math.round(Number(s.value) * 100)}%`));
    s.addEventListener("change", () => edit([{ op: "reentry", bar: r.bar, strength: Number(s.value) }]));
    pane.appendChild(d);
    const del = el(`<button class="pill">${icon("trash", 14)}Remove</button>`);
    del.addEventListener("click", () => edit([{ op: "reentry", bar: r.bar, strength: 0 }]).then((x) => { if (x && x.changed) { selected = null; draw(); } }));
    pane.appendChild(del);
    return;
  }
  if (selected.kind === "line") {
    const ln = song.lines[selected.k];
    pane.appendChild(el(`<div class="h">${icon("text", 18)}Line ${selected.k + 1}<span class="sub">${mmss(ln.in)}</span></div>`));
    pane.appendChild(el(`<div class="quote">${esc(ln.text)}</div>`));
    pane.appendChild(el(`<div class="muted" title="${esc(song.lyrics_from || "")}">Timing: song app</div>`));
  }
}

function nameField(current, commit) {
  const box = el(`<div><div class="field"><input type="text" placeholder="Name these bars" maxlength="40" aria-label="Name"></div><div class="chips"></div></div>`);
  const input = box.querySelector("input");
  input.value = current;
  const go = (name) => { if (name.trim() && name.trim() !== current) commit(name.trim()); };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(input.value); if (e.key === "Escape") input.blur(); });
  input.addEventListener("change", () => go(input.value));
  for (const n of NAMES) {
    const c = el(`<button class="chip">${n}</button>`);
    c.addEventListener("click", () => {
      const same = sheet.heard.sections.filter((x) => x.name.replace(/ \d+$/, "") === n).length;
      go(same ? `${n} ${same + 1}` : n);
    });
    box.querySelector(".chips").appendChild(c);
  }
  return box;
}

function paneGrid(pane) {
  const h = sheet.heard, fixed = h.tempo_times !== 1 || h.meter !== null || h.bar_one !== 0;
  const how = song.grid.source === "lattice" ? `found on the beat to ${Math.round((song.grid.sure || 0) * 100)}%` : "followed by ear";
  pane.appendChild(el(`<div class="h">${icon("metronome", 18)}Grid<span class="sub" title="how the beat was found">${fixed ? "corrected" : how}</span></div>`));
  const grid = (e) => edit([{ op: "grid", ...e }]);
  const row = (label, left, value, right) => {
    const r = el(`<div><div class="label">${label}</div><div class="stepper"><button class="ib"></button><span class="v"></span><button class="ib"></button></div></div>`);
    const [l, rt] = r.querySelectorAll("button");
    l.innerHTML = icon("left", 16); rt.innerHTML = icon("right", 16);
    r.querySelector(".v").textContent = value;
    if (left) l.addEventListener("click", left); else l.disabled = true;
    if (right) rt.addEventListener("click", right); else rt.disabled = true;
    return r;
  };
  const t = h.tempo_times;
  pane.appendChild(row("Tempo", t > 0.5 ? () => grid({ tempo_times: t / 2 }) : null, `${Math.round(song.tempo)} BPM`,
    t < 2 ? () => grid({ tempo_times: t * 2 }) : null));
  const m = el(`<div><div class="label">Beats in a bar</div><div class="chips"></div></div>`);
  for (const k of [2, 3, 4, 5, 6, 7]) {
    const c = el(`<button class="chip${k === song.meter ? " on" : ""}">${k}</button>`);
    c.addEventListener("click", () => { if (k !== song.meter) grid({ meter: k }); });
    m.querySelector(".chips").appendChild(c);
  }
  pane.appendChild(m);
  pane.appendChild(row("Bar 1", h.bar_one > -7 ? () => grid({ bar_one: h.bar_one - 1 }) : null,
    h.bar_one ? `${h.bar_one > 0 ? "+" : ""}${h.bar_one} beat${Math.abs(h.bar_one) === 1 ? "" : "s"}` : "as heard",
    h.bar_one < 7 ? () => grid({ bar_one: h.bar_one + 1 }) : null));
  if (fixed) {
    const reset = el(`<button class="pill" style="margin-top:14px">${icon("undo", 14)}As heard</button>`);
    reset.addEventListener("click", () => grid({ tempo_times: 1, meter: null, bar_one: 0 }));
    pane.appendChild(reset);
  }
  pane.appendChild(el(`<div class="muted small">Turn on the click (${icon("metronome", 12).replace('class="ic"', 'class="ic" style="display:inline;vertical-align:-2px"')}) to hear the grid. A change listens again and makes the shots anew.</div>`));
}

function dial(k, spec, value, commit) {
  const [name, unit] = DIAL[k] || [k, ""];
  const range = spec.high - spec.low;
  const step = k === "size" ? 0.001 : range > 100 ? 8 : range > 10 ? 0.5 : range > 1 ? 0.05 : 0.01;
  const fmt = (v) => (range > 100 ? String(Math.round(v)) : range > 10 ? String(Number(v)) :
    Number(v).toFixed(k === "size" ? 3 : 2)) + (unit ? ` ${unit}` : "");
  const d = el(`<div class="dial${value !== spec.default ? " moved" : ""}" title="${esc(spec.what)}"><div class="top"><span>${name}</span><b>${fmt(value)}</b></div>
    <input type="range" min="${spec.low}" max="${spec.high}" step="${step}" value="${value}" aria-label="${name}"></div>`);
  const s = d.querySelector("input");
  s.addEventListener("input", () => (d.querySelector("b").textContent = fmt(Number(s.value))));
  s.addEventListener("change", () => commit(Number(s.value)));
  return d;
}

function paneFeel(pane) {
  pane.appendChild(el(`<div class="h">${icon("sliders", 18)}Feel</div>`));
  for (const [k, spec] of Object.entries(song.vocabulary.feel)) {
    pane.appendChild(dial(k, spec, sheet.feel[k], (v) => edit([{ op: "feel", dial: k, value: v }])));
  }
}

function paneCast(pane) {
  pane.appendChild(el(`<div class="h">${icon("mic", 18)}Cast</div>`));
  for (const [part, what] of Object.entries(song.vocabulary.parts)) {
    const d = el(`<div class="part"><div class="name" title="${esc(what)}">${cap(part)}</div><div class="chips"></div></div>`);
    for (const c of song.vocabulary.choices[part]) {
      const b = el(`<button class="chip${c === sheet.cast[part] ? " on" : ""}">${c.replace(/-/g, " ")}</button>`);
      b.addEventListener("click", () => edit([{ op: "cast", part, choice: c }]));
      d.querySelector(".chips").appendChild(b);
    }
    pane.appendChild(d);
  }
}

function paneWords(pane) {
  const lx = sheet.lyrics;
  const h = el(`<div class="h">${icon("text", 18)}Words<button class="ib" style="margin-left:auto" title="${lx.show ? "Hide" : "Show"} the words">${icon(lx.show ? "eye" : "eyeoff", 18)}</button></div>`);
  h.querySelector("button").addEventListener("click", () => edit([{ op: "lyrics", key: "show", value: !lx.show }]));
  pane.appendChild(h);
  const tools = el(`<div class="row" style="margin-bottom:12px"><a class="pill" href="http://127.0.0.1:8420/" target="_blank" rel="noopener" title="Word timing is edited in the song app (python -m song)">${icon("out", 14)}Timing</a>
    <button class="pill" title="Read the words again, after changing them in the song app">${icon("refresh", 14)}Reload</button></div>`);
  tools.querySelector("button").addEventListener("click", async () => {
    const r = await change("/api/refresh", {});
    if (r) { song = r.song; draw(); }
  });
  pane.appendChild(tools);
  const px = Math.round(Math.min(Math.max(lx.size * 560, 11), 30));
  pane.appendChild(el(`<div class="preview" style="font-size:${px}px">
    <span style="opacity:${lx.sung}">light</span> <span style="opacity:${lx.peak}">breaks</span> <span style="opacity:${lx.unsung}">through</span></div>`));
  for (const [k, spec] of Object.entries(song.vocabulary.lyrics)) {
    if (typeof spec.default === "boolean") continue;
    pane.appendChild(dial(k, spec, lx[k], (v) => edit([{ op: "lyrics", key: k, value: v }])));
  }
}

// One change, as a person reads it: what kind of thing (its icon), where, what it was and
// what it is now. The same for a hand's edit, the AI's, and a proposal not yet applied.
const KIND_ICON = { shot: "camera", section: "song", moment: "bolt", cast: "mic", feel: "sliders", words: "text", grid: "metronome" };
function changeRow(c) {
  const where = c.bars ? `${c.bars[0]}–${c.bars[1]}` : c.bar !== undefined ? `bar ${c.bar}` : "";
  const row = el(`<div class="chg">${icon(KIND_ICON[c.kind] || "cursor", 14)}<span class="t">${esc(c.title)}</span>
    <span class="was">${esc(c.before)}</span>${icon("right", 12)}<span class="now">${esc(c.after)}</span>
    ${where ? `<span class="where">${where}</span>` : ""}</div>`);
  if (c.bars || c.bar !== undefined) {
    const [a, b] = c.bars || [c.bar, c.bar + 1];
    row.addEventListener("mouseenter", () => hoverBars(a, b));
    row.addEventListener("mouseleave", () => hoverBars(null));
  }
  return row;
}

function hoverBars(a, b) {
  const band = $("hoverband");
  band.hidden = a === null;
  if (a !== null) { band.style.left = P(a); band.style.width = `${((b - a) / N) * 100}%`; }
}

function paneLog(pane) {
  pane.appendChild(el(`<div class="h">${icon("clock", 18)}History<span class="sub">${at} of ${history.length - 1}</span></div>`));
  const list = el(`<div class="hist"></div>`);
  history.map((h, k) => [h, k]).reverse().forEach(([h, k]) => {
    const who = h.source === "ask" ? ["spark", "AI"] : h.source === "open" ? ["check", "Opened"] : ["cursor", "You"];
    const card = el(`<div class="card${k === at ? " now" : k > at ? " ahead" : ""}" title="${k === at ? "Where you are" : "Go back to here"}">
      <div class="who">${icon(who[0], 14)}<span>${who[1]}</span>${h.request ? `<q>${esc(h.request)}</q>` : ""}<span class="when">${h.at || ""}</span></div></div>`);
    for (const c of h.changes) card.appendChild(changeRow(c));
    if (h.source === "open") card.appendChild(el(`<div class="chg muted">The video as the director made it</div>`));
    card.addEventListener("click", () => goTo(k));
    list.appendChild(card);
  });
  pane.appendChild(list);
}

// ---------------------------------------------------------------------------- gestures

function barAtPointer(ev) {
  const r = $("tracks").getBoundingClientRect();
  return Math.min(Math.max(((ev.clientX - r.left) / r.width) * N, 0), N);
}

function dragEdge(ev, e, i) {
  if (busy) return;
  ev.preventDefault(); ev.stopPropagation();
  e.setPointerCapture(ev.pointerId);
  e.classList.add("drag");
  const tip = document.createElement("span");
  tip.className = "tip";
  e.appendChild(tip);
  let to = sheet.acts[i].bars[1];
  const move = (m) => {
    to = Math.min(Math.max(Math.round(barAtPointer(m)), sheet.acts[i].bars[0] + 1), sheet.acts[i + 1].bars[1] - 1);
    e.style.left = P(to);
    tip.textContent = `${to} · ${mmss(tOf(to))}`;
  };
  const up = () => {
    e.removeEventListener("pointermove", move);
    e.removeEventListener("pointerup", up);
    edit(edgeEdits(sheet.acts, i, to));
  };
  e.addEventListener("pointermove", move);
  e.addEventListener("pointerup", up);
}

function dragSectionEdge(ev, e, sec, side) {
  if (busy) return;
  ev.preventDefault(); ev.stopPropagation();
  e.setPointerCapture(ev.pointerId);
  e.classList.add("drag");
  const tip = document.createElement("span");
  tip.className = "tip";
  e.appendChild(tip);
  let to = side === "start" ? sec.bars[0] : sec.bars[1];
  const move = (m) => {
    to = Math.round(barAtPointer(m));
    to = side === "start" ? Math.min(Math.max(to, 0), sec.bars[1] - 1) : Math.max(Math.min(to, N), sec.bars[0] + 1);
    e.style.left = P(to);
    tip.textContent = `${to} · ${mmss(tOf(to))}`;
  };
  const up = () => {
    e.removeEventListener("pointermove", move);
    e.removeEventListener("pointerup", up);
    edit(sectionEdgeEdits(sec, side, to, N));
  };
  e.addEventListener("pointermove", move);
  e.addEventListener("pointerup", up);
}

function dragMoment(ev, d, r) {
  if (busy) return;
  ev.preventDefault(); ev.stopPropagation();
  d.setPointerCapture(ev.pointerId);
  const x0 = ev.clientX;
  let to = r.bar, moved = false;
  const move = (m) => {
    if (Math.abs(m.clientX - x0) > 3) moved = true;
    if (!moved) return;
    to = Math.min(Math.max(Math.round(barAtPointer(m) - 0.5), 1), N - 1);
    d.style.left = P(to + 0.5);
  };
  const up = () => {
    d.removeEventListener("pointermove", move);
    d.removeEventListener("pointerup", up);
    if (!moved) { select({ kind: "moment", bar: r.bar }); seek(tOf(r.bar) - 2); return; }
    edit(momentEdits(r, to)).then((x) => { if (x && x.changed) select({ kind: "moment", bar: to }); });
  };
  d.addEventListener("pointermove", move);
  d.addEventListener("pointerup", up);
}

// Across the ruler, Song or Energy: a drag picks bars, a click plays from there.
function pickBars(ev) {
  if (proposal || ev.button !== 0) return;
  const lane = ev.currentTarget;
  lane.setPointerCapture(ev.pointerId);
  const x0 = ev.clientX, b0 = barAtPointer(ev);
  let dragged = false;
  const move = (m) => {
    if (Math.abs(m.clientX - x0) > 4) dragged = true;
    if (!dragged) return;
    const b1 = barAtPointer(m);
    const a = Math.floor(Math.min(b0, b1));
    selected = { kind: "span", a, b: Math.max(Math.ceil(Math.max(b0, b1)), a + 1) };
    drawSelection();
  };
  const up = (m) => {
    lane.removeEventListener("pointermove", move);
    lane.removeEventListener("pointerup", up);
    if (!dragged) { seek(tOf(barAtPointer(m))); return; }
    tab = "sel";
    draw();
  };
  lane.addEventListener("pointermove", move);
  lane.addEventListener("pointerup", up);
}

// ---------------------------------------------------------------------------- asking

function closeProposal() {
  proposal = null;
  $("proposal").hidden = true;
  draw();
}

// Where the person is, for the AI's "this" and "here": the selection, and the playhead.
function focus() {
  const f = { playhead: Math.min(Math.floor(bOf(now())), N - 1) };
  if (!selected) return f;
  if (selected.kind === "span") f.bars = [selected.a, selected.b];
  else if (selected.kind === "section") { const s = sheet.heard.sections[secAt(selected.bar)]; if (s) f.bars = s.bars; }
  else if (selected.kind === "act") { const a = sheet.acts[actAt(sheet.acts, selected.bar)]; if (a) f.bars = a.bars; }
  else if (selected.kind === "moment") f.bar = selected.bar;
  return f;
}

async function ask() {
  const request = $("ask").value.trim();
  if (!request) { $("ask").focus(); return; }
  if (busy || !song) return;
  busy = true;
  $("askbox").classList.add("thinking");
  status(song.model, "busy");
  const model = $("model").value || song.model;
  let loading = false;
  try { loading = !(await (await fetch("/api/models")).json()).loaded.includes(model); } catch (e) { /* asked anyway */ }
  const t0 = performance.now();
  const tick = setInterval(() => {
    const s = Math.round((performance.now() - t0) / 1000);
    status(loading && s < 25 ? `loading ${model}… ${s} s` : `${model} thinking… ${s} s`, "busy");
  }, 500);
  let r;
  try { r = await call("/api/ask", { request, focus: focus(), model }); } catch (e) { r = { ok: false, refused: [String(e)] }; }
  clearInterval(tick);
  busy = false;
  $("askbox").classList.remove("thinking");
  status(r.ok ? `${r.seconds} s` : "no answer", r.ok ? "" : "bad");
  const pop = $("proposal");
  if (!r.ok) { toast(r.refused); return; }
  if (!r.proposes) {
    pop.className = "pop";
    pop.innerHTML = `<div class="said">${esc(r.already ? "Already so." : r.said || "Nothing to change.")}</div>
      <div class="acts"><button class="pill" id="discard">${icon("check", 14)}OK</button></div>`;
    pop.hidden = false;
    $("discard").addEventListener("click", closeProposal);
    return;
  }
  proposal = { ...r, request };
  pop.className = "pop";
  pop.innerHTML = `<div class="said">${icon("spark", 14)}<span>${esc(r.said)}</span></div><div class="rows"></div>
    <div class="acts"><button class="pill" id="discard">${icon("x", 14)}Discard</button><button class="pill go" id="accept">${icon("check", 14)}Apply</button></div>`;
  for (const c of r.changes) pop.querySelector(".rows").appendChild(changeRow(c));
  pop.hidden = false;
  $("accept").addEventListener("click", async () => {
    const p = proposal;
    closeProposal();
    await edit(p.edits, "ask", p.request);
    $("ask").value = "";
  });
  $("discard").addEventListener("click", closeProposal);
  draw();
}

function showFacts() {
  $("facts").textContent = `${Math.round(song.tempo)} BPM · ${song.meter}/${song.meter > 4 ? 8 : 4} · ${N} bars · ${mmss(song.duration)}`;
  $("facts").title = `sheet: ${song.sheet_path}`;
}

// A click on every beat, higher on the first of each bar: the way to hear whether the grid
// is the song's. Played from here, as the playhead crosses each beat.
let clickOn = false, audioCtx = null, clickedTo = 0;
function click(first) {
  const t = audioCtx.currentTime, o = audioCtx.createOscillator(), g = audioCtx.createGain();
  o.frequency.value = first ? 1760 : 1175;
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(first ? 0.5 : 0.3, t + 0.002);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.05);
  o.connect(g).connect(audioCtx.destination);
  o.start(t); o.stop(t + 0.06);
}
function clicks(t, playing) {
  if (!clickOn || !playing || t < clickedTo || t - clickedTo > 0.25) { clickedTo = t; return; }
  for (const b of song.beats) {
    if (b > clickedTo && b <= t) {
      const first = song.bar_t.some((x) => Math.abs(x - b) < 0.02);
      click(first);
    }
  }
  clickedTo = t;
}

// ---------------------------------------------------------------------------- adding a song
//
// A song is added from the picker's last choice or by dropping its audio (and its lyrics,
// a .txt) anywhere on the page. The server makes it in the background, one song at a
// time; the page asks how it is going every 2 s while something is being made, and when
// a song this page asked for is ready, offers to open it.

const ADD = "+add";
const nameOf = (slug) => slug.replace(/-/g, " ").replace(/^./, (c) => c.toUpperCase());
let audioTypes = [], songList = [];
const isAudio = (f) => audioTypes.some((x) => f.name.toLowerCase().endsWith(x));
const isWords = (f) => f.name.toLowerCase().endsWith(".txt");

function fillSongs(want) {
  const sel = $("songs");
  sel.innerHTML = "";
  if (!songList.length) sel.add(new Option("No songs yet", "", true, true));
  for (const s of songList) sel.add(new Option(nameOf(s), s, false, s === want));
  sel.add(new Option("Add a song…", ADD));
  if (sel.options[0].value === "") sel.options[0].disabled = true;
}

// A small card over the picture that waits for an answer (the toast's place, without its timer).
function offer(text, acts) {
  clearTimeout(toastTimer);
  const t = $("toast");
  t.innerHTML = `<div class="pop" style="position:static;width:auto"><div class="said">${icon("song", 14)}<span>${esc(text)}</span></div>
    <div class="acts"></div></div>`;
  for (const [label, ic, go, fn] of acts) {
    const b = el(`<button class="pill${go ? " go" : ""}">${icon(ic, 14)}${label}</button>`);
    b.addEventListener("click", () => { t.hidden = true; fn(); });
    t.querySelector(".acts").appendChild(b);
  }
  t.hidden = false;
}

// Files picked or dropped: the audio, and its lyrics if they came with it; if they did not,
// asked for (a second file picker needs a click of its own).
function addFiles(files) {
  const audio = files.find(isAudio), words = files.find(isWords);
  if (!audio) { toast([`Not a song: the studio reads ${audioTypes.join(" ")}`]); return; }
  if (words) { upload(audio, words); return; }
  offer(audio.name, [
    ["Cancel", "x", false, () => {}],
    ["Lyrics…", "text", false, () => { pickLyrics = (w) => upload(audio, w); $("picklyrics").click(); }],
    ["Add", "check", true, () => upload(audio, null)],
  ]);
}
let pickLyrics = null;

function pickAudio() {
  if (navigator.userActivation && !navigator.userActivation.isActive) {      // too long since the click: ask for one
    offer("Add a song", [["Cancel", "x", false, () => {}], ["Choose a file", "plus", true, () => $("pickaudio").click()]]);
  } else {
    $("pickaudio").click();
  }
}

const jobState = {}, mine = new Set();
let jobsTimer = 0, jobsTick = 0;

async function upload(audio, words) {
  status(`adding ${audio.name}…`, "busy");
  const form = new FormData();
  form.append("audio", audio);
  if (words) form.append("lyrics", words);
  let r;
  try { r = await (await fetch("/api/import", { method: "POST", body: form })).json(); } catch (e) { r = { ok: false, refused: [String(e)] }; }
  if (!r.ok) { status("not added", "bad"); toast(r.refused); return; }
  mine.add(r.job.id);
  jobState[r.job.id] = r.job.state;
  watchJobs();
}

// Asked every 2 s while a song is being made, and not otherwise.
async function watchJobs() {
  clearTimeout(jobsTimer);
  let jobs;
  try { jobs = (await (await fetch("/api/jobs")).json()).jobs; } catch (e) { jobsTimer = setTimeout(watchJobs, 2000); return; }
  for (const j of jobs) {
    const was = jobState[j.id];
    jobState[j.id] = j.state;
    if (was && was !== j.state && (j.state === "done" || j.state === "failed")) finished(j);
  }
  const live = jobs.filter((j) => j.state === "queued" || j.state === "running");
  clearInterval(jobsTick);
  if (!live.length) return;
  const run = live.find((j) => j.state === "running") || live[0], t0 = performance.now();
  const show = () => {
    if (busy) return;                                   // an edit is saying something: it goes first
    const s = run.seconds + (run.state === "running" ? (performance.now() - t0) / 1000 : 0);
    const more = live.length > 1 ? ` (+${live.length - 1})` : "";
    status(`${nameOf(run.song)} · ${run.step} ${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}${more}`, "busy");
    $("status").title = run.log.length ? run.log[run.log.length - 1] : "";
  };
  show();
  jobsTick = setInterval(show, 1000);
  jobsTimer = setTimeout(watchJobs, 2000);
}

async function finished(j) {
  const was = $("songs").value;
  try { songList = (await (await fetch("/api/songs")).json()).songs; } catch (e) { /* the list stays as it was */ }
  fillSongs(was);
  $("status").title = "";
  if (!mine.has(j.id)) return;
  if (j.state === "failed") { status("not added", "bad"); toast([`${nameOf(j.song)}: ${j.error}`]); return; }
  status(`added in ${Math.floor(j.seconds / 60)}:${String(Math.round(j.seconds % 60)).padStart(2, "0")}`);
  const open = () => { location.search = `?track=${encodeURIComponent(j.song)}`; };
  if (!song) { open(); return; }                        // nothing open here: open it
  offer(`${nameOf(j.song)} is ready`, [["Later", "x", false, () => {}], ["Open", "out", true, open]]);
}

function setUpAdding() {
  $("pickaudio").accept = [...audioTypes, ".txt"].join(",");
  $("pickaudio").addEventListener("change", (e) => { const f = [...e.target.files]; e.target.value = ""; if (f.length) addFiles(f); });
  $("picklyrics").addEventListener("change", (e) => {
    const w = e.target.files[0];
    e.target.value = "";
    if (w && pickLyrics) pickLyrics(w);
    pickLyrics = null;
  });
  // a file dragged over the page: the whole page takes it, the picture too
  const files = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
  const on = (e) => { if (files(e)) { e.preventDefault(); document.body.classList.add("dropping"); } };
  window.addEventListener("dragenter", on);
  window.addEventListener("dragover", (e) => { on(e); if (files(e)) e.dataTransfer.dropEffect = "copy"; });
  window.addEventListener("dragleave", (e) => { if (!e.relatedTarget) document.body.classList.remove("dropping"); });
  window.addEventListener("drop", (e) => {
    document.body.classList.remove("dropping");
    if (!files(e)) return;
    e.preventDefault();
    addFiles([...e.dataTransfer.files]);
  });
  frame.addEventListener("load", () => {
    try { for (const k of ["dragenter", "dragover"]) frame.contentWindow.addEventListener(k, on); } catch (e) { /* not ours */ }
  });
}

// ---------------------------------------------------------------------------- start

async function main() {
  $("askicon").innerHTML = icon("spark", 16);
  $("askbtn").innerHTML = icon("check", 16);
  $("undo").innerHTML = icon("undo", 18);
  $("redo").innerHTML = icon("redo", 18);
  $("play").innerHTML = icon("play", 18);
  $("lyr").innerHTML = icon("eye", 18);
  $("addmoment").innerHTML = icon("plus", 12);
  const labels = $("labels").children;
  [["song", 16], ["wave", 16], ["camera", 16], ["bolt", 16], ["text", 14]].forEach(([n, s], i) => labels[i].insertAdjacentHTML("afterbegin", icon(n, s)));
  $("zoom").innerHTML = `<button class="ib" id="zout" aria-label="Zoom out" title="Zoom out">${icon("zoomout", 16)}</button>` +
    `<button class="ib" id="zin" aria-label="Zoom in" title="Zoom in">${icon("zoomin", 16)}</button>`;

  // the models on this machine; the one last used is kept
  fetch("/api/models").then((r) => r.json()).then((m) => {
    let keep = null;
    try { keep = localStorage.getItem("studio.model"); } catch (e) { /* private window */ }
    const pick = m.installed.includes(keep) ? keep : m.default;
    for (const name of m.installed.length ? m.installed : [m.default]) $("model").add(new Option(name.replace(/:latest$/, ""), name, false, name === pick));
    $("model").addEventListener("change", () => { try { localStorage.setItem("studio.model", $("model").value); } catch (e) { /* fine */ } });
  });
  const list = await (await fetch("/api/songs")).json();
  songList = list.songs;
  audioTypes = list.audio;
  const want = params.get("track") || songList[0];
  fillSongs(want);
  $("songs").addEventListener("change", () => {
    if ($("songs").value !== ADD) { location.search = `?track=${encodeURIComponent($("songs").value)}`; return; }
    $("songs").value = song ? song.slug : "";
    pickAudio();
  });
  setUpAdding();
  watchJobs();
  if (!songList.length) {
    $("undo").disabled = $("redo").disabled = true;
    $("pane").appendChild(el(`<div class="empty">${icon("song", 28)}<span>No songs yet</span><span>Add one from the list, or drop it here</span></div>`));
    return;
  }
  status("opening…", "busy");
  const res = await fetch(`/api/song?track=${encodeURIComponent(want)}`);
  const got = await res.json();
  if (!res.ok) { status(got.refused ? got.refused[0] : "no song", "bad"); return; }
  song = got;
  sheet = song.sheet;
  N = song.bar_t.length;
  history = song.history;
  at = song.at;
  document.title = `${$("songs").selectedOptions[0].text} · Studio`;
  showFacts();
  // an example in the placeholder, in this song's own terms
  const named = sheet.heard.sections;
  const choruses = named.filter((s) => /^(final )?chorus/i.test(s.name));
  const last = choruses[1] || choruses[0] || named[1] || named[0];
  $("ask").placeholder = last ? `Close on Saturn in ${last.name.toLowerCase()}` : `Close on Jupiter from bar ${Math.round(N / 3)} to ${Math.round(N / 2)}`;

  frame.src = `/player/?track=${encodeURIComponent(song.bundle)}&embed=1${params.get("t") ? `&t=${params.get("t")}` : ""}`;
  const ready = () => (player() ? drawTransport() : setTimeout(ready, 200));
  frame.addEventListener("load", ready);

  for (const id of ["ruler", "lane-song", "lane-energy"]) $(id).addEventListener("pointerdown", pickBars);
  $("askbtn").addEventListener("click", (e) => { e.preventDefault(); ask(); });
  $("ask").addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); if (e.key === "Escape") $("ask").blur(); });
  $("undo").addEventListener("click", () => goTo(at - 1));
  $("redo").addEventListener("click", () => goTo(at + 1));
  $("play").addEventListener("click", playPause);
  $("lyr").addEventListener("click", () => { const p = player(); if (p) { p.setLyrics(!p.lyrics); syncTransport(); } });
  $("export").innerHTML = icon("download", 18);
  $("export").addEventListener("click", openExport);
  $("click").innerHTML = icon("metronome", 18);
  $("click").addEventListener("click", () => {
    audioCtx = audioCtx || new AudioContext();
    clickOn = !clickOn;
    $("click").classList.toggle("on", clickOn);
  });
  $("addmoment").addEventListener("click", () => {
    const bar = Math.min(Math.max(Math.round(bOf(now())), 1), N - 1);
    edit([{ op: "reentry", bar, strength: 0.7 }]).then((r) => { if (r && r.changed) select({ kind: "moment", bar }); });
  });
  const zoomTo = (z) => {
    const sc = $("scroll"), mid = (sc.scrollLeft + sc.clientWidth / 2) / sc.scrollWidth;
    zoom = Math.min(Math.max(z, 1), 12);
    draw();
    sc.scrollLeft = mid * sc.scrollWidth - sc.clientWidth / 2;
  };
  $("zin").addEventListener("click", () => zoomTo(zoom * 1.6));
  $("zout").addEventListener("click", () => zoomTo(zoom / 1.6));
  $("scroll").addEventListener("wheel", (e) => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); zoomTo(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)); } }, { passive: false });

  window.addEventListener("keydown", (e) => {
    if (e.target instanceof HTMLInputElement && e.target.type === "text") return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); goTo(e.shiftKey ? at + 1 : at - 1); }
    else if (e.code === "Space") { e.preventDefault(); playPause(); }
    else if (e.key === "Escape") { $("exportpop").hidden = true; if (proposal) closeProposal(); else { selected = null; draw(); } }
  });

  // the split between the picture and the timeline
  $("split").addEventListener("pointerdown", (e) => {
    const s = $("split");
    s.setPointerCapture(e.pointerId);
    const move = (m) => {
      const h = Math.min(Math.max(window.innerHeight - m.clientY - 3, 150), window.innerHeight * 0.7);
      document.documentElement.style.setProperty("--tl", `${h}px`);
    };
    const up = () => { s.removeEventListener("pointermove", move); s.removeEventListener("pointerup", up); drawEnergy(); };
    s.addEventListener("pointermove", move);
    s.addEventListener("pointerup", up);
  });
  new ResizeObserver(() => { drawEnergy(); drawRuler(); }).observe($("scroll"));

  // the playhead and the clock follow the song; the view follows the playhead while it plays
  const head = $("playhead");
  let wasPlaying = null;
  const follow = () => {
    const t = now(), p = player();
    head.style.left = P(bOf(t));
    $("clock").innerHTML = `${clockOf(t)} <span class="of">/ ${mmss(song.duration)}</span>`;
    const playing = !!(p && !p.audio.paused);
    if (playing !== wasPlaying) { $("play").innerHTML = icon(playing ? "pause" : "play", 18); wasPlaying = playing; }
    clicks(t, playing);
    if (playing && zoom > 1) {
      const sc = $("scroll"), x = head.offsetLeft;
      if (x < sc.scrollLeft || x > sc.scrollLeft + sc.clientWidth - 40) sc.scrollLeft = x - sc.clientWidth * 0.2;
    }
    requestAnimationFrame(follow);
  };
  requestAnimationFrame(follow);

  draw();
  status("");
  // an mp4 being written, or written, while this server has run (the page opened again): its progress, or the file
  fetch(exportUrl()).then((r) => r.json()).then((q) => { if (q.job && q.job.state !== "failed") watchExport(q.job); });
}

main().catch((e) => status(String(e), "bad"));
