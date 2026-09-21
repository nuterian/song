// The studio page: one screen, as an editing suite is - the picture, an inspector beside
// it, the song along the bottom on a timeline in bars. Every change is sent to the server
// as edits in the direction sheet's own vocabulary (timeline.js makes them from gestures;
// the local model makes them from words). The server checks, bakes and keeps; the player
// takes the new bake without stopping.

import { barOf, timeOf, edgeEdits, spanEdit, momentEdits, changedActs, changedMoments } from "./timeline.js";
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
const TABS = [["sel", "cursor", "Selection"], ["feel", "sliders", "Feel"], ["cast", "mic", "Cast"], ["words", "text", "Words"], ["log", "clock", "Changes"]];

let song = null, sheet = null, N = 0;
let history = [], at = 0;
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
async function change(path, body) {
  if (busy) { status("baking…", "busy"); return null; }
  busy = true;
  status("baking…", "busy");
  let r;
  try { r = await call(path, body); } catch (e) { r = { ok: false, refused: [String(e)] }; }
  busy = false;
  if (!r.ok) { status("not changed", "bad"); toast(r.refused); return null; }
  if (!r.changed) { status("no change"); return r; }
  sheet = r.sheet;
  status(`${r.seconds.toFixed(1)} s`);
  if (player()) await player().reload();
  return r;
}

async function edit(edits, source = "hand", request = null) {
  if (!edits.length) { draw(); return null; }
  const r = await change("/api/edit", { edits, source, request });
  if (r && r.changed) remember(r.sheet, r.did.join(" · "), source);
  draw();
  return r;
}

function remember(s, label, source) {
  history = history.slice(0, at + 1);
  history.push({ sheet: s, label, source });
  at = history.length - 1;
}

async function goTo(k) {
  if (k < 0 || k >= history.length || k === at) return;
  const r = await change("/api/sheet", { sheet: history[k].sheet, why: k < at ? "undo" : "redo" });
  if (r) at = k;
  draw();
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
  $("lyr").hidden = p.lyrics === null;
  syncTransport();
}

