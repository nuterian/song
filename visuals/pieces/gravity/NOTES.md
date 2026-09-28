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



# Version 4: the solar system, seen three ways

`--style cosmos`. Version 3's picture with the placeholders taken out: the eight
planets in their own colours, their moons, Saturn's rings, two belts, a comet; five
thousand stars from the Yale Bright Star Catalogue at their true places; the Milky Way
cut in flat tones out of NASA's all-sky map. The song's palette is in the *light* -
corona, ripples, the voice's ring - and never repaints a planet. Everything a hit
throws lies in the plane of the orbits, on the axis of the gravity it rides. No orbit
is drawn; each planet leaves a short trail in the mean colour of its own surface
(measured from `surface()` by `surface_means()`, held by a test - the first table was
typed by hand and had Earth the colour of its sea).

## Perspective was the mistake

The first build was a perspective ray tracer with a flying camera, and it was turned
down flat: spheres off-centre became eggs, the plane ran to a horizon, thin things
crawled (edge shimmer 0.097 against v3's 0.047), and the shots were poor. It was
rebuilt orthographic - an orrery's camera, which turns, tilts, rolls, zooms and slides
and distorts nothing - outward from v3's composition. Every edge is resolved against
the size of a pixel *where that edge is*; shimmer 0.014. The sky alone is seen
through a lens, because it is infinitely far.

## Three cameras in one bundle

`static` (the section's tilt and roll; no zoom, no slide), `cinematic` (a shot per
act) and `hybrid` are all baked, as `uCam*.{mode}`, and the player remaps the camera
uniforms live. Acts come from merging sections on boundary strength (`find_acts`);
nothing is keyed to this song's bar numbers. The planets' starting longitudes are
solved so that they stand in a row at the climax, and all three cameras face the same
way at that moment.

## What "jarring" turned out to be

`follow.jolt()` measures it from the channels alone. Close on Saturn, the re-entry's
spread of the orbits - handsome from the home distance - slid the scene at 1.7
frame-heights a second; every camera's re-entry push zoomed at 100 %/s; and the hybrid,
a 40 % blend of the cinematic one, held no subject at all (Saturn wandered over 1.5
frame-heights). So:

- `arriving()`: the spread knows the score. It has *finished* drawing in on the
  downbeat the floor returns on, having taken the bar before; it lets go over two.
  A re-entry is draw-in / hit / release, and the hit itself is light.
- A gesture of the whole system is sized for the frame it is seen in: the spread
  and the kick's tug are baked per camera (`uSpreadSlow.{mode}`), less the closer in.
- Shots arrive on the bar line instead of cross-fading through it.
- The hybrid is the static framing with a slow turn and a gentle lean. It follows nothing.

Slide peak 169 -> 34 %/s, zoom peak 104 -> 27-39 %/s, fastest planet across the frame
255 -> 51 %/s. A test holds the limits.

## Detectors that follow the bodies

`measure` watches a fixed, centred Sun. `follow.geometry()` repeats the shader's
arithmetic and says where the Sun and each planet are in every frame of any camera
(checked against rendered frames: a quarter of a planet's radius), and each detector
looks there. Two lessons:

- With one instrument drawn and everything else frozen, a detector notices anything
  at all; "did it notice" made a matrix of ones. The matrix now reports *how far* a
  detector rises, as a fraction of its rise for its own instrument.
- The Sun's radius is measured from the area of Sun-coloured pixels, and the bass
  from the tallest tongue of the corona's silhouette over the usual one, sector by
  sector - because a kick swells the whole rim alike and a prominence is somewhere.

What it found in the first cosmos build: bass notes and syllables moved nothing, and
the kick's light fell on the planets (the notes') and the Sun's face (the voice's).
Each now has its own: prominences placed round the limb by pitch class; strokes
standing out of the voice's ring; and for the kick, mass bends light - a ripple leaves
the Sun and *moves* the stars it passes without brightening them (brightness is the
hats'; a test holds both halves). A re-entry dims the sky through the bar before and
opens it on the downbeat.

## An orchestra, not a chorus

"Think of this as an orchestra of dancing celestial bodies ... each contributes in
their own unique way." Three things followed from that and from watching the first
prominences:

- **What a planet gives off is the planet's.** Its pool and rings were in the song's
  accent and its dark outline was drawn over them, so they read as something laid on
  it. They are now its own colour, lifted, drawn over the outline; and each planet
  answers in its own manner (`PING_N` and friends): Mercury flicks, Venus blooms,
  Earth rings twice, Jupiter rolls out three, Saturn's answer runs out along its
  rings, Neptune is slow and wide. (Uranus threw its ring upright, for its tilt; it read
  as a wireframe at right angles to everything else, and everything is in the plane now.) A
  note swings a planet's moons out.
- **What the Sun sends, arrives.** A clap's ring, the re-entry's shock and a flare's
  front are circles in the plane about the Sun, so the moment each reaches an orbit
  can be worked out; at that moment the planet is struck - its sunward side flashes
  and a bow wave stands off it toward the Sun. A test sets a ring to arrive and looks.
- **Charge, and the flare.** The bass line charges the corona (`uCharge`: it stands
  further out and hotter as it builds). Past a threshold, the next bass note *that
  lands on a beat* discharges it: one great tongue from where that note's prominence
  stands, the limb flashes, and a front fans out across a third of the plane, striking
  the planets in its way, which ring. The threshold is found by bisection as the one
  at which the song fires about once in two bars of the time its bass is playing
  (`cosmos.flares`; 69 here) - so a sparse line and a relentless one both get events.
  The loop of fire that stood on each prominence is gone: it read as a stray circle.

## Where version 4 stands

Whole song, 960x540, every frame (`--style cosmos --camera <mode> measure`), recall
against the 95th percentile of the same detector where nothing of that kind happened:

|              | first cosmos build (static) | static | cinematic | onset |
|--------------|-----------------------------|--------|-----------|-------|
| kick         | 0.56                        | 0.91   | 0.96      | -37 ms (it swells *into* the hit) |
| clap         | 1.00                        | 1.00   | 0.94      | -17 ms |
| voice        | 0.75                        | 0.84   | 0.87      | -17 ms |
| notes        | 0.54                        | 0.76   | 0.65      | -15 ms |
| bass notes   | 0.03                        | 0.59   | 0.48      | -13 ms |
| hats         | 0.48                        | 0.54   | 0.61      | -15 ms |
| crash        | 0.29                        | 0.29   | 0.31      | +31 ms |

(The first column used the earlier limb and corona detectors, so kick and bass are not
like for like; the others are.)

These were measured *before* the flare and the planets' strikes went in, and those cost
something. On the same 60 seconds (100-160 s, static), before and after: kick 0.96 ->
0.84, clap 0.90 -> 0.82, voice 0.89 -> 0.89, notes 0.78 -> 0.61, bass 0.75 -> 0.56,
hats 0.84 -> 0.61. Part of that is the point - a planet now also answers what the Sun
sends it, so "the planets moved" no longer means "a note was played" - and part is a
corona with more going on in it. The detectors were made robust to the new things
(the limb from the median sector, since a tongue's hot core is the Sun's colour; the
corona measured beyond that limb; the clap's ring looked for from 1.9 radii out), and
the whole-song table has not been re-run since.
Not met: bass at 0.8 (a sixteenth-note bass line at the same pitch re-strikes a tongue
that is already standing); hats and crashes, which coincide with everything else on
the beat; and hits standing six times above the floor in every act - the backbeat's
rings cross the whole system all through the opening and closing acts, and that is
the floor (x2.6-3.2 there, x6-9 in the quiet acts). Nothing answers late but the
crash, whose shooting star takes two frames to grow.

4.7 ms a frame at 1080p and 7.7 at 1440p on the M4: a quarter to a half of the budget.

## ...and the colours stopped changing

Version 4 began with the song's palette "living in the light": the planets their own
colours, the corona, ripples and rings the section's. Seen for long enough, a green
corona is not the solar system. The decision was reversed: in this style nothing
changes colour with the song - a warm Sun in a warm corona, light that is gold going to
white, shadow and sky the deep blue of space. The song animates; it does not repaint.
(`decide`'s palettes are still baked, and the other styles still use them.) A tongue's
hot core became the limb's own tone running on from the limb, because as a paler patch
it sat apart from the Sun it was meant to be part of; and tongues are blunt, and do not
pile into a spike when the same note is played again and again.

Two more things came out after being watched. The filled pool under a planet, and the
globe flashing most of the way to white on its note, were jarring - a strobe on eight
bodies: the rings are the planet's answer now, and the globe only lifts a little. And
the comet near perihelion, with a fat white wedge and a long blue line, was taken for
a satellite: it is smaller, finer, and both tails fade to nothing along their length.


# Version 4.1: a realism pass

Asked: are the planets really all in one plane? They are not, quite - and nothing in
the picture was: eight circles, evenly stepped, in a flat plane, Neptune 2.7 times as
far out as Mercury (it is 78) and its year 4.5 of Mercury's (it is 685). `orrery.py` is
now the one place the solar system's numbers live, and what is drawn is:

- **The real orbits.** J2000 elements: each planet's oval (Mercury's 0.21 and Mars's
  0.09 are visible), its tilt to the ecliptic (Mercury 7 degrees, Venus 3.4, Saturn
  2.5; Earth none, by definition), and where its perihelion and node point - against
  the real stars, since the star catalogue is in the same frame. Kepler's equation
  runs each one, quicker near the Sun. A trail lies along the oval its planet is on.
- **Three honest compressions.** Distance on a log scale, applied to the instantaneous
  distance: the true *pattern* survives - four close in, the wide gap where the
  asteroids are (now at their 2.1-3.3 AU, in three lanes: Kirkwood's gaps), four giants
  spread wide. Years raised to the power that makes Neptune's 12 of Mercury's. Radii
  to the power 0.40: Jupiter four Mercuries across. A power law for distance was tried
  on paper and rejected: the inner orbits end up closer together than the planets are
  wide.
- **Gravity.** A kick is the Sun's mass pulsing. Its pull falls off as the square of
  the distance drawn and it *travels*, so Mercury hops on the beat and Neptune stirs
  most of a second later: the planets answer in turn, outward. It starts from rest
  (the answer's shape is squared), and in a close shot it is scaled to the frame.
- **The conductor.** A discharge of the corona is thrown at the planet that has the
  tune - the one whose note sounded last - in a fan a sixth of a turn wide; that planet
  is struck and rings. As the corona charges, daylight on the planets dims a tenth.
- **Small true things.** Pluto and Charon, 17 degrees off the plane and inside
  Neptune's orbit at perihelion. Jupiter's four moons, Io : Europa : Ganymede going
  round in 1 : 2 : 4 with the phases that keep them from ever lining up. Titan in the
  plane of the rings. The Moon's orbit tipped five degrees. The Sun's equator lapping
  its higher latitudes. The cinematic camera comes down low over the plane in the wide
  acts, where the tilts show.

Not done, and why: the Sun's wobble about the barycentre (over five minutes Jupiter
barely moves, so it would be a fixed offset nobody sees); transits and planet-rise over
the limb (the innermost orbit is deliberately kept clear of the Sun's disc at any
tilt, so that no note is hidden - the two cannot both be had); zodiacal light (a pale
band exactly where the planets are, which was asked to be kept dark).

Cost: 5.5 ms a frame at 1080p, 10 at 1440p (15 worst). The trails' trigonometry runs
only where a pixel could be on that orbit; without that it was 12.7. Jolt: slide 24
%/s, zoom 39, fastest planet 84 (Mercury's hop; the 99th percentile is 18-22, lower
than before). Sync has not been re-measured since the geometry changed.


# Version 4.2: nothing is instant; the planets are bodies; the sky is the real one, with depth

Watched for long enough, three things were wrong. Stars twinkled by jumping 55 % bigger
on a hat (one every 0.12 s) and vanishing in 60 ms: a strobe. A planet threw a ring
every 0.35-0.5 s - Uranus 400 in the song, Earth 2 - each open in a tenth of a second:
too often, too fast to see, and meaningless. And the faint stars were invented.

## Nothing is instant; everything arrives on the beat (`ease.py`)

"Light is instant" is retired. Every channel is baked from a song that is already
known, so a movement can begin *before* its sound and top out *on* it: cubic Bezier
in, cubic Bezier out, flat at both ends and at the top. `ease.envelope` makes the
levels (kick, voice, the hats' three turns, crash, the re-entry's flash and the sky's
opening, the Sun's swell); `ease.advance` makes held events - a clap's ring, a
prominence, a flare, a glint - show up a tenth of a second early with their true time
intact, so the shader sees them coming (`arrive(age, lead, fall)`) and a ring comes up
out of the corona instead of appearing. Where one eased event overtakes another's tail
there is a corner, so levels are softened; softening a skewed shape moves its top a
sample late, which is measured and taken out: a baked level tops out 0.0 ms from its
event. Tests hold: no step, no corner, the top on the event.

## The planets are bodies (`dance.py`)

After the flock on jugalm.com: state that blends, never a switch; temperament; an idle
flock that is never all still. Each planet is a small simulation - how far it leans
toward the Sun or away, how far it has hopped off the plane, its glow, its swell, its
moons' swing (on strings: they lag and overshoot), its spin - springs with mass, driven
by its own notes, by the Sun (a kick's pull, inverse-square, travelling outward; a
flare that strikes it throws it out and makes it ring), and by its neighbours, to which
it is weakly coupled so that a disturbance passes along the system. A note's push is
applied *early* by exactly as long as that body takes to reach the top of its hop:
Jupiter sets off sooner and rises slower than Mercury, and both are at the top on the
note. Left alone for six bars a planet gets restless and does something small on a bar
line, each at its own interval. Pushes are spread over a tenth of a second, so not even
velocity has a corner.

Rings are rare and mean something: a planet's notes charge it, and past a threshold
found from the song the next strong note on the grid throws one - about one per bar
and a half of its playing, never two within a bar (165-400 per planet became about 50),
opening over a second and a half. Notes are shared out so every planet plays (191
each): pitch bands keep their order, low to the giants, and an overfull band trades
its notes with its neighbour, alternately.

Fastest planet across the frame 84 -> 38 %/s; planets' acceleration (99.9th
percentile) 12-38 -> 3.7.

## The real sky, with depth (`sky.build_deep`)

HYG v4.1 (25,791 stars to magnitude 7.5, with distances and constellations) replaces
the Yale catalogue and the invented faint field (which survives only inside the Milky
Way, as its unresolved grain). OpenNGC gives 233 deep-sky objects - everything Messier
listed, anything brighter than magnitude 7, and the famous southern ones - each at its
true place and true angular size, as a flat hard-edged glyph by kind: galaxies (tilted
ovals with a core), open clusters, globulars, nebulae (ragged, hydrogen-pink),
planetary nebulae (rings), supernova remnants (broken shells: the Crab, the Veil). A
test finds Sirius, Alpha Centauri, Betelgeuse, Orion's belt, Andromeda, the Pleiades,
the Orion nebula, the Crab and the Ring where they are, as what they are.

Distance is drawn three ways: a near star is a little larger and crisper, takes its
glints at a fainter magnitude, and *shifts against the far ones as the camera goes
round*. That last is not real - from inside the solar system there is no parallax to
see - and it was chosen knowingly: a third of a degree for the very nearest star. A
constellation's stars take the same turn of the hats, so figures shimmer together.

## What the measuring said, and what it cannot say yet

The Sun-radius detector had been saturated since the corona turned warm (it took the
corona for the Sun): fixed by colour, and the kick reads 1.00 again on the 100-160 s
window, half-way up 41 ms before the sound - as designed, for an 85 ms ease that tops
out on it. Voice 0.74, clap 0.53, crash 0.35. For the busy instruments - bass notes,
planets' notes, hats - recall against "quiet moments" is no longer a meaningful
question: they are continuous motion now, by design, and there are no quiet moments
to compare with. Their timing is held by tests on the baked bodies instead (a hop tops
out within 30 ms of its note). A position-based detector for the dance is the next
measuring job. 6.0 ms a frame at 1080p, 10.0 at 1440p (worst 11.9).


# M0: any song

The piece was directed for one song and read it from constants. It now takes any audio
file or `song` workdir (`track.py`), and one command does everything up to the player,
each step cached under `visuals/cache/<slug>/`:

    python -m visuals make <audio file | song workdir> --theme cosmos
    python -m visuals.pieces.gravity --track <audio | workdir> --style cosmos measure

A lossy file is decoded once into the cache and every step reads that decode, so an
mp3's encoder delay cannot put the stems and the mix on different clocks. The player's
`mix.m4a` is the `song` tool's own recipe. Gravity staged through the new path - the
piece's command line in all three styles, and `make` from the wav and from the workdir -
is **byte-identical** to what it was, and the player's audio sits 0.0 ms from the
analysed samples on all three songs (at 30, 90 and 140 s).

## Two more songs

From what was on disk: *Shattered Voices* (155 s, wav) and *TIDAL CORE* (290 s, mp3).
Demucs took 1:38 and 3:52 on the CPU; the rest of `make` 104 s and 189 s. Neither raised
an exception. That is the finding: nothing failed loudly, and one of the two is wrong
from its first beat.

|                                   | Gravity      | Shattered Voices                  | TIDAL CORE   |
|-----------------------------------|--------------|-----------------------------------|--------------|
| tempo the grid found              | 125.0004     | **125.39 - it is 90.00**          | 127.9997     |
| sharp hits within 4 ms of it      | 723/866 (0.83) | **40/590 (0.07)**               | 620/627 (0.99) |
| bar-phase votes (kick re-entries) | 8-0-0-0      | 2-2-0-0                           | 8-0-0-0      |
| Beat This!: tempo; downbeats agree | 125.0; 146/150 | 90.9; 16/60                    | 130.4; 148/157 |
| kick band's lag, measured         | 24.4 ms      | 3.7 ms (7 against the true grid)  | 22.6 ms      |
| vocal stem present (2 s windows)  | 0.58         | **0.00 - instrumental**           | 0.83         |
| "syllables" where the voice is absent | 0.02     | **1.00 (299 of 299)**             | 0.04         |
| sections / of them "drive"        | 16 / 7       | 6 / **0**                         | 18 / 8       |
| re-entries, acts, climax at       | 10, 7, 81 %  | 4, 4, 58 %                        | 13, 7, 70 %  |
| jolt peaks, cinematic (slide, zoom, planet) | 0.24, 0.32, 0.47 | 0.23, 0.20, 0.36    | 0.25, 0.34, 0.33 |

Jolt is inside the test's limits on every camera of every song. TIDAL CORE, the same kind
of song as Gravity, comes through clean. Shattered Voices is half-time, 90 BPM, with no
voice, and everything the piece assumed about Gravity is visible in it:

**The grid.** The fit starts from the median gap between strong kicks. This kick doubles
0.21 s apart, so it started near 125 and settled on a lattice 7 % of the hats and claps
agree with - and said so, in a number nobody checks. Seeded with 90.00 the same fit puts
93 % within 4 ms at 1.38 ms rms with no drift: the song is on a machine grid, only the
start was wrong. The fit locks only from within about 0.1 % (seeded with Beat This!'s
90.9 it fails again). A scan of lattice coherence over the hats and claps finds 125.000,
90.000 and 128.000 on the three songs, and seeded from it the fit reproduces Gravity's
and TIDAL CORE's grids exactly; but the octave scores nearly as well (180: 0.93 against
90's 0.96), so the octave has to come from elsewhere - Beat This! has it right on all
three. Event times do not depend on the grid, except through the kick's lag correction,
which is measured against it: here that cost 3 ms, because this kick is a click (7 ms of
lag, against 23-24 for the other two). Everything measured in bars does depend on it:
section ramps, drops, acts, shots arriving on bar lines, flares on the beat, a restless
planet's bar line.

**An absent instrument is not dead, it is noise at full size.** The vocal stem sits a
median 51 dB under the mix and peaks at -30 dBFS - Demucs' leakage. The listener found
299 syllables in it, every one where the stem is silent, and the Sun's voice role moves
in 88 % of the song. Every stem is normalised to its own percentiles and its onsets are
picked against its own loudest rises, so there is no such thing as "not playing".

**"Drive" is four on the floor.** A bar drives when it has three or more strong kicks.
A half-time kick has two: even on the right grid only 17 % of Shattered Voices' bars
qualify, and on the wrong one it has no drive section at all, although its kick plays in
86 % of 2 s windows. Drops also use fixed thresholds (a 1.5 dB jump, 0.12 of floor)
rather than the song's.

**Seen, on the rendered picture.** `measure`, whole song, static camera, recall against
the 95th percentile of the same detector where nothing of that kind happened. Gravity's
column is the first whole-song run since version 4.2:

|                      | Gravity | Shattered Voices | TIDAL CORE |
|----------------------|---------|------------------|------------|
| kick -> the limb     | 1.00    | 0.98             | 1.00       |
| clap -> ring in the plane | 0.76 | **0.16**      | **0.25**   |
| syllable -> heart    | 0.61    | 0.60 (on leakage) | 0.31      |
| crash -> sky         | 0.23    | 0.26             | 0.15       |

The kick is seen on every song, half-way up 41 ms before it, as designed. Bass notes,
planets' notes and hats read 0.05-0.31 everywhere, which says nothing: since version
4.2 they are continuous motion and this measure has no quiet moments to compare with
(the position-based detector is still the open job). Two rows are findings. The heart
answers Shattered Voices' leakage visibly (0.60 of the loud "syllables") - the absent
voice is on screen. And the clap's ring, seen for 0.76 of Gravity's claps, is seen for
0.16 and 0.25 of the new songs'. Every clap above 0.30 throws a ring, and Shattered
Voices' rings are *larger* (median size 0.90 against 0.82) and further apart (0.75 s
against 0.48), yet the detector's triggered response is 0.046 against 0.075. So the
rings are there and are not reading; whether because of what else moves in the plane
or how each song's camera frames it is not found yet.

**What is not a finding.** The baked channels were checked against the range Gravity
drives them through. Nothing that sets a size leaves it; what does is a per-song
constant (the camera's heading), the planets' spin (a clock, and TIDAL CORE is longer),
the moons' share of a planet's notes, and TIDAL CORE's camera tilting 0.06 rad further,
13 % of the time. The corona's charge runs lower on both new songs than on Gravity
(median 0.53 and 0.64 against 0.85).

What each of these asks of M1 - a checked grid with an honest fallback, presence per
stem, casting, form that does not need a kick, and a scorecard - is in
`NEXT-music-video-product.md`.


# M1: any song, measured (in progress)

Decided along the way (2026-09-20): the product is for **rights holders** - artists and
AI-song makers make the video for their own song and take it everywhere the song lives.
Listener-side sync to Spotify, Apple Music or TIDAL is ruled out by their terms (see
`NEXT-music-video-product.md`).

## The test set, and songs with parts taken out

Three real songs are not a test set, and all three are the same kind of song. Without
downloading anything, `testset.py` makes more from songs already separated here, by
leaving stems out of the remix: Gravity with no drums, TIDAL CORE with no drums and no
bass, Shattered Voices with only its synths. What is left is real playing, and the truth
- the grid, the bars - is the whole song's. They found more than the real songs did.

## The grid (`grid.py`)

The lattice's spacing comes from a coarse-to-fine scan of how well the hats and claps
line up; which multiple of it is the beat, from Beat This!; then the least-squares fit,
iterated to a fixed point (three passes stopped 13 us short of it on Gravity). Trusted if
half the sharp hits fall within 4 ms, and - when Beat This! is steady enough to referee -
half its beats agree. Otherwise a tracked grid: Beat This!'s beats less its lateness (the
mode, looked for 60 ms before to 20 ms after its beats), snapped to lag-free attacks where
the snap agrees with the local tempo, bars following its downbeats one by one. Only what
is playing places the grid: presence is judged on 2 s windows before there are bars.

| song | grid | tempo | on the lattice | Beat This! steady / agrees | against the truth |
|---|---|---|---|---|---|
| Gravity | lattice | 125.0004 | 0.83 | 0.98 / 0.96 | - |
| Shattered Voices | lattice | 90.0000 (was 125.39) | 0.93 | 1.00 / 0.99 | - |
| TIDAL CORE | lattice | 127.9997 | 0.99 | 0.92 / 0.93 | - |
| Gravity, no drums | tracked (18 hats left) | 125.0000 | - | 0.96 / - | beats 0.87 within 25 ms (median 7 ms); bars 0.78 |
| TIDAL CORE, no drums or bass | lattice | 127.9996 | 0.60 | 0.59 / 0.33 | beats 1.00 (median 0.4 ms); bars 1.00 |

Forced onto the tracked grid, the three real songs keep 96 / 100 / 91 % of their beats -
Beat This!'s own ceiling - at a 1-2 ms median. Two things were tried and dropped: the
synths' attacks as a lattice (21-48 % within 4 ms; their accents did not find the beat),
and letting an unsteady Beat This! veto (it threw out TIDAL-without-drums' exact lattice
for beats that found 32 % of the truth).

**Every 44.1 kHz song was 0.23 % fast.** `power_env` stepped `sr // 1000` = 44 samples
and called it a millisecond: every event early, 0.65 s by five minutes. Found because the
derived songs are written at the stems' 44.1 kHz and fitted 124.715 where the truth is
125.000 - both songs off by 44/44.1 exactly. The three real songs are 48 kHz. Fixed and
tested at three rates; nothing at 48 kHz changed.

## Presence

Per bar, a stem plays when its energy is within 30 dB of the mix's (measured: parts that
play sit at -25 dB and up; leakage never above -40; -20 would have silenced 3 % of
Gravity's pad bars). Its events are kept a bar either side; its levels keep the whole
song's scale and are shut, over a beat, where it does not play (normalising over sung bars
alone made the voice's floor quiet singing, and moved Gravity's voice in 90 % of frames).
Shattered Voices: all 299 "syllables" were leakage; the voice went dark.

## Casting (`cast.py`)

| part | first choice | stand-ins, in order |
|---|---|---|
| pulse | kick | bass attacks on the beat; the mix's low end on the beat; the beat itself, small |
| ring | snare / clap | the mix's strongest accents on the backbeat, the stronger half |
| stars | hats | the synths' high band; the mix's high band |
| corona | bass notes | the synths' low notes (the lowest third, MIDI 60 and under) |
| planets | the synths' notes | (none yet: no song has lacked them) |
| heart | the voice | the synths' lead line (Jugal's call) |

