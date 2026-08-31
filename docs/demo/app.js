'use strict';

/* ---------------------------------------------------------------- state */

const S = {
  project: null,
  an: null,
  audio: new Audio(),
  solo: false,
  follow: true,
  view: { start: 0, dur: 60 },
  sel: 0,
  selWord: null,
  rate: 1,
  additions: [],           // lines heard in the gaps that the lyrics lack
  addAt: 0,
  review: {
    queue: [], at: 0, undo: [], stats: null, wasSolo: false,
    adj: null,            // a timing the reviewer placed by hand, if any
    drag: null,           // an in-progress drag on the review strip
    strip: false,         // the strip is on screen and wants playhead frames
    lastPlayed: null,     // which candidate space last previewed
  },
  todo: new Map(),        // "line:word" -> issue, so every view can mark it
  todoLines: new Set(),
  stale: true,            // the cached waveform layer needs repainting
  lastT: -1,              // last playhead time actually drawn
  hl: { row: null, word: null, line: -1 },
  scrub: null,            // an in-progress drag on the scrub bar
  scrubHoverX: null,
  flash: null,            // a boundary that just locked onto a vocal onset
  hist: { undo: [], redo: [], savedAt: 0, coalesce: null },
  rows: new Map(),        // line index -> row element, so no per-frame lookups
  el: {},                 // hot DOM refs, resolved once
  lyricHoldUntil: 0,      // chase is suspended until this moment (0 = not held)
  filter: 'all',
  drag: null,
  hover: null,
  dirty: false,
  raf: 0,
};

/* ------------------------------------------------------------ static mode

   This app is a local server, but a read-only copy of it runs on GitHub Pages
   so it can be tried before it is installed. A page that sets
   window.SONG_STATIC serves the same UI against files on disk instead of the
   API, and every action that would write is turned off rather than left to
   fail: a Save button that 404s is worse than one that is not there.

   Everything that edits in memory still works - dragging lines and word
   boundaries, the whole Check timings queue, undo - because none of it ever
   needed the server. Only persistence did. */

const STATIC = (typeof window !== 'undefined' && window.SONG_STATIC) || null;

const STATIC_FILES = {
  '/api/project': 'project.json',
  '/api/analysis': 'analysis.json',
  '/api/audit': 'audit.json',
  '/media/mix': 'media/mix.m4a',
  '/media/vocals': 'media/vocals.m4a',
};

/** Where a given endpoint lives: the API, or a file next to the page. */
function api(path) {
  if (!STATIC) return path;
  return STATIC_FILES[path] ? STATIC + STATIC_FILES[path] : path;
}

/** True when the action cannot run here, having said so. */
function needsServer(what) {
  if (!STATIC) return false;
  toast(`${what} needs the app running on your machine — this is a live demo`);
  return true;
}

const canvas = document.getElementById('timeline');
let ctx = canvas.getContext('2d');

/* The waveforms cost ~4.8 ms a frame to rasterise and depend only on the view,
   so they are painted once into an offscreen canvas and blitted afterwards.
   Everything that moves - playhead, active word - is drawn live on top. */
const back = document.createElement('canvas');
const backCtx = back.getContext('2d');

/* Lanes, top to bottom. The mix waveform used to sit between the ruler and the
   vocal; it was dropped because it does not answer the only question this view
   exists to answer. Measured on the sample track, mix amplitude separates
   "someone is singing" from "nobody is singing" by 0.18 sd - the vocal stem
   does it by 1.89 sd. On a compressed master the mix is a solid bar. */
const MINI_H = 20, GAP = 5, SCRUB_H = 19, VOC_H = 118, WORD_STRIP = 24;
const MINI_Y = 0;
const SCRUB_Y = MINI_H + GAP;
const VOC_Y = SCRUB_Y + SCRUB_H;
/* Word cells live in the bottom band of the vocal lane rather than in a lane of
   their own. The old word lane drew a second, dimmed copy of the same vocal
   waveform - the same signal twice, a hundred pixels apart. Now the dividers
   run the full height of the one waveform, so whether a boundary lands on the
   syllable attack is read directly off the audio instead of off a copy. */
const WORD_Y = VOC_Y + VOC_H - WORD_STRIP;
const TOTAL_H = VOC_Y + VOC_H;
const EDGE_GRAB = 7;
const FINE_SCRUB = 6;     // shift-drag on the scrub bar moves this much slower

/* Word lane. Only word *starts* are editable - see normalizeWords. */
const MIN_WORD = 0.06;    // shortest a word may be squeezed to, seconds
const WORD_SNAP = 0.06;   // snap a dragged start to a vocal onset within this
const WORD_GRAB = 5;      // px either side of a divider that grabs it
const WORD_MIN_PX = 200;  // narrower than this and the blocks are unusable

/* Playback speeds. Word work is done by ear, and at 1x a syllable boundary goes
   past faster than you can judge it; 0.5x and 0.25x are the workhorses. */
const RATES = [0.25, 0.5, 0.75, 1];

const C = {
  bg: '#0e1116', panel: '#151a22', grid: '#232c3a', muted: '#8b98ad',
  vocal: '#6fa8ff', active: 'rgba(91,157,255,.065)',
  onset: 'rgba(255,255,255,.20)', head: '#ff5d73',
  good: '#3ecf8e', ok: '#e8b33d', bad: '#ff6b6b', sel: '#5b9dff', todo: '#f0a63c',
  adj: '#b48cff',
  scrub: '#161d29', scrubEdge: '#2a3547', wordDiv: 'rgba(170,203,255,.6)',
};

/* ---------------------------------------------------------------- utils */

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

