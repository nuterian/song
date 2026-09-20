# visuals

Shader visuals that follow a song — moment to moment and as a whole — generated
locally, unique per song, and the same every time for a given song and seed.

This is a second tool in this repository, not a feature of the first. It reads a
song workdir that `song` has already built, and it reads it read-only: the
coupling is `project.json`, `analysis.json`, `beats.json` and `mix.m4a`, and
nothing else. No import crosses between the two packages, they keep separate
virtualenvs, and `visuals/` writes only inside `visuals/`.

```
python -m visuals render <song-workdir> [--preview START] [--seed N]
python -m visuals score  <song-workdir> [--seed N]
python -m visuals serve
```

## The idea

A visual that follows a song has to follow it on two time scales at once. Moment
to moment: the kick, the syllable, the hi-hat, the bar line. And as a whole: this
is a verse and that is a chorus, the second chorus should look like the first, the
colour should have gone somewhere by the end.

The observation the whole design rests on is that **synchronisation does not live
in the shader source**. A shader is a still life with a clock in it. What makes it
move with a song is the sequence of uniform values it is handed, frame by frame.
So the system splits three ways, and only the middle one is GLSL.

**Listen.** Offline feature extraction, per song, cached. Milestone 2 makes this a
beat-synchronous token stream — one token per beat, carrying per-stem onset
strength, chroma and key and mode, loudness, spectral brightness, vocal pitch,
which section the beat is in, a frozen music embedding for the section, and a text
embedding of the lyric line being sung on that beat. Milestone 1 uses only what
the song tool has already computed, on a 120 Hz grid rather than per beat, because
a renderer wants a smooth envelope more than it wants a token.

**Vocabulary.** A shader grammar. Four layers — a gradient wash, a few orbiting
discs, soft travelling bands, one ring — and that is the entire vocabulary of
form. What makes a frame worth watching is not how much is in it, it is how
precisely what is in it moves with the music, so the effort goes into giving each
layer a few inputs that read at a glance rather than into drawing more. The
grammar compiles to GLSL ES 3.0 with a per-frame cost bounded at compile time, and
the same source runs in WebGL2 in a browser and in headless GL from Python.

**Direct.** A **score**: a timeline that is data rather than code, and
specifically a *typed decision schema* rather than free text. Three tiers — song,
section, bar — every slot a categorical over an enumerated set, every continuous
quantity quantised to 32 bins, and a legality function saying which values a slot
may still take given the others. Per-bar slots line up one-to-one with bars in the
audio.

## Two properties the design is built around

Everything below follows from these, and both of them are tested rather than
asserted.

### Nothing cuts

A section boundary should be a place where the picture starts moving somewhere
else, never a place where one picture is replaced by another. Getting that from a
system whose sections make *choices* takes one idea: **no section-level choice is
a switch.**

A scene is not a branch, it is a point in layer-weight space — `bloom` means
(0.45, 0.45, 0.00, 0.70) over wash, orbits, bands and halo. A warp is a point in
warp-weight space; a post chain is a point in post-weight space. All four layers
and all three warps are always compiled and always evaluated, at a weight. Any two
scenes therefore have a straight line between them, and a transition is a walk
along it.

So there is **exactly one shader program per song**, and only song-level choices —
the palette family, the motif, the motion character, the symmetry — are constants
in it. Everything a section decides is a number, and at a boundary the numbers
ramp from the previous section's values to this one's, over a window the section
chose (1, 2, 4 or 8 bars) on a curve it chose (linear, ease, early, late,
sigmoid), starting on the downbeat. The score still names its moods
categorically, which is what the decision model wants; what the name denotes is a
vector, which is what a seamless transition needs.

Measured on the sample track, with routing switched off so that only the ramp is
moving: at every section boundary the frame changes by **1.0–1.5× the median
frame-to-frame change** elsewhere in the run. The boundary frame is an ordinary
frame. For scale, actually cutting between two sections' looks would be about a
20× step.

### Everything moves on the music

Nothing in the grammar advances on wall-clock seconds. The layers turn and travel
on `uBeats` — beats elapsed since the song began, interpolated within each beat —
so a rotation is so many turns per bar rather than per minute. `uTime` appears
exactly once in the whole grammar, to jitter a per-frame shake. Those free-running
rates are also kept deliberately slow, because the large changes in a frame should
be the ones the music caused.

On top of that, each bar of the score has **three routing lanes**: an audio
feature, a uniform to drive with it, a gain, and an attack/release envelope. The
features include `flux` — the half-wave-rectified rise of the mix, which is what
the music just *did* rather than where it currently is, and which is most of what
"the picture noticed that" turns out to mean.

