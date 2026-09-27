# song

[![tests](https://github.com/nuterian/song/actions/workflows/tests.yml/badge.svg)](https://github.com/nuterian/song/actions/workflows/tests.yml)

A music video for any song. Give it a track: it listens to the whole song, then draws it
as a solar system where every beat, note and word moves something. Then direct it
yourself, by hand or by asking, and export it. Free, open source, and made on your own
Mac: no account, no uploads, no keys.

**[Watch one in your browser](https://jugalm.com/song/video/)** · **[jugalm.com/song](https://jugalm.com/song/)**

![A frame of the video: the Sun and its planets against the real sky](docs/img/cosmos-still.webp)

```bash
git clone https://github.com/nuterian/song
cd song && ./setup.sh                        # once: two venvs, then asks about the models
visuals/.venv/bin/python -m visuals studio   # the studio, at http://127.0.0.1:8777
```

## What it makes

The solar system in three dimensions, the real planets against the real sky. Each part
of the picture is played by a part of the song, chosen for that song from what is really
in it: the pulse by the kick, the rings by the snare or clap, the stars by the hats, the
corona by the bass line, the planets by the synths' notes, the heart by the voice. The
song's form moves the camera. The words are placed where nothing in the picture crosses
them, and lit as they are sung. Everything is heard from the song itself, and the same
song makes the same video every time.

## The studio

![The studio: the video above a timeline of the song's sections, camera shots and lyric lines](docs/img/studio.webp)

- **Add a song** by dropping it on the studio or naming it on the command line (wav,
  flac, aiff, mp3, m4a, aac, ogg, opus), with its lyrics as a `.txt` if it has them. The
  first time, it is prepared: Demucs separates the stems, the words are timed, the song
  is listened to and the small models run. After that it opens in seconds.
- **Edit by hand** on the timeline: pick a shot, drag where one ends, choose bars and
  give them a shot, move a dial, correct the beat grid, name the sections. An edit is
  in the picture in about 1.4 s, and every change is a step in one history to undo.
- **Edit by asking**, in words ("a close shot on Saturn in the second chorus"), with a
  model running in [Ollama](https://ollama.com) on the same machine. This is optional:
  without Ollama everything else works and asking says to start it. The answer comes
  back as a proposal drawn on the timeline, to apply or discard. `gpt-oss:20b` edits
  best of the models measured, in about 7 s a request; it is its own download, through
  Ollama.
- **Export an mp4**: 1080p at 60 fps, the camera you chose, the words burned in, the
  song's audio under it.

## What it costs

- **Disk**: `.venv` 1.0 GB and `visuals/.venv` 1.1 GB, plus 7.8 GB of models: 1.8 GB
  for the video and Demucs, 5.9 GB for aligning lyrics (listed below).
- **Install**: `./setup.sh` took 1 min 46 s from a fresh clone with pip's cache warm,
  fetching 30 MB of packages. A first install also downloads two builds of torch and
  the rest, which was not timed. The models are a separate step it asks about.
- **Time**, on an M4 MacBook Air: aligning lyrics about 5 minutes for a 5-minute song;
  preparing it for the video about 7 (Demucs is half of that); rendering the mp4 at
  1080p60 runs at 45 frames a second, so about 7 minutes more.
- **Tested** on macOS on Apple Silicon only.

## What stays local

Everything. The songs, their stems, the edits and the renders stay on the machine; the
studio listens on 127.0.0.1; the edit model is Ollama's, on the same machine. There
are no accounts and no API keys. The network is used to install the packages and to
download each model once.

## How it works

Listening turns the stems into events timed to the millisecond (attacks, notes, the
beat grid) and small models say what they are (notes, chords, key, what a passage
sounds like, what a line is about). A director turns those into decisions - who plays
what, the acts, the shots, the moments the beat comes back - written as a direction
sheet a person or a model can edit, and the decisions are baked into channels a shader
reads frame by frame. `visuals/pieces/gravity/NOTES.md` has the piece, version by
version, with what was measured; `visuals/DESIGN.md` has the ideas the design rests on.

## The words

The words in the video are timed to the song by forced alignment, from the lyrics you
give it. Adding a song with its lyrics does this for you; it can also be run, checked
and corrected on its own:

```bash
./.venv/bin/python -m song song.wav lyrics.txt   # align, and open the review app at http://127.0.0.1:8420
```

Lyrics input is plain text: one line per lyric line, a blank line between
sections, and a header naming each one. `[Verse 1]`, `Chorus:`, `(Bridge)` and
`Verse 1 (8 bars, pulsing bass)` all parse; the note in parentheses is kept as
structure and never aligned as a lyric.

```
Verse 1 (8 bars, pulsing bass)
Light breaks through the skyline haze,
Feet find rhythm in endless maze,

[Chorus]
You're my gravity in motion,
```

Bring your own audio. `examples/lyrics.txt` is the full sample file.

### Why the timing is accurate

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
`NEXT-smart-features.md` has the measurements behind everything below.

### Fixing a word

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

#### Adjusting a word by hand

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

## Commands

```bash
python -m visuals                          # the studio, with every song already prepared
python -m visuals studio song.wav          # ...with a song in it
python -m visuals make song.wav            # prepare a song without opening the studio
python -m visuals edit song.wav "fewer solar flares"   # change its video by asking
python -m visuals render song.wav --theme cosmos --camera hybrid   # an mp4 from the command line
python -m visuals demo                     # the static demo, into docs/video/

python -m song song.wav lyrics.txt         # time the words, and open the review app
python -m song align song.wav lyrics.txt   # time them, no app
python -m song audit workdir/my-track      # repair, and list what needs an ear
python -m song bench workdir/my-track      # word error against a hand-timed gold file
```

`visuals` runs in `visuals/.venv`, `song` in `.venv`; `setup.sh` makes both.

## Tests

```bash
python -m unittest discover -s tests
```

Over 230 tests over the logic that carries the claims (lyrics parsing, the
word-timing invariants, word-to-line mapping, the export formats, the
missing-line thresholds, the bench arithmetic, the word-end rule, the
repeat grouping, the syllable rule),
plus a guard that those modules stay importable with no third-party package
present at all, which is what lets CI run them in seconds without installing
anything. The handful that need numpy skip themselves where it is missing.

The video's tests run in its own venv:

```bash
PYTHONPATH=. visuals/.venv/bin/python -m pytest visuals/tests                  # all of them
PYTHONPATH=. visuals/.venv/bin/python -m pytest visuals/tests -m "not local"   # what CI runs
```

`local` marks the tests that need a GL context, the example song or its listening
cache. The rest need only numpy, scipy, soundfile, moderngl's import and node, which is
all CI installs for them, and run in a few seconds.

## Models and licences

Each is downloaded by the library that runs it, from its publisher, the first time it
is needed (or by `./setup.sh` when asked); none is in this repository.

| Model | For | Licence | Size |
|---|---|---|---|
| [laion/larger_clap_music](https://huggingface.co/laion/larger_clap_music) | video: what each passage sounds like | Apache-2.0 | 1.6 GB |
| [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | video: what each lyric line is about | Apache-2.0 | 92 MB |
| [Beat This!](https://github.com/CPJKU/beat_this) `final0` | video: beats and downbeats | MIT | 81 MB |
| [basic-pitch](https://github.com/spotify/basic-pitch) `nmp.onnx` | video: notes | Apache-2.0 | 0.2 MB |
| [SwiftF0](https://github.com/lars76/swift-f0), [lv-chordia](https://github.com/music-x-lab/ISMIR2019-Large-Vocabulary-Chord-Recognition) | video: the sung melody, chords (in their wheels) | MIT | under 3 MB |
| [Demucs](https://github.com/facebookresearch/demucs) `htdemucs` | both: the four stems | MIT | 84 MB |
| [wav2vec2 MMS_FA](https://pytorch.org/audio/stable/generated/torchaudio.pipelines.MMS_FA.html) | lyrics: the alignment's structure | CC-BY-NC-4.0 | 1.3 GB |
| [Whisper](https://github.com/openai/whisper) `medium`, `large-v3-turbo` | lyrics: aligning within sections, and retries | MIT | 1.5 + 1.6 GB |
| [faster-whisper-medium](https://huggingface.co/Systran/faster-whisper-medium) | lyrics: the blind transcription | MIT | 1.5 GB |
| [Silero VAD](https://github.com/snakers4/silero-vad) | lyrics: voice activity (in its wheel) | MIT | 2 MB |

All but one are under permissive licences (MIT, Apache-2.0) that are compatible with
this repository's MIT licence, and none is redistributed here. The exception is
MMS_FA: Meta publishes its weights under CC-BY-NC 4.0, so aligning lyrics with the
song tool as it stands is for non-commercial use. The video does not use it, but its
words come from that alignment.

## License

MIT, see [LICENSE](LICENSE).