function fmt(t) {
  if (!isFinite(t)) t = 0;
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s < 10 ? '0' : ''}${s.toFixed(2)}`;
}

function grade(score) {
  return score >= 85 ? 'good' : score >= 70 ? 'ok' : 'bad';
}

function toast(msg, isError) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show' + (isError ? ' err' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.className = 'toast'), 2400);
}

const timed = () => S.project.lines.filter(l => l.end > l.start);

/* Mirrors TimedLine.retime in project.py: words ride along proportionally. */
function retimeLine(line, start, end) {
  start = Math.max(0, start);
  end = Math.max(start + 0.05, end);
  const oldStart = line.start, oldSpan = line.end - line.start;
  if (line.words && line.words.length) {
    if (oldSpan > 1e-6) {
      const k = (end - start) / oldSpan;
      for (const w of line.words) {
        w.start = start + (w.start - oldStart) * k;
        w.end = start + (w.end - oldStart) * k;
      }
    } else {
      const step = (end - start) / line.words.length;
      line.words.forEach((w, i) => { w.start = start + i * step; w.end = start + (i + 1) * step; });
    }
  }
  line.start = start;
  line.end = end;
  line.source = 'manual';
  markDirty();
}

function markDirty() {
  S.dirty = true;
  invalidate();
  paintSaveBtn();
}

/** The save button lights only when there is something to save. */
function paintSaveBtn() {
  const b = document.getElementById('btn-save');
  b.innerHTML = 'Save<span class="k">⌘S</span>';
  b.classList.toggle('dirty', S.dirty);
}

/* Edits below record a history step before they mutate anything. */

/* --------------------------------------------------------------- history

   Every edit is reversible. Entries snapshot only the lines they touch - one
   line is a few numbers, so a step is cheap and a deep stack is free.

   Granularity is the whole point: a drag is one step (captured at mousedown,
   discarded on mouseup if nothing actually moved), and a burst of arrow-key
   nudges folds into one step the way typing folds in a text editor. Undoing a
   drag pixel by pixel would be useless. */

const HIST_LIMIT = 200;
const COALESCE_MS = 700;

function snapLine(line) {
  return {
    index: line.index,
    start: line.start,
    end: line.end,
    source: line.source,
    starts: line.words.map(w => w.start),
  };
}

function restoreLine(snap) {
  const line = S.project.lines[snap.index];
  if (!line) return;
  line.start = snap.start;
  line.end = snap.end;
  line.source = snap.source;
  snap.starts.forEach((t, i) => { if (line.words[i]) line.words[i].start = t; });
  normalizeWords(line);
}

/** Review decisions carry queue state too, so undo puts the queue back as well. */
function snapReview(qIndex) {
  const item = S.review.queue[qIndex];
  return { qIndex, at: S.review.at, done: !!(item && item.done) };
}

function pushHistory(label, lines, review) {
  const entry = {
    label,
    lines: (lines || []).map(snapLine),
    review: review === undefined ? null : review,
  };
  S.hist.undo.push(entry);
  if (S.hist.undo.length > HIST_LIMIT) {
    S.hist.undo.shift();
    S.hist.savedAt = Math.max(0, S.hist.savedAt - 1);
  }
  S.hist.redo.length = 0;          // a new edit forks the future away
  S.hist.coalesce = null;
  syncHistory();
  return entry;
}

/** Fold a repeat of the same small edit into the step already on the stack. */
function pushCoalesced(label, line) {
  const h = S.hist, now = performance.now(), c = h.coalesce;
  if (c && c.label === label && c.index === line.index
      && now - c.at < COALESCE_MS && h.undo[h.undo.length - 1] === c.entry) {
    c.at = now;
    return c.entry;
  }
  const entry = pushHistory(label, [line]);
  h.coalesce = { label, index: line.index, at: now, entry };
  return entry;
}

/** A click that started a drag but moved nothing should not cost an undo step. */
function dropIfUnchanged(entry) {
  const h = S.hist;
  if (!entry || h.undo[h.undo.length - 1] !== entry) return;
  const same = entry.lines.every(snap => {
    const line = S.project.lines[snap.index];
    return line && line.start === snap.start && line.end === snap.end
      && snap.starts.every((t, i) => line.words[i] && line.words[i].start === t);
  });
  if (same) { h.undo.pop(); syncHistory(); }
}

/**
 * Toggle exactly one queue item's amber mark to match its current `.done`,
 * without touching any other row. Shared by the review sheet's own forward
 * decisions and by undo/redo stepping back through them - both flip the same
 * single boolean, so both patch the same single word and row.
 */
function syncTodoMark(item) {
  if (!item) return;
  const row = S.rows.get(item.line);
  if (!row) return;                     // filtered out of the current view
  const el = row.querySelectorAll('.w')[item.word];
  if (el) el.classList.toggle('todo', !item.done);
  row.classList.toggle('has-todo', S.todoLines.has(item.line));
}

/** Apply one entry, pushing the state it replaces onto the opposite stack. */
function stepHistory(entry, onto) {
  onto.push({
    label: entry.label,
    lines: entry.lines.map(snap => snapLine(S.project.lines[snap.index])),
    review: entry.review ? snapReview(entry.review.qIndex) : null,
  });

  entry.lines.forEach(restoreLine);
  let toggled = null;
  if (entry.review) {
    toggled = S.review.queue[entry.review.qIndex];
    if (toggled) toggled.done = entry.review.done;
    S.review.at = entry.review.at;
    indexTodo();
    rvBadge();
  }

  S.hist.coalesce = null;
  for (const snap of entry.lines) {
    const line = S.project.lines[snap.index];
    if (line) refreshRow(line);
  }
  // One word's mark flipped, so patch exactly that - a full renderList() here
  // would tear down and rebuild every row in the panel to change one underline.
  syncTodoMark(toggled);
  invalidate();
  draw();
  syncHistory();
}

function undoEdit() {
  const entry = S.hist.undo.pop();
  if (!entry) return false;
  stepHistory(entry, S.hist.redo);
  toast(`undo — ${entry.label}`);
  return true;
}

function redoEdit() {
  const entry = S.hist.redo.pop();
  if (!entry) return false;
  stepHistory(entry, S.hist.undo);
  toast(`redo — ${entry.label}`);
  return true;
}

/** History is also the honest source of "are there unsaved changes". */
function syncHistory() {
  const h = S.hist;
  S.dirty = h.undo.length !== h.savedAt;
  paintSaveBtn();

  const u = document.getElementById('btn-undo');
  const r = document.getElementById('btn-redo');
  if (!u || !r) return;
  u.disabled = !h.undo.length;
  r.disabled = !h.redo.length;
  u.title = h.undo.length ? `Undo ${h.undo[h.undo.length - 1].label}  (⌘Z)` : 'Nothing to undo';
  r.title = h.redo.length ? `Redo ${h.redo[h.redo.length - 1].label}  (⇧⌘Z)` : 'Nothing to redo';
  const rv = document.getElementById('rv-undo');
  if (rv) {
    const top = h.undo[h.undo.length - 1];
    rv.disabled = !(top && top.review);
  }
}

/** Reloading the project from the server invalidates every snapshot. */
function resetHistory() {
  S.hist = { undo: [], redo: [], savedAt: 0, coalesce: null };
  syncHistory();
}

/* ------------------------------------------------------- word-level edits */

/* Enhanced LRC stores one timestamp per word, so a word's end *is* the next
   word's start. Editing starts only makes gaps and overlaps unrepresentable:
   a line of N words has exactly N-1 internal boundaries, and the line's own
   edges own the other two. The price is that Whisper's raw ends - which encode
   small inter-word pauses - get flattened to contiguous. Nothing downstream
   reads them; every export keys off starts. */
function normalizeWords(line) {
  const ws = line.words;
  if (!ws || !ws.length) return;
  ws[0].start = line.start;
  for (let i = 0; i < ws.length - 1; i++) ws[i].end = ws[i + 1].start;
  ws[ws.length - 1].end = line.end;
}

/** Nearest vocal onset to t, or t unchanged if none is within WORD_SNAP. */
function snapOnset(t) {
  let best = t, bestDelta = WORD_SNAP;
  for (const onset of S.an.onsets) {
    if (onset > t + WORD_SNAP) break;          // onsets are sorted
    const delta = Math.abs(onset - t);
    if (delta < bestDelta) { bestDelta = delta; best = onset; }
  }
  return best;
}

/**
 * Move the start of word `i`, absorbing the change into the two words either
 * side of it.
 *
 * Word 0's start *is* the line start, so moving it moves the line's left edge -
 * without rescaling the rest, which is what dragging the region edge does.
 */
function setWordStart(line, i, t) {
  const ws = line.words || [];
  if (i < 0 || i >= ws.length) return;
  const lo = i === 0 ? 0 : ws[i - 1].start + MIN_WORD;
  const hi = (i + 1 < ws.length ? ws[i + 1].start : line.end) - MIN_WORD;
  t = clamp(t, lo, Math.max(lo, hi));
  if (i === 0) line.start = t;
  ws[i].start = t;
  normalizeWords(line);
  line.source = 'manual';
  markDirty();
}

/** Escape hatch: spread the line's words evenly across its span. */
function redistribute(line) {
  const ws = (line && line.words) || [];
  if (ws.length < 2 || line.end <= line.start) return false;
  pushHistory('redistribute words', [line]);
  const step = (line.end - line.start) / ws.length;
  ws.forEach((w, i) => { w.start = line.start + i * step; });
  normalizeWords(line);
  line.source = 'manual';
  markDirty();
  return true;
}

/** Pixel geometry of one line's words, for drawing and hit testing. */
function wordBlocks(line) {
  if (!line || line.end <= line.start) return [];
  return (line.words || []).map((w, i) => ({ w, i, x0: t2x(w.start), x1: t2x(w.end) }));
}

/** Flat (line, word) cursor list, so Tab rolls into the adjacent line. */
function wordCursors() {
  const out = [];
  for (const line of S.project.lines) {
    if (line.end <= line.start) continue;
    (line.words || []).forEach((_, i) => out.push([line.index, i]));
  }
  return out;
}

/* ---------------------------------------------------------------- speed */

/* playbackRate lives on the audio element, so it has to be re-applied every
   time the source is swapped (the solo-vocals toggle replaces src). Pitch is
   preserved, which keeps the words recognisable all the way down to 0.25x. */
function applyRate() {
  S.audio.preservesPitch = true;
  S.audio.webkitPreservesPitch = true;   // Safari
  S.audio.playbackRate = S.rate;
}

function setRate(rate) {
  S.rate = RATES.includes(rate) ? rate : 1;
  applyRate();
  const btn = document.getElementById('btn-rate');
  btn.innerHTML = `${S.rate}×<span class="k">[ ]</span>`;
  btn.classList.toggle('on', S.rate !== 1);
  document.getElementById('clock').classList.toggle('slow', S.rate !== 1);
}

/* The button cycles downward, because slowing is what you reach for; 0.25x
   wraps back to 1x so one control covers the whole ladder. */
function cycleRate() {
  setRate(RATES[(RATES.indexOf(S.rate) - 1 + RATES.length) % RATES.length]);
}

function stepRate(dir) {
  const next = RATES[clamp(RATES.indexOf(S.rate) + dir, 0, RATES.length - 1)];
  if (next === S.rate) return;
  setRate(next);
  toast(`${next}× speed`);
}

/** Swap the audio source. The element keeps its rate only if we re-apply it. */
function setSolo(on) {
  S.solo = on;
  document.getElementById('btn-solo').classList.toggle('on', on);
  const t = S.audio.currentTime, playing = !S.audio.paused;
  S.audio.src = api(on ? '/media/vocals' : '/media/mix');
  S.audio.addEventListener('loadedmetadata', function once() {
    S.audio.removeEventListener('loadedmetadata', once);
    S.audio.currentTime = t;
    applyRate();
    if (playing) S.audio.play();
  });
}

function setFollow(on) {
  S.follow = on;
  document.getElementById('btn-follow').classList.toggle('on', on);
  if (on) { S.lyricHoldUntil = 0; followLyrics(S.hl.row, true); }
}

/* ---------------------------------------------------------------- view */

function duration() { return S.an ? S.an.duration : (S.project ? S.project.duration : 0); }

function setView(start, dur) {
  const total = duration();
  const d = clamp(dur, 0.75, total);
  const st = clamp(start, 0, Math.max(0, total - d));
  if (d !== S.view.dur || st !== S.view.start) invalidate();
  S.view.dur = d;
  S.view.start = st;
}

function zoomAt(t, factor) {
  const frac = clamp((t - S.view.start) / S.view.dur, 0, 1);
  const dur = S.view.dur * factor;
  setView(t - frac * dur, dur);
  draw();
}

const t2x = t => (t - S.view.start) / S.view.dur * canvas.clientWidth;
const x2t = x => S.view.start + (x / canvas.clientWidth) * S.view.dur;

/* ---------------------------------------------------------------- draw */

function layout() {
  const dpr = window.devicePixelRatio || 1;
  const host = canvas.parentElement, cs = getComputedStyle(host);
  const w = Math.max(1, host.clientWidth
    - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight));
  canvas.style.width = w + 'px';
  canvas.style.height = TOTAL_H + 'px';
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(TOTAL_H * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  invalidate();
}

/** Max peak amplitude between two times, from the fixed-rate peak array. */
function peakRange(arr, rate, a, b) {
  let i = Math.max(0, Math.floor(a * rate));
  const j = Math.min(arr.length, Math.max(i + 1, Math.ceil(b * rate)));
  let m = 0;
  for (; i < j; i++) if (arr[i] > m) m = arr[i];
  return m;
}

/**
 * Which pixel columns have someone singing in them.
 *
 * `toTime` is the caller's own mapping, so the main lane and the review strip -
 * which look at different windows - share this without sharing a viewport.
 */
function vocalMask(W, toTime) {
  const mask = new Uint8Array(W);
  const spans = S.an.vocal_spans;
  let i = 0;
  for (let x = 0; x < W; x++) {
    const a = toTime(x), b = toTime(x + 1);
    while (i < spans.length && spans[i][1] < a) i++;   // spans are sorted
    if (i < spans.length && spans[i][0] <= b) mask[x] = 1;
  }
  return mask;
}

/** A lit core falling off towards the extremes, so loud reads as bright. */
function waveGradient(g, y, h) {
  const grad = g.createLinearGradient(0, y, 0, y + h);
  grad.addColorStop(0, 'rgba(80,132,210,.5)');
  grad.addColorStop(0.34, 'rgba(124,178,255,.92)');
  grad.addColorStop(0.5, '#a8ccff');
  grad.addColorStop(0.66, 'rgba(124,178,255,.92)');
  grad.addColorStop(1, 'rgba(80,132,210,.5)');
  return grad;
}

/**
 * The waveform, drawn in two passes.
 *
 * "Is anyone singing here" is the question this lane exists to answer, and the
 * waveform itself can answer it: sung stretches get the lit gradient, the rest
 * drops to a flat dim blue and reads as ground. That carries the signal the
 * shaded bands used to carry alone, so the bands can be much lighter and the
 * lane stops looking like two overlaid pictures of the same thing.
 */
function drawWave(arr, y, h, gain) {
  const W = canvas.clientWidth, rate = S.an.rate, mid = y + h / 2, half = h / 2;
  const mask = vocalMask(W, x2t);

  for (let sung = 0; sung < 2; sung++) {
    ctx.fillStyle = sung ? waveGradient(ctx, y, h) : 'rgba(104,150,214,.26)';
    ctx.beginPath();
    for (let x = 0; x < W; x++) {
      if (mask[x] !== sung) continue;
      const v = peakRange(arr, rate, x2t(x), x2t(x + 1)) * (gain || 1);
      const bar = Math.max(0.6, v * half);
      ctx.rect(x, mid - bar, 1, bar * 2);
    }
    ctx.fill();
  }
}

function drawMinimap() {
  const W = canvas.clientWidth, total = duration();
  ctx.fillStyle = '#131924';
  ctx.fillRect(0, MINI_Y, W, MINI_H);

  // Vocal-active spans give the song's vocal structure at a glance.
  ctx.fillStyle = 'rgba(111,168,255,.16)';
  for (const [a, b] of S.an.vocal_spans) {
    const x = a / total * W;
    ctx.fillRect(x, MINI_Y, Math.max(1, (b - a) / total * W), MINI_H);
  }

  ctx.fillStyle = 'rgba(111,168,255,.75)';
  for (const line of timed()) {
    const x = line.start / total * W;
    ctx.fillRect(x, MINI_Y + MINI_H - 6, Math.max(1.2, (line.end - line.start) / total * W), 4);
  }
  ctx.fillStyle = C.bad;
  for (const line of S.project.lines) {
    if (!line.flagged || line.end <= line.start) continue;
    ctx.fillRect(line.start / total * W, MINI_Y + MINI_H - 6, Math.max(1.5, (line.end - line.start) / total * W), 4);
  }

  // Where you are looking. Filled as well as outlined - an outline alone reads
  // as one more line in a strip already full of them.
  const vx = S.view.start / total * W, vw = Math.max(3, S.view.dur / total * W);
  ctx.fillStyle = 'rgba(255,255,255,.07)';
  ctx.fillRect(vx, MINI_Y, vw, MINI_H);
  ctx.strokeStyle = 'rgba(226,236,250,.65)';
  ctx.lineWidth = 1;
  ctx.strokeRect(vx + 0.5, MINI_Y + 0.5, Math.max(1, vw - 1), MINI_H - 1);

  // A seam under the overview, so it reads as a separate instrument from the
  // ruler and the waveform below it rather than a third waveform.
  ctx.fillStyle = '#080b11';
  ctx.fillRect(0, MINI_Y + MINI_H, W, GAP);
}

function drawMinimapHead() {
  const W = canvas.clientWidth, total = duration();
  if (!total) return;
  ctx.fillStyle = C.head;
  ctx.fillRect(S.audio.currentTime / total * W, MINI_Y, 1.5, MINI_H);
}

/** The ruler doubles as the scrub bar: the one place you can always seek. */
function drawScrubBar() {
  const W = canvas.clientWidth;
  const bed = ctx.createLinearGradient(0, SCRUB_Y, 0, SCRUB_Y + SCRUB_H);
  bed.addColorStop(0, '#1a2231');
  bed.addColorStop(1, '#131a26');
  ctx.fillStyle = bed;
  ctx.fillRect(0, SCRUB_Y, W, SCRUB_H);
  ctx.fillStyle = C.scrubEdge;
  ctx.fillRect(0, SCRUB_Y + SCRUB_H - 1, W, 1);

  const targetPx = 90;
  const steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120];
  const perPx = S.view.dur / W;
  const step = steps.find(s => s / perPx >= targetPx) || 120;

  ctx.font = '10px ui-monospace, Menlo, monospace';
  ctx.fillStyle = C.muted;
  ctx.textBaseline = 'middle';
  for (let t = Math.ceil(S.view.start / step) * step; t < S.view.start + S.view.dur; t += step) {
    const x = t2x(t);
    ctx.fillStyle = C.grid;
    ctx.fillRect(x, SCRUB_Y + SCRUB_H - 6, 1, 6);
    ctx.fillStyle = C.muted;
    ctx.fillText(fmt(t).replace(/\.\d+$/, m => (step < 1 ? m : '')), x + 4, SCRUB_Y + 7);
  }
}

function drawVocalLane() {
  const W = canvas.clientWidth;
  const bed = ctx.createLinearGradient(0, VOC_Y, 0, VOC_Y + VOC_H);
  bed.addColorStop(0, '#0d121c');
  bed.addColorStop(0.5, '#111724');
  bed.addColorStop(1, '#0b0f17');
  ctx.fillStyle = bed;
  ctx.fillRect(0, VOC_Y, W, VOC_H);

  // Bands where the vocal is present. Much lighter than they used to be: the
  // waveform's own brightness now says this, and saying it twice was noise.
  ctx.fillStyle = C.active;
  for (const [a, b] of S.an.vocal_spans) {
    if (b < S.view.start || a > S.view.start + S.view.dur) continue;
    ctx.fillRect(t2x(a), VOC_Y, Math.max(1, t2x(b) - t2x(a)), VOC_H);
  }

  drawWave(S.an.vocal_peaks, VOC_Y, VOC_H, 1);

  // Onset ticks - the things you snap a line start to.
  if (S.view.dur < 90) {
    ctx.fillStyle = C.onset;
    for (const t of S.an.onsets) {
      if (t < S.view.start || t > S.view.start + S.view.dur) continue;
      ctx.fillRect(t2x(t), VOC_Y, 1, 8);
    }
  }
}

function drawRegions() {
  const W = canvas.clientWidth;
  ctx.font = '11px -apple-system, system-ui, sans-serif';
  ctx.textBaseline = 'top';

  for (const line of S.project.lines) {
    if (line.end <= line.start) continue;
    if (line.end < S.view.start || line.start > S.view.start + S.view.dur) continue;

    const x0 = t2x(line.start), x1 = t2x(line.end), w = Math.max(2, x1 - x0);
    const selected = line.index === S.sel;
    const score = (line.score && line.score.total) || 0;
    const tone = line.flagged ? C.bad : grade(score) === 'good' ? C.good : C.ok;

    ctx.fillStyle = selected ? 'rgba(91,157,255,.20)' : 'rgba(255,255,255,.028)';
    ctx.fillRect(x0, VOC_Y, w, VOC_H);

    ctx.fillStyle = tone;
    ctx.globalAlpha = selected ? 1 : 0.6;
    ctx.fillRect(x0, VOC_Y, 2, VOC_H);
    ctx.fillRect(x1 - 2, VOC_Y, 2, VOC_H);
    ctx.fillRect(x0, WORD_Y - 3, w, 3);
    ctx.globalAlpha = 1;

    if (w > 46) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(x0 + 4, VOC_Y, w - 8, 16);
      ctx.clip();
      ctx.fillStyle = selected ? '#fff' : 'rgba(230,237,247,.7)';
      ctx.fillText(line.text, x0 + 5, VOC_Y + 2);
      ctx.restore();
    }
  }
}

/** The part of the word lane that only depends on the view: bed + waveform. */
/** Every line wide enough to read, so the strip is a continuous caption track. */
function eachWordLine(fn) {
  const viewEnd = S.view.start + S.view.dur;
  for (const line of S.project.lines) {
    if (line.end <= line.start || !line.words || !line.words.length) continue;
    if (line.end < S.view.start || line.start > viewEnd) continue;
    const blocks = wordBlocks(line);
    if (!blocks.length) continue;
    if (blocks[blocks.length - 1].x1 - blocks[0].x0 < WORD_MIN_PX) continue;
    if (fn(line, blocks) === false) return false;
  }
  return true;
}

/**
 * Word cells under the waveform, for every line on screen.
 *
 * Only the selected line is editable, but drawing only the selected line left
 * the strip blank the moment playback moved past it - which reads as broken,
 * because the waveform above it is still showing those lines' regions.
 */
function drawWordBlocks() {
  ctx.font = '11px -apple-system, system-ui, sans-serif';
  ctx.textBaseline = 'top';

  const t = S.audio.currentTime;
  let drew = false;

  eachWordLine((line, blocks) => {
    drew = true;
    const live = line.index === S.sel;

    for (const b of blocks) {
      const w = Math.max(1, b.x1 - b.x0);
      const active = t >= b.w.start && t < b.w.end;
      const chosen = live && b.i === S.selWord;
      const todo = S.todo.has(`${line.index}:${b.i}`);
      ctx.fillStyle = active ? 'rgba(91,157,255,.46)'
        : chosen ? 'rgba(91,157,255,.34)'
        : todo ? (live ? 'rgba(240,166,60,.30)' : 'rgba(240,166,60,.18)')
        : live ? (b.i % 2 ? 'rgba(9,13,21,.80)' : 'rgba(17,25,40,.80)')
        : (b.i % 2 ? 'rgba(9,13,21,.55)' : 'rgba(17,25,40,.55)');
      ctx.fillRect(b.x0, WORD_Y, w, WORD_STRIP);
      if (active) {                     // the cell lights along its top edge
        ctx.fillStyle = 'rgba(150,196,255,.9)';
        ctx.fillRect(b.x0, WORD_Y, w, 1.5);
      }
      if (todo) {                       // a bar you can find without reading
        ctx.fillStyle = C.todo;
        ctx.fillRect(b.x0, WORD_Y + WORD_STRIP - 2, w, 2);
      }

      if (w > 16) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(b.x0 + 2, WORD_Y, w - 4, WORD_STRIP);
        ctx.clip();
        ctx.fillStyle = active || chosen ? '#fff'
          : live ? 'rgba(230,237,247,.8)' : 'rgba(230,237,247,.45)';
        ctx.fillText(b.w.text, b.x0 + 4, WORD_Y + 6);
        ctx.restore();
      }
    }

    // The selected line's boundaries run the full height of the waveform: a
    // divider that misses the syllable attack is visible against the audio it
    // is supposed to be cutting. Other lines get a tick inside the strip only,
    // enough to read the split without striping the whole lane.
    for (let i = 1; i < blocks.length; i++) {
      const x = blocks[i].x0;
      if (!live) {
        ctx.fillStyle = 'rgba(170,203,255,.28)';
        ctx.fillRect(x - 0.5, WORD_Y, 1, WORD_STRIP);
        continue;
      }
      const near = i === S.selWord || i - 1 === S.selWord;
      ctx.fillStyle = near ? 'rgba(213,228,255,.95)' : 'rgba(170,203,255,.5)';
      ctx.fillRect(x - 0.5, VOC_Y, 1.5, VOC_H);
      ctx.fillStyle = near ? '#d5e4ff' : C.wordDiv;
      ctx.fillRect(x - 2.5, WORD_Y, 5.5, 3);
      ctx.fillRect(x - 2.5, VOC_Y + VOC_H - 3, 5.5, 3);
    }

    if (live && S.selWord != null && blocks[S.selWord]) {
      const b = blocks[S.selWord];
      ctx.strokeStyle = C.sel;
      ctx.lineWidth = 1;
      ctx.strokeRect(b.x0 + 0.5, WORD_Y + 0.5, Math.max(1, b.x1 - b.x0 - 1), WORD_STRIP - 1);
    }
  });

  if (!drew) laneNote('zoom in to see and edit words');
}

function laneNote(text) {
  ctx.fillStyle = 'rgba(10,15,24,.8)';
  ctx.fillRect(0, WORD_Y, canvas.clientWidth, WORD_STRIP);
  ctx.fillStyle = C.muted;
  ctx.font = '11px -apple-system, system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 8, WORD_Y + WORD_STRIP / 2);
  ctx.textBaseline = 'top';
}

/** Floating time readout under the cursor while over the scrub bar. */
function drawScrubCursor() {
  const x = S.scrubHoverX;
  if (x == null) return;
  const label = fmt(x2t(x));
  ctx.font = '11px ui-monospace, Menlo, monospace';
  const w = ctx.measureText(label).width + 10;
  const bx = clamp(x - w / 2, 0, canvas.clientWidth - w);

  ctx.fillStyle = 'rgba(255,255,255,.28)';
  ctx.fillRect(x, SCRUB_Y, 1, SCRUB_H);
  ctx.fillStyle = '#0b0f16';
  ctx.fillRect(bx, SCRUB_Y + 1, w, 14);
  ctx.strokeStyle = C.scrubEdge;
  ctx.strokeRect(bx + 0.5, SCRUB_Y + 1.5, w - 1, 13);
  ctx.fillStyle = '#dfe8f5';
  ctx.textBaseline = 'top';
  ctx.fillText(label, bx + 5, SCRUB_Y + 4);
}

/* How long the "locked on" ring lives after a boundary snaps to an onset. */
const FLASH_MS = 430;

/** A ring blooming out of the onset a divider just locked onto. */
function drawSnapFlash() {
  if (!S.flash) return;
  const age = performance.now() - S.flash.at;
  if (age >= FLASH_MS) { S.flash = null; return; }

  // Clamped: a throw inside draw() would take the whole render loop with it.
  const k = clamp(1 - age / FLASH_MS, 0, 1);   // 1 -> 0
  const x = t2x(S.flash.t);
  if (x < -20 || x > canvas.clientWidth + 20) return;

  const y = VOC_Y + VOC_H / 2;
  ctx.strokeStyle = `rgba(62,207,142,${0.5 * k})`;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(x + 0.25, y, 4 + 16 * (1 - k), 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = `rgba(62,207,142,${0.55 * k})`;
  ctx.fillRect(x - 0.5, VOC_Y, 1.5, VOC_H);
}

function drawPlayhead() {
  const t = S.audio.currentTime;
  if (t < S.view.start || t > S.view.start + S.view.dur) return;
  const x = t2x(t);

  // The halo swells with the vocal level directly under the playhead, so the
  // cursor breathes with the voice instead of sliding across it. Built from
  // flanking bars rather than shadowBlur - the same look, none of the cost.
  const level = S.an ? peakRange(S.an.vocal_peaks, S.an.rate, t, t + 0.03) : 0;
  const spread = 2.5 + level * 5;
  ctx.fillStyle = `rgba(255,93,115,${0.10 + level * 0.16})`;
  ctx.fillRect(x - spread, SCRUB_Y, spread * 2 + 1.5, TOTAL_H - SCRUB_Y);
  ctx.fillStyle = C.head;
  ctx.fillRect(x, SCRUB_Y, 1.5, TOTAL_H - SCRUB_Y);
  ctx.beginPath();
  ctx.moveTo(x - 5, SCRUB_Y);
  ctx.lineTo(x + 6, SCRUB_Y);
  ctx.lineTo(x + 0.5, SCRUB_Y + 7);
  ctx.closePath();
  ctx.fill();
}

/* With nothing under the cursor the readout says what the surface does, rather
   than sitting blank. It is replaced the moment you point at anything. */
const HINT_REST =
  'drag a line to move it · its edges to resize · the ruler to scrub · a divider to split words';

function restHint() {
  if (!S.el.hint) return;
  S.el.hint.textContent = HINT_REST;
  S.el.hint.classList.add('rest');       // a teaching aid: first thing to drop
}

/** A live readout of whatever is under the cursor - never dropped. */
function setHint(text) {
  if (!S.el.hint) return;
  S.el.hint.textContent = text;
  S.el.hint.classList.remove('rest');
}

/** Mark the cached waveform layer as needing a repaint. */
function invalidate() { S.stale = true; }

/** Repaint everything that depends only on the view, into the back canvas. */
function paintStatic() {
  if (!canvas.width || !canvas.height) return;
  const dpr = window.devicePixelRatio || 1;
  if (back.width !== canvas.width || back.height !== canvas.height) {
    back.width = canvas.width;
    back.height = canvas.height;
  }
  backCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const live = ctx;
  ctx = backCtx;                        // the painters below all target `ctx`
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, canvas.clientWidth, TOTAL_H);
  drawMinimap();
  drawScrubBar();
  drawVocalLane();
  ctx = live;

  S.stale = false;
}

function draw() {
  if (!S.an || !S.project) return;
  // A collapsed or not-yet-laid-out container gives a 0x0 canvas, and drawImage
  // throws on one. Booting into that state would abort main(), not just a frame.
  if (!canvas.width || !canvas.height) return;
  if (S.stale) paintStatic();

  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.drawImage(back, 0, 0);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  drawRegions();
  drawWordBlocks();
  drawMinimapHead();
  drawSnapFlash();
  drawScrubCursor();
  drawPlayhead();
}

/* ---------------------------------------------------------------- hit test */

function hit(x, y) {
  // The bottom band belongs to the word cells, so a line grab cannot start there.
  if (y < VOC_Y || y >= WORD_Y) return null;
  let best = null;
  for (const line of S.project.lines) {
    if (line.end <= line.start) continue;
    const x0 = t2x(line.start), x1 = t2x(line.end);
    if (x < x0 - EDGE_GRAB || x > x1 + EDGE_GRAB) continue;
    const edge = Math.abs(x - x0) <= EDGE_GRAB ? 'start'
      : Math.abs(x - x1) <= EDGE_GRAB ? 'end' : 'move';
    // Prefer the selected line and edge grabs when regions overlap.
    const rank = (line.index === S.sel ? 2 : 0) + (edge !== 'move' ? 1 : 0);
    if (!best || rank > best.rank) best = { line, edge, rank };
  }
  return best;
}

/** Hit test in the word lane: a divider between two words, or a block. */
/**
 * Hit test the word strip across every line on screen.
 *
 * Dividers beat blocks - they are what you came here to drag - and the selected
 * line beats its neighbours where cells touch, so the line you are working on
 * never loses a boundary to the line next to it.
 */
function hitWord(x, y) {
  if (y < WORD_Y || y > VOC_Y + VOC_H) return null;
  let best = null;
  const keep = (cand) => { if (!best || cand.rank > best.rank) best = cand; };

  eachWordLine((line, blocks) => {
    const live = line.index === S.sel;
    for (let i = 1; i < blocks.length; i++) {
      if (Math.abs(x - blocks[i].x0) <= WORD_GRAB) {
        keep({ line, kind: 'divider', i, rank: live ? 4 : 3 });
      }
    }
    for (const b of blocks) {
      if (x >= b.x0 && x <= b.x1) keep({ line, kind: 'block', i: b.i, rank: live ? 2 : 1 });
    }
  });
  return best;
}

/* ---------------------------------------------------------------- lyrics panel */

function renderList() {
  const host = document.getElementById('line-list');
  host.innerHTML = '';
  const bySection = new Map();
  for (const line of S.project.lines) {
    if (S.filter === 'flagged' && !line.flagged) continue;
    if (!bySection.has(line.section)) bySection.set(line.section, []);
    bySection.get(line.section).push(line);
  }

  for (const [sectionIndex, lines] of bySection) {
    const section = S.project.sections[sectionIndex];
    const head = document.createElement('div');
    head.className = 'section-head';
    head.innerHTML = `${section ? section.name : 'Lyrics'}` +
      (section && section.note ? ` <span class="section-note">— ${section.note}</span>` : '');
    host.appendChild(head);

    for (const line of lines) {
      host.appendChild(renderRow(line));
      // A proposal sits where the line would go, between the two that bracket
      // it, so the question is asked in the one place it is easy to answer.
      for (const cand of adPending()) {
        if (cand.after_line === line.index) host.appendChild(renderGhost(cand));
      }
    }
  }
  if (!host.children.length) {
    host.innerHTML = '<div class="section-head">Nothing flagged — every line cleared the benchmark.</div>';
  }

  const shown = host.querySelectorAll('.row:not(.ghost)').length;
  const count = document.getElementById('line-count');
  if (count) {
    count.textContent = S.filter === 'flagged'
      ? `${shown} of ${S.project.lines.length}` : `${shown} lines`;
  }

  // The DOM was just replaced, so every cached element reference is dead.
  S.rows.clear();
  for (const row of host.querySelectorAll('.row:not(.ghost)')) {
    S.rows.set(+row.dataset.index, row);
  }
  S.hl = { row: null, word: null, line: -1 };

  // A rebuild (filter switch, re-score) drops the word highlight and may leave
  // S.selWord pointing past the end of a re-aligned line.
  const line = S.project.lines[S.sel];
  if (S.selWord != null && S.selWord >= ((line && line.words) || []).length) S.selWord = null;
  paintSelWord();
}

function renderRow(line) {
  const row = document.createElement('div');
  row.className = 'row'
    + (line.flagged ? ' flagged' : '')
    + (S.todoLines.has(line.index) ? ' has-todo' : '')
    + (line.index === S.sel ? ' selected' : '');
  row.dataset.index = line.index;

  const score = (line.score && line.score.total) || 0;
  const words = (line.words || []).map((w, i) => {
    const todo = S.todo.get(`${line.index}:${i}`);
    return `<span class="w${todo ? ' todo' : ''}" data-i="${i}" ` +
      `data-s="${w.start}" data-e="${w.end}"` +
      (todo ? ` title="${escapeHtml(todo.reasons[0] || 'needs checking')}"` : '') +
      `>${escapeHtml(w.text)}</span>`;
  }).join(' ');

  const issues = (line.score && line.score.issues) || [];
  row.innerHTML =
    `<div class="idx">${line.index}</div>` +
    `<div class="times">${fmt(line.start)} → ${fmt(line.end)}</div>` +
    `<div class="text">${words || escapeHtml(line.text)}</div>` +
    `<div class="issues"${issues.length ? ` title="${escapeHtml(issues.join(' · '))}"` : ''}>` +
      (issues.length ? `▲ ${escapeHtml(issues.join(' · '))}` : '') + '</div>' +
    `<div class="score ${grade(score)}">${score.toFixed(0)}</div>`;

  row.addEventListener('click', e => {
    const wordEl = e.target.closest && e.target.closest('.w');
    if (wordEl) { pickWord(line.index, +wordEl.dataset.i); return; }
    S.lyricHoldUntil = 0;
    select(line.index);
    focusLine(line);
    draw();
    preview(line);
  });
  return row;
}

/**
 * A line the lyrics file does not have, offered in the place it would occupy.
 *
 * Dashed rather than drawn, and never counted in the list's total: it is a
 * question, not a lyric, until somebody says so.
 */
function renderGhost(cand) {
  const row = document.createElement('div');
  row.className = 'row ghost';
  row.dataset.add = cand.id;
  row.innerHTML =
    '<div class="idx">+</div>' +
    `<div class="times">${fmt(cand.start)} → ${fmt(cand.end)}</div>` +
    `<div class="text">${escapeHtml(cand.text)}` +
      `<span class="ghost-note">heard here · line ${cand.like_line}'s text` +
      `</span></div>` +
    '<div class="ghost-acts">' +
      '<button class="g-hear" title="Play what was heard">▶</button>' +
      '<button class="g-add" title="Add this line to the project">Add line</button>' +
      '<button class="g-no" title="Not a line — do not offer it again">✕</button>' +
    '</div>';

  const at = () => adPending().findIndex(a => a.id === cand.id);
  row.querySelector('.g-hear').addEventListener('click', e => {
    e.stopPropagation();
    S.addAt = Math.max(0, at());
    adPlay();
  });
  row.querySelector('.g-add').addEventListener('click', e => {
    e.stopPropagation();
    S.addAt = Math.max(0, at());
    adDecide('accept');
  });
  row.querySelector('.g-no').addEventListener('click', e => {
    e.stopPropagation();
    S.addAt = Math.max(0, at());
    adDecide('dismiss');
  });
  row.addEventListener('click', () => {
    setView(cand.start - 2, Math.max(6, (cand.end - cand.start) * 2.4));
    S.audio.currentTime = Math.max(0, cand.start - 0.4);
    draw();
  });
  return row;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function refreshRow(line) {
  if (line.index === S.sel) renderPlaceBar();
  const row = S.rows.get(line.index);
  if (!row) return;
  row.querySelector('.times').textContent = `${fmt(line.start)} → ${fmt(line.end)}`;
  // The karaoke highlight reads these back every frame, so they have to track.
  const els = row.querySelectorAll('.w');
  (line.words || []).forEach((w, i) => {
    if (!els[i]) return;
    els[i].dataset.s = w.start;
    els[i].dataset.e = w.end;
  });
}