A first choice needs its stem playing in 15 % of bars (real drums 77-97 %; leakage of
removed drums 3-5 %); a stand-in, events in a fifth of the bars. The heart's lead line is
SwiftF0 on the synths, made into phrases (start at 0.6 confidence, carry on above 0.3,
bridge and drop under 0.25 s): against a sung melody mixed into TIDAL CORE's synths it
finds 78 % of sung frames on the right pitch (60 % raw; a skyline of basic-pitch notes
35-40 %), in phrases a median 2.6 s long. Its notes are its moves of 0.7 semitones and
more, timed by the synths' own attacks, inside phrases.

| song | pulse | ring | stars | corona | heart |
|---|---|---|---|---|---|
| Shattered Voices | kick | snare | hats | bass | **lead synth**, 411 notes |
| Gravity, no drums | **bass on the beat**, 224 | **mix backbeats**, 60 | **synths' highs**, 1901 | bass | voice |
| TIDAL CORE, no drums or bass | **mix low end on the beat**, 108 | **mix backbeats**, 70 | **synths' highs**, 1455 | **synths' low notes**, 1418 | voice |

## Drive

A bar drives at three quarters of what this song's pulse puts in a bar, rounded - 3 for
four on the floor, as it always was, 2 for a half-time kick. Shattered Voices went from
0-8 % of bars driving to 92 %.

