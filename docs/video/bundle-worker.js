// The bundle's unpacking, off the page's thread: the same functions bundle.js has, asked
// for by message, the values handed back without a copy.
import { fetchBytes, gridValues, textureValues } from "./bundle.js";

self.onmessage = async (e) => {
  const { id, url, name, kind, spec, options } = e.data;
  try {
    const buffer = await fetchBytes(url, name, options);
    const out = kind === "grid" ? gridValues(buffer, spec) : textureValues(buffer, spec);
    self.postMessage({ id, buffer: out.buffer }, [out.buffer]);
  } catch (err) {
    self.postMessage({ id, error: String(err && err.message ? err.message : err) });
  }
};
