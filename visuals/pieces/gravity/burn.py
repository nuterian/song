"""The words, burned into an mp4's frames, set as the player sets them over its canvas.

The player draws each line as HTML over the picture (player/index.html, `#lyrics`); an mp4
has no page over it, so here the same lines are set with Pillow, from the same font file,
at the same size and place, with the same letter-spacing, colour and shadow, and laid onto
each rendered frame. How bright a word and a line are at a moment is `lyrics.ink` and
`lyrics.opacity`, the functions the player's copies are held to; nothing about the look
is decided here, and nothing is drawn that the player would not draw.

Each word is set once, when the frame size is known, as two masks: its glyphs, and its
glyphs over their shadow. A frame then only blends the few words that are up, each with
its own alpha, and a frame with no line up is not touched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import ROOT, lyrics

FONT = ROOT / "visuals" / "player" / "fonts" / "Inter-Light.woff2"
COLOUR = np.array([238, 233, 222], dtype=np.float32)   # the player's rgb(238, 233, 222); it never changes
SPACING = 0.06               # em: the player's letter-spacing, after every character
LINE_HEIGHT = 1.5            # font sizes: the player's line box (its body's 13px/1.5, inherited)
SHADOW_BLUR = 0.35           # em: text-shadow 0 0 0.35em, which a browser draws as a Gaussian of half that deviation
SHADOW_ALPHA = 0.55          # rgba(0, 0, 0, 0.55)
FINE = 4                     # letters are drawn this many times larger and scaled down: Pillow puts a glyph
                             # on whole pixels, and a browser places it to a fraction of one
WEIGHT = 0.023               # em added to every stroke: Chrome on macOS draws light-on-dark type this much
                             # heavier than its outline (0.75 px of a 2.15 px stem at 1080p, measured)


@dataclass
class Word:
    x: int                   # where its patch sits in the frame, top left (it may reach past an edge)
    y: int
    glyph: np.ndarray        # (h, w) float32, 0..1: how much of each pixel the letters cover
    cover: np.ndarray        # (h, w, 1): the letters over their shadow, how much of the frame a pixel hides at full ink
    paint: np.ndarray        # (h, w, 3): what the letters lay on it at full ink, the colour times the glyph
    start: float
    end: float


class Words:
    """The lines of `lyrics.layout` for one camera, set for frames of `size` (width, height)."""

    def __init__(self, spec: dict, camera: str, size: tuple[int, int]) -> None:
        st = spec["style"]
        self.inks = {"unsung": st["unsung"], "peak": st["peak"], "sung": st["sung"]}
        self.size = size
        px = st["size"] * size[1]                                   # the font size, in pixels: a share of the frame's height
        font = ImageFont.truetype(str(FONT), px * FINE)
        ascent, descent = (m / 1000 for m in ImageFont.truetype(str(FONT), 1000).getmetrics())
        self.lines: list[tuple[lyrics.Line, list[Word]]] = []
        for ln in spec["lines"]:
            line = lyrics.Line([tuple(w) for w in ln["words"]], *ln["in"], *ln["out"], place=ln["place"])
            region = spec["regions"][ln["place"].get(camera, "low")]
            self.lines.append((line, self._set(line, region, font, px, ascent, descent)))

    def _set(self, line: lyrics.Line, region: dict, font, px: float, ascent: float, descent: float) -> list[Word]:
        """Each word of the line, drawn where the player's CSS puts it: the line's box centred
        on the region's height, and its left, centre or right on the region's x."""
        w, h = self.size
        text = line.text
        spacing = SPACING * px
        # each character's pen position: the font's own advances and kerning, plus the spacing
        pen = [font.getlength(text[:i]) / FINE + i * spacing for i in range(len(text) + 1)]
        width = pen[-1]
        cx = w * (0.5 + region["x"] * 9 / 16)                        # the player's left: 50% + x * 9/16 of the width
        left = {"center": cx - width / 2, "right": cx - width}.get(region["align"], cx)
        # the line box centred on the region's height, the font's ascent and descent (in whole
        # pixels) centred in it, and the baseline on the whole pixel above: as Chrome sets it,
        # measured against its screenshots
        box_top = h * (0.5 - region["y"]) - LINE_HEIGHT * px / 2
        up, down = round(ascent * px), round(descent * px)
        baseline = math.floor(box_top + (LINE_HEIGHT * px - up - down) / 2 + up)
        sigma = SHADOW_BLUR / 2 * px
        pad = math.ceil(3 * sigma) + 2
        top = math.floor(baseline - ascent * px) - pad
        bottom = math.ceil(baseline + descent * px) + pad
        words, i = [], 0
        for text_w, start, end in line.words:
            x0 = math.floor(left + pen[i]) - pad
            x1 = math.ceil(left + pen[i + len(text_w)]) + pad
            fine = Image.new("L", ((x1 - x0) * FINE, (bottom - top) * FINE), 0)
            draw = ImageDraw.Draw(fine)
            for k, ch in enumerate(text_w):
                draw.text((round((left + pen[i + k] - x0) * FINE), (baseline - top) * FINE), ch,
                          font=font, fill=255, anchor="ls", stroke_width=WEIGHT / 2 * px * FINE, stroke_fill=255)
            mask = fine.reduce(FINE)                                 # each pixel, the share of it the letters cover
            glyph = np.asarray(mask, dtype=np.float32) / 255.0
            shadow = np.asarray(mask.filter(ImageFilter.GaussianBlur(sigma)), dtype=np.float32) / 255.0 * SHADOW_ALPHA
            cover = glyph + shadow * (1.0 - glyph)
            # only the pixels the word can change by half a level or more: the shadow's far tail is not drawn
            rows, cols = np.nonzero(cover.max(axis=1) * 255 >= 0.5)[0], np.nonzero(cover.max(axis=0) * 255 >= 0.5)[0]
            keep = slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1)
            words.append(Word(x0 + int(cols[0]), top + int(rows[0]), glyph[keep], cover[keep][..., None],
                              glyph[keep][..., None] * COLOUR, start, end))
            i += len(text_w) + 1                                     # and the space after it
        return words

    def draw(self, frame: np.ndarray, t: float) -> bool:
        """Lay the words up at `t` onto `frame` (height, width, 3) uint8, in place. Each word's
        alpha is its line's opacity times its own ink, as the player's nested opacities are.
        Says whether anything was drawn."""
        drawn = False
        for line, words in self.lines:
            op = lyrics.opacity(line, t)
            if op <= 0.0:
                continue
            for word in words:
                a = op * lyrics.ink(t, word.start, word.end, **self.inks)
                self._blend(frame, word, a)
            drawn = True
        return drawn

    def _blend(self, frame: np.ndarray, word: Word, a: float) -> None:
        h, w = frame.shape[:2]
        gh, gw = word.glyph.shape
        fy0, fx0 = max(word.y, 0), max(word.x, 0)
        fy1, fx1 = min(word.y + gh, h), min(word.x + gw, w)
        if fy1 <= fy0 or fx1 <= fx0:
            return
        sy, sx = slice(fy0 - word.y, fy1 - word.y), slice(fx0 - word.x, fx1 - word.x)
        region = frame[fy0:fy1, fx0:fx1].astype(np.float32)
        # region (1 - a cover) + a paint: stays within 0..255, since paint is at most 255 cover
        region += a * (word.paint[sy, sx] - region * word.cover[sy, sx])
        region += 0.5
        frame[fy0:fy1, fx0:fx1] = region.astype(np.uint8)