/**
 * Select a line. `keepView` holds the viewport still: scrolling a partly
 * visible line into view is helpful when you arrow onto it, and a bug when you
 * grabbed it with the mouse - the ground would move under the drag and every
 * delta after it would be measured against the wrong origin.
 */
function select(index, keepView) {
  if (index == null || index < 0 || index >= S.project.lines.length) return;
  S.sel = index;
  S.selWord = null;
  paintSelWord();
  for (const el of document.querySelectorAll('.row.selected')) el.classList.remove('selected');
  const row = S.rows.get(index);
  if (row) {
    row.classList.add('selected');
    row.scrollIntoView({ block: 'nearest' });
  }
  if (!keepView) ensureVisible(S.project.lines[index]);
  renderPlaceBar();
  draw();
}

function ensureVisible(line) {
  if (!line || line.end <= line.start) return;
  const span = line.end - line.start;
  if (line.start < S.view.start || line.end > S.view.start + S.view.dur) {
    setView(line.start - Math.max(1.5, span * 0.4), Math.max(S.view.dur, span * 2.2));
  }
}

/** Zoom the view onto one line, close enough to do word work in it. */
function focusLine(line) {
  if (!line || line.end <= line.start) return;
  const span = line.end - line.start;
  const dur = Math.max(4, span * 2.5);
  setView(line.start + span / 2 - dur / 2, dur);
}