Measured on the sample track, as how much more the picture moves in the 100 ms
after a beat than between beats:

| section | hand-written score | nothing routed |
| --- | --- | --- |
| intro | 0.99× | 0.99× |
| verse | 1.20× | 0.99× |
| pre-chorus | 2.05× | 1.01× |
| chorus | 2.83× | 0.99× |
| bridge | 1.16× | 0.99× |
| final chorus | 2.77× | 1.00× |
| outro | 1.08× | 1.00× |

The control column is the point: a score that routes nothing shows no preference
for the beat at all, so the number is measuring the score rather than the shader.
And the routed column has the shape a song has — locked hardest through the
choruses, loosest in the intro, the bridge and the outro.

## The director is a decision model

Milestone 4 fills the score with a small model. The ideas below are borrowed from
the way "System One" decision models such as TypeSafe's Jev are described. Jev
itself is a closed API with an undisclosed architecture, so none of it is used;
these are the transferable parts.

**State in, typed decisions out.** The model never emits text and never emits
GLSL. It fills schema slots. Illegal values are masked out of the logits using the
grammar, so every score it produces is valid — 0% invalid output is a structural
guarantee, not a trained behaviour, and it holds on the first training step as
firmly as on the last.

**Parallel, not autoregressive.** A small bidirectional transformer encoder —
pre-norm RMSNorm, RoPE, SwiGLU, QK-norm, 5–20M parameters — reads the beat tokens
and the slot tokens together and predicts every masked slot at once. Visual
decisions are not independent (the palette and the layers have to agree; chorus 2
has to match chorus 1), so decoding is MaskGIT / masked-discrete-diffusion style:
8–16 passes, committing the most confident slots each pass, song tier first, then
sections, then bars. Training is the ordinary random-masking objective.

**Editing falls out for free.** Lock any subset of slots — "keep the palette,
re-roll the bridge" — and the model infills the rest. Hand edits are first class
because they are the same operation the model performs, and each one is a training
signal.

**Calibrated probabilities.** Trained and evaluated with proper scoring rules (log
loss plus Brier), temperature fitted on held-out data, reliability curves
reported. Calibration is what makes a seed mean something: the seed draws from an
honest distribution, which gives variety without nonsense, and it is what tells
the system where it does not know.

**Optional depth without parameters.** Weight-shared recursion in the spirit of
Tiny Recursive Models — a two-layer block applied repeatedly while refining the
answer — measured as an ablation against a plain 6–8 layer stack. With little data
the smaller network is the one to bet on.

## Learning plan

The rating budget is the scarce resource — hundreds to low thousands of judgments,
from one person — so every stage is chosen for sample efficiency.

- **Stage 1, no human data.** Sample a few hundred thousand scores from the seeded
  grammar sampler under hand-written priors, render short probes, keep the ones
  that pass automatic filters (not black, not blown out, inside the frame-time
  budget, no flicker above about 3 Hz, no frame that changes far more than its
  neighbours, and visual motion energy locked to the beat where the score says it
  should be), and train the masked model on the survivors. The last two filters
  already exist as tests.
- **Stage 2, reward model.** Pairwise A/B on 10-second clips, with ties and "both
  bad" allowed. Frozen CLIP/SigLIP frame embeddings plus the audio embedding plus
  the director's own encoder states, into a small head. Bradley–Terry with ties,
  plus a Brier term for calibration. A deep ensemble of about five (or a Bayesian
  last layer) gives epistemic uncertainty, used both for active pair selection and
  as a penalty against reward hacking. "Looks good at all" and "fits this passage"
  are asked separately.
- **Stage 3, policy improvement**, in this order: best-of-N against the reward
  model; then reward-weighted or rejection-sampling fine-tuning, which needs only
  the ordinary masked loss and so sidesteps the likelihood-estimation problem
  masked models have; and only if that plateaus, a variance-reduced preference
  objective (VRPO, as in LLaDA 1.5) or a diffu-GRPO-style policy gradient (as in
  d1). A KL-style anchor to the stage-1 model, a novelty term against previous
  songs' outputs, and a style latent keep diversity from collapsing. No PPO.
- **Improves with use.** Implicit pairs from kept versus re-rolled candidates,
  exported versus abandoned, hand-edited score versus its original. Retraining
  happens in the background, and a checkpoint is promoted only if it predicts a
  held-out slice of past choices better *and* stays calibrated.

## Milestones

1. **Runtime and the typed score schema.** *(this one)* Headless renderer, the
   score as slots with legality, the workdir loader, the four-layer grammar, a
   hand-written score, mp4 out, and the same thing in a browser.
