# Gravity in Motion — a piece

One song, directed by hand from measurements, outside the typed score. The grammar
and the slot schema exist so a model can direct any song; this is the other thing —
a single track taken as far as it will go, so there is a gold example of what
"follows the song" means when nothing is holding it back.

```
.venv/bin/python -m demucs -n htdemucs -d cpu \
    -o visuals/cache/gravity-in-motion/demucs_raw "examples/Gravity in Motion.wav"   # once, root venv
visuals/.venv/bin/python -m visuals.pieces.gravity listen     # stems -> events and streams
visuals/.venv/bin/python -m visuals.pieces.gravity models     # notes, melody, chords, mood, lyrics, from small local models
visuals/.venv/bin/python -m visuals.pieces.gravity render     # 1080p60 mp4 + the player's files
visuals/.venv/bin/python -m visuals.pieces.gravity measure    # decode the mp4, check it against the audio
visuals/.venv/bin/python -m visuals.pieces.gravity matrix     # solo each instrument: what does it move?
visuals/.venv/bin/python -m visuals.pieces.gravity smooth     # only section decisions live: is there a step?
python -m visuals serve   ->   player/?track=gravity-in-motion-piece
```

## The picture

One body, eight satellites on concentric tilted orbits, a field, thrown rings.
One instrument, one visual role, nothing sharing:

| heard | seen |
| --- | --- |
| kick | the body punches — radius +26 %, and the whole system is tugged inward |
| sub floor | the body's mass, and how hard it holds: orbits tight and quick, or wide and slow |
| bass level | the body's glow |
| clap / snare | a ring thrown outward from the surface |
| hats | the orbit hairlines tick |
| synth notes | a satellite pops — *which* one is the note's pitch, low notes close in, high notes far out |
| voice level, syllables | the light inside the body |
| voice pitch | an aura standing off the body, moving out and back with the melody |
| pad brightness | how far the field reaches |
| harmony, and energy spent so far | hue: teal before dawn, gold by the last chorus |
| loudness | how much ambient light there is |
| the floor coming back | the shock: the largest ring, a flash, the frame pushed in |

The song has three states of floor, and they fell out of the data rather than the
lyric sheet: **drive** (kick in), **float** (bass, no kick) and **void** (nothing
below — the bars before every re-entry). The orbits are a spring on that: as the
floor goes the satellites drift out and slow, weightless; when it returns they fall
in and overshoot. That is the gravity in the title, and it is the only metaphor.

Nothing reads a previous frame. Anything that happens at an instant is handed to
the shader as the *time* it happened, in a held channel, and the shader works out
how long ago that was. So an attack is as sharp as the frame rate allows, a ring's
radius is exact, and any frame can be drawn cold.

## What listening found

**The beat tracker's grid was half a beat out.** `beats.json` says 123.05 bpm, with
16 ms of jitter, and its beats sit on the off-beat hat. The track is 125.0004 bpm
and does not drift: 723 hats and claps lie within **1.04 ms rms** of a constant
grid, and the per-30-second mean residual never leaves ±0.4 ms. Every one of the
eight places the kick re-enters after a rest lands on the same bar phase, and they
are all multiples of eight bars apart. The grid here is fitted to the sharp
percussion and phased by those re-entries; the tracker's is not used.

**A kick's low band reads 24 ms late.** Its click starts the beat; its energy below
140 Hz takes another frame and a half to get half way up. Timed from the low band,
every kick would have been a frame and a half behind the hats. The lag is measured
against the lattice and removed (kick 24.4 ms, bass notes 15.2 ms, synth notes
3.0 ms). Stems sit 0 samples from the mix; `mix.m4a` sits 0 samples from the wav.

**The lyric sheet is not the structure.** "Verse 1" is a breakdown with no kick;
the first "Chorus" has no drums at all; the first full drop is an instrumental at
bar 50. The ten re-entries are found from the audio — a downbeat where the loudness
steps up and the sub arrives together — at bars 2, 34, 42, 50, 66, 82, 90, 98, 116
and 132.

**A bass note beats in its own envelope.** A 49 Hz fundamental leaves a 49 Hz
ripple in a power envelope low-passed at 35 Hz, and at 60 fps that reaches the
screen as an 11 Hz shimmer nothing in the music asked for. The bass envelope is
low-passed at 12 Hz.

## What measuring found

`measure` decodes the mp4 as a player would and knows nothing about the renderer.
Each of these was a number before it was a fix:

- **Snares on their own were seen 22 % of the time; on a kick, 100 %.** The ring was
  born a hairline. It is now born thick and bright just off the surface and thins as
  it travels, and a quiet clap is a smaller ring but never no ring.
- **Loudness was dimming the hits.** One exposure multiplier over everything put
  snare recall at 0.10 in the quiet sections. Loudness now sets the ambient light
  only; a hit brings its own, because it already carries its own size.
- **The voice washed out the kick.** With the voice lighting the body, the corona
  was as bright as the rim and the body's edge — which is how a kick is seen —
  disappeared, in exactly the sections where both play. The tonemap compresses
  everything near white, so steady light is kept low to leave room; the voice's core
  is held inside the body and its aura stands off the surface.
- **A third of the notes lit something invisible.** Solo, satellites 1, 4, 5, 6, 7
  were seen 100 % of the time and 0, 2, 3 never: the inner orbits crossed behind the
  body or in front of its glare. The orbits now clear the body at the top of a kick.
  Note recall solo went 0.48 → 0.99.
- **Note pops masked each other.** A 200 ms decay under sixteenths 120 ms apart. A
  pop (55 ms) and a short tail instead.
- **Drop 1 was the stillest loud section in the song**, because only the kick plays
  there and the kick moved only the body. The kick now tugs every orbit and pulses
  the field.

## Where it stands

Final render, whole song, 17,148 frames — see `out/gravity-in-motion-piece/measure.txt`
for the run this table was copied from.

| check | result |
| --- | --- |
| response begins | inside the frame before the hit, for every instrument; never after |
| kick / snare / hat recall | 1.00 / 0.97 / 0.99 |
| note recall | 0.79 in the mix, 0.98 solo |
| syllable recall | 0.61 over all 366, and 0.97 solo for the prominent ones — it is proportional to the syllable, on purpose |
| precision | 100 % of the 571 sharpest visual onsets have an audio event in their frame |
| impact | the 10 largest luminance steps in the video are the 10 re-entries |
| separation (solo) | diagonal 1.00 / 1.00 / 1.00 / 0.98 / 0.97 |
| streams | body radius against mass r = 0.97; core light against the voice r = 0.80; luminance against loudness r = 0.68 |
| container | mp4 audio 0.00 ms from the wav |
| flicker | mean-luminance rms above 3 Hz: 0.010 of full scale |

**Not met: the arc.** Per-bar picture energy (luminance + motion) against per-bar
loudness is r = 0.45. Luminance alone tracks loudness at r ≈ 0.68; motion does not,
because motion follows how much percussion is playing, and on this track that is
not loudness — the intro has full drums at −6 dB, and the choruses are louder with
no drums at all, carried by a held bass note and the voice. The picture is still
there because the music is. Bending it to the metric would mean inventing motion
the song does not have.

**Known cross-talk.** With only rings drawn, a ring's birth registers on the
body-radius detector at 24 % of kick times and reads as fine detail to the hat
detector on 21 %. "Registers" is against a null that is otherwise perfectly still:
the radius moves by at most 0.0009 frame heights, against 0.0202 for a real kick.

**A detector can be wrong too.** The first body-radius detector took the innermost
steep fall of the radial profile, and in a tenth of the voiced frames that was the
voice's light inside the body, not the rim. It now takes the *sharpest* fall - a
rim falls in a bin or two, a glow in five or more - and reads the rim in every
frame (radius against mass went 0.64 -> 0.97 with no change to the picture).


# Version 2: colour, variety, and what small models hear

Version 1 was judged good but wanting: more colour, a little more variety, a little
more reactivity, nothing crazy - and every addition to arrive smoothly. It was also
asked whether small local models could say more about the audio than arithmetic on
the stems does. They can, about one kind of thing.

## Models say what; the stems say when

Six models, all permissively licensed, all local, 42 seconds for the whole song:

| model | licence | gives | checked against | verdict |
| --- | --- | --- | --- | --- |
| Beat This! | MIT | beats, downbeats | the percussion lattice | bar phase agrees on 146 of 150 downbeats and tempo is 125.00 - an independent confirmation. Its beat *times* sit a median 38 ms off the lattice, 21 % within 25 ms |
| basic-pitch (`nmp.onnx`, 230 KB) | Apache-2.0 | notes on the synth and bass stems | constant-Q guesses; the bass envelope | synth line A3 E4 B3 C4; bass on G1 - 49 Hz, the ripple found in the bass envelope in version 1 |
| SwiftF0 (135 KB) | MIT | the sung melody | pyin | within a semitone on 92 % of sung frames, no octave errors, 1 % false voicing in silence |
| lv-chordia | MIT | chords | the key | Am F G Dm7, in A minor |
| `larger_clap_music` | Apache-2.0 | each section against pairs of opposite words | measured loudness, drive, brightness | **mixed** - see below |
| all-MiniLM-L6-v2 | Apache-2.0 | each lyric line and word against eight images | reading them | "Silver lights" -> silver, "Shadow dancers" -> shadow, "electric, raw" -> electric, "fades into dawn" -> gold, "slow explosion" -> fire |

The division of labour fell out of the first check and was kept everywhere: **a model
frame is 10 to 20 ms wide and a model's idea of an onset is a person's idea of one,
so no model is trusted for time.** A model note is snapped to the stem attack within
45 ms of it (69 % of synth notes have one) and the attack's time is used. The model
says which note; the stem says when.

**CLAP was audited, not believed.** Each axis was correlated with measured section
features. *bright* follows loudness (+0.73), the kick (+0.62) and spectral centroid
(+0.55); *tension* is highest on the three risers and lowest on the steady drives
(-0.66 with the kick); *warm* carries its own information (voids and sweeps are cold).
Those are used. *energy* has no relation to loudness on this track (-0.05) - it calls
the drumless verse more energetic than the loudest drive - and *dreamy* mostly counts
hi-hats (+0.78). Those are not; loudness and the kick are asked instead.

What could not be used for licence reasons: MuQ, MERT and the Essentia mood heads
(all non-commercial weights), and ADTOF, the only small drum transcriber. What could
not be installed on Python 3.12: the basic-pitch package itself (hence the bare ONNX
file and a ported decoder), essentia-tensorflow, and anything that needs madmom.

## The song's form is its colour

Sections come from the measurements: runs of bars in one floor state with the voice
in or out, cut at every re-entry. Sixteen of them, on the song's eight-bar phrasing
without having been told about it.

Each section is embedded twice - CLAP, and bar-averaged timbre and chroma - what the
whole song has in common is removed, and the sections are laid out in the plane in
which they differ most. **A section's hue is its direction in that plane.** Sections
that sound alike wear the same hue; three families appear on their own:

- **voice over a held bass** (verse 1, both choruses): rose and wine
- **the kick driving** (intro, drop, verse 2, bridge, last chorus, outro): blue to violet
- **risers and turnarounds**: emerald and teal - CLAP hears them as the cold ones

The second chorus looks like the first because it sounds like the first. On top of
that the whole wheel turns a tenth warmer from the first bar to the last. Two arcs
are eased round (`avoid_murk`): yellow-green, and orange, which at the lightness a
dark frame needs is simply brown.

A palette is five roles in OKLCH - field, far field, body, two accents thrown a third
of the wheel either side of the field. Inside a section: a **chord** leans the field's
hue by its distance from home round the circle of fifths (major a little lighter);
the **bass note** leans the body; a **synth note's** colour is how far it is from the
tonic, between the two accents, so a melody paints with two colours against a third;
a **clap's** ring is coloured by how bright that clap is; and what a **lyric line** is
about tints the singer's aura - fully, on the word itself.

## What was added, and what each is tied to

| layer | weight from | moved by |
| --- | --- | --- |
| rays fanned from the body | the kick driving, per section | each kick; turn with the bars |
| bands drifting in the far field | floating, voiced sections | the pad ducking under the kick |
| stars | space (CLAP), hats per bar | each hat lights a third of them in turn; a crash leaves them ringing; a riser draws them outward, endlessly |
| wakes behind the satellites | - | length is how hard the body holds: orbital speed made visible |
| the plane of the orbits | tips face-on as the music opens out, swings with the hue | - |
| the aura swelling | - | a held sung note (SwiftF0: sure of the pitch, pitch not moving) |

The tone map was also changed: an exponential per channel pulls every bright colour
toward white, which is where most of version 1's colour was going. The curve is now
applied mostly to luminance with the colour carried through it.

## Nothing that was added can cut

Everything decided per section is held per section and low-passed twice into an
S-curve four bars long, centred on the bar line - it starts before the boundary and
arrives after it, the way a lighting change is called - and hue goes the short way
round. Every layer is drawn always, at a weight, and is the identity at zero.

