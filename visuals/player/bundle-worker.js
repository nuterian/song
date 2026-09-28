// The bundle's unpacking, off the page's thread: the same function bundle.js has, asked
// for by message with the file's bytes, the values handed back without a copy.
import { unpacked } from "./bundle.js";

self.onmessage = async (e) => {
  const { id, bytes, name, kind, spec } = e.data;
  try {
    const out = await unpacked(bytes, name, kind, spec);
    self.postMessage({ id, buffer: out.buffer }, [out.buffer]);
  } catch (err) {
    self.postMessage({ id, error: String(err && err.message ? err.message : err) });
  }
};