function preview(line) {
  if (!line || line.end <= line.start) return;
  S.audio.currentTime = Math.max(0, line.start - 1.0);
  S.audio.play();
}

/* --------------------------------------------------------- word selection */

function paintSelWord() {
  for (const el of document.querySelectorAll('.w.sel')) el.classList.remove('sel');
  if (S.selWord == null) return;
  const row = S.rows.get(S.sel);
  const el = row && row.querySelectorAll('.w')[S.selWord];
  if (el) el.classList.add('sel');
}

function selectWord(lineIndex, wordIndex, focus) {
  const line = S.project.lines[lineIndex];
  if (!line) return;
  const changedLine = lineIndex !== S.sel;
  if (changedLine) select(lineIndex, focus === false);
  const ws = line.words || [];
  S.selWord = ws.length ? clamp(wordIndex, 0, ws.length - 1) : null;
  // focus === false means the click came from the word lane: the word is
  // already on screen, and moving the view would yank it out from under a drag.
  if (focus === false) { /* leave the view alone */ }
  else if (S.selWord != null && (focus || changedLine)) focusLine(line);
  else ensureVisible(line);
  paintSelWord();
  draw();
}

function deselectWord() {
  S.selWord = null;
  paintSelWord();
  draw();
}

/** The primary entry point: you heard a word land wrong, so you click it. */
function pickWord(lineIndex, wordIndex) {
  const line = S.project.lines[lineIndex];
  const word = ((line && line.words) || [])[wordIndex];
  if (!word) return;
  selectWord(lineIndex, wordIndex, true);
  S.audio.currentTime = Math.max(0, word.start - 0.4);
  S.audio.play();
}

/** Tab / shift+Tab, rolling into the adjacent line at either end. */
function stepWord(dir) {
  const cursors = wordCursors();
  if (!cursors.length) return;
  let at;
  if (S.selWord != null) {
    at = cursors.findIndex(([li, wi]) => li === S.sel && wi === S.selWord) + dir;
  } else {
    const here = [];
    cursors.forEach(([li], k) => { if (li === S.sel) here.push(k); });
    at = here.length ? (dir > 0 ? here[0] : here[here.length - 1])
      : (dir > 0 ? 0 : cursors.length - 1);
  }
  if (at < 0 || at >= cursors.length) return;
  selectWord(cursors[at][0], cursors[at][1]);
}

/* ---------------------------------------------------------------- scorecard */

function renderScorecard(card) {
  const host = document.getElementById('scorecard');
  if (!card || !card.n_lines) { host.innerHTML = ''; return; }

  const delta = card.median_start_delta;
  // Terse labels keep the bar to one row; the full wording is the tooltip.
  const chips = [
    ['aligned', `${card.n_aligned}/${card.n_lines}`, 'good', 'lines that carry timings'],
    ['Δ median', delta == null ? 'n/a' : `${Math.round(delta * 1000)} ms`,
      delta == null ? '' : delta <= 0.15 ? 'good' : delta <= 0.3 ? 'ok' : 'bad',
      'median start disagreement between the two aligners'],
    ['≤300ms', `${Math.round(card.pct_within_300ms)}%`,
      card.pct_within_300ms >= 85 ? 'good' : card.pct_within_300ms >= 70 ? 'ok' : 'bad',
      'lines where the two aligners agree within 300 ms'],
    ['coverage', `${Math.round(card.mean_coverage * 100)}%`,
      card.mean_coverage >= 0.7 ? 'good' : card.mean_coverage >= 0.5 ? 'ok' : 'bad',
      'mean share of each line span that is actually vocal'],
    ['score', `${card.mean_score.toFixed(0)}`, grade(card.mean_score), 'mean line score out of 100'],
    ['review', `${card.n_flagged}`, card.n_flagged ? 'bad' : 'good', 'lines flagged for review'],
  ];
  host.innerHTML = chips.map(([label, value, tone, title]) =>
    `<span class="chip ${tone}" title="${title}">${label} <b>${value}</b></span>`).join('');
}

/* ---------------------------------------------------------------- playback */

/* How long a manual scroll of the lyrics suspends auto-following. Long enough
   to read ahead without being yanked back, short enough to resume by itself. */
const LYRIC_HOLD_MS = 4000;

const REDUCED_MOTION = matchMedia('(prefers-reduced-motion: reduce)');

/**
 * Bring the playing line into view, biased high so you can read ahead.
 *
 * `jumped` says the song did not simply advance a line - a seek, a click, the
 * first line after Follow came on. Those snap: a long smooth scroll is just a
 * distraction you have to sit through before you can read anything.
 */
function followLyrics(row, jumped) {
  const host = S.el.lyrics;
  if (!row || !host) return;
  const hostBox = host.getBoundingClientRect();
  const rowBox = row.getBoundingClientRect();
  const top = Math.max(0, host.scrollTop + (rowBox.top - hostBox.top) - hostBox.height * 0.36);
  if (Math.abs(top - host.scrollTop) < 1) return;
  host.scrollTo({ top, behavior: jumped || REDUCED_MOTION.matches ? 'auto' : 'smooth' });
}

/** Move the playing/active classes, touching only the elements that changed. */
function paintPlayback(active, t) {
  if (active !== S.hl.line) {
    const previous = S.hl.line;
    if (S.hl.row) S.hl.row.classList.remove('playing');
    const row = active >= 0 ? S.rows.get(active) : null;
    if (row) row.classList.add('playing');
    S.hl.row = row || null;
    S.hl.line = active;
    S.hl.word = null;
    // Only chase the lyrics when the line actually changes - a few times a
    // minute, not sixty times a second.
    if (row && S.follow && performance.now() >= S.lyricHoldUntil) {
      followLyrics(row, previous < 0 || Math.abs(active - previous) > 1);
    }
  }

  if (!S.hl.row) return;
  let hit = null;
  for (const el of S.hl.row.querySelectorAll('.w')) {
    if (t >= +el.dataset.s && t <= +el.dataset.e) { hit = el; break; }
  }
  if (hit !== S.hl.word) {
    if (S.hl.word) S.hl.word.classList.remove('on');
    if (hit) hit.classList.add('on');
    S.hl.word = hit;
  }
}

function tick() {
  const t = S.audio.currentTime;
  const playing = !S.audio.paused;

  // Idle frames must cost nothing: when the playhead has not moved and no edit
  // has landed, there is nothing new to show.
  if (t !== S.lastT || S.stale || S.flash) {
    const clock = `${fmt(t)} / ${fmt(duration())}` + (S.rate !== 1 ? `  ${S.rate}×` : '');
    if (clock !== S.el.clockText) {
      S.el.clock.textContent = clock;
      S.el.clockText = clock;
    }

    if (S.follow && playing) {
      const rel = (t - S.view.start) / S.view.dur;
      if (rel > 0.72 || rel < 0) setView(t - S.view.dur * 0.3, S.view.dur);
    }

    let active = -1;
    for (const line of S.project.lines) {
      if (t >= line.start && t <= line.end && line.end > line.start) { active = line.index; break; }
    }
    paintPlayback(active, t);

    draw();
    // The strip only needs frames for the preview playhead and the snap ring,
    // and this block only runs when one of those is actually moving.
    if (S.review.strip) rvDrawStrip();
    if (!RV('rv-add').hidden) adDraw();
    S.lastT = t;
  }

  S.raf = requestAnimationFrame(tick);
}

/* ---------------------------------------------------------------- edits */

function nudge(delta) {
  const line = S.project.lines[S.sel];
  if (!line || line.end <= line.start) return;
  pushCoalesced('nudge line', line);
  retimeLine(line, line.start + delta, line.end + delta);
  refreshRow(line);
  ensureVisible(line);
  draw();
}

function setEdge(which) {
  const line = S.project.lines[S.sel];
  if (!line) return;
  pushHistory(`set line ${which}`, [line]);
  const t = S.audio.currentTime;
  if (which === 'start') retimeLine(line, t, Math.max(t + 0.25, line.end));
  else retimeLine(line, Math.min(line.start, t - 0.25), t);
  refreshRow(line);
  draw();
}

/** Keep the placement bar showing whatever line the buttons would act on. */
function renderPlaceBar() {
  const line = S.project.lines[S.sel];
  const btn = S.el.placeBtn;
  if (!line) { btn.disabled = true; return; }
  S.el.placeIdx.textContent = `line ${line.index}`;
  S.el.placeText.textContent = line.text;
  S.el.placeTime.textContent = line.end > line.start
    ? `${fmt(line.start)} → ${fmt(line.end)}` : 'not placed yet';
  btn.disabled = false;
}

/**
 * Move the selected line so it begins at the playhead, keeping its length.
 *
 * This is the "put this lyric here" primitive: scrub to the moment, press the
 * button. Length is preserved because the words inside are already spaced
 * correctly relative to each other far more often than they are not.
 */
function placeLineAtPlayhead() {
  const line = S.project.lines[S.sel];
  if (!line) return;
  pushHistory('place line', [line]);
  const t = S.audio.currentTime;
  const span = Math.max(0.4, line.end - line.start);
  retimeLine(line, t, t + span);
  refreshRow(line);
  renderPlaceBar();
  ensureVisible(line);
  draw();
  toast(`line ${line.index} placed at ${fmt(t)}`);
}

