// The studio's timeline, as arithmetic: where things are in bars, and what a gesture on
// the timeline asks of the sheet. A gesture is turned into edits in the sheet's own
// vocabulary (visuals/pieces/gravity/editor.py, `apply`) - the edits the model makes - and
// the server applies them. Nothing here changes a sheet itself; a test holds these edits
// to what `apply` then does.

// The bar a moment falls in, with its fraction: bar i runs from barT[i] to barT[i+1],
// and the last to the end of the song.
export function barOf(barT, duration, t) {
  const n = barT.length;
  if (t <= barT[0]) return 0;
  if (t >= duration) return n;
  let lo = 0, hi = n - 1;
  while (lo < hi) {                                   // the last bar line at or before t
    const mid = (lo + hi + 1) >> 1;
    if (barT[mid] <= t) lo = mid; else hi = mid - 1;
  }
  const end = lo + 1 < n ? barT[lo + 1] : duration;
  return lo + (t - barT[lo]) / Math.max(end - barT[lo], 1e-6);
}

// ...and back: the moment a (fractional) bar begins.
export function timeOf(barT, duration, b) {
  const n = barT.length;
  if (b <= 0) return Math.max(barT[0], 0);
  if (b >= n) return duration;
  const i = Math.floor(b);
  const end = i + 1 < n ? barT[i + 1] : duration;
  return barT[i] + (b - i) * (end - barT[i]);
}

const shotEdit = (bars, act) => ({ op: "shot", bars, shot: act.shot, subject: act.subject || "none" });

// The line between act i and the next, dragged to bar `to`: the act it moves into gives
// up those bars to the other. Each act keeps at least a bar.
export function edgeEdits(acts, i, to) {
  const at = acts[i].bars[1];
  const b = Math.min(Math.max(Math.round(to), acts[i].bars[0] + 1), acts[i + 1].bars[1] - 1);
  if (b === at) return [];
  return b < at ? [shotEdit([b, at], acts[i + 1])] : [shotEdit([at, b], acts[i])];
}

// Bars [a, b) given a shot (and, for the close shots, a planet).
export function spanEdit(a, b, shot, subject) {
  return { op: "shot", bars: [Math.min(a, b), Math.max(a, b)], shot, subject: subject || "none" };
}

// A moment dragged from its bar to another; strength kept.
export function momentEdits(moment, to) {
  const b = Math.round(to);
  if (b === moment.bar) return [];
  return [{ op: "reentry", bar: moment.bar, strength: 0 }, { op: "reentry", bar: b, strength: moment.strength }];
}

// What a proposal changes, for drawing it over what is there: the acts of `after` that
// `before` does not have, and the moments added, taken out or made stronger or weaker.
export function changedActs(before, after) {
  const key = (a) => `${a.bars[0]}-${a.bars[1]}-${a.shot}-${a.subject || ""}`;
  const had = new Set(before.map(key));
  return after.map((a, i) => (had.has(key(a)) ? -1 : i)).filter((i) => i >= 0);
}

export function changedMoments(before, after) {
  const was = new Map(before.map((r) => [r.bar, r.strength]));
  const now = new Map(after.map((r) => [r.bar, r.strength]));
  return {
    added: after.filter((r) => !was.has(r.bar)).map((r) => r.bar),
    removed: before.filter((r) => !now.has(r.bar)).map((r) => r.bar),
    changed: after.filter((r) => was.has(r.bar) && Math.abs(was.get(r.bar) - r.strength) > 1e-9).map((r) => r.bar),
  };
}
