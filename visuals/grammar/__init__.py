"""The vocabulary: GLSL blocks, and the rule for assembling a score into a shader.

This is grammar v0. It has the shape the real thing will have - typed blocks,
composed under legality rules, compiling to one fragment shader with a bounded
per-frame cost - but the blocks are hand-written and selected by a switch rather
than being nodes in a graph whose input and output types decide what may plug
into what. Milestone 3 is the version with fifteen to twenty blocks and legality
derived from their types instead of from a table.
"""

from .compose import GL_HEADER, WEBGL_HEADER, fragment_source, program_key, vertex_source

__all__ = [
    "GL_HEADER",
    "WEBGL_HEADER",
    "fragment_source",
    "program_key",
    "vertex_source",
]