function syncTransport() {
  const p = player();
  if (!p) return;
  const cam = p.chosen.camera;
  for (const b of $("cams").children) b.classList.toggle("on", b.dataset.name === cam);
  $("lyr").innerHTML = icon(p.lyrics ? "eye" : "eyeoff", 18);
  $("lyr").classList.toggle("on", !!p.lyrics);
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

function drawSections() {
  const el = $("lane-song");
  el.innerHTML = "";
  for (const s of song.sections) {
    const [a, b] = s.bars;
    const on = selected && selected.kind === "span" && selected.a === a && selected.b === b;
    const d = block(el, "sec" + (on ? " sel" : ""), a, b, esc(s.name), `${s.name} · bars ${a}–${b} · ${mmss(tOf(a))}`);
    d.addEventListener("pointerdown", (e) => e.stopPropagation());
    d.addEventListener("click", () => { select({ kind: "span", a, b, name: s.name }); seek(tOf(a)); });
  }
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
  ({ sel: paneSelection, feel: paneFeel, cast: paneCast, words: paneWords, log: paneLog })[tab](pane);
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
  if (selected.kind === "span") {
    const { a, b } = selected;
    pane.appendChild(el(`<div class="h">${icon("song", 18)}${esc(selected.name || "Bars")}<span class="sub">${a}–${b} · ${mmss(tOf(a))}</span></div>`));
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
  const px = Math.round(Math.min(Math.max(lx.size * 560, 11), 30));
  pane.appendChild(el(`<div class="preview" style="font-size:${px}px">
    <span style="opacity:${lx.sung}">light</span> <span style="opacity:${lx.peak}">breaks</span> <span style="opacity:${lx.unsung}">through</span></div>`));
  for (const [k, spec] of Object.entries(song.vocabulary.lyrics)) {
    if (typeof spec.default === "boolean") continue;
    pane.appendChild(dial(k, spec, lx[k], (v) => edit([{ op: "lyrics", key: k, value: v }])));
  }
}

function paneLog(pane) {
  pane.appendChild(el(`<div class="h">${icon("clock", 18)}Changes</div>`));
  const ol = el(`<ol class="log"></ol>`);
  history.map((h, k) => [h, k]).reverse().forEach(([h, k]) => {
    const ic = h.source === "ask" ? "spark" : k === 0 ? "check" : "cursor";
    const li = el(`<li class="${k === at ? "now" : k > at ? "ahead" : ""}">${icon(ic, 14)}<span>${esc(h.label)}</span></li>`);
    li.addEventListener("click", () => goTo(k));
    ol.appendChild(li);
  });
  pane.appendChild(ol);
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

async function ask() {
  const request = $("ask").value.trim();
  if (!request) { $("ask").focus(); return; }
  if (busy) return;
  busy = true;
  $("askbox").classList.add("thinking");
  status(song.model, "busy");
  let r;
  try { r = await call("/api/ask", { request }); } catch (e) { r = { ok: false, refused: [String(e)] }; }
  busy = false;
  $("askbox").classList.remove("thinking");
  status(r.ok ? `${r.seconds} s` : "no answer", r.ok ? "" : "bad");
  const pop = $("proposal");
  if (!r.ok) { toast(r.refused); return; }
  if (!r.changes) {
    pop.className = "pop";
    pop.innerHTML = `<div class="said">${esc(r.already ? "Already so." : r.said || "Nothing to change.")}</div>
      <div class="acts"><button class="pill" id="discard">${icon("check", 14)}OK</button></div>`;
    pop.hidden = false;
    $("discard").addEventListener("click", closeProposal);
    return;
  }
  proposal = { ...r, request };
  pop.className = "pop";
  pop.innerHTML = `<div class="said">${esc(r.said)}</div><ul>${r.did.map((x) => `<li>${icon("spark", 14)}<span>${esc(x)}</span></li>`).join("")}</ul>
    <div class="acts"><button class="pill" id="discard">${icon("x", 14)}Discard</button><button class="pill go" id="accept">${icon("check", 14)}Apply</button></div>`;
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

  const list = await (await fetch("/api/songs")).json();
  const want = params.get("track") || list.songs[0];
  for (const s of list.songs) $("songs").add(new Option(s.replace(/-/g, " ").replace(/^./, (c) => c.toUpperCase()), s, false, s === want));
  $("songs").addEventListener("change", () => { location.search = `?track=${encodeURIComponent($("songs").value)}`; });
  const res = await fetch(`/api/song?track=${encodeURIComponent(want)}`);
  song = await res.json();
  if (!res.ok) { status(song.refused ? song.refused[0] : "no song", "bad"); return; }
  sheet = song.sheet;
  N = song.bar_t.length;
  history = [{ sheet, label: "As made", source: "made" }];
  at = 0;
  document.title = `${$("songs").selectedOptions[0].text} · Studio`;
  $("facts").textContent = `${Math.round(song.tempo)} BPM · ${song.meter}/4 · ${N} bars · ${mmss(song.duration)}`;
  $("facts").title = `sheet: ${song.sheet_path}`;
  // an example in the placeholder, in this song's own terms
  const last = song.sections.find((s) => /chorus/i.test(s.name)) || song.sections[0];
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
    else if (e.key === "Escape") { if (proposal) closeProposal(); else { selected = null; draw(); } }
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
    if (playing && zoom > 1) {
      const sc = $("scroll"), x = head.offsetLeft;
      if (x < sc.scrollLeft || x > sc.scrollLeft + sc.clientWidth - 40) sc.scrollLeft = x - sc.clientWidth * 0.2;
    }
    requestAnimationFrame(follow);
  };
  requestAnimationFrame(follow);

  draw();
  status("");
}

main().catch((e) => status(String(e), "bad"));
