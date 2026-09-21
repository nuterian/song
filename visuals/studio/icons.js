// The studio's icons: thin line drawings on a 24 grid, drawn here so the page needs nothing
// from anywhere else. `icon(name)` gives the SVG markup; it takes the colour of its text.

const P = {
  play: '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M8 5h3v14H8zM13 5h3v14h-3z" fill="currentColor" stroke="none"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
  spark: '<path d="M12 3.5 13.9 9 19.5 11 13.9 13 12 18.5 10.1 13 4.5 11 10.1 9z"/><path d="M19 3v3M17.5 4.5h3"/>',
  song: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
  wave: '<path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 7v10M21 12h0"/>',
  camera: '<rect x="3" y="7" width="12" height="10" rx="2"/><path d="m15 11 6-3.5v9L15 13"/>',
  bolt: '<path d="M13 3 5 13.5h6L10 21l8-10.5h-6z"/>',
  text: '<path d="M5 7V5h14v2M12 5v14M9 19h6"/>',
  cursor: '<path d="m6 4 12 7-5.5 1.5L10 18z"/>',
  sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
  clock: '<path d="M4 12a8 8 0 1 0 2.3-5.7L4 8.5"/><path d="M4 4v4.5h4.5M12 8v4l3 2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeoff: '<path d="M4 4l16 16M9.9 5.8A9.7 9.7 0 0 1 12 5.5C18 5.5 21.5 12 21.5 12a17 17 0 0 1-2.8 3.6M6.3 7.5C3.9 9.3 2.5 12 2.5 12S6 18.5 12 18.5c1.4 0 2.7-.4 3.8-.9"/><path d="M9.9 10a3 3 0 0 0 4.1 4.1"/>',
  zoomin: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.4-4.4M8 11h6M11 8v6"/>',
  zoomout: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.4-4.4M8 11h6"/>',
  metronome: '<path d="M9.5 3.5h5L19 20.5H5z"/><path d="M12 15.5 16.5 7M8 16h8"/>',
  refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3L19.5 9"/><path d="M19.5 4v5h-5"/>',
  left: '<path d="m14.5 6-6 6 6 6"/>',
  right: '<path d="m9.5 6 6 6-6 6"/>',
  out: '<path d="M14 4h6v6M20 4l-8.5 8.5"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  // the six shots, as pictures of what the camera does
  approach: '<path d="M3 12h11M10.5 8.5 14 12l-3.5 3.5"/><circle cx="19" cy="12" r="2.5"/>',
  wide: '<ellipse cx="12" cy="12" rx="9.5" ry="4.5"/><circle cx="12" cy="12" r="2"/><circle cx="20" cy="10.3" r="1" fill="currentColor"/>',
  intimate: '<circle cx="8.5" cy="12" r="4.5"/><circle cx="18" cy="12" r="2.2"/>',
  eclipse: '<circle cx="12" cy="12" r="5"/><ellipse cx="12" cy="12" rx="10" ry="2.8"/>',
  alignment: '<circle cx="4" cy="12" r="2.2"/><circle cx="9.5" cy="12" r="1.4"/><circle cx="14" cy="12" r="1.8"/><circle cx="18.5" cy="12" r="1.2"/><circle cx="21.5" cy="12" r=".8"/>',
  pullback: '<circle cx="5" cy="12" r="1.6"/><path d="M9 12h11M16.5 8.5 20 12l-3.5 3.5"/>',
};

export function icon(name, size = 16) {
  return `<svg class="ic" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ""}</svg>`;
}

// Each planet's own colour, as the picture has it (shader_cosmos.PLANET_TINT, in sRGB): a
// subject is picked by colour.
export const PLANET_INK = {
  mercury: "#c8c2bd", venus: "#f6e5b9", earth: "#afd2dd", mars: "#e4a785",
  jupiter: "#ead3b9", saturn: "#f2e2bd", uranus: "#c8eff3", neptune: "#7ca3ef",
};
