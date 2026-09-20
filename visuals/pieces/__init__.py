"""Pieces: one song, directed by hand from measurements, outside the typed score.

The grammar and the slot schema exist so that a model can direct any song. A piece
is the other thing - a single track taken as far as it will go, with as many
parallel streams as the arrangement actually has, so that there is a gold example
of what "follows the song" means when nothing is holding it back.

A piece reuses the runtime (headless GL, the baked 120 Hz grid, the player's
plan.json + frames.bin) and nothing of the schema.
"""
