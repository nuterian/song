'use strict';

/* ---------------------------------------------------------------- state */

const S = {
  project: null,
  an: null,
  audio: new Audio(),
  solo: false,
  follow: true,
  view: { start: 0, dur: 60 },
  glide: 0,                 // the rAF of a view glide in flight, if any
  sel: 0,
  selWord: null,
  selBound: 'left',        // which of the selected word's two bounds keys act on
  hoverBound: null,        // the bound under the cursor, so it can light up
  rate: 1,
  additions: [],           // lines heard in the gaps that the lyrics lack
  addAt: 0,
  review: {
    queue: [], at: 0, stats: null, wasSolo: false,
    adj: null,            // bounds the reviewer placed by hand: {t, end}
    side: 'left',         // which bound the sheet's own arrow keys move
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
  wbDrag: null,            // a drag on one of the deck's bound chips
  dirty: false,
  saveTimer: 0,            // debounced write-back; see persistSoon
  saving: false,
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
const MINI_H = 20, GAP = 5, SCRUB_H = 19, VOC_H = 124, WORD_STRIP = 28;
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
const BOUND_GRAB = 8;     // px either side of a selected word's bound that grabs it
const CAP_H = 10, CAP_W = 7;   // the tab at each end of a bound handle
/* The line's own label strip along the top of the lane. A word bound outranks
   everything else in the lane, but not here: this band stays the line's, so
   selecting a word never takes the line's own edges away from the mouse. */
const LINE_BAND = 18;

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
  // The toast is a popover so it can rise above an open modal sheet. The
  // reflow between showing it and lighting it is what lets the fade run.
  const popover = !!el.showPopover;
  if (popover && !el.matches(':popover-open')) el.showPopover();
  void el.offsetWidth;
  el.className = 'toast show' + (isError ? ' err' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.className = 'toast';
    if (popover) setTimeout(() => { if (el.matches(':popover-open')) el.hidePopover(); }, 350);
  }, 2400);
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
  persistSoon();
}

/** The save button lights only when there is something to save. */
function paintSaveBtn() {
  const b = document.getElementById('btn-save');
  if (!b) return;
  if (b.classList.contains('just-saved')) return;   // let the confirmation stand
  b.innerHTML = 'Save<span class="k">⌘S</span>';
  b.classList.toggle('dirty', S.dirty);
}

/* --------------------------------------------------------- write-back

   An edit is not a proposal. Dropping a bound *is* the new state, so it goes to
   disk by itself; ⌘S stays as the "now, and tell me" version of the same thing.

   Debounced rather than immediate, and deferred while a gesture is in flight:
   a drag lands sixty edits a second and every save rewrites five files. The
   dirty flag and the beforeunload guard are left in place as the backstop for
   the window where a write is still pending. */

const AUTOSAVE_MS = 700;

function cancelPersist() { clearTimeout(S.saveTimer); S.saveTimer = 0; }

function persistSoon() {
  if (STATIC) return;                   // the demo has nowhere to write
  cancelPersist();
  S.saveTimer = setTimeout(async () => {
    S.saveTimer = 0;
    // Never mid-gesture: the state to save is the one you let go of.
    if (S.drag || S.wbDrag || S.scrub || S.review.drag || S.saving) return persistSoon();
    if (!S.dirty) return;
    await save({ quiet: true });
  }, AUTOSAVE_MS);
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
  const ws = line.words || [];
  return {
    index: line.index,
    start: line.start,
    end: line.end,
    source: line.source,
    // Both edges: a word's end is a measured quantity now, so restoring the
    // starts and re-deriving would quietly close every rest in the line.
    starts: ws.map(w => w.start),
    ends: ws.map(w => w.end),
  };
}

function restoreLine(snap) {
  const line = S.project.lines[snap.index];
  if (!line) return;
  line.start = snap.start;
  line.end = snap.end;
  line.source = snap.source;
  snap.starts.forEach((t, i) => { if (line.words[i]) line.words[i].start = t; });
  snap.ends.forEach((t, i) => { if (line.words[i]) line.words[i].end = t; });
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
      && snap.starts.every((t, i) => line.words[i] && line.words[i].start === t)
      && snap.ends.every((t, i) => line.words[i] && line.words[i].end === t);
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
  // Taking an edit back is an edit. Without this the disk would keep whatever
  // the last write-back caught until the next unrelated change flushed it.
  persistSoon();
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
  cancelPersist();                      // whatever was queued was for the old copy
  S.hist = { undo: [], redo: [], savedAt: 0, coalesce: null };
  syncHistory();
}

/* ------------------------------------------------------- word-level edits */

/* Mirrors TimedLine.normalize_words in project.py.

   Word spans are ordered and nested inside the line, but they are not a tiling:
   a word ends where the singer stops, and a line can hold a rest in the middle
   of it. An end that carries no information (at or before its own start) still
   falls back to the next word's start - that is all that is known about it. */
