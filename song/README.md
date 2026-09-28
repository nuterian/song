# Timing the words

The lyric tool: how it times a song's words, how accurate that is, and the app for
checking and fixing them. Run from the repository's root, in its `.venv`:

```bash
.venv/bin/python -m song song.wav lyrics.txt   # align, and open the review app at http://127.0.0.1:8420
```

The file names here (`examples/gold/`, `workdir/`) are from the repository's root.

## Why the timing is accurate

Because the words are known, this is **forced alignment**, not transcription, so a
chorus that repeats four times resolves by position instead of by guesswork. One
aligner is not enough, and there is no ground truth for an AI-generated song, so
three independent passes cross-examine each other:

1. **Demucs** isolates the vocal. Aligning against the stem rather than the mix is
   the single biggest accuracy win on dense productions.
2. **wav2vec2 CTC** anchors the structure with one global Viterbi pass, so
   instrumental stretches are absorbed as blanks instead of desynchronizing the
   rest of the song the way a whole-track Whisper pass does.
3. **Whisper** refines inside each ~20-second section. Coarse-to-fine: CTC for
   structure, Whisper for edges.
4. **A blind transcription**, told nothing, adjudicates where the two forced
   aligners disagree. It is the strongest single signal in the merge.

Every line then gets a 0–100 score from six independent signals, and the pipeline
re-aligns only the sections holding weak lines until an iteration changes nothing.
On the sample track:

```
  lines aligned             33/33
  median start disagreement 160 ms
  heard independently       33/33 lines
  vocal coverage            mean 99%, min 80%
  mean line score           94.5/100
  needs review              2 line(s)
```

The same score drives the UI, so review time goes exactly where the benchmark says
it should. Run against a deliberately degraded alignment it drops to 69.9 with 11
lines flagged: it discriminates.

It is still one model checking another. `examples/gold/` holds the sample
track timed word by word against the stem's spectrogram, pitch track and
envelope, and `song bench` measures a project against it: per-word start and
end error as a distribution, split by the line score so the score's own
calibration is visible, and which of the singer's rests the alignment kept,
closed or invented. On the sample track the automatic pass benches at a 76 ms
median on word starts and 103 ms on ends; the three lines it gets most wrong
score 99.7 or better, which is the number that says why a gold file is needed.

## Fixing a word

One waveform: a minimap, a scrub bar, and the isolated vocal with draggable line
regions and word cells whose dividers snap to vocal onsets. Colour means *act
here* and nothing else. Two guided paths sit on top of it:

- **Check timings** walks the words two aligners disagree about, playing each
  candidate from the moment it claims the word begins. If neither is right, drag
  the word's own bounds on the card's waveform strip to place a third.
- **Missing lines.** A lyrics file typed by hand drops things, usually a chorus
  repeat. The blind transcription already hears them; anything no line claims is,
  by construction, sung and absent from the lyrics. Proposed only when it matches
  a line you already wrote, so approving is a five-second listen, never proofreading.

The audit also repairs two things without asking, because the stem and the
song itself are unambiguous about them. A word that runs on after the
envelope says the voice stopped is pulled back ("ended 0.31 s after the voice
stopped"), and a chorus line whose word lengths sit far from its other
renditions is re-placed from the rendition nearest their median, by warping
the stem of one onto the other: that is what fixes the lines the score calls
perfect and gets wrong by half a second. A word whose length disagrees with
its repeats while they agree with each other goes into the queue as an A/B
choice. Every decision taken in the review card, and every bound dragged on
the timeline, is appended to `decisions.jsonl` in the workdir with the word's
features at the time, so that once a few hundred exist the queue can be ranked
by what people actually changed.

### Adjusting a word by hand

Click a word (in the lyrics, in a word cell, on the strip inside the Check
timings card) and both of its bounds appear as handles running the full height
of the waveform, with its start, length and end written above them. Every
surface that shows a word offers the same two handles, the same keys and the
same undo step, because they are all one operation underneath:

| | |
|---|---|
| drag a handle | moves that bound; snaps to a vocal onset, and shut against a neighbour it comes near (`alt` drags free) |
| `shift`-drag | takes the neighbouring word along, re-cutting a boundary without changing what sits either side |
| drag a word edge | the same edit on any edge in the cells, without selecting first |
| drag a time in the deck | scrubs that bound 4 ms a pixel (`shift` 1 ms) |
| `,` `.` | aim the arrows at the left / right bound |
| `←` `→` | move it ±50 ms, coarse |
| `shift` `←` `→` | ±10 ms, fine |
| `alt` `←` `→`, `tab` | previous / next word, rolling into the adjacent line |
| `S` `E` | put the left / right bound at the playhead |
| `⌘Z` | undo: a drag is one step, a burst of nudges folds into one |

**A word ends where the singer stops**, not where the next word starts, so a
line can hold a rest in the middle of it and both bounds are real, separate
numbers. Pull a bound inward and the word gets shorter, leaving a rest; push it
outward and it shoves the neighbour along rather than crossing it. The first
word's left bound is the line start and the last word's right bound is the line
end, which is why dragging either also moves the line's own edge.

A rest is kept only when it is at least 150 ms: the two aligners disagree about
where a word sits by 160 ms at the median, so a narrower gap is inside their own
error. On a freshly aligned sample track that is 7 rests held and 14 gaps closed.

A project aligned before this change has no rests in it: the ends were
flattened on the way to disk and cannot be recovered from the file. Re-run
`align` to get the aligners' own ends back, or open the rests you want by hand;
nothing else about the project changes.

Edits write themselves back a moment after you stop, rewriting `project.json`
and every export, and every write is re-scored, so the chips and the flags
always describe the timings under them; `⌘S` is the version that says so out
loud. A line you have placed by hand is scored without the agreement term -
you are the reference there, and `song bench` is what measures you.
