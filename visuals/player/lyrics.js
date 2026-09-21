// How bright a lyric is at a moment: copies of visuals/pieces/gravity/lyrics.py's `ink`
// and `opacity`, which decide it. A test (test_lyrics.py) runs these under node and holds
// them to the Python to within rounding. Nothing here touches the page.

export function ease(x) {
  x = Math.min(Math.max(x, 0), 1);
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

// a word: unsung until `lead` before it, eased up to `peak` on it, down to `sung` over its length
export function lyricInk(t, start, end, st) {
  if (t < start - st.lead) return st.unsung;
  if (t < start) return st.unsung + (st.peak - st.unsung) * ease((t - (start - st.lead)) / st.lead);
  const settle = Math.max(end - start, 0.25);
  if (t < start + settle) return st.peak + (st.sung - st.peak) * ease((t - start) / settle);
  return st.sung;
}

// a line: eased in and out on its four moments, in: [in0, in1], out: [out0, out1]
export function lyricOpacity(t, line) {
  const [in0, in1] = line.in, [out0, out1] = line.out;
  if (t <= in0 || t >= out1) return 0;
  return Math.min(ease((t - in0) / Math.max(in1 - in0, 1e-3)), ease((out1 - t) / Math.max(out1 - out0, 1e-3)));
}