## The scorecard (`scorecard.py`)

`visuals make` ends with one screen, and `scorecard.json` beside the bundle: grid, presence,
casting (each part judged by its own channels - a role's list includes channels others
move, so "did any move" never found a dead part), structure, jolt per camera, channels
outside the range Gravity was tuned in; `--render` adds recall of the sparse parts and
frame time at 1080p (one-pixel readback per frame: with `finish()` alone Apple's GL skips
frames nobody reads). Gravity passes; so, with warnings, do the other four.

Gravity and TIDAL CORE are byte-identical through all of it.

## Four more songs, four more breaks

Rise and Glow (130.0002 BPM, 96 % of hits on the lattice), Infinite Fire (124.0001, 98 %)
and the 39 s Untitled Project (100.998, 88 %) came through with every part cast. Getting
there, and getting Shattered Voices' synths alone through, found:

- the stems' alignment was checked on six seconds from a minute in - a 39 s song has none
  (from its middle now, when under 66 s)
- a section under a second gave CLAP nothing to hear (heard whole now)
- 32 leaked "hats" in 155 s made a lattice at 180.2 BPM (a lattice now needs a hit every
  two seconds; real drums give three or four a second)
- a line through Beat This!'s beats, 80 ms apart there, put a beat 235 ms before its
  predecessor (tracked beats only go forward now)
