"""visuals - music-synchronised shader visuals, generated locally.

A song workdir goes in; an mp4 and a browser page come out, both driven by the
same score and the same baked uniforms. The score is typed data, which is what
lets a small model fill it in later without ever writing a line of GLSL.

    python -m visuals render <song-workdir> [--preview START] [--seed N]

See DESIGN.md for the whole design and the milestone it is on.
"""

__all__ = ["authoring", "export", "grammar", "listen", "render", "schema", "uniforms"]
