# Frozen versions

A tag keeps the recipe; these keep the dish. Each archive is a staged player bundle -
`plan.json` (which holds the exact GLSL that drew it) and `frames.bin` (every baked
channel, 120 Hz, float32) - so the version plays again even if the listening, the
models or the direction that produced it have since changed.

    mkdir -p visuals/out/frozen-v3 && tar -xzf visuals/pieces/gravity/snapshots/v3-cel-2026-09-20.tgz -C visuals/out/frozen-v3
    ln -s "$PWD/workdir/gravity-in-motion/mix.m4a" visuals/out/frozen-v3/mix.m4a
    python -m visuals serve      # then  player/?track=frozen-v3

| archive | tag | what it is |
| --- | --- | --- |
| `v3-cel-2026-09-20.tgz` | `piece-v3-cel` | the clean cel-shaded solar system: flat-toned sun with the voice as its heart, planets with real phases, belts, a comet, shooting stars, a real-looking sky. The version Jugal called brilliant and asked to have kept. |