/** Tap-along: stamp the selected line's start at the playhead, then advance. */
function tap() {
  if (!S.project.lines[S.sel]) return;
  placeLineAtPlayhead();
  select(Math.min(S.sel + 1, S.project.lines.length - 1));
}

/** Nudge the selected word's start. Returns false if no word is selected. */
function nudgeWord(delta) {
  const line = S.project.lines[S.sel];
  const ws = (line && line.words) || [];
  if (S.selWord == null || !ws[S.selWord]) return false;
  pushCoalesced('nudge word', line);
  setWordStart(line, S.selWord, ws[S.selWord].start + delta);
  refreshRow(line);
  draw();
  return true;
}

/** Word tap-along: stamp the selected word's start at the playhead, advance. */
function tapWord() {
  const line = S.project.lines[S.sel];
  const ws = (line && line.words) || [];
  if (!ws.length) return;
  if (S.selWord == null) { selectWord(S.sel, 0); return; }  // arm, don't stamp
  pushHistory('stamp word', [line]);
  setWordStart(line, S.selWord, S.audio.currentTime);
  refreshRow(line);
  stepWord(1);
}

/* ------------------------------------------------------- guided review

   The expert path is the timeline. This is the other one: the machine has
   already repaired everything provably wrong and thrown away every word the two
   aligners agree on, so what is left is a short list of genuine judgement calls.
   Each is presented as "listen to these two, pick the one that starts on the
   word" - no timeline, no dragging, no vocabulary to learn. */

const RV = id => document.getElementById(id);
const rvPanes = ['rv-intro', 'rv-busy', 'rv-add', 'rv-card', 'rv-done'];

function rvShow(which) {
  for (const id of rvPanes) RV(id).hidden = id !== which;
  S.review.strip = which === 'rv-card';
}

function rvBadge() {
  const n = S.review.queue.filter(i => !i.done).length;
  const done = !n && !!S.review.stats;
  const btn = RV('btn-review');
  btn.textContent = n ? `Check timings (${n})` : done ? 'All clear' : 'Check timings';
  btn.classList.toggle('has-work', n > 0);
  btn.classList.toggle('all-clear', done);
}

/** Index the queue so the lyrics panel and word cells can mark it in place. */
function indexTodo() {
  S.todo.clear();
  S.todoLines.clear();
  for (const item of S.review.queue) {
    if (item.done) continue;
    S.todo.set(`${item.line}:${item.word}`, item);
    S.todoLines.add(item.line);
  }
}

async function loadAudit() {
  try {
    const data = await (await fetch(api('/api/audit'))).json();
    S.review.queue = data.queue || [];
    S.review.additions = null;
    S.additions = data.additions || [];
    S.review.stats = data.never_run ? null : data;
    indexTodo();
    rvBadge();
  } catch { /* an audit is optional; the timeline works without one */ }
}

function openReview() {
  const dlg = RV('review');
  S.review.wasSolo = S.solo;
  S.review.applied = 0;
  // The dialog has to be up before the card renders: a strip measured while
  // the sheet is still closed is 0 px wide and cannot lay itself out.
  dlg.showModal();
  // A missing line comes first: the word queue below it is a list of timings
  // inside lines, and one of the lines is not there yet.
  if (adPending().length) {
    S.addAt = 0;
    rvShow('rv-add');
    adRender();
    rvSyncSolo();
    return;
  }
  rvShow(S.review.queue.length ? 'rv-card' : 'rv-intro');
  if (S.review.queue.length) { S.review.at = 0; rvRender(); rvSyncSolo(); }
}

function closeReview() {
  rvStopPlay();
  S.review.strip = false;
  S.review.drag = null;
  if (S.solo !== S.review.wasSolo) setSolo(S.review.wasSolo);
  RV('review').close();
}