2. **Extended listening.** Own four-stem Demucs run (the song tool keeps only
   vocals), chroma/key/mode, brightness, vocal pitch, beat-synchronous tokens, a
   frozen music embedding per section, a text embedding per lyric line. Cached per
   song under `visuals/cache/<track>/`.
3. **Grammar v1.** Fifteen to twenty typed blocks, legality derived from the
   blocks' own input and output types rather than from a table, a seeded sampler
   with priors, and the automatic filters.
4. **The masked decision model.** Pretraining on stage-1 survivors, MaskGIT
   decoding with grammar masking, and a calibration report.
5. **Rating UI and reward model.** A/B on clips, ties and "both bad", the ensemble
   head, active pair selection.
6. **The improvement loop.** Best-of-N, reward-weighted fine-tuning, implicit
   feedback, background retraining with a promotion gate.
7. **Lyric-aware direction.** The text embedding of the line actually reaching the
   score, and word-level timing reaching the uniforms.
8. **Block authoring with a local coder model.** New blocks proposed, compiled,
   probed and filtered automatically, so the vocabulary grows without hand-writing
   every block.

## What milestone 1 actually built

### The headless renderer spike, and what it found

This was done first, because it was the largest unknown: can a GLSL ES 3.0
fragment shader be run off-screen on macOS from Python at all?

**It works, with one shim.** `moderngl.create_standalone_context()` comes up on
macOS with no window and no display, reporting:

```
GL_VENDOR   Apple
GL_RENDERER Apple M4
GL_VERSION  4.1 Metal - 89.4
```

**`#version 300 es` is rejected outright.** Apple's desktop GL stops at 4.1 and a
core-profile context treats GLSL ES as a different language:

```
ERROR: 0:1: '' :  version '300' is not supported
ERROR: 0:1: '' : syntax error: #version
```

So the shim is the version line, and only the version line. Every block is written
in the intersection of GLSL ES 3.00 and desktop GLSL 4.10 core — explicit
`layout(location = 0) out vec4`, `texture()` rather than `texture2D()`, a
`precision` statement (desktop GL accepts and ignores it), constant loop bounds,
and no integer-to-float slop. `grammar.compose` prepends `#version 410 core` for
the renderer and `#version 300 es` for the browser, and a test asserts the two
sources are identical below that first line. Both compile; the browser and the mp4
agree.

**wgpu-py was never needed.** It was the fallback if moderngl failed, and moderngl
did not fail.

**It is fast.** Measured on an M4 at 1280×720, drawing and reading back every
frame:

| what | measured |
| --- | --- |
| the original spike, 720p, draw + readback | 145 fps (6.9 ms/frame) |
| 25-second preview, 60 fps, the real pipeline | 107–156 fps (6.4–9.3 ms/frame) |
| the whole song, 285.8 s at 60 fps, 17,148 frames | ~100 fps GL; under three minutes wall clock |

The whole song renders in well under real time, and the wall clock is dominated by
x264, not by GL. Frame feedback needs a ping-pong pair, so the renderer keeps two
RGBA8 textures and alternates; eight bits is enough because the tonemap has
already bounded the frame to 0..1 by the time it is stored.

**What does not work, and is not pretended to.** Off-screen GL here has no
multisampling and no sRGB framebuffer; the shader does its own tonemap and gamma,
which is what the browser path does too. A preview starting mid-song begins with an
empty feedback buffer, so trails take a few frames to establish — warming them up
would mean rendering the whole song to preview a bar of it, and it is the one real
discontinuity a preview contains.

### The score

`schema.py`. Three tiers, and a flat integer layout: song slots, then section
slots section by section, then bar slots bar by bar, with bar *j* of the score
lining up with bar *j* of the audio. `MASK` is −1, outside every slot's value
range, so a partially filled score is representable and bin 0 is never mistaken
for "undecided". `to_slots`/`from_slots` round-trip exactly, including through
JSON, where a masked slot is `null`. The sample track's score is 1,864 slots.

Song tier: palette family, palette shift, block set, motif, motion character,
symmetry, grain. Section tier: scene, warp, post, density, energy, softness,
palette rotation, transition bars, transition curve. Bar tier: three routing
lanes, each a source, a target, a gain and an envelope.

`legal_values(shape, slots, i)` returns the boolean mask over slot *i*'s values.
The rules in force:

- a kaleidoscope needs a radial motif; on a motif that points somewhere, only
  `none` and `mirror_x`
- a scene must be one the song's block set admits
- a `still` song may not churn and may not trail
- a `mono` palette pins its rotation to bin 0 — there is nothing to rotate
- the first section may not arrive over one bar: a one-bar ramp out of darkness is
  a cut with extra steps