- with no drums Beat This! took eighth notes for the beat - 182 BPM in two, where the
  song is 90 in four - and the scorecard failed the camera and the planets on jolt. A
  tempo prior: at 160 BPM and above the picture follows every other beat, a bar keeping
  its length. The synths alone now pass at 90.5 BPM, with an honest warning that their
  bar lines are a guess (Beat This!'s downbeats split evenly over the four beats).

## The clap's ring is drowned by the heart

On the rendered picture the clap's ring is seen for 0.76 of Gravity's claps, 0.25 of TIDAL
CORE's and 0.16 of Shattered Voices'. Drawn alone, Shattered Voices' ring is seen for 0.84
(Gravity's, over the same length, 0.69): the rings are thrown and read. Each part drawn
alone, the band the ring is looked for in (1.9-3.4 Sun radii, along the plane) is lit at
the baseline 0.023 - except by the voice, 0.068, nearly all of the 0.083 of everything.
The heart's ring stands at 1.55-2.70 radii with the pitch, and its crown strokes off it:
the same band. The more the heart sings, the less the clap is seen (voice in 64 % of
Gravity's bars, 94 % of TIDAL CORE's). Whether that was the picture or only the detector
- a lit-share measure cannot tell a new ring from a standing one - was measured before
anything was decided (Jugal: "measure first").

**It was the detector.** `follow.ring_follow` follows each clap's ring out at the radius
the shader puts it (`R + 0.035 + 0.66 age^0.72`, found frame by frame against a ring drawn
alone - the first version left out the 0.035 and was a steady 0.034 frame heights short,
and rounded the clap to a frame, half a frame being five annuli at birth): the lit share
of the annulus at that radius, 0.05-0.35 s after the clap, less the same annulus just
before it. A standing ring is lit both times and cancels. Shattered Voices, 60-100 s:

| drawn | ring follower | the band detector |
|---|---|---|
| the ring alone | 1.00 (rise +0.86) | 0.84 |
| the heart alone, no rings - the control | 0.11 | 0.11 |
| everything | **1.00** (rise +0.81, threshold 0.05) | 0.04 |

The ring is there for every clap, heart or no heart. The picture is unchanged; `sync`
(and so the scorecard's `--render`) reports the follower for the clap, and the band
detector's figure alongside.

## Open
- Re-entries still use fixed thresholds (1.5 dB, 0.12 of floor); every song so far has
  some, so nothing has yet shown them wrong.
- Gravity-without-drums' tracked grid: 87 % of beats, 78 % of bars.
- Frame time measured 8.3-9.8 ms at 1080p with the machine busy (QuickTime, Chrome);
  version 4.2 recorded 6.0. Inside the budget either way; not a regression (A/B).

# M2: the words (`lyrics.py`, `player/lyrics.js`)

Agreed with Jugal: subtle, elegant, never pulling the eye off the system; "just the right
amount of attention". One line at a time, small (0.03 of the frame's height, 32 px at
1080p), a light face letter-spaced, in warm off-white. No colour and no karaoke bar - the
system keeps its real colours, and so do its words; the song is in how they move. A word
lifts from 0.42 ink to full over the 90 ms before it is sung and peaks on it, then settles
to 0.64, so what has been sung reads a little brighter than what is to come. A line eases
in over 0.35 s, arriving on its first word, and out 0.5 s after its last; lines back to
back dissolve into each other in the middle of the gap, never quicker than 0.16 s.
Instrumental stretches are clean.

**Where.** For each line and each camera, the first of 14 places in the frame that nothing
crosses while the line is up: the Sun out to three radii (its corona can stand out that
far) and each planet out to 2.5 (its rings and moons; four left too few places). Other
things equal, the place the last line used. A line never moves while it is up. On
Gravity, text comes within its margin of a body in 0.0 % of lyric moments on the static
camera, 0.4 % on the hybrid and 2.7 % on the cinematic.

**One definition.** `lyrics.ink` and `lyrics.opacity` say how bright a word and a line are
at a moment; the player's copies are held to them by a test (Node, both sides). The player
sets the words in percentages of the frame and container units, so they are right at any
size. The first version slid each line in from the corner: a CSS transition animating from
where the element was made. Transitions are gone; `seating` fixes a line's place when it
appears, for as long as it is up, whatever the camera does.

Words come from the song tool's timings: Gravity's hand-timed gold (34 lines, 182 words -
the committed gold file lacks a sung chorus line), else the tool's own alignment. The
mp4 has them burned in, as the player sets them (see Export, under the studio).

# The direction sheet (`sheet.py`)

Everything the director decides about a song, in about fifty lines a person - or a small
model, prompted - can read and change: who plays each part (`cast`), the bars where the
floor comes back and how hard (`reentries`), the song cut into acts with a shot each and,
for the close shots, a planet (`acts`), five dials with a range and a meaning (`feel`), and
the words' settings (`lyrics`). What was heard is not in it - that is the song.

**The default sheet is the video.** Baking from the sheet the director writes gives the
same channels, byte for byte, as a bake with no sheet, on all nine songs of the test set;
so everything the video does is in the sheet, and an edit to the sheet is an edit to the
video. Tests hold that an edit changes what it names and little else: a shot moves only
the cinematic camera and only near its act; a re-entry taken out is gone from the
picture; `flares_every_bars` 6 gives a third as many flares. `validate` turns away
anything outside the vocabulary with the reason ("the eclipse shot needs a subject",
"acts must follow on, no gaps or overlaps").

Sheets a person has edited are kept in `visuals/sheets/` (Gravity's and Shattered Voices'
are there); any other song's is written beside its bundle and remade with it.

## Editing by asking (`editor.py`)

A request in words ("close on Saturn during the second chorus") goes to a model on this
machine (Ollama), with the song as a person would describe it - its sections by name, in
bars and minutes, the acts, moments, cast and dials, and what each part of the cast does in
the picture - and comes back as edits from the sheet's five kinds: shot, cast, reentry,
feel, lyrics. The answer is held to a JSON schema in which each kind has exactly its own
fields, all given, and a part can only be given one of its own choices; every edit is then
checked by `validate`, and a refused answer is shown back to the model, with why, once.

`editor_eval` asks 20 requests with known right outcomes - 17 on Gravity, 3 on Shattered
Voices, among them two that cannot be done ("let the drums play the heart", "make the sun
blue") and one that is already so - and a request passes only if the sheet it leads to
does what was asked and changes nothing else. An answer the checker refused fails, even
where the sheet already had what was asked.

| model | one loose shape (first run) | strict shapes | strict, parts described |
|---|---|---|---|
| gpt-oss:20b (13.8 GB) | 0/18 - see below | **20/20**, 6.6 s | **19/20**, 7.7 s |
| qwen3.5:9b (6.6 GB) | 16/18, 13.1 s | 16/20, 12.0 s | 17/20, 10.7 s |
| qwen3:8b (5.2 GB) | 16/18, 34.7 s | 15/20, 4.5 s | 16/20, 4.9 s |

(median seconds a request, the model loaded.) The first run was unfair twice over: gpt-oss
cannot answer with its thinking off - it returns nothing - and was asked that way; and
qwen3:8b ran with another model still in memory. gpt-oss now thinks at its lowest level,
and each model is run alone. With one loose shape for every edit the small models left
fields out (a shot with no shot) and filled in fields of other edits, and qwen3.5 silenced
every part of the cast while giving Saturn a close shot. Their failures now are the same
kind, rarer: an edit nobody asked for ("a two-shot of the Sun and Jupiter" also silences
the planets' rings), or the sheet restated whole. gpt-oss's one miss: asked for the drums
to play the heart, it silenced the heart. **gpt-oss:20b is the default**; the others stay
a `--model` away for a machine with less memory. A cold start adds about 20 s, loading it.

# The studio (`studio.py`, `visuals/studio/`)

    python -m visuals studio "examples/Gravity in Motion.wav" ~/Downloads/"Shattered Voices.wav"
    -> http://127.0.0.1:8777/studio/?track=gravity-in-motion

One screen, laid out as an editing suite is (Jugal: "like DaVinci Resolve ... less text,
more visuals"): the picture, with its own transport and camera switch; an inspector beside
it, in icon tabs (selection, feel, cast, words, changes); the song along the bottom on a
timeline in bars - sections by name, an energy strip (loudness, lit by whether the kick
is in, floating or empty), the shots as clips, the moments the beat comes back as marks as
tall as they are strong, the lines of the words. Nothing scrolls but the panels in it.

**A gesture is an edit the model could have made.** Clicking a shot and picking another,
dragging the line between two shots, dragging a moment, choosing bars across the energy
strip and giving them a shot, moving a dial: each is turned (timeline.js) into edits in
the sheet's vocabulary and applied by the same `editor.apply` the model's answers go
through, so a hand and a model change the video one way, and every change reads back in
words in the list of changes. A request in the ask box comes back as a proposal, drawn
dashed on the timeline, and is applied or discarded. Planets are picked by their own
colours (the shader's tints).

**The loop.** The server keeps each song's listening in memory; an edit is baked and
written over the bundle the player shows, and the player takes it without stopping -
the channels, acts and words read again, the shader and the sky kept. Edit to picture:
1.3-1.4 s on Gravity (2.6-7 s while the model comparison had the machine). The star
textures, 7.5 s of every export, are built once per server. A request to the model: about
7 s, 28 s the first time (loading it). The picture plays at 60 fps inside the page.

Each change is kept in `visuals/sheets/<song>.json` and logged, with who made it - a hand,
or a request and the model's edits - to the song's cache (`edits.jsonl`): what people
change is what the director gets wrong.

Found on the way: the static server's no-cache header was never sent (a second
`end_headers` replaced the first), which is why a browser kept yesterday's player.js.

## Correcting what was heard (sheet version 2: `heard`)

The sheet now holds the few facts about the song a person may need to correct, and the
names its parts go by:

- **The grid**: the beat twice or half as fast as found, the beats in a bar, and where
  bar 1 falls, in beats (`grid.find(fix=...)`). A correction listens to the song again on
  the corrected grid - Beat This! is not run again - and the director makes its shots and
  moments anew on the new bars; the cast, the dials and the words' settings are kept, and
  the sections' names carried across by time. The first time a grid is corrected: 161 s
  on Gravity (bar 1 moved a beat: 65 s listening, 95 s the models), 103-107 s on
  Shattered Voices at twice the tempo (180 BPM, 117 bars). Each corrected grid's
  listening is kept in its own folder in the cache (2.2 MB), so going back is 1-2 s and
  nothing heard is overwritten. A click on every beat, higher on the bar, is the way to
  hear whether a grid is right.
- **Sections by name**: the lyric sheet's, and between them, four bars or more, "Intro",
  "Instrumental n", "Outro"/"End"; a song with no lyrics gets the director's own sections
  (cut where the floor comes back), named by how full they are - Drive, Float, Break - and
  numbered. They change nothing in the picture (a rename is not baked); they are how a
  person, or the model, says where. Renamed, moved, added, unnamed in the studio, or asked
  for ("call this the drop").

Sheets written before (version 1) are given `heard` when they are read, and kept so.

A song from outside the repository is now copied into its cache when first prepared,
and read from there: the studio, started by the desktop app, was not allowed by macOS to
read ~/Downloads, and a correction that listens again failed on it.

## One history

Every change - a hand's, the model's, a correction of the grid - is a step in one history,
kept with the song (it is there when the studio is opened again). A step is described by
comparing the sheets before and after it (`editor.changes`): what kind of thing, where
(bars, a bar, the whole song), what it was, what it is now - so the model's proposal, a
hand's edit and an undo all read the same way, as cards: who (you, or the AI with the
request in quotes), and a line per change. Undo, redo and a click on any step move along
it; a change after an undo drops what was undone.

**The AI knows where you are.** The song map tells the model what is selected, or, with
nothing selected, where the playhead is: "a close shot on Jupiter here" with Instrumental 1
selected gave bars 50-66, all of it (before, told of both selection and playhead, it took
the playhead's single bar); "make this part wide" with the playhead in Chorus 2 changed
the shot it is in, 77-98. Edits that restate what the sheet already has are dropped.

**What made the model slow was not the model.** In the studio, gpt-oss:20b took 19-118 s a
request against ~7 s measured alone. Ollama's log: another workload on the machine (an
image server, with qwen3.5:9b) shared the same Ollama, and each request evicted the other's
model - 20-52 s of every request was loading. The studio now keeps its model loaded for
30 minutes, loads it when it starts, says when it is loading, and has a model picker: a
smaller model answers in seconds when memory is short, and an answer is only ever a
proposal, shown on the timeline, applied or discarded. The prompt has changed since the
comparison (sections, the selection); `editor_eval` is to be run again when the machine
is otherwise quiet.

## The demo (`demo.py`, `render.pack`, `player/bundle.js`)

    python -m visuals make "examples/Gravity in Motion.wav"     (and Shattered Voices)
    python -m visuals demo                                      -> docs/video/, served by GitHub Pages

The player and both songs as a static page: no server, no keys, nothing fetched from
anywhere else. The landing page (docs/index.html) shows a poster of it and puts the page
in a frame only when play is clicked: 0.1 MB for the landing page as it is, against 7.3 MB
in its first 8 s with the frame in the markup (headless Chrome, 10 Mbps).

**The compact form.** Plain float16 halves the frames and is wrong: the clocks and the
times of the last hits (`uKickT`, the moment of the last kick) run to the song's length,
and at 280 s a float16 is 0.25 s coarse, so hits would land up to 0.12 s off, `uBeats` a
quarter of a beat off, and the orbits and the camera's turn would step. So `pack` keeps
each channel as float16 only if that holds it to within 2^-11 (half a float16 step between
1 and 2), and as float32 otherwise; 201 of Gravity's 262 channels are float16. Each channel
is written as a column of byte planes (every value's first byte, then every second...),
which is what lets gzip find the shared high bytes, then the whole is gzipped. The plan
says so: `frames_packing: "planes"`, `frames_dtype` (one per channel), a `.gz` name; the
textures carry the same per texture (the star catalogue stays float32, the Milky Way is
float16). `player/bundle.js` reads either form into the same Float32Array, inflating with
DecompressionStream and converting float16 by hand; the local form is read as it always
was. A test runs the reader under node against numpy.

| Gravity's frames | size |
|---|---|
| float32, as `export` writes them | 35.9 MB |
| float32, gzipped | 14.7 MB |
| float16, gzipped (wrong, above) | 5.1 MB |
| per channel, byte planes, gzipped | **2.9 MB** |

| docs/video/ | frames | sky (2 textures) | plan | audio | all |
|---|---|---|---|---|---|
| Gravity in Motion (4:46) | 2.94 MB | 0.85 MB | 0.10 MB | 4.76 MB | 8.65 MB |
| Shattered Voices (2:35) | 1.59 MB | 0.85 MB | 0.08 MB | 2.61 MB | 5.13 MB |
| the page and its three scripts | | | | | 0.04 MB |
| | | | | | **13.82 MB** |

(Since then the frames are in pieces and the sky is kept once: see "Seen in sync, and a
faster start" at the end.)

The sky is the same for both songs and is shipped twice (0.85 MB); a shared copy would
need the plan to point outside its own folder. Opening the demo fetches 4.0 MB before the
first frame (the plan, the frames, the sky; the audio streams), drawn 0.5 s after the
request from this machine and 4.2 s after it at 10 Mbps. Inflating and unpacking Gravity's
frames takes 43 + 64 ms (node).

Audio seeking needs Range requests: GitHub Pages answers them, `python3 -m http.server`
does not (a seek falls back to 0:00 there), `python -m visuals serve` does.

## Adding a song

    python -m visuals studio        -> every song already listened to, and "Add a song…"

With no songs named, the studio offers every song whose cache has `listen.json`, read from
its copy in the cache (`source.*`, or the decode `audio.wav`), else a file named for it in
`examples/` or the test set, else its song workdir. Each is opened the first time it is
asked for, not at the start: the first in 9.1 s (the star textures are built then), the
next ones in 1.7-3.1 s, so the nine here, all opened at the start, would be about half a
minute of waiting (reckoned from those, not measured). A song
made from its copy does not know the name Demucs gave its stems' folder (the original
file's), so `Track.stems_dir` now also finds that folder by the song's slug.

A song is added from the picker's last choice, or by dropping its audio, and its lyrics
if it has them (a `.txt`), anywhere on the page, the picture too. The audio is kept where
a song given on the command line would be: lossless as `cache/<slug>/source.<ext>`, which
every step reads in place, lossy beside it and decoded once to `audio.wav`; the lyrics as
`workdir/<slug>/lyrics.txt`. A background job (`studio.Jobs`: one at a time, in order,
since the machine cannot separate two songs at once; an export can be another kind) then
does what `make` does, a step at a time so the page can say where it is: separating,
aligning the words, listening, the models, staging, opening. With lyrics, the stems come
first and their vocals are linked into the workdir, so the song tool aligns on them and
does not run Demucs a second time. The page asks `/api/jobs` every 2 s while something is
being made, and not otherwise; the status shows the song, the step and the time; when the
song is ready it joins the picker, and the page that asked for it offers to open it (or
opens it, if nothing is open). Refused, with the reason: a file that is not audio, lyrics
not in a `.txt`, a song already in the studio or already being added, and a recording
whose name is taken in the cache by a different one (its stems would be the other's).

Measured, Rise and Glow (3:16, 38 MB wav, its stems already separated), added with `curl`
to a studio with its cache otherwise empty: the upload 1.1 s; separating 1.6 s (only the
player's mix.m4a to make); listening 47.2 s; the models 25.2 s; staging 3.4 s; opening
0.9 s; 78.4 s in all. Added again from the page, everything kept: 8.5 s from "Add" to the
song open. The alignment step, run as the studio runs it on Gravity's lyrics (into a
scratch workdir): 850 s, all of it the song tool's own passes with its Whisper models on
the CPU; the vocals were linked, not separated again (no `demucs_raw`), and the words
read back as the studio reads them, 33 lines and 177 words. A song never separated adds
Demucs's few minutes; that was not measured here.

## Export (`render.render`, `burn.py`)

    python -m visuals render "examples/Gravity in Motion.wav" --theme cosmos [--camera hybrid] [--no-lyrics]
    -> visuals/out/gravity-in-motion-cosmos/gravity-in-motion-static.mp4

The mp4 is what the player shows: baked from the song's sheet, seen through one of the
three cameras (the camera's channels fed to the camera's uniforms, as the player's variants
do), with the words burned in. In the studio, the download button beside the words' eye
says what will be written and where (the camera and the words as they are on screen, the
whole song), and writes it in the background, one at a time; the status says frames done,
time gone and time left, and then offers the file.

**The words are the player's.** Both set them in Inter Light (SIL OFL, one woff2 in
`player/fonts/` that Pillow reads too), 0.03 of the frame's height, letter-spaced 0.06 em,
rgb(238, 233, 222), under a 0.35 em shadow at 0.55. How bright a word and its line are is
`lyrics.ink` and `lyrics.opacity`, the functions the player's copies are held to. Each word
is drawn once per frame size, four times over and scaled down so it sits to a quarter
pixel, as two masks (its letters, and its letters over their shadow); a frame blends only
the words that are up. Measured against headless Chrome's screenshots of the player at
1920x1080, at 36.4 s, 38.35 s (two lines mid-dissolve) and 128.4 s of the full mp4, and
at five lines in five places of the frame before it: the same line (or two) up, in the same
place, the letters within 0.2 px, the words adding the same light to within 2 %, the
picture under them identical (0.000 levels mean, on all three cameras at 128.4 s). Two things had to be learned from the
screenshots: Chrome puts the baseline on the whole pixel above where the CSS box model
would, with the font's ascent and descent rounded (a 1.4 px drop before), and it draws light
type on a dark ground 0.75 px heavier than its outline (the mp4's words were 26 % dimmer
before the strokes were thickened by that).

Changing the face changed `lyrics.CHAR_W`: Inter Light letter-spaced measures 0.52 of the
font size a character on Gravity's lines (0.47-0.59), Helvetica Neue Light 0.49; it was
0.56, and is now 0.53, a little wide on purpose.

**Measured**, on a machine shared with other work (load average 8 during the full render,
27-41 during the clips): Gravity in Motion, static camera, words in, 1920x1080 at 60 fps,
x264 crf 17: 17,148 frames in 488 s (35 fps), 492 s in all, 273 MB (7.4 Mb/s video, 256k
AAC), moov at the front. A 6 s clip on the quieter machine before it: 46 fps. Thirty
seconds of each camera (2:00-2:30), at load 27: static 90 s (20 fps), hybrid 87 s (21 fps),
cinematic 79 s (23 fps); the words are the same line in the same place on all three there
(the layout puts it bottom left for each). The words cost 0.02 ms a frame with no line up,
3.2 ms with one and 6.4 ms mid-dissolve (at load 38); the full render above was made before
each word's patch was cropped to the pixels it can change by half a level, when a line
cost 10.4 ms, so it would now be a little quicker. From the studio, the whole song on the
hybrid camera without words took 633 s at load 20-40 (the first 20 s preparing: the bake,
the sky's textures, the shader); the progress was there again when the page was reopened,
and the finished file was offered and served (293 MB).

# The MVP (2026-09-26)

What ships, decided with Jugal: one repository, the product called "song", the editor
"song studio"; a static demo of the player alone; export as 1080p60 16:9 with the words
burned in, set in Inter Light; the landing page for both tools. Four tracks were built in
parallel in worktrees and merged: adding a song from the studio (with the job runner),
the export, the demo and the landing page, the install. What the merge added: an export
is a job of the same runner as an import, so the two never run together, and the demo was
built again after the lyric width changed.

Measured on the merged branch, the machine otherwise quiet: 216 tests in 61 s; the CI
selection (`-m "not local"`) 158 in 9 s; Shattered Voices exported from the studio, static
camera, no words, 9,322 frames in 248 s (38 fps), 141 MB; the studio with every prepared
song opened at the start in about 40 s (nine songs); the demo 13.94 MB. Not verified here:
the demo on a real GPU in a browser (the pane was hidden; the studio's player ran at 60 fps
earlier), Safari and Firefox, GitHub Pages' headers for `.gz`, a first install with an empty
pip cache, a fresh import through the merged studio (every prepared song was already open;
the import track verified one, 78 s with the stems there).

Open, and Jugal's to decide: the song tool's aligner, MMS_FA, is CC-BY-NC 4.0, so lyric
alignment is non-commercial as it stands; every other model is MIT or Apache. Not in the
MVP: vertical video, the Canvas loop, per-section feel; `editor_eval` is to be run again on
a quiet machine, the prompt having changed.

## The landing page, and what it asked of the player

The page (docs/index.html) is the video itself, pinned edge to edge, with what is said
about it scrolled over it a screen at a time; each statement directs the picture (its
camera, whether the words show). Jugal: "dramatic, but simple and minimal", then "some
abrupt moments ... no way to pause ... extremely performant". What was abrupt, and what
each became:

- **A change of camera was a cut.** It is a move now (`player.choose(kind, name,
  seconds)`): each camera uniform goes from the camera left to the one taken, eased, by
  the wall's clock; angles the short way round, the zoom by ratio. Static to the close
  shot on Saturn, traced by screenshots: one continuous push-in, the Sun out of the top of
  the frame as Saturn comes to the middle.
- **The words were switched.** They fade (0.6 s).
- **The film jumped back mid-song** (a loop of one minute). It plays to the song's own end
  and begins again from its beginning.
- **Text and dimming came at a threshold.** Where the browser has scroll-driven animations
  they follow the scroll itself (`animation-timeline`), on the compositor; elsewhere the
  classes the script sets do it in eased steps; with no script everything is there.
- **Sound and pause** are eased too (0.26 s down, 0.42 s up). Pause: a button in the bar, a
  click on the picture, the space bar.
- **The player's clock.** `audio.currentTime` moves in steps, and a frame was skipped when
  two fell close together; the time is carried between them by the wall's clock. The frame
  count the player shows is of frames drawn now, not of frames asked for.

For speed: no mask and no blur over the live canvas (its edges go to black under two
strips of its own); only translate, scale and opacity move; the bundle is fetched, inflated
and unpacked in a worker (`bundle-worker.js`, the same functions), about 110 ms taken off
the page's thread; `?adapt=1` gives a machine that cannot keep 60 frames a second fewer
pixels, a step at a time.

Measured in headless Chrome with the machine's GPU (ANGLE Metal, Apple M4; 1440x900 at 2x,
the canvas 1920x1080), five runs: at rest, scrolling through the film, scrolling on to the
end and back at the top, 60 frames a second each, the median frame 16.7 ms, the worst
17.6-17.8 ms, none over 20 ms; the player drawing 60 a second; the picture live 0.40-0.42 s
after the page asks for it. One run of the five, the first, had one frame of 234 ms
scrolling from the film into the studio section (a long task of 323 ms); the studio's
picture is decoded ahead of time since, and it has not come back in the runs after. Not
measured: Safari, Firefox, a phone, the fanless machine once it is hot.

## Seen in sync, and a faster start (2026-09-27)

Two things the page did badly. It claims that everything moves with the music and starts
silent, so most visitors never hear what the picture is moving to. And it took 2.5 s at
20 Mbps to show a moving picture, because everything was fetched one thing after another
and the whole song's frames came before the first of them was drawn.

**What was heard, drawn** (`render.heard`, `player/heard.js`). The plan carries the
moments themselves: every kick, every note of the bass line, every note a planet plays,
every syllable. They are read back out of the baked channels (`uKickT`, `uPromT0..3`,
`uWindT0..3`) and the planets' parts, so they are the moments the picture moves to and
not a second opinion. `heard.js` draws them as four lines running through a line in the
middle, which is now; a mark comes up over its last tenth of a second and is brightest on
its moment. It is under "First, it listens." on the landing page and under the picture in
the demo (`heard on | off`; left out where the window is under 600 px high). The clock is
the player's (`player.time()`), so the strip and the picture cannot disagree. Gravity: 291
kicks, 1580 bass notes, 1555 notes, 416 syllables; 55 KB in the plan, which goes out
gzipped at 46 KB with the rest of it.

**Said once, that it has a sound.** "Best with sound", under the sound control, up as the
next re-entry lands (a kick, if no re-entry is within 14 s), the control swelling with it;
gone after 6 s or when the sound is turned on. Once a page load, and never while the song
is heard, paused or out of view.

**The link's card**: `docs/img/card.jpg`, 1200x630, a frame of the video (static camera,
1:40) under the headline, set in Helvetica Neue. 61 KB.

**The start.** What changed, in the order it mattered:

- The frames are in pieces of 15 s (`render.PIECE_SECONDS`, `frames_files`,
  `frames_piece`). The player is ready with the piece under the moment it starts at, and
  has the rest come after the first picture: from there to the end, then from the
  beginning. A moment whose piece has not come is drawn as the nearest that has, and its
  piece is asked for next and the order goes on from it. The pieces cost 12 % more in all
  (3.31 MB against 2.94 MB for Gravity), which keeping the sky once pays for.
- Everything the first picture needs is asked for at once and is on its way while the
  shader compiles: the plan, the sky and the scripts from the page's head (preload), the
  piece and the song as soon as the plan is read. The files are fetched on the page and
  unpacked in the worker, which is hired before the first file is asked for.
- The audio has its index first (`render.faststart`, and `track.prepare` for songs from
  now on): one request to start a song in its middle, where it was three. Nothing is
  encoded again; the decoded samples are the same (md5).
- The sky is kept once (`docs/video/sky/`, `demo.share`).
- The landing page asks for the player as its own script runs, not at `load`, and looks
  for it every 40 ms, not every 200.

The frames, the sky and the sound are what is deployed, value for value (checked against
`HEAD`'s files). Measured in headless Chrome against a server that gives every response
one shared link of the stated speed and delay, and gzips text as GitHub Pages does; three
runs each, the spread under 0.02 s:

| the landing page, from the request to a moving picture | before | after |
|---|---|---|
| 20 Mbps, 40 ms | 2.50 s, 4.15 MB fetched first | **0.77 s**, 1.51 MB |
| 5 Mbps, 80 ms | 7.95 s, 4.13 MB | **2.61 s**, 1.22 MB |

| docs/video/ | frames | plan | audio | all |
|---|---|---|---|---|
| Gravity in Motion (4:46), 20 pieces, the largest 0.20 MB | 3.31 MB | 0.15 MB | 4.76 MB | 8.22 MB |
| Shattered Voices (2:35), 11 pieces | 1.77 MB | 0.11 MB | 2.61 MB | 4.49 MB |
| the sky, once | | | | 0.85 MB |
| the page, its scripts, the font | | | | 0.18 MB |
| | | | | **13.74 MB** |

Frame pacing is as it was: 60 frames a second at rest, on the strip, scrolling through
the film and past it, the worst frame 17.6-17.8 ms, none over 20 ms, no long task (three
runs); and the same in the 7 s after the picture starts to move, while the other nineteen
pieces arrive. A jump in the demo to 4:10 the moment it opens: its piece came 0.36 s
later at 20 Mbps, and the ones after it next.

What is left of the wait is the sky: 0.85 MB of the 1.5 MB. It could be packed smaller
without changing a value (the Milky Way is a smooth field; its differences would gzip far
better than its values). Not done.

Found on the way: Gravity has no kick from 0:26 to 1:36 but one, and the landing page
starts at 1:01, so the strip's first line is empty for the first half minute, and "the
kick pulls the orbits" is said over a passage with none. `?t=` on the landing page starts
it elsewhere, to try: 1:32 puts the re-entry at 1:36, the song's strongest after its
first, four seconds after the page opens.

Jugal took the later start: the page opens at 1:32. The Sun is larger there (the kick is
in), so the picture sits lower in the hero (21 % of the height under the middle, 28 % in
a window wider than 19:10), and the headline is sized by the window's height as well as
its width; the Sun is clear of the two links at 1440x900, 977x758, 1440x700, 1920x1000
and 390x844, as the re-entry lands. The play button of a browser that will not start the
video unasked was in the middle, over the links; it is at the foot of the picture, where
the cue to scroll is, and clear of what is said by 29 px or more at those sizes, in the
hero and on each statement. Not changed: in a window wider than about 2:1 the picture is
narrower than the window and its sides show.

A browser holding the old `player.js` and fetching the new plan fails (it has no
`frames_file`); GitHub Pages keeps files for ten minutes, so that is a visitor who was
there in the ten minutes before a deploy. Not measured: Safari, Firefox, a phone.

## The demo page, again (2026-09-27)

Jugal, of the demo page as it was deployed: "this ui doesn't look great, it needs to be
way more polished". It was the player's own controls, as made for working: a button that
said "pause", a time to the tenth of a second, the browser's slider in orange, four rows of
labelled pills. The page has its own now (`player/demo.html`), over `window.player`, and
the player's are kept out of sight (`#own`):

- a bar as wide as the picture: the name, the songs, "Make your own";
- the picture; what was heard; the song's length as a hair of a line, filled as far as it
  has come, its handle there when reached for;
- one row: play and the time (a click copies a link to the moment, and says so), the three
  cameras as one control whose light slides to the one taken, and three icons: the words,
  what was heard, full screen (`f`; left out where the browser has it only for video).

The landing page's colours and its ease, black under everything, nothing orange but the
mark. It fits the window at 1440x900, 1920x1080, 1000x574 and 390x844 (no scroll in any),
and each control was pressed and read back in each. 60 frames a second while it plays and
through a change of camera, the worst frame 17.7-17.8 ms, in eight runs of nine; one run
had five frames over 20 ms (the worst 33.7 ms), which did not come back and whose cause is
not known. Not looked at: Safari, Firefox, a phone in the hand.

# The tall frame (2026-09-27)

A video for a telephone held upright: 9:16, 1080 by 1920. Jugal chose how (of three, shown
as stills of three moments beside the wide frame) and what first: the quarter turn; the
words kept clear of what the apps lay over a tall video; the mp4 and the studio first, the
site's own pages on a telephone after.

**What was tried.** The wide picture is wide because the system is: the plane is seen
tipped, so it is an oval lying down.

| | what it is | what the stills showed |
|---|---|---|
| quarter turn | the camera rolled 90 degrees about its line of sight, 16/9 as far off | all of every shot in the frame: the row of planets runs down it, the two-shots hold |
| level, the same distance | the wide frame's middle | the row and the two-shots cut at the sides |
| level, 1.7 times as far off | | the row still cut, and everything small |

**What it is** (`cosmos.turned`). The tall frame's camera is the wide frame's: `uCamRoll`
a quarter turn on, `uCamSpan` times 16/9, `uCamX, uCamY` become `uCamY, -uCamX`. A point
at (x, y) of the wide frame, in its heights, is at (9/16 y, -9/16 x) of the tall one: the
wide frame's width is the tall frame's height. So nothing is decided twice and nothing is
baked for it: the renderer (`Renderer.bind(..., shape)`), the geometry (`follow.geometry`)
and the player (`player.setShape`, `?shape=tall`) turn whichever camera is chosen, moves
between cameras included. The bundle is the same bundle.

Two things in the shader were sized by the camera's distance: the planets' dance (a lean
or a hop is scaled down in a close shot, to be the same movement on screen) and the sky's
lens. With the camera 16/9 as far off they came out another size, and the planets stood up
to 0.006 of the frame's height from where the wide frame has them. The shader takes
`uTall` now, and sizes both by the wide frame's distance. Measured, drawn at 540 by 960
against the wide frame at 960 by 540 turned, five moments over the three cameras: of the
pixels on and beside the bodies, none more than 24 of 255 apart; of the sky's, 1.0 %, its
stars being sized in pixels. The wide picture with the shader as it was deployed and as it
is: not a pixel different, four moments. A frame's time, 1080p, read back: 7.97 ms before,
7.96 after, 8.09 tall (the best of three rounds; the fanless machine, once warm, gives 17
to 18 ms for any of them, so only the best are compared). In the player, 1080 by 1920
drawn: 60 frames a second, the worst frame 17.6 to 17.8 ms, none over 20 ms, four runs.

**The words** (`lyrics.TALL`, `lyrics.wrapped`). Smaller, 0.022 of the height (42 px of
1920; the sheet's size, times 0.733), in the middle of the width, in two rows where a line
is longer than there is room for (15 of Gravity's 34), rows of a length. Kept inside what
the apps leave clear: an eighth of the height at the top, a fifth at the foot, an eighth
of the width at each side. Those are their published advice as remembered; they were not
looked up or measured. A line that dissolves out of the one before it is in its place or
clear of it (two lines 3 % apart in height overlapped, the first time).

The wide frame's rule, that a line comes no nearer a body than its corona or its rings
reach, cannot be kept: there is no sky beside the system in a frame this narrow. By that
rule a line is near a body in 25 to 38 % of its frames on Gravity, from 6 places or from 21,
in one row or two. So in the tall frame a line keeps off the bodies themselves first (the
Sun's corona as it stands, 1.7 radii; a planet and its rings, 1.3), and as far from them
as the wide rule asks where it can, choosing among 21 heights:

| Gravity, of the frames a line is up | static | hybrid | cinematic |
|---|---|---|---|
| wide: within a body's reach | 0.0 % | 0.1 % | 2.6 % |
| tall: on or against a body | 2.9 % | 2.8 % | 5.8 % |
| tall: within the wide frame's reach of one | 36.3 % | 24.9 % | 37.9 % |
| changes of place, wide / tall | 5 / 11 | 10 / 17 | 11 / 14 |

The target, none, is not met, and the tall frame is worse than the wide by this measure:
it is worst in the planets' row, where the frame is full from top to bottom. The words are
over orbits and beside bodies there, with their shadow under them.

**The mp4** (`render.render(..., shape="tall")`, `--tall`, the studio's frame control).
1080 by 1920, 60 frames a second, the words burned in by rows (`burn.Words`); named
`<song>-<camera>-tall.mp4`. A clip of 20 s from 3:42, cinematic, was rendered and looked
at: 1200 frames in 34 s. A whole song was not.

**The studio.** Two frames beside the cameras, wide and tall; the choice is kept from one
visit to the next, and the export is of the frame shown and says so before it starts.

Not done: the site's pages on a telephone (the demo page takes `?shape=tall`, and nothing
offers it); the loop for Spotify's Canvas. Not looked at: Safari, Firefox, a telephone in
the hand; a tall video inside any of the apps it is for.

# A loop for Spotify's Canvas (2026-09-27, `loop.py`)

    python -m visuals render <song> --theme cosmos --canvas [--camera ...]
    the studio: Export, "Canvas loop"

What Spotify asks, read on its own pages that day (support.spotify.com/us/artists/article/
canvas-guidelines): "3-8 seconds long, Vertical 9:16 ratio, Between 720px - 1080px tall, An
MP4 or JPG file"; no talking or singing to camera, no rapid cuts or intense flashing, the
song's and the artist's names better left out; "the edges may get cut off on some phones".
It gives no limit on the file's size. A Canvas is the app's to start and is not in step
with the song, so the loop is the picture for its own sake, and has no words.

"720px - 1080px tall" read to the letter is a frame at most 608 by 1080. It is taken here
to mean 720p to 1080p, and the loop is 1080 by 1920, which is what is commonly sent. That
is a reading, not a thing tried: no loop has been given to Spotify.

**Which bars.** Whole bars, as many as fit in eight seconds (four of Gravity's, 7.68 s;
of a bar longer than eight seconds, as many of its beats), starting on a bar line, where
the most is played: the kicks, the bass line's notes and the planets' notes of
`render.heard`, by their sizes. Not bars a re-entry falls in or just before (its flash,
every few seconds, is what Spotify asks not to be sent), and not bars in which the camera
chosen is on its way somewhere (its distance changing by more than 5 %). Gravity: static,
bar 140, 4:28; hybrid and cinematic, bar 106, 3:23, the last bars being their pull back.

**How it runs round.** The picture is drawn from the channels and from the time, and the
shader asks the time only how long ago a hit was. So the channels are made to come back:
a level or a clock loses over the loop what it gained in it, a little each frame (a level
at a bar line had gained next to nothing; a clock had gained its run, and stands: the
planets keep their places on their orbits for these seconds, and dance there); a slot's
hits are the loop's own, its first frames holding its last hit a loop's length ago; a slot
with no hit in the loop holds none. The loop is a whole number of frames, 461 for 7.68 s.
What was not done, and why: joining the song's own bars end to beginning (the clocks have
moved on: the join is five times a usual step between frames), a dissolve over the join (a
planet that has moved is two planets for as long as it lasts), playing it forward and then
back (Spotify's "rebound": a ring thrown would be a ring drawn in).

Measured on the mp4s, 1080 by 1920, read back at 270 by 480: the mean change of a pixel
across the join against the median from one frame to the next in the loop.

| Gravity | across the join | a usual step | the largest step | the join, in usual steps |
|---|---|---|---|---|
| static | 1.28 | 1.20 | 2.44 | 1.07 |
| hybrid | 1.42 | 1.15 | 2.79 | 1.24 |
| cinematic | 1.65 | 1.14 | 2.94 | 1.45 |
| the song's own bars, static, not looped | 12.3 | 2.40 | 4.09 | 5.13 |

And no part of the picture changes more across the join than parts do between frames: the
most any 24-pixel block changes is 21 across it, against a median of 40 elsewhere. Each
is 461 frames, 7.683 s, h264 with no sound, 5.9 to 9.5 MB; the studio writes one in 11 s.

The bars can be chosen: the studio's Export offers "Liveliest bars" or "From the
playhead", the bar the playhead is in (`loop.window(..., at=)`, `--canvas START`); what
falls in bars asked for, a re-entry or a camera on its way, is in the loop. Not tried:
sending one to Spotify; how it looks under the app's own controls.

# The site on a telephone (2026-09-27)

Held upright, the landing page was the wide picture as a strip across the screen, a
quarter of its height, with what is said under it. It is the tall picture now, filling
the screen (`?shape=tall`, asked for where the window is taller than it is wide, and
changed with `player.setShape` if the telephone is turned): as wide as the screen or, on
a screen narrower than 9:16, as high, its sides a little outside it, where the tall frame
keeps nothing. What is said is over it, as on a wide screen, the picture dimmed under the
three statements. The Sun is seated under the headline and its two links, which are a
height in pixels, so lower on a short screen. The poster is a tall one
(`img/cosmos-still-tall.webp`, 29 KB), preloaded by the window's shape.

The demo page has the tall frame too: on a screen held upright unless the address says
(`?shape=`), and from a control beside the full screen on any screen. Its controls keep
the wide picture's width; on a telephone the caption gives its room to the picture.

Looked at, at the moment the re-entry lands and with the video not started: 390x844,
360x640, 430x932, 820x1180 upright, and 1440x900 as before. The play button of a browser
that will not start it is clear of what is said by 91 px or more at each. The demo fits
390x844 without a scroll (it was 5 px over, the first time). Frame pacing at 390x844, the
canvas 1080 by 1920, in headless Chrome on this machine's GPU, which is not a
telephone's: 60 frames a second, the worst 17.5 to 17.8 ms, in four runs of five; in one,
its first seconds had 8 frames over 20 ms (the worst 34 ms) and the player drew 54 that
second. Not looked at: a telephone.

Jugal, on his telephone, the day it went out: "the full screen button doesn't work". Two
faults. The page hid the button where the browser has no full screen but for a video (a
telephone's Safari), by its `hidden` attribute, and the button's own `display: grid`
undid that: it was shown and did nothing. And nothing was offered in its place. Now
`[hidden]` hides whatever else is said, and where the browser has no full screen, or
refuses it, the picture is laid over the whole page (`body.filled`) with a way out at
its corner. Pressed and read back in headless Chrome at 390x844 with the browser's full
screen taken away, with it, and at 1440x900: the picture goes from 281 by 500 to 390 by
693 and back, the song playing on. Not on a telephone.

The demo had a control for the tall frame, beside the full screen. Jugal: "what's the
point of it?" It was for seeing the tall video on a wide screen, it did nothing worth
having on a telephone, and it had not been asked for. It is gone: the demo's frame is the
screen's, and the address no longer keeps it (a link made on a telephone opened tall on a
desk). `?shape=` still says which, for a link that means to.