async function runAudit() {
  if (needsServer('Re-running the check')) return;
  rvShow('rv-busy');
  let data;
  try {
    const res = await fetch('/api/audit', { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
    data = await res.json();
  } catch (err) {
    rvShow('rv-intro');
    toast('could not check timings: ' + err.message, true);
    return;
  }

  // The repair pass edits the project server-side, so take the fresh copy.
  S.project = await (await fetch(api('/api/project'))).json();
  resetHistory();                            // the repair pass replaced the project
  S.review = { ...S.review, queue: data.queue || [], at: 0, stats: data };
  S.additions = data.additions || [];
  S.addAt = 0;
  indexTodo();
  renderList();
  draw();
  rvBadge();

  if (data.repairs && data.repairs.length) {
    toast(`repaired ${data.repairs.length} impossible timing(s) automatically`);
  }
  if (adPending().length) { rvShow('rv-add'); adRender(); rvSyncSolo(); return; }
  if (!S.review.queue.length) { rvFinish(); return; }
  rvShow('rv-card');
  rvRender();
  rvSyncSolo();
}

function rvCurrent() { return S.review.queue[S.review.at]; }

function rvRender() {
  const item = rvCurrent();
  if (!item) return rvFinish();
  const total = S.review.queue.length;

  // A new word is a clean slate: no adjustment carried over, nothing armed.
  S.review.adj = null;
  S.review.drag = null;
  S.review.lastPlayed = null;

  RV('rv-count').textContent = `Word ${S.review.at + 1} of ${total}`;
  RV('rv-where').textContent = `line ${item.line}`;
  RV('rv-progress-fill').style.width = `${(S.review.at / total) * 100}%`;

  // ⸤word⸥ marks the word under judgement; render it as the highlight.
  RV('rv-context').innerHTML = escapeHtml(item.context)
    .replace('⸤', '<b>').replace('⸥', '</b>');

  RV('rv-reasons').innerHTML = item.reasons
    .map(r => `<li>${escapeHtml(r)}</li>`).join('');

  RV('rv-cur-time').textContent = fmt(item.current);
  RV('rv-new-time').textContent = fmt(item.proposed);

  const later = item.delta > 0;
  const dragNote = item.scope === 'line'
    ? ' Drag the strip to shift the whole proposed placement.'
    : ' If neither is right, drag the strip to put the word where you hear it.';
  RV('rv-hint').innerHTML = (item.scope === 'line'
    ? 'The second model puts this word outside the line altogether, so the whole ' +
      'line looks misplaced. <em>Use suggested</em> re-times the entire line.'
    : `Each button plays from the moment that version says the word begins. ` +
      `The right one starts <em>on</em> the word. ` +
      `(${Math.abs(item.delta).toFixed(2)}s ${later ? 'later' : 'earlier'})`)
    + dragNote + ' <em>space</em> replays the last one you heard.';

  // Restart the arrival animation, so advancing reads as the next card coming
  // in rather than this one's text being swapped underneath you.
  const card = RV('rv-card');
  card.classList.remove('stepped');
  void card.offsetWidth;
  card.classList.add('stepped');

  rvSetWindow(item);
  if (rvLayoutStrip()) rvDrawStrip();
  rvSyncAdj();                          // also owns the primary button's label
  syncHistory();
}

/** Play from exactly where a version claims the word starts - the whole test. */
function rvPlayFrom(t, which) {
  const item = rvCurrent();
  if (which) S.review.lastPlayed = which;
  const line = S.project.lines[item.line];
  const w = line && line.words[item.word];
  const span = clamp(w ? (w.end - w.start) + 0.4 : 1.0, 0.8, 1.6);
  rvStopPlay();
  S.audio.currentTime = Math.max(0, t);
  S.audio.play();
  // The strip only gets frames while the audio is moving, so the playhead has
  // to be cleared off it by the same timer that stops the preview.
  S.review.stop = setTimeout(() => { S.audio.pause(); rvDrawStrip(); },
                             (span / S.rate) * 1000);
}

function rvStopPlay() {
  clearTimeout(S.review.stop);
  S.review.stop = 0;
}

/** Space: hear again whatever you heard last, adjusted included. */
function rvReplay() {
  const item = rvCurrent();
  if (!item) return;
  const which = S.review.lastPlayed;
  if (which === 'adj' && S.review.adj) rvPlayFrom(rvAdjPlay(item), 'adj');
  else if (which === 'new') rvPlayFrom(item.proposed, 'new');
  else rvPlayFrom(item.current, 'cur');
}

function rvSyncSolo() {
  const want = RV('rv-solo').checked;
  if (S.solo !== want) setSolo(want);
}

function rvDecide(action) {
  const item = rvCurrent();
  if (!item) return;
  const line = S.project.lines[item.line];
  // An adjustment is just a third candidate: same one entry, same apply paths,
  // so cmd-Z after the sheet is closed takes it back exactly like an accept.
  const adj = action === 'accept' ? S.review.adj : null;

  // Every decision is undoable, not just the ones that edited something: a
  // mis-clicked "keep as is" is exactly as worth taking back as a mis-accept.
  // These land on the same stack as timeline edits, so a decision can still be
  // taken back with cmd-Z after the sheet is closed.
  pushHistory(action === 'accept' ? (adj ? 'use adjusted' : 'use suggested') : `${action} word`,
              action === 'accept' && line ? [line] : [],
              snapReview(S.review.at));

  if (action === 'accept' && line) {
    if (item.scope === 'line') {
      const lp = rvProposal(item);
      if (lp) {
        // A line-scope adjustment shifts the whole proposed placement, so it is
        // one offset applied to the line's edges and to every word start in it.
        const off = adj ? adj.t - item.proposed : 0;
        retimeLine(line, lp.start + off, lp.end + off);
        // retimeLine rescales words; the proposal has real per-word starts.
        lp.starts.forEach((t, i) => { if (line.words[i]) line.words[i].start = t + off; });
        line.start = lp.starts[0] + off;
        normalizeWords(line);
        markDirty();
      }
    } else {
      setWordStart(line, item.word, adj ? adj.t : item.proposed);
    }
    refreshRow(line);
    draw();
    S.review.applied = (S.review.applied || 0) + 1;
  }

  if (action !== 'skip') {
    item.done = true;                   // decided: stop marking it as pending
    indexTodo();
    rvBadge();
    syncTodoMark(item);
    draw();
  }

  S.review.adj = null;
  S.review.at++;
  if (S.review.at >= S.review.queue.length) return rvFinish();
  rvRender();
}

/** The sheet's own button walks the shared history, but only over decisions. */
function rvUndo() {
  const top = S.hist.undo[S.hist.undo.length - 1];
  if (!top || !top.review) return;
  undoEdit();
  rvShow('rv-card');
  rvRender();
}

function rvFinish() {
  rvStopPlay();
  const st = S.review.stats || {};
  const applied = S.review.applied || 0;
  RV('rv-done-title').textContent = applied ? 'Nice work' : 'All checked';
  RV('rv-summary').innerHTML =
    `${st.n_verified || 0} of ${st.n_words || 0} words were agreed on by both models and left alone. ` +
    (st.repairs && st.repairs.length
      ? `${st.repairs.length} impossible timing${st.repairs.length === 1 ? ' was' : 's were'} repaired automatically. ` : '') +
    `You changed ${applied} word${applied === 1 ? '' : 's'}.`;
  RV('rv-progress-fill').style.width = '100%';
  rvShow('rv-done');
}

function rvShowOnTimeline() {
  const item = rvCurrent();
  closeReview();
  if (item) selectWord(item.line, item.word, true);
}

/* --------------------------------------------- review: the waveform strip

   The card used to be audio-only. You could hear both candidates and see
   neither, and when both were wrong the only way out was to leave for the
   timeline - which is exactly the thing this path exists to spare you. The
   strip closes that: the disputed word's neighbourhood, both candidates on it,
   and a third one you place yourself.

   It keeps its own time<->x mapping on purpose. drawWave and t2x are wired to
   the main canvas's module-global ctx and to S.view; borrowing them would tie
   this strip to the viewport and let a drag in here scroll the timeline
   underneath, which is the bug class that ate a previous afternoon. */

const RV_H = 72;                  // strip height, css px
const RV_PAD = 0.75;              // air either side of what is being judged
const RV_GRAB = 7;                // px either side of a marker that grabs it

let rvCtx = null;
const RVW = { a: 0, b: 1, w: 0 };  // the strip's own window, over w css px

const rvT2X = t => (t - RVW.a) / (RVW.b - RVW.a) * RVW.w;
const rvX2T = x => RVW.a + (x / RVW.w) * (RVW.b - RVW.a);

function rvProposal(item) {
  const all = (S.review.stats && S.review.stats.line_proposals) || {};
  return all[String(item.line)] || null;
}

/**
 * The three candidates, always as "where this version says the word begins".
 *
 * That is the one thing all three buttons already mean, so markers, time
 * readouts, previews and nudges share a single space in both scopes. Line scope
 * differs in what an adjustment *does* - it shifts the whole proposed placement
 * by the same offset, drawn as the bands behind the markers - not in what the
 * marker points at. Keeping one space keeps one drag, one clamp, one nudge.
 */
function rvCands() {
  const item = rvCurrent();
  if (!item) return null;
  return {
    cur: item.current,
    alt: item.proposed,
    adj: S.review.adj ? S.review.adj.t : null,
  };
}

/** How far a line-scope adjustment moves the proposed placement. */
function rvOffset(item) {
  return S.review.adj ? S.review.adj.t - item.proposed : 0;
}

/** The moment the adjusted version says the word begins - what to play. */
function rvAdjPlay(item) {
  if (!item) return 0;
  return S.review.adj ? S.review.adj.t : item.current;
}

/**
 * Fix the window for this item: everything being judged, plus a little air.
 *
 * Set once per item and never moved. A window that shifted mid-drag would
 * change the meaning of every pixel already travelled.
 */
function rvSetWindow(item) {
  const line = S.project.lines[item.line];
  let a = line ? line.start : item.current;
  let b = line ? line.end : item.current + 1;
  const c = rvCands();
  for (const t of [c.cur, c.alt]) {
    if (t == null) continue;
    a = Math.min(a, t);
    b = Math.max(b, t);
  }
  if (item.scope === 'line') {
    const lp = rvProposal(item);
    if (lp) { a = Math.min(a, lp.start); b = Math.max(b, lp.end); }
  }
  const w = line && line.words && line.words[item.word];
  if (w) b = Math.max(b, w.end);
  RVW.a = Math.max(0, a - RV_PAD);
  RVW.b = Math.max(RVW.a + 0.5, b + RV_PAD);
}

function rvLayoutStrip() {
  const el = RV('rv-wave');
  const w = el.clientWidth;
  if (!w) return false;                 // sheet still closed: nothing to measure
  const dpr = window.devicePixelRatio || 1;
  if (!rvCtx) rvCtx = el.getContext('2d');
  el.width = Math.round(w * dpr);
  el.height = Math.round(RV_H * dpr);
  rvCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  RVW.w = w;
  return true;
}

function rvBand(g, a, b, fill) {
  const x0 = rvT2X(a), x1 = rvT2X(b);
  g.fillStyle = fill;
  g.fillRect(x0, 0, Math.max(1, x1 - x0), RV_H);
}

/** One candidate: a hairline through the audio with a grab tab on top. */
function rvMarker(g, t, color, strong) {
  const x = rvT2X(t);
  if (x < -8 || x > RVW.w + 8) return;
  g.globalAlpha = strong ? 1 : 0.72;
  g.fillStyle = color;
  g.fillRect(x - 0.75, 0, 1.5, RV_H);
  g.beginPath();
  g.moveTo(x - 5.5, 0);
  g.lineTo(x + 5.5, 0);
  g.lineTo(x, 7);
  g.closePath();
  g.fill();
  g.globalAlpha = 1;
}

/** The same "locked on" ring the timeline draws, in the strip's own window. */
function rvFlashRing(g) {
  if (!S.flash) return;
  const age = performance.now() - S.flash.at;
  if (age >= FLASH_MS) return;          // drawSnapFlash owns clearing it
  const k = clamp(1 - age / FLASH_MS, 0, 1);
  const x = rvT2X(S.flash.t);
  if (x < -24 || x > RVW.w + 24) return;
  g.strokeStyle = `rgba(62,207,142,${0.55 * k})`;
  g.lineWidth = 1.5;
  g.beginPath();
  g.arc(x + 0.25, RV_H / 2, 4 + 14 * (1 - k), 0, Math.PI * 2);
  g.stroke();
}

/* Both strips draw the same instrument over different windows, so they share
   the painting and differ only in what they overlay on it. */

function stripBed(g, W, H) {
  const bed = g.createLinearGradient(0, 0, 0, H);
  bed.addColorStop(0, '#0d121c');
  bed.addColorStop(0.5, '#111724');
  bed.addColorStop(1, '#0b0f17');
  g.fillStyle = bed;
  g.fillRect(0, 0, W, H);
}

function stripWave(g, W, H, a, b) {
  const span = b - a, mid = H / 2, half = H / 2 - 5;
  const toT = x => a + (x / W) * span;
  const mask = vocalMask(W, toT);
  for (let sung = 0; sung < 2; sung++) {
    g.fillStyle = sung ? waveGradient(g, 0, H) : 'rgba(104,150,214,.26)';
    g.beginPath();
    for (let x = 0; x < W; x++) {
      if (mask[x] !== sung) continue;
      const v = peakRange(S.an.vocal_peaks, S.an.rate, toT(x), toT(x + 1));
      const bar = Math.max(0.6, v * half);
      g.rect(x, mid - bar, 1, bar * 2);
    }
    g.fill();
  }
  g.fillStyle = C.onset;
  for (const t of S.an.onsets) {
    if (t < a) continue;
    if (t > b) break;
    g.fillRect((t - a) / span * W, H - 7, 1, 7);
  }
}

function rvDrawStrip() {
  const item = rvCurrent();
  const g = rvCtx;
  if (!item || !g || !RVW.w || !S.an) return;
  const W = RVW.w, span = RVW.b - RVW.a;

  stripBed(g, W, RV_H);

  const line = S.project.lines[item.line];
  const c = rvCands();

  // What is under judgement, shaded: one word, or - when the second aligner
  // put the word outside the line - the whole line at both placements.
  if (item.scope === 'line') {
    const lp = rvProposal(item);
    if (line) rvBand(g, line.start, line.end, 'rgba(91,157,255,.13)');
    if (lp) {
      const off = rvOffset(item);
      rvBand(g, lp.start + off, lp.end + off,
             c.adj == null ? 'rgba(62,207,142,.12)' : 'rgba(180,140,255,.13)');
    }
  } else {
    const w = line && line.words[item.word];
    if (w) rvBand(g, w.start, w.end, 'rgba(91,157,255,.13)');
  }

  // The vocal itself - the only evidence any of this is decided on - and the
  // onset ticks a snap lands on, so a snap is never a surprise.
  stripWave(g, W, RV_H, RVW.a, RVW.b);

  // The adjusted one, when it exists, is the live one; the other two dim.
  if (c.cur != null) rvMarker(g, c.cur, C.sel, c.adj == null);
  if (c.alt != null) rvMarker(g, c.alt, C.good, c.adj == null);
  if (c.adj != null) rvMarker(g, c.adj, C.adj, true);

  rvFlashRing(g);

  if (!S.audio.paused) {
    const t = S.audio.currentTime;
    if (t >= RVW.a && t <= RVW.b) {
      g.fillStyle = C.head;
      g.fillRect(rvT2X(t), 0, 1.5, RV_H);
    }
  }
}

/* --------------------------------------------- the adjusted candidate */

/**
 * The range the model would actually accept.
 *
 * Word scope mirrors setWordStart's clamp exactly, so the strip can never show
 * a position that would be silently dragged somewhere else on accept. Line
 * scope has no such neighbours - the whole line moves - so it is held to the
 * drawn window, which already spans both placements plus the padding.
 */
function rvRange(item) {
  const line = S.project.lines[item.line];
  // A line-scope drag has no neighbouring words to answer to - the whole line
  // rides along - so it is held to the drawn window, which already spans both
  // placements and the padding either side of them.
  if (item.scope === 'line') return [Math.max(0, RVW.a), RVW.b];
  const ws = (line && line.words) || [];
  const i = item.word;
  const lo = i === 0 ? 0 : ws[i - 1].start + MIN_WORD;
  const hi = (i + 1 < ws.length ? ws[i + 1].start : line.end) - MIN_WORD;
  return [lo, Math.max(lo, hi)];
}

function rvClampT(item, t) {
  const [lo, hi] = rvRange(item);
  return clamp(t, lo, hi);
}

/** Place the adjusted candidate. `free` is alt: take the time literally. */
function rvSetAdj(t, free) {
  const item = rvCurrent();
  if (!item) return;
  const snapped = free ? t : snapOnset(t);
  const out = rvClampT(item, snapped);
  // Flash only on a snap that survived the clamp - a ring on a boundary the
  // model then moved would be a lie about what just happened.
  if (snapped !== t && out === snapped) S.flash = { t: out, at: performance.now() };
  S.review.adj = { t: out };
  rvSyncAdj();
  rvDrawStrip();
}

function rvResetAdj() {
  S.review.adj = null;
  if (S.review.lastPlayed === 'adj') S.review.lastPlayed = null;
  rvSyncAdj();
  rvDrawStrip();
}

/**
 * Nudge by 50 ms (shift: 10 ms), creating the adjusted candidate from whichever
 * one is armed - the last you listened to, or else the suggestion, which is
 * what the primary button would take.
 */
function rvNudgeAdj(delta) {
  const item = rvCurrent();
  if (!item) return;
  const c = rvCands();
  const base = c.adj != null ? c.adj
    : S.review.lastPlayed === 'cur' ? c.cur
    : c.alt != null ? c.alt : c.cur;
  if (base == null) return;
  S.review.adj = { t: rvClampT(item, base + delta) };
  rvSyncAdj();
  rvDrawStrip();
}

/** Everything that changes the moment a third candidate exists. */
function rvSyncAdj() {
  const item = rvCurrent();
  const on = !!S.review.adj;
  RV('rv-ab').classList.toggle('has-adj', on);
  RV('rv-opt-adj').hidden = !on;
  RV('rv-key-adj').hidden = !on;
  RV('rv-adj-reset').hidden = !on;
  RV('rv-strip-hint').hidden = on;
  if (on && item) RV('rv-adj-time').textContent = fmt(rvAdjPlay(item));
  RV('rv-accept').textContent = on ? 'Use adjusted'
    : item && item.scope === 'line' ? 'Use suggested for the line' : 'Use suggested';
}

/* --------------------------------------------- dragging the strip */

function rvStripDown(e) {
  const item = rvCurrent();
  if (!item || !RVW.w) return;
  e.preventDefault();
  const x = e.clientX - RV('rv-wave').getBoundingClientRect().left;
  const c = rvCands();

  // Grabbing a marker drags from where that marker is, so a candidate can be
  // refined without first jumping to the cursor. Clicking bare waveform is the
  // blunt version of the same thing: put it here.
  let from = rvX2T(x), near = RV_GRAB + 1;
  for (const t of [c.adj, c.alt, c.cur]) {
    if (t == null) continue;
    const d = Math.abs(rvT2X(t) - x);
    if (d < near) { near = d; from = t; }
  }
  S.review.drag = { x0: x, t0: from };
  if (near > RV_GRAB) rvSetAdj(from, e.altKey);
}

function rvStripMove(e) {
  const d = S.review.drag;
  if (!d) return;
  const x = e.clientX - RV('rv-wave').getBoundingClientRect().left;
  rvSetAdj(d.t0 + (x - d.x0) * (RVW.b - RVW.a) / RVW.w, e.altKey);
}

function rvStripUp() { S.review.drag = null; }

/* ------------------------------------------------- lines the lyrics lack

   A lyrics file is typed by hand and hands drop things - most often a chorus
   repeat, because it is the line already typed three times. The aligner cannot
   notice: it is told the lyrics and consumes them in order, so the omission
   shows up as a hole nobody looks in. See gaps.py for how a candidate is found
   and, more importantly, how the bad ones are refused.

   Approving is deliberately not a writing task. Every proposal is text already
   in the lyrics, so the only question put to a human is the one an ear can
   answer in five seconds: is that line sung here? */

const AD_H = 72;
const AD_PAD = 1.2;                  // context either side of what was heard
let adCtx = null;
const ADW = { a: 0, b: 1, w: 0 };

function adPending() {
  return (S.additions || []).filter(a => !a.dismissed);
}

function adCurrent() { return adPending()[S.addAt || 0] || null; }

function adLayout() {
  const el = RV('ad-wave');
  const w = el.clientWidth;
  if (!w) return false;
  const dpr = window.devicePixelRatio || 1;
  if (!adCtx) adCtx = el.getContext('2d');
  el.width = Math.round(w * dpr);
  el.height = Math.round(AD_H * dpr);
  adCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ADW.w = w;
  return true;
}

/**
 * The heard span with room either side.
 *
 * Reaching out far enough to always show a neighbouring line is tempting and
 * wrong: the hole on the sample track is 45.8 s, so a window wide enough to
 * touch both ends would render the thing being judged five pixels wide. The
 * strip shows what was heard; the distance to the neighbours is a sentence.
 */
function adSetWindow(cand) {
  const before = S.project.lines[cand.after_line];
  const after = S.project.lines[cand.after_line + 1];
  let a = cand.start - AD_PAD - 1.8, b = cand.end + AD_PAD + 1.8;
  if (before) a = Math.max(a, Math.min(before.end - 0.4, cand.start - 0.5));
  if (after) b = Math.min(b, Math.max(after.start + 0.4, cand.end + 0.5));
  ADW.a = Math.max(0, a);
  ADW.b = Math.max(ADW.a + 1, b);
}

function adDraw() {
  const cand = adCurrent();
  const g = adCtx;
  if (!cand || !g || !ADW.w || !S.an) return;
  const W = ADW.w, span = ADW.b - ADW.a;
  const x = t => (t - ADW.a) / span * W;

  stripBed(g, W, AD_H);

  // Any line that already exists in view, so the hole reads as a hole rather
  // than as one more stretch of waveform. Often there is none - the gap can be
  // far wider than the window - and the legend below is told so.
  g.fillStyle = 'rgba(91,157,255,.13)';
  let known = false;
  for (const line of S.project.lines) {
    if (line.end <= ADW.a || line.start >= ADW.b) continue;
    known = true;
    g.fillRect(x(line.start), 0, Math.max(1, x(line.end) - x(line.start)), AD_H);
  }
  RV('ad-key-known').hidden = !known;
  // What was heard in it.
  g.fillStyle = 'rgba(62,207,142,.17)';
  g.fillRect(x(cand.start), 0, Math.max(2, x(cand.end) - x(cand.start)), AD_H);

  stripWave(g, W, AD_H, ADW.a, ADW.b);

  g.fillStyle = C.good;
  for (const t of [cand.start, cand.end]) g.fillRect(x(t) - 0.75, 0, 1.5, AD_H);
  // Each word the transcription placed, so the shading has visible evidence.
  g.fillStyle = 'rgba(62,207,142,.55)';
  for (const t of cand.starts || []) g.fillRect(x(t) - 0.5, AD_H - 14, 1, 7);

  if (!S.audio.paused) {
    const t = S.audio.currentTime;
    if (t >= ADW.a && t <= ADW.b) {
      g.fillStyle = C.head;
      g.fillRect(x(t), 0, 1.5, AD_H);
    }
  }
}

function adRender() {
  const list = adPending();
  const cand = list[S.addAt || 0];
  if (!cand) return rvAfterAdditions();

  RV('ad-count').textContent = list.length > 1
    ? `Missing line ${(S.addAt || 0) + 1} of ${list.length}` : 'A line you did not write down';
  RV('ad-where').textContent = `${fmt(cand.start)} — after line ${cand.after_line}`;
  RV('ad-progress-fill').style.width = `${((S.addAt || 0) / list.length) * 100}%`;
  RV('ad-text').textContent = cand.text;

  const before = S.project.lines[cand.after_line];
  const after = S.project.lines[cand.after_line + 1];
  const neighbours = [];
  if (before) neighbours.push(`line ${before.index} ends ${(cand.start - before.end).toFixed(1)}s before it`);
  if (after) neighbours.push(`line ${after.index} starts ${(after.start - cand.end).toFixed(1)}s after`);

  RV('ad-why').innerHTML = [
    `${(cand.end - cand.start).toFixed(1)}s of vocal that nothing in your lyrics covers`,
    `heard as “${escapeHtml(cand.heard)}” with ${Math.round(cand.confidence * 100)}% confidence`,
    `that is line ${cand.like_line}'s text, which your lyrics already repeat ${cand.repeats} times`,
    neighbours.join(', '),
  ].filter(Boolean).map(r => `<li>${r}</li>`).join('');

  adSetWindow(cand);
  if (adLayout()) adDraw();
}

/** Play the heard span and stop itself, exactly like the A/B previews do. */
function adPlay() {
  const cand = adCurrent();
  if (!cand) return;
  rvStopPlay();
  S.audio.currentTime = Math.max(0, cand.start - 0.25);
  S.audio.play();
  const span = (cand.end - cand.start) + 0.5;
  S.review.stop = setTimeout(() => { S.audio.pause(); adDraw(); },
                             (span / S.rate) * 1000);
}

async function adDecide(action) {
  const cand = adCurrent();
  if (!cand) return;
  rvStopPlay();
  S.audio.pause();

  // Adding a line renumbers the whole project - the review queue, the marks,
  // both aligners' spans, the round-trip's observations - and that belongs on
  // the server, which owns the model. Dismissing one is only "not now", so the
  // hosted demo does it in memory rather than dead-ending on this card and
  // never letting anyone reach the word queue behind it.
  if (STATIC) {
    if (action === 'accept') { needsServer('Adding a line'); return; }
    cand.dismissed = true;
    renderList();
    S.addAt = 0;
    if (adPending().length) adRender();
    else rvAfterAdditions();
    return;
  }

  let data;
  try {
    const res = await fetch('/api/additions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, candidate: cand }),
    });
    if (!res.ok) throw new Error(await res.text());
    data = await res.json();
  } catch (err) {
    return toast('could not update the lyrics: ' + err.message, true);
  }

  if (action === 'accept') {
    // Every line after the insertion is renumbered, so the queue, the todo
    // marks and the undo stack all have to come from the server's new truth
    // rather than be patched here - the same reset the audit itself does.
    S.project = data.project;
    S.review.queue = (data.audit.queue || []);
    if (S.review.stats) S.review.stats = { ...S.review.stats, ...data.audit };
    S.additions = data.audit.additions || [];
    resetHistory();
    indexTodo();
    renderList();
    invalidate();
    draw();
    rvBadge();
    toast(`line added at ${fmt(cand.start)} — it is in the exports now`);
  } else {
    S.additions = (data.audit && data.audit.additions) || [];
    renderList();
  }

  S.addAt = 0;
  if (adPending().length) adRender();
  else rvAfterAdditions();
}

/** Additions are settled first; then the sheet is the timing queue it was. */
function rvAfterAdditions() {
  if (S.review.queue.length) {
    S.review.at = 0;
    rvShow('rv-card');
    rvRender();
    rvSyncSolo();
  } else if (S.review.stats) {
    rvFinish();
  } else {
    rvShow('rv-intro');
  }
}

function bindAdditions() {
  RV('ad-close').addEventListener('click', closeReview);
  RV('ad-play').addEventListener('click', adPlay);
  RV('ad-accept').addEventListener('click', () => adDecide('accept'));
  RV('ad-skip').addEventListener('click', () => adDecide('dismiss'));
}

function bindReview() {
  RV('btn-review').addEventListener('click', openReview);
  RV('rv-start').addEventListener('click', runAudit);
  RV('rv-close').addEventListener('click', closeReview);
  RV('rv-done-close').addEventListener('click', closeReview);
  RV('rv-play-cur').addEventListener('click', () => rvPlayFrom(rvCurrent().current, 'cur'));
  RV('rv-play-new').addEventListener('click', () => rvPlayFrom(rvCurrent().proposed, 'new'));
  RV('rv-play-adj').addEventListener('click', () => rvPlayFrom(rvAdjPlay(rvCurrent()), 'adj'));
  RV('rv-adj-reset').addEventListener('click', rvResetAdj);
  RV('rv-wave').addEventListener('mousedown', rvStripDown);
  window.addEventListener('mousemove', rvStripMove);
  window.addEventListener('mouseup', rvStripUp);
  RV('rv-accept').addEventListener('click', () => rvDecide('accept'));
  RV('rv-keep').addEventListener('click', () => rvDecide('keep'));
  RV('rv-skip').addEventListener('click', () => rvDecide('skip'));
  RV('rv-undo').addEventListener('click', rvUndo);
  RV('rv-show').addEventListener('click', rvShowOnTimeline);
  RV('rv-solo').addEventListener('change', rvSyncSolo);
  RV('rv-save').addEventListener('click', async () => { await save(); closeReview(); });
}

/* ------------------------------------------------------- tracks & import

   The session is not tied to the track it opened with: any aligned track under
   the workdir root can be opened, and a new pair of files can be brought in
   here rather than at a command line. */

const IM_PANES = ['tk-list', 'im-pick', 'im-busy', 'im-done'];
const imShow = which => IM_PANES.forEach(id => (RV(id).hidden = id !== which));

async function openTracks() {
  imShow('tk-list');
  RV('tracks').showModal();
  const rows = RV('tk-rows');
  rows.innerHTML = '<div class="rv-foot">loading…</div>';
  let list = [];
  try { list = await (await fetch('/api/tracks')).json(); }
  catch { rows.innerHTML = '<div class="rv-foot">could not read the track list</div>'; return; }

  rows.innerHTML = '';
  for (const t of list) {
    const row = document.createElement('button');
    row.className = 'tk-row' + (t.active ? ' active' : '');
    row.innerHTML =
      `<span class="tk-name">${escapeHtml(t.name)}</span>` +
      `<span class="tk-meta">${t.lines} lines · score ${t.score}</span>` +
      (t.flagged ? `<span class="tk-badge todo">${t.flagged} to review</span>` : '') +
      (t.active ? '<span class="tk-badge here">open</span>' : '');
    if (!t.active) row.addEventListener('click', () => switchTrack(t.dir));
    rows.appendChild(row);
  }
  if (!list.length) rows.innerHTML = '<div class="rv-foot">no aligned tracks yet</div>';
}

async function switchTrack(dir) {
  const res = await fetch('/api/open', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dir }),
  });
  if (!res.ok) return toast('could not open that track', true);
  location.reload();                     // simplest correct reset of every cache
}

