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
mp4 burn-in waits for Jugal's look at them in the player.

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
