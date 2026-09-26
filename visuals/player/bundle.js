// How the player reads a bundle's arrays, in either of its two forms. Which form is the
// plan's to say, never the URL's:
//
//   as `export` writes it (render.py): float32, frame by frame, as is. This machine.
//   as `pack` writes it: channel by channel, each column float16 or float32 as the plan's
//   `frames_dtype` lists, as byte planes, gzipped (the file's name ends in .gz). The demo.
//
// Everything comes out as the same Float32Array, so nothing after this knows which it was.
// A test (test_pack.py) runs this under node against what Python packed; nothing here
// touches the page.

// One float16, by hand: `Float16Array` is too new to rely on.
export function halfToFloat(h) {
  const sign = h & 0x8000 ? -1 : 1;
  const exp = (h >> 10) & 0x1f;
  const frac = h & 0x3ff;
  if (exp === 0) return sign * frac * 2 ** -24;             // zero and the subnormals
  if (exp === 31) return frac ? NaN : sign * Infinity;
  return sign * (1 + frac / 1024) * 2 ** (exp - 15);
}

// Every float16 there is, looked up rather than worked out nine million times a song.
let table = null;
export function halves(u16) {
  if (!table) {
    table = new Float32Array(65536);
    for (let h = 0; h < 65536; h++) table[h] = halfToFloat(h);
  }
  const out = new Float32Array(u16.length);
  for (let i = 0; i < u16.length; i++) out[i] = table[u16[i]];
  return out;
}

// `bytes` holds one column of `length` values for each entry of `dtypes`, one after the
// other, each as byte planes: every value's first byte, then every value's second, and so on.
export function columns(bytes, dtypes, length) {
  const out = [];
  let at = 0;
  for (const dtype of dtypes) {
    const size = dtype === "f16" ? 2 : dtype === "f32" ? 4 : 0;
    if (!size) throw new Error(`no such dtype: ${dtype}`);
    const col = new Uint8Array(length * size);
    for (let b = 0; b < size; b++) {
      const plane = at + b * length;
      for (let i = 0; i < length; i++) col[i * size + b] = bytes[plane + i];
    }
    out.push(size === 2 ? halves(new Uint16Array(col.buffer)) : new Float32Array(col.buffer));
    at += length * size;
  }
  if (at !== bytes.length) throw new Error(`${bytes.length} bytes where ${at} were expected`);
  return out;
}

// A gzipped file, inflated. A server that sends it with Content-Encoding: gzip has had the
// browser inflate it already, and then it no longer starts with gzip's two magic bytes.
export async function inflate(buffer) {
  const head = new Uint8Array(buffer, 0, Math.min(2, buffer.byteLength));
  if (head[0] !== 0x1f || head[1] !== 0x8b) return buffer;
  const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).arrayBuffer();
}

// A file of the bundle, as bytes, inflated if the plan named it .gz.
export async function fetchBytes(url, name, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${name}: ${res.status} ${res.statusText}`);
  const buffer = await res.arrayBuffer();
  return name.endsWith(".gz") ? inflate(buffer) : buffer;
}

// The grid: frames x channels, frame by frame, float32.
export function gridValues(buffer, plan) {
  if (plan.frames_packing !== "planes") return new Float32Array(buffer);
  const frames = plan.grid.frames, stride = plan.frames_dtype.length;
  const cols = columns(new Uint8Array(buffer), plan.frames_dtype, frames);
  const out = new Float32Array(frames * stride);
  cols.forEach((col, c) => { for (let i = 0; i < frames; i++) out[i * stride + c] = col[i]; });
  return out;
}

// A lookup texture's values, float32, as Python wrote them (to within HALF_ERROR if float16).
export function textureValues(buffer, spec) {
  if (spec.packing !== "planes") return new Float32Array(buffer);
  return columns(new Uint8Array(buffer), [spec.dtype], spec.width * spec.height * (spec.channels || 4))[0];
}