/* ---------------- import ---------------- */

const IM = { audio: null, lyrics: null };

function imSetFile(kind, file) {
  IM[kind] = file || null;
  const box = RV(kind === 'audio' ? 'drop-audio' : 'drop-lyrics');
  const label = RV(kind === 'audio' ? 'name-audio' : 'name-lyrics');
  box.classList.toggle('set', !!file);
  label.textContent = file
    ? `${file.name}  (${(file.size / 1e6).toFixed(1)} MB)`
    : (kind === 'audio' ? 'drop a .wav or .mp3, or click to pick' : 'drop the .txt, or click to pick');
  RV('im-start').disabled = !(IM.audio && IM.lyrics);
}

function bindDrop(boxId, inputId, kind) {
  const box = RV(boxId), input = RV(inputId);
  box.addEventListener('click', () => input.click());
  input.addEventListener('change', () => imSetFile(kind, input.files[0]));
  for (const type of ['dragenter', 'dragover']) {
    box.addEventListener(type, e => { e.preventDefault(); box.classList.add('over'); });
  }
  for (const type of ['dragleave', 'drop']) {
    box.addEventListener(type, e => { e.preventDefault(); box.classList.remove('over'); });
  }
  box.addEventListener('drop', e => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) imSetFile(kind, file);
  });
}

/** POST the File as the raw request body - no multipart, no dependency. */
async function upload(file) {
  const res = await fetch(`/api/upload?name=${encodeURIComponent(file.name)}`,
    { method: 'POST', body: file });
  if (!res.ok) throw new Error(`upload failed for ${file.name}`);
  return (await res.json()).path;
}

async function startImport() {
  imShow('im-busy');
  RV('im-log').textContent = 'uploading…';
  try {
    const [audio, lyrics] = [await upload(IM.audio), await upload(IM.lyrics)];
    const res = await fetch('/api/import', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ audio, lyrics }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || 'import refused');
  } catch (err) {
    return imFailed(err.message);
  }
  pollImport();
}

function imFailed(message) {
  imShow('im-done');
  RV('im-done-title').textContent = 'That did not work';
  RV('im-done-msg').textContent = message;
  RV('im-open').hidden = true;
}

async function pollImport() {
  let data;
  try { data = await (await fetch('/api/import')).json(); }
  catch { return setTimeout(pollImport, 1500); }

  const log = RV('im-log');
  log.textContent = (data.lines || []).join('\n');
  log.scrollTop = log.scrollHeight;

  if (data.state === 'running') return setTimeout(pollImport, 1200);
  if (data.state === 'failed') return imFailed(data.error || 'alignment failed');

  imShow('im-done');
  RV('im-done-title').textContent = 'Aligned';
  RV('im-done-msg').textContent = 'The track is ready to review.';
  RV('im-open').hidden = false;
}

function bindTracks() {
  RV('btn-tracks').addEventListener('click', openTracks);
  RV('tk-close').addEventListener('click', () => RV('tracks').close());
  RV('tk-add').addEventListener('click', () => { imShow('im-pick'); imSetFile('audio', null); imSetFile('lyrics', null); });
  RV('im-back').addEventListener('click', openTracks);
  RV('im-start').addEventListener('click', startImport);
  RV('im-open').addEventListener('click', () => location.reload());
  RV('im-done-close').addEventListener('click', () => RV('tracks').close());
  RV('tracks').addEventListener('click', e => { if (e.target === RV('tracks')) RV('tracks').close(); });
  bindDrop('drop-audio', 'file-audio', 'audio');
  bindDrop('drop-lyrics', 'file-lyrics', 'lyrics');
}

/* ---------------------------------------------------------------- server */

async function save() {
  if (needsServer('Saving')) return;
  const res = await fetch('/api/project', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(S.project),
  });
  if (!res.ok) return toast('save failed', true);
  S.hist.savedAt = S.hist.undo.length;      // undoing back to here is "clean" again
  syncHistory();
  toast('saved — lrc, word-lrc, srt and vtt rewritten');
}

async function rescore() {
  if (needsServer('Re-scoring')) return;
  toast('re-running the benchmark…');
  await save();
  const res = await fetch('/api/rescore', { method: 'POST' });
  if (!res.ok) return toast('re-score failed', true);
  const card = await res.json();
  const fresh = await (await fetch('/api/project')).json();
  S.project = fresh;
  resetHistory();                            // snapshots point at replaced objects
  renderScorecard(card);
  renderList();
  draw();
  toast(`re-scored — ${card.n_flagged} line(s) need review`);
}

/* ---------------------------------------------------------------- events */

