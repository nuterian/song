# lyricsync

Turn an audio track plus a plain-text lyrics file into accurate, time-synchronized
lyrics — `.lrc`, word-level `.lrc`, `.srt`, `.vtt` — using only free, locally-run
open-source models. Built for AI-generated songs, where the lyrics are known
exactly but the timing is not, and the end goal is burning synchronized captions
into a video.

Everything runs on your machine. No API keys, no uploads, no per-track cost.

```bash
./setup.sh                                              # one-time, ~5 min
./.venv/bin/python -m lyricsync "data/Gravity in Motion.wav" data/lyrics.txt
```

That aligns the track and opens the review UI at <http://127.0.0.1:8420>.

---

## Why it is built this way

The naive approach — transcribe with Whisper, fuzzy-match the text — falls apart
on songs: a chorus that repeats four times has four identical transcripts, and
nothing tells you which is which. Since we already know the words, this is a
**forced alignment** problem, not a transcription problem. Alignment consumes the
text in order, so repeats resolve by position for free.

But one aligner is not enough, and there is no ground-truth timing file for an
AI-generated song to check against. So the pipeline runs three independent
passes and cross-examines them.

### 1. Isolate the vocal first

[Demucs](https://github.com/facebookresearch/demucs) splits out a vocals-only
stem. Aligning against the stem rather than the full mix is the single biggest
accuracy win on dense productions — the aligners stop locking onto kick drums
and synth stabs. It also makes "is anyone singing right now?" a simple, reliable
energy question, which the scorer and the UI both lean on heavily.

### 2. CTC anchors the structure

A Whisper forced-alignment pass over a whole song **desynchronizes**. A 4-bar
instrumental is longer than Whisper's 30-second attention window, and once it
loses the thread the rest of the track slides. Measured on the sample track, a
global Whisper pass put the closing line at 2:37 of a 4:46 song — off by nearly
two minutes.

wav2vec2 CTC forced alignment (torchaudio's `MMS_FA`) has no such failure mode:
it emits per-frame probabilities and finds one globally optimal path, so
instrumental stretches are absorbed as blanks. Long tracks are handled by
computing emissions in chunks and running a **single global Viterbi alignment**
over the concatenation, so long-range ordering is never lost.

### 3. Whisper refines inside each section

With the structure anchored, each section is cropped to a ~20-second window and
re-aligned with Whisper, which is both accurate and precise at that length.
Coarse-to-fine: CTC for structure, Whisper for edges.

On the sample track this took median cross-aligner disagreement from unusable to
**140 ms**.

### 4. A blind transcription adjudicates

Both aligners are *told* the lyrics, so both can be confidently wrong in the same
place, and their agreement can flag a line as uncertain but cannot say which
candidate is right. So a third pass transcribes the vocal stem **blind** — told
nothing — and its words are matched back to the lyrics with an order-preserving
character-stream match.

Where that lands is the tiebreaker, and it is the strongest single signal in the
merge. On the sample track it correctly resolved all three disputed lines.

---

## The benchmark

There is no reference timing file, so accuracy is *estimated from evidence*
rather than measured against truth. Every line gets a 0–100 score from six
signals:

| Signal | Weight | What it catches |
|---|---|---|
| Cross-aligner agreement | 30 | Two unrelated model families disagreeing means the line is uncertain |
| Blind-transcription corroboration | 22 | Both aligners wrong together; whole sections misplaced |
| Vocal coverage | 20 | A line parked over an instrumental break |
| Onset proximity | 12 | Starts that don't land on a vocal onset |
| Word density | 8 | Spans far too long or short for the words in them |
| Aligner confidence | 8 | Low per-word probability |

Rolled up into a scorecard, printed after every run and saved into
`workdir/<track>/project.json`. On the sample track:

```
  lines aligned             33/33
  median start disagreement 160 ms
  agreement <=150/300/500ms 48% / 76% / 85%
  heard independently       33/33 lines
  vocal coverage            mean 99%, min 80%
  mean line score           94.5/100
  needs review              2 line(s)  [5, 31]
```

**Read the flags as "look here", not "this is wrong."** They mark lines where the
independent methods disagreed. On the sample track both flagged lines are in fact
correctly placed — verified against the blind transcription — and are flagged
only because CTC and Whisper disagree about them by seconds. That is the flags
doing their job: they point at genuine ambiguity (a held note, a quiet lead-in).
What they buy you is the absence of false negatives.

The same per-line scores drive the UI, so review time goes exactly where the
benchmark says it should.

### Does the benchmark actually discriminate?

A quality score that always says "fine" is worthless, so it was checked against a
deliberately degraded run — the same track aligned against the full mix with
`--no-separate`, skipping vocal isolation:

| | normal | degraded (`--no-separate`) |
|---|---|---|
| mean line score | **94.5** | 69.9 |
| vocal coverage | 99% | 9% |
| lines needing review | 2 of 33 | 11 of 33 |
| quality gate | passed | failed on 3 criteria |

The thresholds are calibrated against what two *different* model families can
actually achieve, not against perfection — demanding near-total agreement makes
the gate fail on good output and retry toward a target it can never reach.

### The gate and the repair loop

The pipeline is a state machine, not a single pass, and it separates two
questions:

- **The gate** asks *is something systemically wrong?* — median disagreement,
  agreement rate, coverage, mean score, ordering.
- **The flags** ask *which individual lines can still be improved?*

Either one triggers another iteration, because a track can clear every aggregate
threshold while still holding one badly placed line — and that line is exactly
what a viewer notices. Only the **sections containing weak lines** are re-aligned,
first with a larger Whisper model and a wider crop, then with a local CTC pass
added to the candidate pool. Each iteration re-scores and keeps the
best-supported candidate per line, so a retry can never make a line worse, and
the loop stops early once an iteration changes nothing rather than burning
minutes to confirm it.

This matters concretely: on the sample track the gate passes on the first pass,
but the repair loop still moves the closing chorus line from a 7.6-second span
(0.7 words/sec — visibly wrong as a caption) onto the 4.4-second span the blind
transcription actually heard.

`lyricsync score <workdir>` re-runs the benchmark against your manual edits, so
it measures the file that actually ships. It reuses the aligner outputs and
transcription observations stored in `project.json`, so it needs no models and
returns in seconds.

---

## Adding a track

Click the track name in the header. That sheet lists every aligned track under
`workdir/` and switches between them; **Add a track…** takes an audio file and a
lyrics `.txt`, dropped or picked, and runs the whole pipeline right there with
the progress log visible. When it finishes the new track is the open one.

The files are uploaded as raw request bodies rather than multipart, so this adds
no dependency to move two files across localhost. The command line still works
the same way and is better for batches:

```bash
python -m lyricsync song.wav lyrics.txt
```

Lyrics are plain text: one line per lyric line, blank lines between sections, and
a `Verse 1 (...)` or `[Chorus]` style header naming a section.

## Checking the timings

There are two ways in, and most of the time you want the first.

### Check timings — the guided path

`Check timings` in the header, or `python -m lyricsync audit workdir/song`.

Two aligners of different model families time every word: Whisper (the primary)
and a wav2vec2 CTC pass re-run **per line**, constrained to that line's own audio
and its known words so it cannot drift the way a whole-track pass can. On the
sample track that takes about 15 seconds and splits 177 words three ways:

| | words | what happens |
|---|---|---|
| both models agree within 150 ms | 137 (77%) | trusted, never shown to you |
| provably impossible | 2 | **repaired automatically** |
| genuinely ambiguous | 40 | **you decide, by ear** |

*Provably impossible* means no reading of the audio could justify it: a word
lasting zero seconds, a word starting before the word in front of it, a word
starting where the vocal stem is silent. Those are repaired without asking,
because there is nothing to ask about. The repair only removes the impossible
state — it does not claim to know the truth, so those words still come to you.

Everything left is presented one at a time: the line with the word marked, why it
was flagged in plain language, and two buttons that each **play from the moment
that version says the word begins**. The right one starts *on* the word. Use
suggested, keep as is, or decide later — with undo.

Where the second model puts a word outside the line entirely, the line itself is
misplaced rather than the boundary, and the choice becomes a whole-line re-time.

### When neither candidate is right

An A/B is only honest when one of the two is correct, and sometimes neither is.
So the card carries **its own waveform strip** — the word's neighbourhood, the
line plus about three quarters of a second of air either side, with both
candidates marked on it: blue where the timing is now, green where the second
model wants it, onset ticks along the bottom, and the playhead running while a
preview plays. You can see what you are choosing between instead of only hearing
it.

**Drag it and you make a third candidate**, drawn in violet. Grab either marker
or click anywhere on the audio; it snaps to a vocal onset within 60 ms
(`alt` drags free) and it is clamped to the range the timing model would
actually accept, so the strip can never show you a position that would be
silently moved on the way in. The buttons become *Now / Suggested / Adjusted*,
each still playing from its own start, and the primary button becomes **Use
adjusted**. `reset` puts you back to the plain A/B.

Accepting an adjustment is one undo step, exactly like accepting a suggestion,
so `⌘Z` after closing the sheet takes back the timing *and* the queue mark
together. On a line-scope decision the drag shifts the whole proposed placement
by one offset rather than moving a single word.

That closes the last reason to leave: a song can be word-aligned end to end from
inside this one dialog.

| Key | Action (while the sheet is open) |
|---|---|
| `←` `→` | nudge the adjusted timing ±50 ms (`shift` = ±10 ms) — creating it from whichever candidate is armed |
| `space` | replay whichever version you heard last |
| `1` `2` `3` | hear now / suggested / adjusted |
| `enter` | take the primary button — *use suggested*, or *use adjusted* |
| `esc` | close the sheet |

### Lines the lyrics file does not have

A lyrics `.txt` is typed by hand, and hands drop things — most often a chorus
repeat, because it is the line already typed three times. The aligner cannot
notice: it is *told* the lyrics and consumes them in order, so the omission does
not raise an error, it leaves a hole nobody looks in. On the sample track that
hole is **45.8 seconds** between the first chorus and verse 2, with a clearly
sung line inside it.

The evidence to catch this was already being computed and thrown away. The blind
transcription pass reads the whole vocal stem and each known line claims the
words near it; **whatever no line claims was, by construction, sung and is not in
the lyrics as timed.** Those leftovers are now kept.

Finding candidates is easy. Refusing bad ones is the work — a vocal stem carries
pads, "ooh"s and reverb tails, and Whisper will cheerfully hallucinate
"Thank you." over a fade. So a candidate has to clear four tests at once: at
least three words, mean confidence ≥ 0.6, no overhang onto a neighbouring line,
and a ≥ 0.8 text match to a line the lyrics already contain, covering ≥ 60% of
it. Every gap on the sample track, scored:

| gap | vocal | heard | conf | matches a line? |
|---|---|---|---|---|
| **1:20.55→2:06.40** | 12.5s | **"You're my gravity in motion"** | **0.89** | **1.00 — exact, 5/5 words** |
| 1:02.20→1:04.54 | 1.5s | "You're my" | 0.60 | 0.50 — 2/5, and it overhangs the next line |
| 4:05.83→4:08.74 | 2.2s | "Ocean" | 0.29 | 0.21 — one word |
| 4:38.05→end | 1.8s | "Thank you." | 0.50 | 0.30 — hallucinated over the fade |
| five others | 1.7–9.3s | *nothing transcribed* | — | — |

One candidate survives, and it is the right one. Note the last test: the text
has to be **a line you already wrote**. A transcription confident enough to
trust for novel words is also confident enough to be wrong in a way nobody
catches by ear, and approving that means proofreading a machine instead of
confirming what you just heard. Every proposal is a line you wrote, heard
somewhere you did not write it — so the only question put to a human is one an
ear settles in five seconds.

It is asked in two places. A dashed **ghost row** sits in the lyrics exactly
where the line would go, between the two lines that bracket it, with *hear it*,
*add*, and *dismiss* — judged in reading order, next to the chorus it repeats.
And `Check timings` puts it first, as a card with the waveform around it: a line
cannot have its words timed before it exists. A dismissal is remembered and
survives re-running the audit.

Accepting inserts the line, and **index is position** in this project — the
review queue, the queued-word marks, the undo snapshots, both aligners' raw
spans and the round-trip's per-line observations are all keyed by it. All of
them are renumbered in one step. (The scorer caught that the last two were not,
by reporting the entire back half of the song as suddenly misheard.) The new
line also inherits the observation that found it, because that transcription is
precisely the evidence it is there.

On the sample track, adding it takes the benchmark from 33/33 lines aligned at a
mean of 94.5 to **34/34 at 94.6, all 34 heard independently**, with the same two
lines flagged. Your `lyrics.txt` is left alone and told you about — inserting a
line renumbers everything after it, which is more than `⌘Z` can express, so it
is the one action in the app that is not undoable.

**What is deliberately not automated:** snapping word starts to the nearest
detected vocal onset. It looks like free accuracy, but on the sample track 41% of
word starts have more than one onset within ±150 ms — snapping would be a coin
flip wearing a lab coat. Where two independent models disagree and both are
plausible, no heuristic settles it honestly, so a human ear does.

## The review UI

The timeline is the expert path — reach for it when you want direct control, or
when the guided pass hands you something it cannot decide.

- **One waveform, and only one.** A minimap of the whole track, a scrub bar, and
  the isolated vocal with onset ticks marked. There is no second waveform,
  because there was nothing a second one could say. A line boundary that is
  wrong looks wrong.
- **The waveform says who is singing.** Sung stretches are drawn with a lit
  core; everywhere else drops to a flat dim blue and reads as ground. That is
  the one question this lane exists to answer, and the waveform can answer it
  itself — so the shaded band laid over the top, which used to carry that alone,
  is now half its old weight. Two pictures of the same fact was one too many.
- **Scrub bar** — the ruler strip always seeks: click or drag it anywhere, even
  straight over a line, where clicking the waveform would select that line
  instead. `shift`-drag anchors at the playhead and moves 6× slower, which is
  about a millisecond per pixel at working zoom. The exact time floats under the
  cursor before you commit.
- **Place line at playhead** — scrub to the moment, press the button (or `T`).
  The line moves there keeping its length, so the words inside stay correctly
  spaced relative to each other. This is the whole line-placing job in one
  visible control rather than a remembered key.
- **Minimap** of the whole track showing vocal structure, every line, and flagged
  lines in red.
- **Draggable regions** — drag a line's body to move it, its edges to resize.
  Word timings rescale proportionally.
- **Word cells** — a continuous caption strip along the bottom of the vocal
  lane: every line on screen shows its words, and the active word highlights
  during playback wherever it is. The selected line is the editable one, drawn
  brighter with its boundaries running the full height of the waveform — a
  divider that misses the syllable attack is visible against the audio it is
  supposed to be cutting, which is the whole point. Drag a divider to move a
  boundary; it snaps to a vocal onset within 60 ms, and `alt` drags freely.
  Clicking a word in any line selects that line and word. Zoomed out it says
  *zoom in to see and edit words* rather than drawing unusable slivers.
- **Click a word** in the lyrics text to select it, focus the timeline on its
  line and seek 0.4 s before it — the path from *that word landed late* to
  fixing it.
- **Karaoke preview** — the active line and the active *word* highlight during
  playback, so you verify by ear and eye without exporting anything.
- **Follow** keeps the current moment in view in both places at once: the
  timeline pans, and the lyrics scroll the playing line into a read-ahead band a
  third of the way down. Scrolling the lyrics by hand suspends the chase for four
  seconds so you can read ahead without being yanked back; clicking a line
  resumes it immediately. Line-to-line advances glide, seeks snap.
- **Solo vocals** toggle, to hear exactly what the aligner heard.
- **Variable speed** — 0.25× / 0.5× / 0.75× / 1×, pitch-preserved so the words
  stay recognisable. Word boundaries are judged by ear, and at 1× a syllable
  goes past faster than you can react to it; at 0.5× a tap-along gives you twice
  the reaction room per word. The toolbar button cycles the ladder and the clock
  shows the rate whenever it is not 1×.
- **Colour means "act here", and nothing else.** A line that is fine carries no
  mark at all, so the eye lands on the few that do: amber for words the audit
  queued for your ear, red for a line the benchmark flagged, blue for whatever
  is selected or sounding. Good scores are printed grey — they are the default
  and should not compete for attention.
- **The queue is marked in place.** Every word waiting on your ear is underlined
  in the lyrics and tinted amber in the word cells, so the audit and the timeline
  show the same thing. Resolving one clears its mark everywhere, and the counter
  on **Check timings** counts down as you go.
- **Issue text** on every flagged line, straight from the benchmark, sitting in
  the space to the right of the words rather than on a row of its own — plus a
  "Needs review" filter, and a count of what the filter is showing.
- **One deck under the waveform** carries both halves of the same sentence: the
  selected line on the left (what the buttons act on) and a live readout of
  whatever is under the cursor on the right. With nothing hovered the readout
  names the gestures the surface supports, so the timeline teaches itself.
- **The reading column is bounded.** The timeline is an instrument and takes the
  full window; the lyrics are text, and a lyric stretched across 1440 px ends a
  third of the way in with its score a thousand pixels from the words it grades.
- **Save lights only when there is something to save.** Two permanently blue
  buttons teach you to ignore both, so the bar holds exactly one lit control at
  a time — *Check timings* while the queue has work, *Save* once you have made
  some.

Keyboard-first, because this is repetitive work. The toolbar carries buttons for
the handful of things you also reach for with the mouse — play, solo, follow,
speed, zoom, save — and each one prints its own hotkey in light condensed type,
so the keyboard is learned by using the buttons. Everything else lives behind
`?`, which opens the full shortcut sheet.

| Key | Action |
|---|---|
| `?` | open / close the shortcut sheet |
| `space` | play / pause |
| `↑` `↓` | select previous / next line |
| `←` `→` | nudge the selected word — or the whole line — ±50 ms (`shift` = ±10 ms) |
| `S` / `E` | set line start / end at the playhead |
| `enter` | preview the selected line |
| `T` | tap-along: stamp line start at playhead, advance to next line |
| `tab` / `shift+tab` | select next / previous word, rolling into the adjacent line |
| `W` | word tap-along: stamp the selected word's start at the playhead, advance |
| `R` | redistribute the line's words evenly across its span |
| `esc` | deselect the word, back to line-level editing |
| `[` / `]` | slower / faster playback (`\` back to 1×) |
| `V` / `F` | solo the vocal stem / follow the playhead (timeline **and** lyrics) |
| `⌘Z` / `⇧⌘Z` | undo / redo |
| `⌘S` | save (rewrites all export formats) |

Nothing above is needed for the guided path. `Check timings` is usable entirely
with the mouse, and its own handful of keys are listed with it above.

Every edit is reversible, at the granularity you'd expect rather than the
granularity the code happens to run at: a drag is one step no matter how many
mouse events it fired, a burst of arrow-key nudges folds into one step the way
typing does in a text editor, and a click that started a drag but moved nothing
costs no step at all. Review decisions land on the same stack, so *use
suggested* can still be taken back with `⌘Z` after the sheet is closed. Undoing
back to the last save marks the project clean again.

`←` / `→` are context-sensitive: with a word selected they move that word, with
none they move the whole line, so existing muscle memory carries over.

### Word editing edits starts only

Enhanced LRC encodes one timestamp per word, and a word's end *is* the next
word's start. So a line of N words has exactly **N−1 editable internal
boundaries** — word 0's start is the line start and the last word's end is the
line end, and both are already draggable as the line's own edges.

Editing starts only makes gaps and overlaps unrepresentable: one handle per
boundary, and the two words either side absorb every change. Selecting word 0
and nudging it therefore moves the line's left edge (without rescaling the rest
— that is what dragging the region edge does).

The accepted cost is that word `end` values are normalized to contiguous
(`words[i].end = words[i+1].start`) on load, on save and on export, in both the
UI and `project.py`. Whisper's raw ends encode inter-word pauses; flattening
them changes nothing that renders, because every export keys off starts and a
karaoke player holds a word until the next timestamp regardless. It does mean
`project.json` word ends now describe what a player actually shows — on the
sample track that absorbed 21 pauses, mostly under 165 ms but up to 9.4 s
across the long instrumental gap inside the closing line.

---

## Commands

```bash
# align + open the review UI (the default)
python -m lyricsync song.wav lyrics.txt

# align and export, no UI
python -m lyricsync align song.wav lyrics.txt

# repair impossible word timings, list what needs an ear
python -m lyricsync audit workdir/song

# re-run the benchmark against edited timings
python -m lyricsync score workdir/song

# rewrite lrc/srt/vtt from project.json
python -m lyricsync export workdir/song
```

Useful flags: `--model large-v3-turbo` (better refinement, slower),
`--no-roundtrip` (skip the blind transcription, ~90 s faster, weaker benchmark),
`--no-separate` (align against the full mix), `--force` (re-run, discarding
manual edits), `--max-iterations N`.

## Output

Everything lands in `workdir/<track-slug>/`:

| File | Purpose |
|---|---|
| `lyrics.lrc` | Line-level synced lyrics, the standard format |
| `lyrics.word.lrc` | Enhanced LRC with per-word timings, for karaoke highlighting |
| `lyrics.srt` / `.vtt` | Subtitles — feed straight to `ffmpeg -vf subtitles=` |
| `project.json` | Word-level timings, per-line scores and the scorecard — the richest source for a video generator |
| `vocals.wav` | Cached vocal stem (separation is the slow step; it is never redone) |
| `audit.json` | Last timing check: what was auto-repaired and what still needs an ear |

## Verified end to end

The point of all this is captions on a video, so that is what was checked:
`lyrics.srt` burned onto video with `ffmpeg -vf subtitles=lyrics.srt`, then
frames sampled across the track. At 0:36, 1:00, 3:10 and 4:10 the expected
line — and only the expected line — is on screen.

```bash
ffmpeg -i lyrics.srt -i song.wav -vf "subtitles=lyrics.srt" out.mp4
```

## Notes

- **The timeline draws exactly one waveform.** It used to draw three. The mix
  lane was measured out: on the sample track mix amplitude separates "someone is
  singing" from "nobody is singing" by 0.18 standard deviations, where the
  isolated stem manages 1.89 — on a compressed master it is a solid bar, and it
  cost 44 px of height and half the analysis payload (0.69 MB of 1.43 MB) to say
  almost nothing. The word lane then drew a *second, dimmed copy of the vocal* to
  put word cells over; that copy is gone too, and the word cells now sit in the
  bottom band of the one vocal lane with their dividers running its full height,
  which reads the boundary against the real audio instead of a duplicate of it.
  235 px of timeline became 180 px, and three waveform rasterisations became one.
  The mix peaks are still cached on disk, just not drawn or shipped.
- The timeline holds 60 fps with room to spare. The waveforms depend only on the
  visible window, so they are rasterised once into an offscreen canvas and
  blitted; only the playhead, the region overlays and the active word are drawn
  per frame. A steady playback frame costs ~0.5 ms of a 16.7 ms budget, panning
  (which does rebuild the waveform layer) ~1.9 ms, and a paused frame costs
  nothing at all — when the playhead has not moved and no edit has landed, the
  loop draws nothing. Splitting the waveform into a sung pass and a silent pass
  is free: each pixel column's peak is still computed exactly once, and a full
  rebuild measures ~1.1 ms. Playback highlighting mutates only the two elements
  that changed rather than re-querying the document, and the lyrics scroll on
  line changes, not on frames.
- Roughly 5 minutes end-to-end for a 5-minute track on an M4 CPU (≈3.5 min when
  no repair iterations are needed). Re-runs reuse the cached stem.
- Models download once on first run (~3 GB total) to the usual torch/HF caches.
- Demucs on Apple MPS is broken under torch 2.5, so separation runs on CPU.
  Whisper decoding hits unimplemented sparse ops on MPS too — CPU throughout.
- Section headers like `Chorus (8 bars, full drop)` are parsed as structure and
  are never aligned as lyrics. `[Verse 1]`, `Chorus:` and `(Bridge)` all work.
