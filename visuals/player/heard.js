// What was heard, drawn beside the picture: a line each for the kick, the bass, the notes
// and the voice, every moment of theirs a mark on it. The song runs through from the right,
// at the same pace whatever the width; a mark lights as it comes to the line in the middle,
// which is now, and that is the moment the picture moves. They are the plan's own moments (render.heard), read back from the
// channels the picture is drawn from, and the clock is the picture's own (player.time).
//
//   strip(canvas, player)   draws into `canvas`, at the size the page gives it, for as long
//                           as it is on screen; returns { stop() }
//
// Nothing is decided here. It draws what it is given, sixty times a second, and costs a
// few dozen rectangles a frame.

const PARTS = [
  { name: "kick", height: 16 },
  { name: "bass", height: 16 },
  { name: "notes", height: 26 },
  { name: "voice", height: 16 },
];
const GAP = 8;                   // between two lines
const LABELS = 52;               // the names' column
const PACE = 110;                // pixels to a second,
const LEAST = 4.2;               // unless that would show fewer seconds than this
const INK = "245,245,247";

export const HEIGHT = PARTS.reduce((h, p) => h + p.height, 0) + GAP * (PARTS.length - 1);

const smooth = (x) => { const c = Math.min(Math.max(x, 0), 1); return c * c * (3 - 2 * c); };

// How lit a mark is, `age` seconds after its moment (before it, negative): it comes up over
// the last tenth of a second, is brightest on its moment, and settles after.
export function lit(age) {
  if (age < 0) return smooth(1 + age / 0.1);
  return Math.exp(-age / 0.22);
}

// the first of the sorted `times` that is not before `t`
export function from(times, t) {
  let a = 0, b = times.length;
  while (a < b) { const m = (a + b) >> 1; if (times[m] < t) a = m + 1; else b = m; }
  return a;
}

export function strip(canvas, player) {
  const ctx = canvas.getContext("2d");
  let W = 0, H = 0, dpr = 1, frame = 0, shown = true, drawn = -1, stopped = false;

  function fit() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    drawn = -1;
  }

  function draw(t) {
    const heard = player.heard;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    if (!heard) return;
    const left = LABELS, width = W - left;
    const now = Math.round(W / 2);                          // under the middle of the picture
    const per = Math.min(PACE, width / LEAST);              // pixels to a second
    const BEFORE = (now - left) / per, AHEAD = (W - now) / per;
    ctx.font = '500 11px -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif';
    ctx.textBaseline = "middle";
    let top = Math.max(0, (H - HEIGHT) / 2);
    for (const part of PARTS) {
      const got = heard[part.name], h = part.height, mid = top + h / 2;
      let loudest = 0;
      if (got) {
        for (let i = from(got.t, t - BEFORE); i < got.t.length && got.t[i] <= t + AHEAD; i++) {
          const age = t - got.t[i], x = now - age * per, a = got.a[i], glow = lit(age);
          // it comes in at the right edge and goes out at the left, never at once
          const edge = smooth((x - left) / 36) * smooth((left + width - x) / 36);
          const ink = (age < 0 ? 0.24 + 0.76 * glow : 0.42 + 0.58 * glow) * edge;
          if (Math.abs(age) < 0.5) loudest = Math.max(loudest, glow * (0.4 + 0.6 * a));
          ctx.fillStyle = `rgba(${INK},${ink.toFixed(3)})`;
          if (part.name === "kick") {                        // a stroke the height of the line
            const tall = h * (0.45 + 0.55 * a) * (1 + 0.18 * glow);
            ctx.fillRect(Math.round(x) - 1, mid - tall / 2, 2, tall);
          } else if (part.name === "bass") {                 // a block, standing on the line's foot
            const tall = Math.max(2, h * (0.2 + 0.8 * a));
            ctx.fillRect(Math.round(x) - 2, top + h - tall, 5, tall);
          } else if (part.name === "notes") {                // a dash at its planet's height, the Sun's side lowest
            const y = top + h - 2 - (got.k[i] / 7) * (h - 4);
            ctx.fillRect(Math.round(x) - 3, Math.round(y) - 1, 6 + 4 * glow, 2);
          } else {                                           // a dot, as big as the syllable
            const r = 1.4 + 2.2 * a + 1.2 * glow;
            ctx.beginPath(); ctx.arc(x, mid, r, 0, 6.2832); ctx.fill();
          }
        }
      }
      ctx.fillStyle = `rgba(${INK},${(0.38 + 0.62 * Math.min(loudest, 1)).toFixed(3)})`;
      ctx.fillText(part.name, 0, mid + 0.5);
      top += h + GAP;
    }
    ctx.fillStyle = `rgba(${INK},0.5)`;
    ctx.fillRect(now, 0, 1, H);
  }

  function tick() {
    if (stopped) return;
    frame = shown ? requestAnimationFrame(tick) : 0;
    if (!W) return;
    const t = player.time();
    if (t === drawn) return;                                 // the song stands still, and so does this
    draw(t);
    drawn = t;
  }

  const sized = new ResizeObserver(() => { fit(); if (W) draw(player.time()); });
  sized.observe(canvas);
  const seen = new IntersectionObserver((entries) => {
    shown = entries[entries.length - 1].isIntersecting;
    if (shown && !frame && !stopped) frame = requestAnimationFrame(tick);
  });
  seen.observe(canvas);
  fit();
  frame = requestAnimationFrame(tick);

  return {
    stop() { stopped = true; cancelAnimationFrame(frame); sized.disconnect(); seen.disconnect(); },
  };
}