function bindCanvas() {
  canvas.addEventListener('mousedown', e => {
    const r = canvas.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;

    if (y < MINI_H) {
      const t = (x / canvas.clientWidth) * duration();
      setView(t - S.view.dur / 2, S.view.dur);
      draw();
      return;
    }

    // The scrub bar always seeks - it is the one strip no region can cover, so
    // there is always somewhere to click even in the middle of a dense line.
    if (y >= SCRUB_Y && y < SCRUB_Y + SCRUB_H) {
      // shift starts a fine adjustment from where the playhead already is,
      // rather than jumping to the click.
      const from = e.shiftKey ? S.audio.currentTime : clamp(x2t(x), 0, duration());
      S.scrub = { x0: x, t0: from };
      S.audio.currentTime = from;
      canvas.style.cursor = 'ew-resize';
      draw();
      return;
    }

    const word = hitWord(x, y);
    if (word) {
      selectWord(word.line.index, word.i, false);
      if (word.kind === 'divider') {
        S.drag = {
          word: true, line: word.line, i: word.i,
          entry: pushHistory('move boundary', [word.line]),
        };
        canvas.style.cursor = 'col-resize';
      }
      return;
    }

    const target = hit(x, y);
    if (target) {
      select(target.line.index, true);        // must not move the view mid-grab
      S.drag = {
        line: target.line, edge: target.edge, t0: x2t(x),
        start: target.line.start, end: target.line.end,
        entry: pushHistory(target.edge === 'move' ? 'move line' : 'resize line', [target.line]),
      };
      canvas.style.cursor = target.edge === 'move' ? 'grabbing' : 'col-resize';
      return;
    }

    S.audio.currentTime = clamp(x2t(x), 0, duration());
    draw();
  });

  window.addEventListener('mousemove', e => {
    // A drag inside the review sheet is none of this handler's business, and a
    // hover readout computed under it would be noise at best.
    if (S.review.drag) return;

    const r = canvas.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;

    if (S.scrub) {
      const perPx = S.view.dur / canvas.clientWidth;
      const scale = e.shiftKey ? 1 / FINE_SCRUB : 1;
      const t = S.scrub.t0 + (x - S.scrub.x0) * perPx * scale;
      S.audio.currentTime = clamp(t, 0, duration());
      S.scrubHoverX = null;
      draw();
      return;
    }

    if (S.drag && S.drag.word) {
      const d = S.drag;
      const raw = x2t(x);
      const snapped = e.altKey ? raw : snapOnset(raw);
      if (snapped !== raw) S.flash = { t: snapped, at: performance.now() };
      setWordStart(d.line, d.i, snapped);
      refreshRow(d.line);
      draw();
      return;
    }

    if (S.drag) {
      const dt = x2t(x) - S.drag.t0;
      const d = S.drag;
      if (d.edge === 'move') retimeLine(d.line, d.start + dt, d.end + dt);
      else if (d.edge === 'start') retimeLine(d.line, Math.min(d.start + dt, d.end - 0.15), d.end);
      else retimeLine(d.line, d.start, Math.max(d.end + dt, d.start + 0.15));
      refreshRow(d.line);
      draw();
      return;
    }

    if (x < 0 || x > canvas.clientWidth || y < 0 || y > TOTAL_H) {
      if (S.scrubHoverX !== null) { S.scrubHoverX = null; draw(); }
      return;
    }

    const overScrub = y >= SCRUB_Y && y < SCRUB_Y + SCRUB_H;
    if (overScrub !== (S.scrubHoverX !== null) || (overScrub && x !== S.scrubHoverX)) {
      S.scrubHoverX = overScrub ? x : null;
      draw();
    }
    if (overScrub) {
      canvas.style.cursor = 'ew-resize';
      setHint(`${fmt(x2t(x))}   click or drag to scrub  ·  shift-drag for fine control`);
      return;
    }

    const word = hitWord(x, y);
    if (word) {
      const w = word.line.words[word.i];
      canvas.style.cursor = word.kind === 'divider' ? 'col-resize' : 'pointer';
      setHint(word.kind === 'divider'
        ? `boundary ${word.i}: "${word.line.words[word.i - 1].text}" | "${w.text}" ` +
          `at ${fmt(w.start)}   drag to move (alt = no onset snap)`
        : `word ${word.i}: "${w.text}"  ${fmt(w.start)} → ${fmt(w.end)}`);
      return;
    }

    const target = hit(x, y);
    canvas.style.cursor = !target ? 'crosshair'
      : target.edge === 'move' ? 'grab' : 'col-resize';
    setHint(target
      ? `line ${target.line.index}: ${fmt(target.line.start)} → ${fmt(target.line.end)}   ` +
        `[${target.line.source}]  ${(target.line.score && target.line.score.issues || []).join('; ')}`
      : `${fmt(x2t(x))}`);
  });

  canvas.addEventListener('mouseleave', () => {
    if (!S.drag && !S.scrub) restHint();
  });

  window.addEventListener('mouseup', () => {
    if (S.drag) {
      dropIfUnchanged(S.drag.entry);       // a click that moved nothing is not an edit
      canvas.style.cursor = 'crosshair';
      S.drag = null;
    }
    if (S.scrub) { canvas.style.cursor = 'crosshair'; S.scrub = null; }
  });

  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect();
    const t = x2t(e.clientX - r.left);
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY) || e.shiftKey) {
      setView(S.view.start + (e.deltaX || e.deltaY) * S.view.dur / canvas.clientWidth, S.view.dur);
    } else {
      zoomAt(t, e.deltaY > 0 ? 1.12 : 0.89);
      return;
    }
    draw();
  }, { passive: false });
}

function bindKeys() {
  window.addEventListener('keydown', e => {
    const tag = e.target.tagName;
    if ((tag === 'INPUT' && e.target.type !== 'checkbox') || tag === 'SELECT') return;

    const tracksDlg = document.getElementById('tracks');
    if (tracksDlg.open) {
      if (e.key === 'Escape') { e.preventDefault(); tracksDlg.close(); }
      return;
    }

    const review = document.getElementById('review');
    if (review.open) {
      if (e.key === 'Escape') { e.preventDefault(); closeReview(); return; }
      if (!RV('rv-add').hidden) {
        if (e.metaKey || e.ctrlKey) return;
        if (e.key === ' ') { e.preventDefault(); adPlay(); }
        else if (e.key === 'Enter') { e.preventDefault(); adDecide('accept'); }
        return;
      }
      const item = RV('rv-card').hidden ? null : rvCurrent();
      if (!item || e.metaKey || e.ctrlKey) return;
      // Arrows here move your own adjusted timing, not the selected line: the
      // sheet is a different job with the same muscle memory.
      const step = e.shiftKey ? 0.01 : 0.05;
      switch (e.key) {
        case ' ': e.preventDefault(); rvReplay(); break;
        case 'ArrowLeft': e.preventDefault(); rvNudgeAdj(-step); break;
        case 'ArrowRight': e.preventDefault(); rvNudgeAdj(step); break;
        case 'Enter': e.preventDefault(); rvDecide('accept'); break;
        case '1': e.preventDefault(); rvPlayFrom(item.current, 'cur'); break;
        case '2': e.preventDefault(); rvPlayFrom(item.proposed, 'new'); break;
        case '3':
          e.preventDefault();
          if (S.review.adj) rvPlayFrom(rvAdjPlay(item), 'adj');
          break;
      }
      return;
    }

    // While the sheet is up it owns the keyboard; esc closes it natively.
    const help = document.getElementById('help');
    if (help.open) {
      if (e.key === '?' || e.key === 'Escape') { e.preventDefault(); help.close(); }
      return;
    }
    if (e.key === '?') { e.preventDefault(); help.showModal(); return; }

    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
      e.preventDefault(); save(); return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      (e.shiftKey ? redoEdit : undoEdit)();
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'y') {
      e.preventDefault(); redoEdit(); return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;


    // Arrows are context-sensitive: they move the selected word if there is
    // one, otherwise the whole line, so existing muscle memory carries over.
    const step = e.shiftKey ? 0.01 : 0.05;

    switch (e.key) {
      case ' ':
        e.preventDefault();
        S.audio.paused ? S.audio.play() : S.audio.pause();
        break;
      case 'Tab': e.preventDefault(); stepWord(e.shiftKey ? -1 : 1); break;
      case 'Escape': e.preventDefault(); deselectWord(); break;
      case 'ArrowLeft': e.preventDefault(); if (!nudgeWord(-step)) nudge(-step); break;
      case 'ArrowRight': e.preventDefault(); if (!nudgeWord(step)) nudge(step); break;
      case 'ArrowUp': e.preventDefault(); select(S.sel - 1); break;
      case 'ArrowDown': e.preventDefault(); select(S.sel + 1); break;
      case 'Enter': e.preventDefault(); preview(S.project.lines[S.sel]); break;
      case 's': case 'S': e.preventDefault(); setEdge('start'); break;
      case 'e': case 'E': e.preventDefault(); setEdge('end'); break;
      case 't': case 'T': e.preventDefault(); tap(); break;
      case 'w': case 'W': e.preventDefault(); tapWord(); break;
      case '[': e.preventDefault(); stepRate(-1); break;
      case ']': e.preventDefault(); stepRate(1); break;
      case '\\': e.preventDefault(); setRate(1); toast('1× speed'); break;
      case 'v': case 'V': e.preventDefault(); setSolo(!S.solo); break;
      case 'f': case 'F': e.preventDefault(); setFollow(!S.follow); break;
      case 'r': case 'R': {
        e.preventDefault();
        const line = S.project.lines[S.sel];
        if (redistribute(line)) { refreshRow(line); draw(); toast('words redistributed evenly'); }
        break;
      }
    }
  });
}

function bindChrome() {
  document.getElementById('btn-play').addEventListener('click', () =>
    S.audio.paused ? S.audio.play() : S.audio.pause());
  S.audio.addEventListener('play', () => {
    document.getElementById('btn-play').textContent = 'Pause';
    document.body.classList.add('playing');
  });
  S.audio.addEventListener('pause', () => {
    document.getElementById('btn-play').textContent = 'Play';
    document.body.classList.remove('playing');
  });

  document.getElementById('btn-zoom-in').addEventListener('click', () => zoomAt(S.audio.currentTime, 0.6));
  document.getElementById('btn-zoom-out').addEventListener('click', () => zoomAt(S.audio.currentTime, 1.7));
  document.getElementById('btn-zoom-fit').addEventListener('click', () => { setView(0, duration()); draw(); });

  document.getElementById('btn-solo').addEventListener('click', () => setSolo(!S.solo));
  document.getElementById('btn-follow').addEventListener('click', () => setFollow(!S.follow));
  document.getElementById('btn-rate').addEventListener('click', cycleRate);
  S.el.placeBtn.addEventListener('click', placeLineAtPlayhead);
  document.getElementById('btn-undo').addEventListener('click', undoEdit);
  document.getElementById('btn-redo').addEventListener('click', redoEdit);

  const help = document.getElementById('help');
  document.getElementById('btn-help').addEventListener('click', () => help.showModal());
  document.getElementById('btn-help-close').addEventListener('click', () => help.close());
  // Clicks land on .help-body for real content, so this is the backdrop only.
  help.addEventListener('click', e => { if (e.target === help) help.close(); });

  document.getElementById('btn-save').addEventListener('click', save);
  document.getElementById('btn-rescore').addEventListener('click', rescore);
  document.getElementById('btn-export').addEventListener('click', async () => {
    if (needsServer('Exporting')) return;
    await save();
    const res = await fetch('/api/export', { method: 'POST' });
    const paths = await res.json();
    toast(`exported: ${Object.keys(paths).join(', ')}`);
  });

  for (const btn of document.querySelectorAll('.filter')) {
    btn.addEventListener('click', () => {
      for (const b of document.querySelectorAll('.filter')) b.classList.remove('active');
      btn.classList.add('active');
      S.filter = btn.dataset.filter;
      renderList();
    });
  }

  // Reading the lyrics by hand suspends the chase, then it resumes by itself.
  const lyrics = S.el.lyrics;
  const held = () => { S.lyricHoldUntil = performance.now() + LYRIC_HOLD_MS; };
  lyrics.addEventListener('wheel', held, { passive: true });
  lyrics.addEventListener('touchmove', held, { passive: true });

  window.addEventListener('resize', () => {
    layout();
    draw();
    if (S.review.strip && rvLayoutStrip()) rvDrawStrip();
    if (!RV('rv-add').hidden && adLayout()) adDraw();
  });
  window.addEventListener('beforeunload', e => {
    if (S.dirty) { e.preventDefault(); e.returnValue = ''; }
  });
}

/* ------------------------------------------------------------- the curtain

   Three states the app can be in before it has a track: loading, empty, and
   failed. Each replaces the working surfaces rather than covering them, so a
   dead app never presents a toolbar full of live-looking buttons. */

function showCurtain(which, message) {
  const on = !!which;
  RV('curtain').hidden = !on;
  for (const id of ['cur-loading', 'cur-error', 'cur-welcome']) {
    RV(id).hidden = id !== `cur-${which}`;
  }
  // The chrome is only meaningful with a track behind it. `?` stays: the
  // shortcut sheet is reference material, and it explains Check timings.
  document.querySelector('.stage').hidden = on;
  document.querySelector('.lyrics').hidden = on;
  document.body.classList.toggle('no-track', on);
  for (const id of ['btn-review', 'btn-rescore', 'btn-export', 'btn-save',
                    'btn-undo', 'btn-redo']) {
    const el = RV(id);
    if (el) el.disabled = on;
  }
  if (which === 'error' && message) RV('cur-error-msg').textContent = message;
}

function bindCurtain() {
  RV('cur-retry').addEventListener('click', () => location.reload());
  RV('cur-tracks').addEventListener('click', openTracks);
  RV('cur-add').addEventListener('click', () => {
    openTracks();
    imShow('im-pick');
    imSetFile('audio', null);
    imSetFile('lyrics', null);
  });
}

/** Say what this copy is, and take away the controls that cannot work in it. */
function markStaticDemo() {
  if (!STATIC) return;
  document.body.classList.add('is-demo');
  const bar = document.querySelector('.bar-right');
  const note = document.createElement('a');
  note.className = 'demo-badge';
  note.href = 'https://github.com/nuterian/song';
  note.title = 'Everything edits here; saving needs the app on your machine';
  note.innerHTML = 'live demo <span>· read-only</span>';
  bar.parentNode.insertBefore(note, bar);
}

/* ---------------------------------------------------------------- boot */

async function main() {
  bindCurtain();
  bindTracks();
  markStaticDemo();
  showCurtain('loading');

  S.el.clock = document.getElementById('clock');
  S.el.hint = document.getElementById('hint');
  S.el.lyrics = document.querySelector('.lyrics');
  S.el.placeIdx = document.getElementById('place-idx');
  S.el.placeText = document.getElementById('place-text');
  S.el.placeTime = document.getElementById('place-time');
  S.el.placeBtn = document.getElementById('btn-place');

  S.project = await (await fetch(api('/api/project'))).json();
  // Nothing aligned yet: the app opens on its own first run rather than
  // refusing to start, which is how the import flow used to be unreachable
  // until you had already done the same job at a command line.
  if (S.project.empty) {
    document.getElementById('track-name').textContent = 'no track';
    showCurtain('welcome');
    return;
  }
  S.an = await (await fetch(api('/api/analysis'))).json();
  showCurtain(null);

  document.getElementById('track-name').textContent =
    S.project.audio_path.split('/').pop();

  S.audio.src = api('/media/mix');
  S.audio.preload = 'auto';
  setRate(1);
  setFollow(true);

  setView(0, duration());
  layout();
  renderScorecard(S.project.scorecard);
  renderList();
  bindCanvas();
  bindKeys();
  bindChrome();
  bindReview();
  bindAdditions();
  syncHistory();
  restHint();
  await loadAudit();
  renderList();          // now that the queue is known, mark it in the list
  draw();
  tick();

  const firstFlagged = S.project.lines.find(l => l.flagged);
  select(firstFlagged ? firstFlagged.index : 0);

  // A reload during an import should rejoin it rather than look idle.
  try {
    if (STATIC) return;
    const job = await (await fetch('/api/import')).json();
    if (job.state === 'running') { RV('tracks').showModal(); imShow('im-busy'); pollImport(); }
  } catch { /* no job endpoint yet is fine */ }
}

main().catch(err => {
  console.error(err);
  // A toast that vanishes in 2.4 s left a full toolbar over an empty page with
  // no way to tell what had happened. This states it and stays.
  showCurtain('error', err && err.message ? err.message : String(err));
});
