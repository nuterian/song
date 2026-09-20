# Gravity in Motion — a piece

One song, directed by hand from measurements, outside the typed score. The grammar
and the slot schema exist so a model can direct any song; this is the other thing —
a single track taken as far as it will go, so there is a gold example of what
"follows the song" means when nothing is holding it back.

```
.venv/bin/python -m demucs -n htdemucs -d cpu \
    -o visuals/cache/gravity-in-motion/demucs_raw "examples/Gravity in Motion.wav"   # once, root venv
visuals/.venv/bin/python -m visuals.pieces.gravity listen     # stems -> events and streams
visuals/.venv/bin/python -m visuals.pieces.gravity render     # 1080p60 mp4 + the player's files
visuals/.venv/bin/python -m visuals.pieces.gravity measure    # decode the mp4, check it against the audio
visuals/.venv/bin/python -m visuals.pieces.gravity matrix     # solo each instrument: what does it move?
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