- within a lane, a source and a target are both silent or both not, and a silent
  lane's gain is bin 0
- two lanes of one bar may not claim the same uniform

Legality is **monotone**: a rule whose dependency is still masked is evaluated over
every value that dependency could take and the results unioned, so committing a
slot can only narrow what is legal elsewhere, never widen it. That is what lets a
MaskGIT decode commit slots in any order without painting itself into a corner,
and there is a test for it.

`random_fill` walks the layout in order and draws from the legal values, so it
needs no rejection and is deterministic from a seed — same seed, byte-identical
score, on disk as well as in memory. `Score.filled(seed)` fills only the masked
slots, which is the "lock the palette, re-roll the bridge" operation already
working, a milestone early.

### Listening

`listen.py`. The workdir goes onto one 120 Hz grid — the rate the song tool
already used, so nothing is resampled. Fifteen feature channels: the mix and vocal
peak envelopes, the low and high bands, flux, impulse trains for onsets, beats and
downbeats, beats elapsed, beat and bar phase, section index and progress, bar
index, line index and word progress.

Two things are derived rather than read. **Section spans**, because the project
file records which lines belong to a section but not when a section starts: a
section's own extent is its lines' extent, each gap between two sections is split
at the downbeat nearest its middle, and the first and last are stretched to the
ends of the song, so sections tile the track and every boundary is a downbeat. On
the sample track that matters — there is a 46-second instrumental between chorus 1
and verse 2. **Bars**, one per downbeat, with the count-in belonging to bar 0.

The stored envelopes already arrive compressed into 0..1, so they are clipped
rather than renormalised; guessing at a second normalisation would only move
loudness around behind the routing gains.

Sawtooth channels (the phases, section progress, word progress) are **held**
between grid points rather than interpolated. Interpolating one reads halfway
through the beat at the exact instant the beat lands, which is a visible pop once
a bar. This was found by a test failing on the real track, and it is worth keeping
in mind wherever a phase is stored.

### Routing and ramping, and why everything is baked

`uniforms.py`. Each lane of each bar names a feature, a uniform, a gain and an
envelope. Per uniform, those are stitched into one continuous channel: a
single-pole follower whose attack and release change at bar boundaries but whose
state carries across them. When a bar stops driving a uniform, the gain and the
release time are held and only the source falls to zero, so the route decays on
its own envelope instead of being cut off at the bar line. Alongside that, every
section-level number is ramped, as described above.

All of it is **baked once**, onto the same 120 Hz grid, and written to disk as one
float32 blob. Two consequences, both of them the point:

- The follower runs over the whole song rather than per frame, so the result is
  frame-rate independent and no onset can be stepped over however low the frame
  rate is.
- The browser samples exactly the numbers the mp4 sampled. There is no second
  implementation of the routing or the ramping in JavaScript, so there is nothing
  to drift. The player interpolates an array and sets uniforms; that is all it
  does.

### What went wrong, and what it taught

Five things had to be fixed after looking at real frames or at real measurements,
and each is a rule worth remembering.

**Post-processing ran in the wrong colour space.** `uPrev` holds a finished,
tonemapped frame, but post was running before the tonemap, so the feedback and
bloom stages were comparing a linear colour with a display-space one. The frame
drifted brighter on every pass and settled into a flat grey haze. The tonemap now
happens before post. Bloom additionally had a near-unity feedback gain, which on
its own produces a DC wash; it is now about a tenth.

**Routed brightness was additive.** `c += uBright * palette(...)` lifts the empty
parts of the frame exactly as much as the drawn parts, so a routed brightness read
as a flat colour over the whole screen rather than as the picture getting
brighter. It scales the picture now.

**A post stage was not weighted, only offset.** The chromatic split was guarded by
`if (uPostSplit > 0.001)` but applied at full strength inside the branch. A
section whose post chain ramped that weight down to nothing therefore switched the
stage off in a single frame — a cut, in a design that has no others. Every stage
is now the identity at weight zero.

**A count was an integer of a ramping number.** The orbit layer did
`int n = 2 + int(floor(uDensity * 5.99))`, so as the density ramped past a
threshold a whole disc appeared in one frame. The count is a real number now and
the last disc fades in across the fractional part. This is the subtler version of
the previous bug and the one worth generalising: in a design with no cuts, **any
rounding of a ramped value is a cut waiting to happen**.