That is tested directly (`smooth`): the whole song is rendered with **only the
section decisions live** - every hit silenced, every follower of the audio held still,
the clocks running - and any step left in the picture is a step in a decision.

Median frame-to-frame change 0.0013; the largest anywhere in the song is 4.2x that.
At the fifteen section boundaries the largest change within half a second is
**1.3x to 3.9x the median, where cutting between the same two looks would have been
16x to 80x.** A boundary frame is an ordinary frame.

## Where version 2 stands

Whole song, 1080p60, 17,148 frames; `out/gravity-in-motion-piece/measure.txt` is the run.

| check | version 1 | version 2 |
| --- | --- | --- |
| response begins | inside the frame before the hit, never after | the same |
| kick / snare / hat recall | 1.00 / 0.97 / 0.99 | 1.00 / 1.00 / 0.99 |
| note recall, in the mix / solo | 0.79 / 0.98 | 0.75 / 0.98 |
| syllable recall, all / prominent solo | 0.61 / 0.97 | 0.58 / 0.97 |
| precision | 100 % of 571 | 100 % of 571 |
| impact | the 10 largest luminance steps are the 10 re-entries | the same |
| separation (solo diagonal) | 1.00 1.00 1.00 0.98 0.97 | 1.00 1.00 1.00 0.98 0.97 |
| luminance against loudness | r = 0.68 | r = 0.77 |
| per-bar arc | r = 0.45 | r = 0.53 |
| hues on screen at once (of 24) | 2.1 | 4.1 |
| hues visited over the song (of 24) | 11.2 | 15.9 |
| colourfulness, median / p90 | 0.077 / 0.104 | 0.092 / 0.116 |
| container, flicker above 3 Hz | 0.00 ms, 0.010 | 0.00 ms, 0.011 |

**What it cost.** Note recall in the mix fell from 0.79 to 0.75 and syllables from
0.61 to 0.58: there is more on screen for a pop or a syllable to be seen against -
stars, wakes, a tinted voice. Both are unchanged solo, so it is masking, not loss.
The ring's cross-talk onto the body-radius detector is 0.33 of kick times (it was
0.24), still a movement of under 5 % of a real kick's.

**Colourfulness moved least.** Twice the hues at once and half again as many over the
song, but the Hasler-Suesstrunk number only rose a fifth, because it is averaged over
every pixel and most of the frame is, on purpose, dark: the hits need the dark to be
hits. Lifting it further means lighting the background, which trades directly against
impact. That is a taste call, and it is one number to turn (`amb` and the far-field
gain in the shader).



# Version 3: the same piece, printed