function normalizeWords(line) {
  const ws = line.words;
  if (!ws || !ws.length || line.end <= line.start) return;
  ws[0].start = line.start;
  let previous = line.start;
  for (const w of ws) { w.start = clamp(w.start, previous, line.end); previous = w.start; }
  for (let i = 0; i < ws.length - 1; i++) {
    const ceiling = ws[i + 1].start;
    ws[i].end = ws[i].end <= ws[i].start ? ceiling : Math.min(ws[i].end, ceiling);
  }
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

/* ------------------------------------------------------------- word bounds

   A word covers a span of the track and *both* ends of that span are editable,
   on every surface that draws the word. The two are genuinely independent: a
   word ends where the singer stops, so pulling a word short opens a rest rather
   than dragging its neighbour along.

   Two words that touch share a pixel but not a number, so every edge is still
   one edge and one drag. Holding shift brings the neighbour along, which keeps
   a shut boundary shut and a rest the width it was - the re-cut this lane has
   always had, now one of two things a boundary can do rather than the only one.

   Everything that moves a word edge - drag, arrow key, stamp, review sheet -
   goes through setBound or setPair. One clamp, one snap, one normalisation. */

/** Where a bound sits now. */
function boundTime(line, i, side) {
  const w = ((line && line.words) || [])[i];
  return !w ? 0 : side === 'left' ? w.start : w.end;
}

/**
 * How far a bound may travel.
 *
 * Pulling a bound *into* its own word opens a rest and answers to nothing but
 * MIN_WORD. Pushing it *out* runs into the neighbour, and rather than stopping
 * dead it shoves that neighbour's facing edge along - so the limit is the
 * neighbour's far edge, less its own MIN_WORD.
 *
 * Stopping dead was the alternative and it is unusable: words arrive from the
 * aligner shut against each other, so a bound that refused to push could not
 * move outward at all, and "this word starts too late" - the commonest repair
 * there is - would have no gesture.
 *
 * Word 0's left bound is the line start and the last word's right bound is the
 * line end, so those two answer to the track rather than to a neighbour.
 */
function boundRange(line, i, side) {
  const ws = (line && line.words) || [];
  const last = ws.length - 1;
  if (!ws.length || i < 0 || i > last) return [0, 0];
  if (side === 'left') {
    const lo = i === 0 ? 0 : ws[i - 1].start + MIN_WORD;
    return [lo, Math.max(lo, ws[i].end - MIN_WORD)];
  }
  const lo = ws[i].start + MIN_WORD;
  const hi = i === last ? (duration() || line.end) : ws[i + 1].end - MIN_WORD;
  return [lo, Math.max(lo, hi)];
}

/** Move one bound of one word. The single writer for a word's own span. */
function setBound(line, i, side, t) {
  const ws = (line && line.words) || [];
  if (!ws[i]) return;
  const [lo, hi] = boundRange(line, i, side);
  t = clamp(t, lo, hi);
  if (side === 'left') {
    ws[i].start = t;
    if (i === 0) line.start = t;             // word 0's start *is* the line start
    else if (ws[i - 1].end > t) ws[i - 1].end = t;        // shoved out of the way
  } else {
    ws[i].end = t;
    if (i === ws.length - 1) line.end = t;   // and the last word's end is its end
    else if (ws[i + 1].start < t) ws[i + 1].start = t;
  }
  normalizeWords(line);
  line.source = 'manual';
  markDirty();
}

/**
 * Move an edge and carry its neighbour with it, keeping whatever sits between
 * the two: a shut boundary stays shut, a rest keeps its width.
 *
 * This is the old divider drag - the one that re-cuts a pair of syllables
 * without disturbing anything outside them - now available at every edge under
 * shift, rather than being the only thing a boundary could do.
 */
function setPair(g, t) {
  const ws = (g.line && g.line.words) || [];
  const i = g.i, near = g.side === 'left' ? ws[i - 1] : ws[i + 1];
  if (!ws[i]) return;
  if (!near) return setBound(g.line, i, g.side, t);   // the line's own outer edge
  const [lo, hi] = grabRange(g, true);
  t = clamp(t, lo, hi);
  if (g.side === 'left') {
    const gap = ws[i].start - near.end;
    near.end = t - gap;
    ws[i].start = t;
  } else {
    const gap = near.start - ws[i].end;
    ws[i].end = t;
    near.start = t + gap;
  }
  normalizeWords(g.line);
  g.line.source = 'manual';
  markDirty();
}

/* A grab is {line, i, side}: one word, one of its two edges. The drag, the
   keyboard, the deck chips and the review strip all hold one of these, so none
   of them grows its own idea of what is being moved. */

function grabTime(g) { return boundTime(g.line, g.i, g.side); }

/** How far a grab may travel, on its own or with its neighbour in tow. */
function grabRange(g, pair) {
  if (!pair) return boundRange(g.line, g.i, g.side);
  const ws = g.line.words, i = g.i;
  if (g.side === 'left') {
    const prev = ws[i - 1];
    if (!prev) return boundRange(g.line, i, 'left');
    const lo = prev.start + MIN_WORD + (ws[i].start - prev.end);
    return [lo, Math.max(lo, ws[i].end - MIN_WORD)];
  }
  const next = ws[i + 1];
  if (!next) return boundRange(g.line, i, 'right');
  const lo = ws[i].start + MIN_WORD;
  return [lo, Math.max(lo, next.end - MIN_WORD - (next.start - ws[i].end))];
}

/** The neighbouring edge a bound would close onto, or null if there is none. */
function neighbourEdge(g) {
  const ws = g.line.words;
  return g.side === 'left' ? (g.i > 0 ? ws[g.i - 1].end : null)
    : (g.i + 1 < ws.length ? ws[g.i + 1].start : null);
}

/* Close onto a neighbour from this far out. Restoring an exact touch by eye is
   hopeless at any zoom, and "nearly shut" is a rest nobody meant to leave. */
const GAP_SNAP = 0.05;

/**
 * Place whatever a drag has hold of.
 *
 * Snaps shut onto its neighbour when it comes near one, else onto a vocal
 * onset; `free` (alt) takes the time literally and `pair` (shift) brings the
 * neighbour along instead of leaving it.
 *
 * The lock-on ring is only shown for a snap that survived the clamp - a ring on
 * a boundary the model then moved somewhere else would be a lie about what
 * just happened.
 */
function placeGrab(g, t, free, pair) {
  let snapped = t;
  if (!free) {
    const near = pair ? null : neighbourEdge(g);
    snapped = near != null && Math.abs(near - t) < GAP_SNAP ? near : snapOnset(t);
  }
  const [lo, hi] = grabRange(g, pair);
  const out = clamp(snapped, lo, hi);
  if (snapped !== t && out === snapped) S.flash = { t: out, at: performance.now() };
  if (pair) setPair(g, out); else setBound(g.line, g.i, g.side, out);
  return out;
}

/**
 * Move a word's start the way a re-timing pass means it.
 *
 * If the word before it ended exactly where this one began, the two stay shut
 * and the boundary moves; if a rest was already there, the rest is left as it
 * was. Only a deliberate pull on an edge opens or closes one, so re-timing by
 * ear - tap-along, taking a review card - never invents a silence.
 */
function setWordStart(line, i, t) {
  const ws = (line && line.words) || [];
  if (!ws[i]) return;
  if (i > 0 && touching(ws[i - 1], ws[i])) setPair({ line, i, side: 'left' }, t);
  else setBound(line, i, 'left', t);
}

/** The selected word, with its bounds already in pixels. Null if none. */
function selWordGeom() {
  if (!S.project) return null;
  const line = S.project.lines[S.sel];
  const w = ((line && line.words) || [])[S.selWord];
  if (S.selWord == null || !w || line.end <= line.start) return null;
  return { line, i: S.selWord, w, x0: t2x(w.start), x1: t2x(w.end) };
}

/** Escape hatch: spread the line's words evenly across its span. */
function redistribute(line) {
  const ws = (line && line.words) || [];
  if (ws.length < 2 || line.end <= line.start) return false;
  pushHistory('redistribute words', [line]);
  const step = (line.end - line.start) / ws.length;
  // Evenly means a tiling: this is the escape hatch from tangled edits, so it
  // closes every rest as well as re-spacing the starts.
  ws.forEach((w, i) => {
    w.start = line.start + i * step;
    w.end = line.start + (i + 1) * step;
  });
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

function zoomAt(t, factor, animate) {
  const frac = clamp((t - S.view.start) / S.view.dur, 0, 1);
  const dur = S.view.dur * factor;
  if (animate) return glideView(t - frac * dur, dur, 240);
  setView(t - frac * dur, dur);
  draw();
}

/* A discrete view change - a zoom button, Fit, a jump to a line, the follow
   catching up - glides rather than cuts. The wheel and a drag stay instant:
   they are continuous already, and an ease under a hand that is still moving
   reads as lag. Eased out, so the destination arrives first and the last few
   pixels settle; anything still in flight is replaced, not queued. */
function glideView(start, dur, ms) {
  const total = duration();
  const d = clamp(dur, 0.75, total);
  const st = clamp(start, 0, Math.max(0, total - d));
  const from = { start: S.view.start, dur: S.view.dur };
  if (REDUCED_MOTION.matches || !ms || (Math.abs(st - from.start) < 1e-6 && Math.abs(d - from.dur) < 1e-6)) {
    cancelAnimationFrame(S.glide);
    setView(st, d);
    draw();
    return;
  }
  cancelAnimationFrame(S.glide);
  const t0 = performance.now();
  const step = now => {
    const u = clamp((now - t0) / ms, 0, 1);
    const k = 1 - Math.pow(1 - u, 3);          // ease-out cubic
    // Interpolate the duration in log space, so a zoom feels linear in scale
    // rather than racing at the start and crawling at the end.
    const dd = Math.exp(Math.log(from.dur) + (Math.log(d) - Math.log(from.dur)) * k);
    setView(from.start + (st - from.start) * k, dd);
    draw();
    if (u < 1) S.glide = requestAnimationFrame(step);
  };
  S.glide = requestAnimationFrame(step);
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

  ctx.font = '11px ui-monospace, Menlo, monospace';
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
  ctx.font = '12px -apple-system, system-ui, sans-serif';
  ctx.textBaseline = 'top';

  for (const line of S.project.lines) {
    if (line.end <= line.start) continue;
    if (line.end < S.view.start || line.start > S.view.start + S.view.dur) continue;

    const x0 = t2x(line.start), x1 = t2x(line.end), w = Math.max(2, x1 - x0);
    const selected = line.index === S.sel;
    const scored = !!(line.score && line.score.total != null);
    const score = scored ? line.score.total : 0;
    const tone = line.flagged ? C.bad : !scored ? C.muted
      : grade(score) === 'good' ? C.good : C.ok;

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
      ctx.rect(x0 + 4, VOC_Y, w - 8, 18);
      ctx.clip();
      ctx.font = (selected ? '600 ' : '') + '12px -apple-system, system-ui, sans-serif';
      ctx.fillStyle = selected ? '#fff' : 'rgba(230,237,247,.72)';
      ctx.fillText(line.text, x0 + 6, VOC_Y + 3);
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
  ctx.font = '12px -apple-system, system-ui, sans-serif';
  ctx.textBaseline = 'top';

  const t = S.audio.currentTime;
  let drew = false;

  eachWordLine((line, blocks) => {
    drew = true;
    const live = line.index === S.sel;

    // A rest between two words, painted as its own thing. An empty stretch of
    // the strip has to read as "nobody is singing here" rather than as a cell
    // that failed to draw - it is the one state the old model could not hold.
    for (let i = 0; i + 1 < blocks.length; i++) {
      const a = blocks[i], b = blocks[i + 1];
      const w = b.x0 - a.x1;
      if (w <= 0.5) continue;
      ctx.fillStyle = live ? 'rgba(5,8,14,.85)' : 'rgba(5,8,14,.5)';
      ctx.fillRect(a.x1, WORD_Y, w, WORD_STRIP);
      ctx.fillStyle = live ? 'rgba(140,170,215,.32)' : 'rgba(140,170,215,.16)';
      ctx.fillRect(a.x1 + 1, WORD_Y + WORD_STRIP / 2 - 0.5, Math.max(0, w - 2), 1);
    }

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
        ctx.font = (active || chosen ? '600 ' : '') + '12px -apple-system, system-ui, sans-serif';
        ctx.fillStyle = active || chosen ? '#fff'
          : live ? 'rgba(230,237,247,.82)' : 'rgba(230,237,247,.5)';
        ctx.fillText(b.w.text, b.x0 + 5, WORD_Y + Math.round((WORD_STRIP - 14) / 2));
        ctx.restore();
      }
    }

    // Every internal edge of the line. Two touching words share one; two with
    // a rest between them have one each, bracketing it.
    const ws = line.words;
    const edges = [];
    for (let i = 0; i < blocks.length; i++) {
      const b = blocks[i], nxt = blocks[i + 1];
      if (i > 0) edges.push({ x: b.x0, i, side: 'left' });
      if (nxt && !touching(b.w, nxt.w)) edges.push({ x: b.x1, i, side: 'right' });
    }

    // The selected line's edges run the full height of the waveform: a boundary
    // that misses the syllable attack is visible against the audio it is
    // supposed to be cutting. Other lines get a tick inside the strip only,
    // enough to read the split without striping the whole lane.
    for (const e of edges) {
      if (!live) {
        ctx.fillStyle = 'rgba(170,203,255,.28)';
        ctx.fillRect(e.x - 0.5, WORD_Y, 1, WORD_STRIP);
        continue;
      }
      const near = e.i === S.selWord
        || (e.side === 'left' && e.i - 1 === S.selWord && touching(ws[e.i - 1], ws[e.i]));
      ctx.fillStyle = near ? 'rgba(213,228,255,.95)' : 'rgba(170,203,255,.5)';
      ctx.fillRect(e.x - 0.5, VOC_Y, 1.5, VOC_H);
      ctx.fillStyle = near ? '#d5e4ff' : C.wordDiv;
      ctx.fillRect(e.x - 2.5, WORD_Y, 5.5, 3);
      ctx.fillRect(e.x - 2.5, VOC_Y + VOC_H - 3, 5.5, 3);
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

/* ------------------------------------------------------- drawing a bound

   One painter, used by the timeline and by the review strip. They have
   different windows, different heights and different canvases, and share this
   so that the thing you learn to grab in one is the thing you grab in the
   other. */

/** The tab at one end of a bound bar, pointing into the word it belongs to. */
function boundCap(g, x, y, dir, down) {
  const s = down ? 1 : -1;
  g.beginPath();
  g.moveTo(x, y);
  g.lineTo(x + dir * CAP_W, y);
  g.lineTo(x + dir * CAP_W, y + s * (CAP_H - 4));
  g.lineTo(x, y + s * CAP_H);
  g.closePath();
  g.fill();
}

/**
 * One bound of one word: a bar through the whole waveform, capped at both ends
 * with a tab pointing into the word.
 *
 * The tabs are the grab target and the direction cue at once - you can see
 * which side of the span you have hold of before you pull. `state` is how live
 * it is: the focused bound (the one the arrow keys move) is bright, the one
 * under the cursor brighter still.
 */
function drawBound(g, x, y, h, side, state, tone) {
  const hot = state === 'hot', live = hot || state === 'focus';
  const dir = side === 'left' ? 1 : -1;
  const colour = tone || (live ? '#dce9ff' : 'rgba(160,198,255,.75)');

  if (hot) {                            // a soft column under the cursor
    g.fillStyle = 'rgba(120,175,255,.16)';
    g.fillRect(x + (dir > 0 ? 0 : -BOUND_GRAB), y, BOUND_GRAB, h);
  }
  const w = live ? 2.5 : 1.5;
  g.fillStyle = colour;
  g.fillRect(x - w / 2, y, w, h);
  boundCap(g, x, y, dir, true);
  boundCap(g, x, y + h, dir, false);
}

/** A small dark plate carrying a time, so a readout stays legible over audio. */
function timeChip(g, x, y, text, align, tone) {
  g.font = '600 11px ui-monospace, Menlo, monospace';
  const w = g.measureText(text).width + 10;
  const bx = align === 'right' ? x - w : align === 'mid' ? x - w / 2 : x;
  g.fillStyle = 'rgba(8,12,20,.88)';
  g.fillRect(bx, y, w, 16);
  g.fillStyle = tone || '#dbe7ff';
  g.textBaseline = 'top';
  g.fillText(text, bx + 5, y + 3);
  return w;
}

/**
 * The selected word: its coverage of the track, and both of its bounds as
 * handles you can take hold of.
 *
 * Drawn independently of the word cells, which switch off when a line is too
 * narrow to caption. The one word you are working on is exactly what you zoom
 * to, so its handles have to survive whatever the rest of the lane does.
 */
function drawWordFocus() {
  const g = selWordGeom();
  if (!g) return;
  const W = canvas.clientWidth;
  if (g.x1 < -40 || g.x0 > W + 40) return;

  const w = Math.max(1, g.x1 - g.x0);
  ctx.fillStyle = 'rgba(91,157,255,.10)';
  ctx.fillRect(g.x0, VOC_Y, w, VOC_H);

  const g2 = S.drag && S.drag.grab;
  const held = g2 && g2.line === g.line && g2.i === g.i ? g2.side : null;
  const over = S.hoverBound ? S.hoverBound.side : null;
  for (const side of ['left', 'right']) {
    const x = side === 'left' ? g.x0 : g.x1;
    const state = held === side || (!held && over === side) ? 'hot'
      : S.selBound === side ? 'focus' : 'idle';
    drawBound(ctx, x, VOC_Y, VOC_H, side, state);
  }

  // Both ends and the span between them, in numbers. The focused bound's own
  // readout is lit, so the arrow keys never act on a value you cannot see.
  const y = WORD_Y - 17;
  const lit = '#eaf2ff', dim = 'rgba(190,208,232,.75)';
  timeChip(ctx, clamp(g.x0 - 2, 40, W - 4), y, fmt(g.w.start), 'right',
       S.selBound === 'left' ? lit : dim);
  timeChip(ctx, clamp(g.x1 + 2, 4, W - 44), y, fmt(g.w.end), 'left',
       S.selBound === 'right' ? lit : dim);
  if (w > 74) {
    timeChip(ctx, (g.x0 + g.x1) / 2, y, `${(g.w.end - g.w.start).toFixed(2)}s`, 'mid', dim);
  }
}

function laneNote(text) {
  ctx.fillStyle = 'rgba(10,15,24,.8)';
  ctx.fillRect(0, WORD_Y, canvas.clientWidth, WORD_STRIP);
  ctx.fillStyle = C.muted;
  ctx.font = '12px -apple-system, system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 10, WORD_Y + WORD_STRIP / 2);
  ctx.textBaseline = 'top';
}

/** Floating time readout under the cursor while over the scrub bar. */
function drawScrubCursor() {
  const x = S.scrubHoverX;
  if (x == null) return;
  const label = fmt(x2t(x));
  ctx.font = '600 11px ui-monospace, Menlo, monospace';
  const w = ctx.measureText(label).width + 12;
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
  'click a word for its two bounds · drag either · shift takes the neighbour · , . pick, ← → nudge';

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
  drawWordFocus();
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

/** True when two words meet with no rest between them. */
function touching(a, b) { return a && b && Math.abs(b.start - a.end) < 1e-6; }

/**
 * Hit test the word strip across every line on screen.
 *
 * Every word edge is grabbable here, not only the selected word's - the cells
 * are where you reach for a boundary you can see without first selecting the
 * word under it. Where a rest sits between two words there are two edges to
 * grab, one per word, which is how a rest is widened or shut.
 *
 * Edges beat blocks - they are what you came here to drag - and the selected
 * line beats its neighbours where cells touch, so the line you are working on
 * never loses a boundary to the line next to it.
 */
function hitWord(x, y) {
  if (y < WORD_Y || y > VOC_Y + VOC_H) return null;
  let best = null;
  const keep = (cand) => { if (!best || cand.rank > best.rank) best = cand; };

  eachWordLine((line, blocks) => {
    const live = line.index === S.sel, ws = line.words;
    for (const b of blocks) {
      const rank = live ? 4 : 3;
      if (b.i > 0 && Math.abs(x - b.x0) <= WORD_GRAB) {
        keep({ line, kind: 'edge', i: b.i, side: 'left', rank });
      }
      // Where two words touch their edges are the same pixel, and the one
      // offered is the later word's start - which is the boundary you mean.
      // Shift carries the word behind it along; see setPair.
      if (Math.abs(x - b.x1) <= WORD_GRAB && !touching(b.w, ws[b.i + 1])) {
        keep({ line, kind: 'edge', i: b.i, side: 'right', rank });
      }
    }
    for (const b of blocks) {
      if (x >= b.x0 && x <= b.x1) keep({ line, kind: 'block', i: b.i, rank: live ? 2 : 1 });
    }
  });
  return best;
}

/**
 * The selected word's bounds, which own the vocal lane while a word is up.
 *
 * They beat the word cells and the line body: when a word is selected, its two
 * edges are the thing the surface is for. The line's own label strip along the
 * top is left alone (see LINE_BAND), so a line can still be moved and resized
 * without deselecting first.
 */
function hitBound(x, y) {
  if (y < VOC_Y + LINE_BAND || y > VOC_Y + VOC_H) return null;
  const g = selWordGeom();
  if (!g) return null;
  let best = null;
  for (const [side, bx] of [['left', g.x0], ['right', g.x1]]) {
    const d = Math.abs(x - bx);
    if (d > BOUND_GRAB) continue;
    // A tie on a word only a few pixels wide goes to the bound already focused.
    const rank = -d + (side === S.selBound ? 0.5 : 0);
    if (!best || rank > best.rank) best = { line: g.line, i: g.i, side, rank };
  }
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

  // A line nobody has scored is not a line that scored zero: the gold file
  // and a freshly added line both arrive without a scorecard, and a red 0 on
  // every row is a false alarm the eye cannot unsee.
  const scored = !!(line.score && line.score.total != null);
  const score = scored ? line.score.total : 0;
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
    (scored ? `<div class="score ${grade(score)}">${score.toFixed(0)}</div>`
            : '<div class="score none" title="not scored">—</div>');

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
  // Every edit path already refreshes the row it touched, so this is the one
  // place the deck's readouts have to be kept honest - undo and the review
  // sheet included.
  if (line.index === S.sel) { renderPlaceBar(); syncWordBar(); }
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
    glideView(line.start - Math.max(1.5, span * 0.4), Math.max(S.view.dur, span * 2.2), 300);
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
  const row = S.rows.get(S.sel);
  const el = S.selWord == null ? null : row && row.querySelectorAll('.w')[S.selWord];
  if (el) {
    el.classList.add('sel');
    el.dataset.bound = S.selBound;      // lights the bracket on the focused side
  }
  syncWordBar();
}

/**
 * The word bar: the selected word's span as numbers you can grab.
 *
 * The waveform is the place to drag a bound *against the audio*; this is the
 * place to see exactly where it is and move it by a known amount. Same word,
 * same two bounds, same focus - a click here and a click on a handle out there
 * mean the same thing, and the arrow keys act on whichever was clicked last.
 */
function syncWordBar() {
  const bar = S.el.wordBar;
  if (!bar) return;
  const line = S.project && S.project.lines[S.sel];
  const w = ((line && line.words) || [])[S.selWord];
  if (S.selWord == null || !w) { bar.hidden = true; return; }
  bar.hidden = false;
  S.el.wbText.textContent = w.text;
  S.el.wbLeft.querySelector('span').textContent = fmt(w.start);
  S.el.wbRight.querySelector('span').textContent = fmt(w.end);
  S.el.wbDur.textContent = `${(w.end - w.start).toFixed(2)}s`;
  S.el.wbLeft.classList.toggle('on', S.selBound === 'left');
  S.el.wbRight.classList.toggle('on', S.selBound === 'right');
}

/** Point the keyboard at one of the two bounds. The mouse does this by grabbing. */
function focusBound(side) {
  if (S.selWord == null) return false;
  if (S.selBound !== side) {
    S.selBound = side;
    paintSelWord();
    draw();
  }
  return true;
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
  S.hoverBound = null;
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
      if (rel > 0.72 || rel < 0) glideView(t - S.view.dur * 0.3, S.view.dur, 420);
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

/**
 * Nudge the focused bound of the selected word. False if no word is up, which
 * is what makes the arrow keys fall through to the line - the same key does
 * the finest thing available in the context you are actually in.
 */
function nudgeBound(delta) {
  const g = selWordGeom();
  if (!g) return false;
  const side = S.selBound;
  pushCoalesced(`nudge ${side} bound`, g.line);
  setBound(g.line, g.i, side, boundTime(g.line, g.i, side) + delta);
  refreshRow(g.line);
  ensureVisible(g.line);
  draw();
  return true;
}

/**
 * Stamp a bound at the playhead - S and E, the same two keys that set a line's
 * edges, acting on the word when there is one selected.
 */
function stampBound(side) {
  const g = selWordGeom();
  if (!g) return false;
  pushHistory(`set word ${side} bound`, [g.line]);
  S.selBound = side;
  setBound(g.line, g.i, side, S.audio.currentTime);
  refreshRow(g.line);
  paintSelWord();
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

/**
 * Take the audit from the project it belongs to. The queue and the proposals
 * are the project's own arrays, not copies: a `done` mark or a dismissal set
 * here is saved with the next write-back and survives a reload.
 */
function adoptAudit() {
  const data = (S.project.meta && S.project.meta.audit) || null;
  S.review.queue = (data && data.queue) || [];
  S.additions = (data && data.additions) || [];
  S.review.stats = data;
  S.review.at = 0;
  S.addAt = 0;
  indexTodo();
  rvBadge();
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

  // The repair pass edits the project server-side, and the audit lives in it.
  S.project = data;
  resetHistory();                            // the repair pass replaced the project
  adoptAudit();
  renderList();
  invalidate();
  draw();

  const repairs = (S.review.stats && S.review.stats.repairs) || [];
  if (repairs.length) {
    toast(`repaired ${repairs.length} impossible timing(s) automatically`);
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
  S.review.side = 'left';
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
    : ' If neither is right, drag either bracket on the strip to say where the ' +
      'word begins and ends — <kbd>,</kbd> and <kbd>.</kbd> aim the arrows at one.';
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
      // Left first, then right: the right bound's clamp is measured against the
      // left one, which is the order the strip staged them in - so what was
      // drawn is exactly what lands.
      setWordStart(line, item.word, adj && adj.t != null ? adj.t : item.proposed);
      if (adj && adj.end != null) setBound(line, item.word, 'right', adj.end);
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
    persistSoon();                      // the mark lives in the project now
  }

  // The decision itself is the label - including "keep as is", which says the
  // aligner was right and the rule that queued it was not.
  if (action !== 'skip' && line) {
    const after = action === 'accept'
      ? (adj && adj.t != null ? adj.t : item.proposed) : item.current;
    logDecisions([{
      source: 'review', action: adj ? 'adjust' : action, line: item.line, word: item.word,
      bound: item.scope === 'line' ? 'line' : 'start',
      before: item.current, after, proposed: item.proposed,
      reasons: item.reasons || [], severity: item.severity,
    }]);
    // The line as it stands now is what the next save should diff against;
    // otherwise the same edit would be logged again as a timeline drag.
    if (S.logged && S.loggedFor === S.project) rememberLogged(line);
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
  const adj = S.review.adj;
  return {
    cur: item.current,
    alt: item.proposed,
    adj: adj ? adj.t : null,
    adjEnd: adj ? adj.end : null,
  };
}

/**
 * Where the word's two bounds would sit if this card were accepted.
 *
 * The sheet stages rather than commits: its whole job is "listen to these, pick
 * one", and a drag that wrote through would leave the *Now* marker pointing at
 * a place the word no longer is. So the handles here move a proposal - drawn,
 * grabbed, snapped and nudged exactly like the ones on the timeline, and
 * applied through the same setBound the moment you take the card.
 */
function rvEff(item) {
  const line = S.project.lines[item.line];
  const w = line && (line.words || [])[item.word];
  const adj = S.review.adj;
  return {
    left: adj && adj.t != null ? adj.t : (w ? w.start : item.current),
    right: adj && adj.end != null ? adj.end : (w ? w.end : item.current + 0.3),
    staged: !!adj,
  };
}

/** How far a line-scope adjustment moves the proposed placement. */
function rvOffset(item) {
  return S.review.adj && S.review.adj.t != null ? S.review.adj.t - item.proposed : 0;
}

/** The moment the adjusted version says the word begins - what to play. */
function rvAdjPlay(item) {
  if (!item) return 0;
  const adj = S.review.adj;
  return adj && adj.t != null ? adj.t : rvEff(item).left;
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
    const e = rvEff(item);
    rvBand(g, e.left, e.right, e.staged ? 'rgba(180,140,255,.15)' : 'rgba(91,157,255,.13)');
  }

  // The vocal itself - the only evidence any of this is decided on - and the
  // onset ticks a snap lands on, so a snap is never a surprise.
  stripWave(g, W, RV_H, RVW.a, RVW.b);

  // The adjusted one, when it exists, is the live one; the other two dim.
  if (c.cur != null) rvMarker(g, c.cur, C.sel, c.adj == null);
  if (c.alt != null) rvMarker(g, c.alt, C.good, c.adj == null);

  // The word's two bounds, drawn by the same painter as the timeline's. Grab
  // either one; the focused one is what the arrow keys move.
  if (item.scope !== 'line') {
    const e = rvEff(item);
    const tone = e.staged ? C.adj : null;
    for (const side of ['left', 'right']) {
      const x = rvT2X(side === 'left' ? e.left : e.right);
      const held = S.review.drag && S.review.drag.side === side;
      drawBound(g, x, 0, RV_H, side,
                held ? 'hot' : S.review.side === side ? 'focus' : 'idle', tone);
    }
  } else if (c.adj != null) {
    rvMarker(g, c.adj, C.adj, true);
  }

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
 * Word scope defers to boundRange - the very function the accept will clamp
 * with - so the strip can never show a position that would be silently dragged
 * somewhere else. Line scope has no neighbours to answer to, the whole line
 * moves, so it is held to the drawn window instead.
 */
function rvRange(item, side) {
  // A line-scope drag has no neighbouring words to answer to - the whole line
  // rides along - so it is held to the drawn window, which already spans both
  // placements and the padding either side of them.
  if (item.scope === 'line') return [Math.max(0, RVW.a), RVW.b];
  const line = S.project.lines[item.line];
  let [lo, hi] = boundRange(line, item.word, side || 'left');

  // Both bounds can be staged at once, and the card is applied left first, so
  // each has to be held to what the other will already have made true. Without
  // this the strip could draw a span the accept would then quietly reshape.
  const adj = S.review.adj;
  if (adj) {
    if (side === 'left' && adj.end != null) hi = Math.min(hi, adj.end - MIN_WORD);
    if (side === 'right' && adj.t != null) lo = adj.t + MIN_WORD;
  }
  return [lo, Math.max(lo, hi)];
}

function rvClampT(item, t, side) {
  const [lo, hi] = rvRange(item, side || 'left');
  return clamp(t, lo, hi);
}

/**
 * Place one staged bound. `free` is alt: take the time literally.
 *
 * Line scope has only the one handle - the marker that shifts the whole
 * proposed placement - so it always writes the left side.
 */
function rvSetAdj(t, free, side) {
  const item = rvCurrent();
  if (!item) return;
  side = item.scope === 'line' ? 'left' : (side || S.review.side || 'left');
  const snapped = free ? t : snapOnset(t);
  const out = rvClampT(item, snapped, side);
  // Flash only on a snap that survived the clamp - a ring on a boundary the
  // model then moved would be a lie about what just happened.
  if (snapped !== t && out === snapped) S.flash = { t: out, at: performance.now() };
  const eff = rvEff(item);
  const adj = S.review.adj || { t: null, end: null };
  // The first touch of either handle stages both, so what the strip draws is
  // the whole span the accept will write - never half of it.
  S.review.adj = side === 'left'
    ? { t: out, end: item.scope === 'line' ? null : (adj.end != null ? adj.end : eff.right) }
    : { t: adj.t != null ? adj.t : eff.left, end: out };
  S.review.side = side;
  rvSyncAdj();
  rvDrawStrip();
}

function rvResetAdj() {
  S.review.adj = null;
  S.review.side = 'left';
  if (S.review.lastPlayed === 'adj') S.review.lastPlayed = null;
  rvSyncAdj();
  rvDrawStrip();
}

/** Point the sheet's arrow keys at one bound. Grabbing a handle does the same. */
function rvFocus(side) {
  const item = rvCurrent();
  if (!item || item.scope === 'line') return;
  S.review.side = side;
  rvSyncAdj();
  rvDrawStrip();
}

/**
 * Nudge the focused bound by 50 ms (shift: 10 ms).
 *
 * The left bound starts from whichever candidate is armed - the last you
 * listened to, or else the suggestion, which is what the primary button would
 * take. The right bound has no candidates to choose between, so it starts from
 * where the word currently ends.
 */
function rvNudgeAdj(delta) {
  const item = rvCurrent();
  if (!item) return;
  const c = rvCands();
  const side = item.scope === 'line' ? 'left' : (S.review.side || 'left');
  let base;
  if (side === 'right') {
    base = c.adjEnd != null ? c.adjEnd : rvEff(item).right;
  } else {
    base = c.adj != null ? c.adj
      : S.review.lastPlayed === 'cur' ? c.cur
      : c.alt != null ? c.alt : c.cur;
  }
  if (base == null) return;
  rvSetAdj(base + delta, true, side);   // a nudge is deliberate: no onset snap
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
  if (on && item) {
    // Word scope adjusts a span, so the readout is a span. Line scope adjusts
    // one placement, and says so with one time.
    const e = rvEff(item);
    RV('rv-adj-time').textContent = item.scope === 'line'
      ? fmt(rvAdjPlay(item)) : `${fmt(e.left)} → ${fmt(e.right)}`;
  }
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

  // A bound handle first, exactly as on the timeline: whichever of the word's
  // two edges is nearest the grab, dragged from where it already is rather
  // than jumping to the cursor.
  let side = 'left', from = rvX2T(x), near = RV_GRAB + 1;
  if (item.scope !== 'line') {
    const eff = rvEff(item);
    for (const [s, t] of [['left', eff.left], ['right', eff.right]]) {
      const d = Math.abs(rvT2X(t) - x);
      if (d < near) { near = d; from = t; side = s; }
    }
  }
  // Failing that, one of the two candidate markers - they are start times, so
  // they refine the left bound. Clicking bare waveform is the blunt version of
  // the same thing: put this bound here.
  if (near > RV_GRAB) {
    for (const t of [c.adj, c.alt, c.cur]) {
      if (t == null) continue;
      const d = Math.abs(rvT2X(t) - x);
      if (d < near) { near = d; from = t; side = 'left'; }
    }
  }
  S.review.side = side;
  S.review.drag = { x0: x, t0: from, side };
  if (near > RV_GRAB) rvSetAdj(from, e.altKey, side);
  else { rvSyncAdj(); rvDrawStrip(); }
}

function rvStripMove(e) {
  const d = S.review.drag;
  if (!d) return;
  const x = e.clientX - RV('rv-wave').getBoundingClientRect().left;
  rvSetAdj(d.t0 + (x - d.x0) * (RVW.b - RVW.a) / RVW.w, e.altKey, d.side);
}

function rvStripUp() {
  if (!S.review.drag) return;
  S.review.drag = null;
  rvDrawStrip();
}

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

  // Dismissing is only "not now": a flag on the proposal, which sits in the
  // project and goes to disk with the next write-back. Adding a line renumbers
  // the whole project - the review queue, the marks, both aligners' spans, the
  // round-trip's observations - and that belongs on the server, which owns the
  // model.
  if (action !== 'accept') {
    cand.dismissed = true;
    markDirty();
    renderList();
  } else {
    if (needsServer('Adding a line')) return;
    let data;
    try {
      const res = await fetch('/api/additions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate: cand }),
      });
      if (!res.ok) throw new Error(await res.text());
      data = await res.json();
    } catch (err) {
      return toast('could not update the lyrics: ' + err.message, true);
    }
    // Every line after the insertion is renumbered, so the queue, the todo
    // marks and the undo stack all have to come from the server's new truth
    // rather than be patched here - the same reset the audit itself does.
    S.project = data.project;
    resetHistory();
    adoptAudit();
    renderList();
    invalidate();
    draw();
    toast(`line added at ${fmt(cand.start)} — it is in the exports now`);
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
      // The name comes from the audio file, so two alignments of one song are
      // the same name twice. The folder is what actually tells them apart.
      `<span class="tk-meta">${escapeHtml(t.dir.split('/').pop())} · ` +
        `${t.lines} lines · score ${t.score}</span>` +
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

/* ------------------------------------------------------------- decisions

   Every bound a person moves is a label: the aligner said one thing, the ear
   said another, by this much. The server keeps them (decisions.jsonl in the
   workdir, with the word's features at the time) so that, with a few hundred
   across several tracks, the audit queue can be ranked by "a human changed
   this" instead of by rule severity. Nothing here can fail a save: the post
   is fire-and-forget, and the demo has nowhere to send it. */

function logDecisions(entries) {
  if (STATIC || !entries.length) return;
  try {
    fetch('/api/decisions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entries),
      keepalive: true,
    }).catch(() => {});
  } catch (err) { /* a log is never worth an error */ }
}

/** Remember the bounds as last logged, so a save can report what moved. */
function rememberLogged(line) {
  if (!S.logged || S.loggedFor !== S.project) { S.logged = {}; S.loggedFor = S.project; }
  S.logged[line.index] = (line.words || []).map(w => [w.start, w.end]);
}

/** Timeline edits since the last save or review decision, one per bound. */
function timelineDecisions() {
  const out = [];
  if (!S.logged || S.loggedFor !== S.project) {
    // First sight of this project: baseline it and report nothing, because
    // nothing has been decided yet.
    (S.project.lines || []).forEach(rememberLogged);
    return out;
  }
  for (const line of S.project.lines || []) {
    const was = S.logged[line.index];
    const ws = line.words || [];
    if (!was || was.length !== ws.length) { rememberLogged(line); continue; }
    ws.forEach((w, i) => {
      if (Math.abs(w.start - was[i][0]) > 1e-6)
        out.push({ source: 'timeline', action: 'drag', line: line.index, word: i,
                   bound: 'start', before: was[i][0], after: w.start });
      if (Math.abs(w.end - was[i][1]) > 1e-6)
        out.push({ source: 'timeline', action: 'drag', line: line.index, word: i,
                   bound: 'end', before: was[i][1], after: w.end });
    });
    rememberLogged(line);
  }
  return out;
}

async function save(opts) {
  const quiet = !!(opts && opts.quiet);
  if (quiet ? !!STATIC : needsServer('Saving')) return;
  cancelPersist();
  logDecisions(timelineDecisions());
  const at = S.hist.undo.length;            // what this write actually covers
  S.saving = true;
  let res;
  try {
    res = await fetch('/api/project', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(S.project),
    });
  } catch (err) {
    S.saving = false;
    if (!quiet) toast('save failed — ' + err.message, true);
    return;
  }
  S.saving = false;
  if (!res.ok) return toast('save failed', true);
  S.hist.savedAt = at;                      // undoing back to here is "clean" again
  syncHistory();
  adoptScores(await res.json());
  if (quiet) flashSaved(); else toast('saved — lrc, word-lrc, srt and vtt rewritten');
}

/**
 * Take the scores the server computed for what was just saved.
 *
 * Scores only - the timings, the history and the selection stay as they are,
 * because more edits may have landed while the write was in flight. The
 * score is a function of the file, so it arrives with every save rather than
 * on request; this is what keeps the chips and the flags telling the truth
 * about the timings under them.
 */
function adoptScores(fresh) {
  if (!fresh || !fresh.lines || !S.project) return;
  fresh.lines.forEach((l, i) => {
    const line = S.project.lines[i];
    if (!line || line.text !== l.text) return;
    line.score = l.score;
    line.flagged = l.flagged;
  });
  S.project.scorecard = fresh.scorecard;
  renderScorecard(fresh.scorecard);
  if (S.filter === 'flagged') { renderList(); }
  else for (const line of S.project.lines) refreshScore(line);
  invalidate();                           // the minimap marks the flagged lines
  draw();
}

/** Patch one row's score cell and issues to match the line. */
function refreshScore(line) {
  const row = S.rows.get(line.index);
  if (!row) return;
  const scored = !!(line.score && line.score.total != null);
  const score = scored ? line.score.total : 0;
  const issues = (line.score && line.score.issues) || [];
  row.classList.toggle('flagged', !!line.flagged);
  const cell = row.querySelector('.score');
  cell.className = scored ? `score ${grade(score)}` : 'score none';
  cell.textContent = scored ? score.toFixed(0) : '—';
  const why = row.querySelector('.issues');
  why.textContent = issues.length ? `▲ ${issues.join(' · ')}` : '';
  why.title = issues.join(' · ');
}

/** A quiet save says so on the button rather than over the whole window. */
function flashSaved() {
  const b = document.getElementById('btn-save');
  if (!b) return;
  b.classList.remove('dirty');
  b.classList.add('just-saved');
  b.innerHTML = 'Saved<span class="k">⌘S</span>';
  clearTimeout(flashSaved._t);
  flashSaved._t = setTimeout(() => {
    b.classList.remove('just-saved');
    paintSaveBtn();
  }, 1300);
}

/* ---------------------------------------------------------------- events */

/**
 * Take hold of a bound.
 *
 * Every grab in the lane ends up here - a handle on the selected word, or a
 * divider between two cells - so there is one history step, one clamp, one
 * snap and one cursor for all of them. The grab offset is carried so the bound
 * never jumps to the pointer on the first pixel of the drag.
 */
function startBoundDrag(g, x) {
  selectWord(g.line.index, g.i, false);
  S.selBound = g.side;
  S.drag = {
    grab: g,
    off: grabTime(g) - x2t(x),
    entry: pushHistory(`move ${g.side} bound`, [g.line]),
  };
  canvas.style.cursor = 'col-resize';
  paintSelWord();
  draw();
}

/**
 * What a bound is, in words - including what else it is.
 *
 * A word ends where the next begins, so a right bound *is* the next word's
 * start and moving it moves both. Saying so on hover is the cheapest way to
 * teach the one rule this model runs on.
 */
function boundLabel(line, i, side) {
  const ws = line.words || [];
  const w = ws[i];
  const t = fmt(boundTime(line, i, side));
  const rest = gap => gap > 1e-6 ? `${gap.toFixed(2)}s of rest` : 'no rest';
  if (side === 'left') {
    return i === 0 ? `"${w.text}" starts at ${t} — and so does the line`
      : `"${w.text}" starts at ${t} — ${rest(w.start - ws[i - 1].end)} ` +
        `after "${ws[i - 1].text}"`;
  }
  return i === ws.length - 1 ? `"${w.text}" ends at ${t} — and so does the line`
    : `"${w.text}" ends at ${t} — ${rest(ws[i + 1].start - w.end)} ` +
      `before "${ws[i + 1].text}"`;
}

/** True when the bound under the cursor changed, so the caller repaints once. */
function hoverBoundChanged(b) {
  const was = S.hoverBound;
  if ((!was && !b) || (was && b && was.line === b.line && was.i === b.i
      && was.side === b.side)) return false;
  S.hoverBound = b;
  return true;
}

function bindCanvas() {
  canvas.addEventListener('mousedown', e => {
    const r = canvas.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;

    if (y < MINI_H) {
      const t = (x / canvas.clientWidth) * duration();
      glideView(t - S.view.dur / 2, S.view.dur, 260);
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

    // The selected word's own bounds come first: while a word is up, its two
    // edges are what this lane is for.
    const bound = hitBound(x, y);
    if (bound) {
      startBoundDrag(bound, x);
      return;
    }

    const word = hitWord(x, y);
    if (word) {
      // An edge in the cells is the same edit as a handle on the selected word,
      // reached without selecting first, so it starts the very same drag.
      if (word.kind === 'edge') {
        startBoundDrag({ line: word.line, i: word.i, side: word.side }, x);
      } else {
        selectWord(word.line.index, word.i, false);
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

    if (S.drag && S.drag.grab) {
      const d = S.drag;
      // Carrying the grab offset means the bound never jumps to the cursor on
      // the first pixel - you keep hold of exactly where you took it.
      placeGrab(d.grab, x2t(x) + d.off, e.altKey, e.shiftKey);
      refreshRow(d.grab.line);
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

    const bound = hitBound(x, y);
    if (hoverBoundChanged(bound)) draw();
    if (bound) {
      canvas.style.cursor = 'col-resize';
      setHint(`${boundLabel(bound.line, bound.i, bound.side)}` +
        `   drag to move  ·  shift = take the neighbour too  ·  alt = no snap`);
      return;
    }

    const word = hitWord(x, y);
    if (word) {
      const w = word.line.words[word.i];
      canvas.style.cursor = word.kind === 'edge' ? 'col-resize' : 'pointer';
      setHint(word.kind === 'edge'
        ? `${boundLabel(word.line, word.i, word.side)}   drag to move  ·  ` +
          `shift = take the neighbour too`
        : `word ${word.i}: "${w.text}"  ${fmt(w.start)} → ${fmt(w.end)}` +
          `  (${(w.end - w.start).toFixed(2)}s)`);
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
    if (S.drag || S.scrub) return;
    restHint();
    if (hoverBoundChanged(null)) draw();
  });

  window.addEventListener('mouseup', () => {
    if (S.drag) {
      dropIfUnchanged(S.drag.entry);       // a click that moved nothing is not an edit
      canvas.style.cursor = 'crosshair';
      S.drag = null;
      draw();                              // drop the held highlight off the handle
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
        // The same two keys the timeline uses to pick a bound.
        case ',': case '<': e.preventDefault(); rvFocus('left'); break;
        case '.': case '>': e.preventDefault(); rvFocus('right'); break;
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
    // alt+arrow walks the words, the way alt+arrow walks words in a text
    // field. Same job as tab, on the hand that is already nudging.
    if (e.altKey && !e.metaKey && !e.ctrlKey
        && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      e.preventDefault();
      stepWord(e.key === 'ArrowRight' ? 1 : -1);
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;


    // Arrows are context-sensitive: they move the focused bound of the selected
    // word if there is one, otherwise the whole line, so existing muscle memory
    // carries over. Coarse by default, fine with shift.
    const step = e.shiftKey ? 0.01 : 0.05;

    switch (e.key) {
      case ' ':
        e.preventDefault();
        S.audio.paused ? S.audio.play() : S.audio.pause();
        break;
      case 'Tab': e.preventDefault(); stepWord(e.shiftKey ? -1 : 1); break;
      case 'Escape': e.preventDefault(); deselectWord(); break;
      case 'ArrowLeft': e.preventDefault(); if (!nudgeBound(-step)) nudge(-step); break;
      case 'ArrowRight': e.preventDefault(); if (!nudgeBound(step)) nudge(step); break;
      case 'ArrowUp': e.preventDefault(); select(S.sel - 1); break;
      case 'ArrowDown': e.preventDefault(); select(S.sel + 1); break;
      case 'Enter': e.preventDefault(); preview(S.project.lines[S.sel]); break;
      // The two keys that set a line's edges, acting on the word when one is
      // selected - the same context-sensitivity the arrows have.
      case 's': case 'S': e.preventDefault(); if (!stampBound('left')) setEdge('start'); break;
      case 'e': case 'E': e.preventDefault(); if (!stampBound('right')) setEdge('end'); break;
      // Which bound the arrows move. Clicking a handle does the same thing.
      case ',': case '<': e.preventDefault(); focusBound('left'); break;
      case '.': case '>': e.preventDefault(); focusBound('right'); break;
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

/* The deck's two bound chips.

   A click aims the arrow keys at that bound - exactly what clicking its handle
   on the waveform does. A horizontal drag scrubs it at 4 ms a pixel (shift:
   1 ms), which is the fine control a wide zoom cannot give you out on the lane.
   Same setBound underneath, so the same one undo step and the same write-back. */

const CHIP_MS = 0.004, CHIP_FINE = 0.001;

function bindWordBar() {
  for (const btn of [S.el.wbLeft, S.el.wbRight]) {
    const side = btn.dataset.side;

    btn.addEventListener('pointerdown', e => {
      const g = selWordGeom();
      if (!g) return;
      e.preventDefault();
      btn.setPointerCapture(e.pointerId);
      focusBound(side);
      S.wbDrag = {
        side, i: g.i, line: g.line, x0: e.clientX,
        t0: boundTime(g.line, g.i, side),
        entry: pushHistory(`move ${side} bound`, [g.line]),
      };
    });

    btn.addEventListener('pointermove', e => {
      const d = S.wbDrag;
      if (!d) return;
      const dx = e.clientX - d.x0;
      if (Math.abs(dx) < 2) return;      // a click is a click, not a 1 ms edit
      setBound(d.line, d.i, d.side, d.t0 + dx * (e.shiftKey ? CHIP_FINE : CHIP_MS));
      refreshRow(d.line);
      draw();
    });

    const done = e => {
      const d = S.wbDrag;
      if (!d) return;
      S.wbDrag = null;
      dropIfUnchanged(d.entry);          // a plain click costs no undo step
      if (btn.hasPointerCapture(e.pointerId)) btn.releasePointerCapture(e.pointerId);
    };
    btn.addEventListener('pointerup', done);
    btn.addEventListener('pointercancel', done);
  }
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

  document.getElementById('btn-zoom-in').addEventListener('click', () => zoomAt(S.audio.currentTime, 0.6, true));
  document.getElementById('btn-zoom-out').addEventListener('click', () => zoomAt(S.audio.currentTime, 1.7, true));
  document.getElementById('btn-zoom-fit').addEventListener('click', () => glideView(0, duration(), 360));

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
  for (const id of ['btn-review', 'btn-export', 'btn-save', 'btn-undo', 'btn-redo']) {
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
  // The one card whose primary action cannot run here says so on the card,
  // rather than looking like a button that does nothing.
  RV('rv-add').querySelector('.rv-foot').innerHTML =
    'In this demo, adding a line needs the app on your machine - it writes the ' +
    'line into the project and every export, and renumbers everything after it. ' +
    '<em>Not a line</em> works here.';
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
  S.el.wordBar = document.getElementById('wordbar');
  S.el.wbText = document.getElementById('wb-text');
  S.el.wbLeft = document.getElementById('wb-left');
  S.el.wbRight = document.getElementById('wb-right');
  S.el.wbDur = document.getElementById('wb-dur');

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
  adoptAudit();          // before the list, so the queue is marked in it
  renderList();
  bindCanvas();
  bindKeys();
  bindChrome();
  bindReview();
  bindWordBar();
  bindAdditions();
  syncHistory();
  restHint();
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