Both of those were found by the same test — the one that takes the largest
frame-to-frame step in the whole song and asks what its neighbours were doing. In
a ramp they are doing nearly the same thing; in a cut they are doing nothing. That
is a better operationalisation of "seamless" than a threshold on how fast the
picture may change, because a two-bar arrival into a chorus *should* change it
quickly.

**One routing event per bar was not enough.** The bar tier started with a single
source/target/gain/envelope. Every uniform the song was not currently pointing at
had decayed to neutral, and a chorus that wants the kick on the scale *and* the
voice on the hue *and* the onsets on the shake could not say so. Three lanes per
bar fixed it, and bought a genuinely useful extra legality rule — two lanes of one
bar may not claim the same uniform. That rule then caught a mistake in the
hand-written score, which is the best evidence it was worth having.

### The player

`player/`, static, no build step. It fetches `plan.json` (the sections, the one
program as GLSL ES 3.0 source, the grid header), `frames.bin` (the baked uniforms)
and `mix.m4a`, compiles the program, and ping-pongs two textures the way the
renderer does, blitting the result to the canvas. It steps at 60 Hz rather than at
the display's rate, because frame feedback decays once per frame and a 120 Hz
screen would otherwise clear the trails twice as fast as the mp4.

`python -m visuals serve` answers Range requests. The stock
`SimpleHTTPRequestHandler` does not, and without `Accept-Ranges` a browser will
download the whole audio file, report it fully buffered, and still refuse to seek
in it — `HTMLMediaElement.seekable` stays empty and the scrubber does nothing.

## Layout

```
visuals/
  DESIGN.md          this
  requirements.txt   its own pins; venv at visuals/.venv
  schema.py          the typed score: slots, legality, the flat layout
  listen.py          a song workdir -> features on a 120 Hz grid
  uniforms.py        routing, ramping, and every uniform baked onto that grid
  grammar/           the GLSL layers, and score -> one shader per song
  render.py          headless GL, and the mp4
  export.py          staging plan.json + frames.bin + audio for the browser
  authoring.py       the hand-written score, and the seeded sampler
  pieces/            one song taken as far as it will go, outside the schema;
                     pieces/gravity/NOTES.md is what that found
  cli.py             render / score / serve
  player/            static WebGL2 page
  scores/            hand-written scores, one per track
  cache/  out/       derived, ignored
  tests/             run with visuals/.venv
```

## What milestone 2 needs

- **Its own stem separation.** The song tool keeps only `vocals.wav`; per-stem
  onset strength needs drums, bass and other as well. That is a four-stem Demucs
  run, once per song, cached under `visuals/cache/<track>/`. It brings torch into
  this venv — pin numpy<2 and torch 2.5.1, as the root requirements do and as
  `visuals/requirements.txt` already anticipates.
- **Beat-synchronous tokens.** The 120 Hz grid stays for the renderer, but the
  model reads one token per beat. That means deciding how each channel reduces to
  a beat (max for onsets, mean for loudness, argmax for chroma) and writing the
  token layout down as firmly as the slot layout is written down now.
- **Musical features that are not envelopes.** Chroma, key and mode, spectral
  brightness, vocal pitch. librosa covers all of these and is already pinned in
  the root requirements; adding it here is a version decision, not a research one.
- **An embedding, and its licence.** Evaluate MuQ first — it leads MARBLE — with
  MERT and LAION-CLAP as alternatives, and MuQ-MuLan or CLAP where text-aligned
  mood matters. **Check the weight licence before depending on any of them and
  record it in this file**; that check has not been done yet, and the MIT claim
  above covers only the code.
- **A lyric text embedding**, local and small, per line, so milestone 7 has
  something to reach for.
- **A cache format with a version in it**, because everything above is expensive
  and will be recomputed as the extractor changes.
- **A decision about the section-span heuristic.** Splitting the gap at its middle
  is defensible but it is a guess. With per-stem onsets and a music embedding,
  section boundaries can be detected rather than inferred from where the singing
  is, and the 46-second instrumental in the sample track deserves to be its own
  section rather than half a chorus and half a verse. This matters more than it
  looks: a boundary in the wrong place is a transition in the wrong place, and the
  transitions are the part this is being judged on.
- **Per-stem sources for the routing.** `low` and `high` are bands of the mix, so
  a kick and a bass note are the same feature to the score. With four stems the
  bar tier can point at the drums and the bass separately, which is the single
  biggest available improvement to how closely the picture tracks an arrangement.
- **A tempo curve rather than one tempo.** `uBeats` interpolates within each
  tracked beat, so it already follows a drifting tempo. But the transition window
  is computed from a single bars-to-seconds figure; on a song that changes tempo,
  a four-bar ramp would not be four bars. It should be measured in beats and
  converted through the same beat grid.