Version 2 was right and read as arcade. What was asked for instead: cel-shaded,
semi-realistic space - "something that would be part of the universe", with stars,
asteroids, shooting stars, things with momentum, gravity - in the look of
[forge](https://github.com/nuterian/forge). Two things were named as the essence of
that look while it was being built: **attention to detail** - galaxies, dust clouds,
belts, comets, moons, each with a place, each behaving as it would, each in ink - and
**sharpness**: things may fade, shrink or break up, but nothing on screen is blurred.

It is a second shader, `shader_ink.py` (`--style ink`), fed by exactly the channels
version 2 bakes. Nothing about the music's mapping moved; only what each thing *is*.

    python -m visuals.pieces.gravity --style ink render | measure | matrix | smooth
    player/?track=gravity-in-motion-ink

## What forge's look is, and what was taken from it

Read from its `DESIGN.md`, `ink.glsl`, `sun.frag`, `glow.frag`, `body.frag`,
`orbit.frag`, `sky.frag`, `rings.frag`, the asteroid shaders and `post.frag`; the ink
library (posterize, inkShade, the Bayer screen, value-noise fbm) is ported from it.

- Light and shadow are two **inks**, not a colour and a darker one. N.L is clamped at
  zero and then banded, so the night side is one ink and the terminator is where it is.
- The star is **flat cells** chosen by noise - no gradient inside a cell.
- Glow is **stepped contour bands whose edges wander**. No blur, no rays.
- Orbits are ink lines, **brightest just behind the body**, stepped.
- A printed sky: hashed hard-edged stars, the brightest four-pointed.
- One print pass: ordered dither, paper fibre, a vignette toward the *paper*.

## What each thing became

| heard | version 2 | printed |
| --- | --- | --- |
| kick | the body punches | the **star** punches; its cells run hotter; both belts and every orbit are tugged in |
| bass | the body's glow | how hot the cells run; how far the corona's bands reach |
| voice | light inside the body; an aura | the star's **heart** - a cell of its hottest ink as wide as the voice is loud - and a thin band standing off the corona, in the lyric's colour, reaching with the melody; a strong syllable throws a **prominence** |
| synth notes | a satellite pops | a **planet** - banded, lit by the star, with a real phase - flares: it grows, two contour bands stand off it, a hard ring is thrown |
| hats | lines tick, stars | rocks of the **asteroid belts** glint in turn; stars bloom |
| clap | a glowing ring | an ink **shockwave** that shoves the belts and the orbit lines outward as it passes |
| crash, re-entry | shimmer; the shock | a **shooting star**, its path bent toward the star as it passes |
| pad brightness | the field's reach | how far the star blows a **comet's** two tails (dust, and a straighter ion tail) |

And what is simply there, because space has it: two moons and one, a ringed planet
with its own shadow across its rings, an outer debris belt, two fields of dust cloud,
a galactic lane, three far galaxies turning too slowly to see, and parallax - the
camera drifts a hair on the bars, and each layer of sky moves by how far away it is.

The comet's orbit is Kepler's equation solved in the shader (five Newton steps); its
tails always point away from the star and lengthen as it falls inward. The belts'
lanes turn at their own Keplerian rates. Planets spin, so their markings cross the
disc. Nothing else moves unless the music moved it.

## What printing changes about a hit

**On a printed page nothing can get brighter.** Every ink is already at full
strength, so version 2's vocabulary - flash, glow, bloom - does nothing. The first
ink render measured it: a planet's note changed the brightest-pixels signal by 0.00,
note recall 0.29, hats 0.21. Hits have to be said in print: a thing gets **bigger**,
is given **more ink** (contour bands standing off it), **throws a line**, or grows an
**area** of hotter ink. Planets now rest in a muted ink so that sounding has somewhere
to go.

**A glow that outshines its source reads as the source.** The first corona was an
opaque slab brighter and more saturated than the star. The star is now the most
saturated thing on the page, its corona darker than it, the voice a thin band.

**The detectors were for the old look, and three broke honestly.** Ink rings are as
hard an edge as the star's rim, and the voice's heart is a hard edge *inside* it, so
"the sharpest edge" stopped meaning the rim; it is now the innermost hard edge with
the dark beyond it (kick recall 0.01 -> 1.00 with the picture unchanged). The voice's
light saturates at the centre, so syllables are looked for in the disc the heart
swells in. And the paper - nine tenths of the frame, with a breath of colour in it -
no longer votes in the hue histogram.

## ...and then the print was taken back out

The printed draft was shown and turned down, rightly: it had copied forge's *print*
when what was wanted from forge was its *cel shading*. The dither read as pixel art,
the noisy sun cells and the posterised dust as clutter, the galaxies as fake, the
colours as dull, and the orbits - the inner planet going round once a second - as
nothing a solar system does. "The noise should come from the motion, which
represents the music itself, not so much from the visuals."

What `shader_ink.py` is now: flat clean colour, one pixel of anti-aliasing on every
edge, no dither, no grain. A sun in four tones (corona, limb, surface, and the voice
as its white-hot heart). Planets in a lit tone, a half tone and a shadow that keeps
its colour, with real phases and a sunward rim; a ringed planet with its shadow on
its rings; moons; two belts; a comet on a Kepler orbit; shooting stars on crashes,
re-entries and every second bar line. A sky as skies are - many faint stars and few
bright, in star colours, crowded into a lane and two clusters, with three figures of
bright stars and no lines. The innermost planet takes half a minute to go round and
the rest follow Kepler's third law (`uOrbitSlow`); what is fast is what the music does.

Two bugs worth remembering. **A star was being cut in half** at the edge of each
cluster, because whether a star exists was being decided from the star density *at
the pixel*, and density changes across a cluster; it is decided once, at the star's
own position, now, and a test measures every four-pointed star's arms. And a
four-pointed star whose arm fell across two pixel rows printed it as two dim rows
while its other arm printed as one bright column; such stars are seated on the pixel
grid. This version is frozen in `snapshots/` and tagged `piece-v3-cel`. Its sync has
been checked solo (diagonal 1.00 / 1.00 / 0.98 / 0.84 / 0.97 on the printed draft) but
the full measurement has not been re-run since the print came out.

