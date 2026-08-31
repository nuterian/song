"""Parse an unstructured lyrics .txt into sections and singable lines.

Handles the shapes AI song tools emit:
    [Verse 1]
    Verse 1 (8 bars, pulsing bass + filtered synth pad)
    Chorus:
    (Bridge)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

SECTION_WORDS = (
    "intro",
    "verse",
    "pre-chorus",
    "prechorus",
    "pre chorus",
    "chorus",
    "post-chorus",
    "postchorus",
    "hook",
    "refrain",
    "bridge",
    "breakdown",
    "drop",
    "interlude",
    "instrumental",
    "solo",
    "outro",
    "ending",
    "coda",
    "final chorus",
    "last chorus",
)

# "Verse 1 (8 bars, ...)" / "Pre-Chorus" / "Final Chorus (16 bars...)"
_HEADER_RE = re.compile(
    r"""^\s*
        [\[\(]?                              # optional opening bracket
        (?P<name>(?:final|last|second|third|repeat)?\s*
                 [A-Za-z][A-Za-z\-\ ]{0,20}?  # the section word(s)
                 (?:\s*\d+)?                  # optional number: "Verse 2"
        )
        [\]\)]?                              # optional closing bracket
        \s*
        (?:[:\-–]\s*)?                       # optional separator
        (?:\((?P<note>[^)]*)\))?             # optional production note
        \s*$
    """,
    re.VERBOSE,
)

# Sections that are, by definition, not sung.
NON_VOCAL = ("instrumental", "solo", "interlude", "drop", "breakdown")


@dataclass
class Section:
    index: int
    name: str
    note: str = ""
    raw: str = ""
    line_indices: list[int] = field(default_factory=list)

    @property
    def is_vocal_hint(self) -> bool:
        """False when the header names a section that usually has no vocal."""
        low = self.name.lower()
        return not any(w in low for w in NON_VOCAL)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "note": self.note,
            "raw": self.raw,
            "line_indices": list(self.line_indices),
        }


@dataclass
class Line:
    index: int
    section: int
    text: str
    words: list[str]

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "section": self.section,
            "text": self.text,
            "words": list(self.words),
        }


@dataclass
class Lyrics:
    sections: list[Section]
    lines: list[Line]

    @property
    def plain_text(self) -> str:
        """Sung lines only, one per line - what the aligners consume."""
        return "\n".join(line.text for line in self.lines)

    def section_of(self, line_index: int) -> Section:
        return self.sections[self.lines[line_index].section]


def normalize_text(text: str) -> str:
    """Fold smart quotes/dashes to ASCII so aligners tokenize predictably."""
    text = unicodedata.normalize("NFKC", text)
    for src, dst in (
        ("’", "'"),
        ("‘", "'"),
        ("“", '"'),
        ("”", '"'),
        ("–", "-"),
        ("—", "-"),
        ("…", "..."),
    ):
        text = text.replace(src, dst)
    return text


def tokenize(text: str) -> list[str]:
    """Words as an aligner sees them: apostrophes kept, other punctuation dropped."""
    cleaned = re.sub(r"[^\w'\s-]", " ", normalize_text(text))
    return [w for w in cleaned.split() if any(c.isalnum() for c in w)]


def _looks_like_header(raw: str) -> tuple[str, str] | None:
    """Return (name, note) when the line is a section header, else None."""
    stripped = raw.strip()
    if not stripped:
        return None

    match = _HEADER_RE.match(stripped)
    if not match:
        return None

    name = " ".join(match.group("name").split())
    note = (match.group("note") or "").strip()
    probe = name.lower().rstrip("0123456789 ").strip()

    # Require an actual section word so ordinary short lyric lines
    # ("Still in motion") are not mistaken for headers.
    if not any(probe == w or probe.endswith(w) or probe.startswith(w) for w in SECTION_WORDS):
        return None

    # A bracketed header is unambiguous; a bare one must not end in
    # sentence punctuation, which would make it a lyric.
    bracketed = stripped[0] in "[("
    if not bracketed and stripped.rstrip()[-1] in ",.;!?":
        return None

    return name, note


def parse(text: str) -> Lyrics:
    sections: list[Section] = []
    lines: list[Line] = []

    def ensure_section() -> Section:
        if not sections:
            sections.append(Section(index=0, name="Lyrics", raw=""))
        return sections[-1]

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue

        header = _looks_like_header(stripped)
        if header is not None:
            name, note = header
            sections.append(
                Section(index=len(sections), name=name, note=note, raw=stripped)
            )
            continue

        section = ensure_section()
        words = tokenize(stripped)
        if not words:
            continue

        line = Line(
            index=len(lines),
            section=section.index,
            text=normalize_text(stripped),
            words=words,
        )
        section.line_indices.append(line.index)
        lines.append(line)

    # Headers with no lyrics under them (e.g. a trailing "[Instrumental]")
    # would break index assumptions downstream; drop them.
    kept = [s for s in sections if s.line_indices]
    remap = {s.index: i for i, s in enumerate(kept)}
    for new_index, section in enumerate(kept):
        section.index = new_index
    for line in lines:
        line.section = remap[line.section]

    return Lyrics(sections=kept, lines=lines)


def parse_file(path) -> Lyrics:
    from pathlib import Path

    return parse(Path(path).read_text(encoding="utf-8"))
