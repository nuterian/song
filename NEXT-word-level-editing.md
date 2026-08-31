# Plan: word-level timing adjustment in the review UI

## Problem

The review UI edits lyrics at **line** level only. Word timings exist in
`project.json` and are exported to `lyrics.word.lrc`, and the UI highlights the
active word during playback — so you can *see* a word-level error, but the only
way to act on it is to move the whole line, which rescales every word
proportionally and cannot fix a single late word.

## The design decision that makes this simple

**Only word starts are editable.**

Enhanced LRC encodes one timestamp per word (`<mm:ss.xx>word`); a word's end is
the next word's start. So a line of N words has exactly **N−1 editable internal
boundaries** — word 0's start *is* the line start, and the last word's end *is*
the line end, both already draggable as the line's edges.

This removes the whole class of fiddly problems: no per-word ranges to keep
consistent, no way to create a gap or an overlap, one handle per boundary.

Consequence to accept and document: word `end` values get normalized to
contiguous (`words[i].end = words[i+1].start`) when a line is word-edited.
Whisper's raw ends encode small inter-word pauses; karaoke rendering ignores
them, and the exports already key off starts.

## Layout

Add a **word lane** below the vocal lane, showing the selected line's words as
contiguous labeled blocks, with a dimmed copy of the vocal waveform drawn behind
them on the same time axis. That visual correspondence is the point: a boundary
sitting off the syllable transient is what makes the error obvious.

```
MINI_H=30, GAP=7, RULER_H=15, MIX_H=44, VOC_H=92 (was 106), WORD_H=42
VOC_Y  = MIX_Y + MIX_H + 3
WORD_Y = VOC_Y + VOC_H + 2
TOTAL_H = WORD_Y + WORD_H          // ~235px, was 199
```

If the selected line renders narrower than ~200px, draw "zoom in to edit words"
instead of unusable slivers.

## Interactions

**Getting to the word** (the "I heard something wrong" path):

- **Click a word in the lyrics panel text** → select it, focus the timeline on
  its line, seek 0.4 s before it. This is the primary entry point: you hear the
  highlight land late on "gravity", you click "gravity".
- Click a block in the word lane → select it.
- `Tab` / `shift+Tab` → next / previous word, rolling into the adjacent line at
  the ends.

**Fixing it:**

- **Drag a divider** → moves the boundary between two adjacent words. Clamp to
  `neighbour ± MIN_WORD` (0.06 s).
- **`←` / `→`** → nudge the **selected word's start** by 50 ms (`shift` = 10 ms).
  With no word selected this keeps nudging the whole line, as today —
  context-sensitive, so existing muscle memory carries over.
- **`W`** → word tap-along: stamp the selected word's start at the playhead and
  advance to the next word. Held down through a playing line, this re-times the
  whole line by ear. Mirrors the existing `T` for lines and is the fastest
  repair path.
- **`R`** → redistribute the line's words evenly across its span (escape hatch
  when manual edits get tangled).
- **`esc`** → deselect the word, back to line-level editing.

**Snapping:** while dragging, snap a word start to a vocal onset within 60 ms.
Onsets are already computed and served (`analysis.onsets`, 657 on the sample
track). Hold `alt` to drag freely.

**Focus:** clicking a lyric row should also focus the timeline on that line
(view = line span × 2.5, min 4 s). Today it only seeks and plays, which leaves
you zoomed out and unable to do fine work.

**Playback:** highlight the active word's block in the word lane during
playback, not just in the lyrics panel — seeing the highlight advance against
the waveform is how the error gets noticed.

## Invariants

- `line.start === words[0].start`, `line.end === words.at(-1).end`
- after any word edit, `words[i].end === words[i+1].start`
- word edits set `line.source = 'manual'` and mark the project dirty
- `retimeLine` (line move/resize) keeps rescaling words proportionally — unchanged

## Files

| File | Change |
|---|---|
| `ui/app.js` | Bulk of the work: geometry constants, `S.selWord` state, word helpers (`wordBlocks`, `normalizeWords`, `setWordStart`, `redistribute`), `drawWordLane`, `hitWord`, mouse + key handlers, clickable words in the panel, `focusLine` |
| `ui/styles.css` | Selected-word style (`.w.sel`), word-lane hint text |
| `ui/index.html` | Footer key hints: `Tab`, `W`, `R`, `esc` |
| `lyricsync/project.py` | `TimedLine.normalize_words()` mirroring the JS rule, applied on load/save so Python and UI agree |
| `lyricsync/exports.py` | Confirm enhanced LRC keys off starts (it does); ensure last word end tracks line end |
| `README.md` | Document word-level editing and the starts-only model |

## Verification

1. Drag a divider → the two adjacent words change, no gap or overlap appears,
   line start/end unchanged.
2. `W` tap-along across a line during playback → each word start lands at the
   playhead, order preserved, line bounds intact.
3. Save → `lyrics.word.lrc` reflects the new starts; re-load the page and the
   edits persist.
4. Karaoke highlight during playback matches the edited boundaries.
5. `python -m lyricsync score workdir/gravity-in-motion` still runs (word edits
   shift density slightly; nothing should crash).
6. Line-level editing (drag, `←`/`→` with no word selected, `T`) still behaves
   exactly as before.

## Known-good baseline

Current state is verified working: `align` scores 94.5/100 mean, 33/33 lines,
2 flagged. Do not regress line-level drag/resize/nudge or the save→export→
re-score round trip while adding this.
