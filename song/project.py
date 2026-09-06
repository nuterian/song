"""The project state: timed lines + words, persisted as project.json.

This is the single source of truth shared by the aligners, the scorer, the
exporters and the UI.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .parse_lyrics import Lyrics, Section

SCHEMA_VERSION = 1


def slugify(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[-\s]+", "-", name) or "track"


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float = 1.0
    # Where the word's syllables begin, as fractions of its span:
    # [{"text": "gra", "at": 0.0}, {"text": "vi", "at": 0.31}, {"text": "ty", "at": 0.6}].
    # They come from the character-level aligner (ctc.py) and are fractions on
    # purpose: a word dragged in the UI carries its syllables with it, retime()
    # needs no second pass, and there is still exactly one representation of
    # where a word is - its two bounds. Empty when unknown; a one-syllable word
    # needs none.
    syllables: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "prob": round(self.prob, 4),
        }
        if self.syllables:
            d["syllables"] = [
                {"text": s["text"], "at": round(float(s["at"]), 3)} for s in self.syllables
            ]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Word":
        return cls(
            text=d["text"],
            start=float(d["start"]),
            end=float(d["end"]),
            prob=float(d.get("prob", 1.0)),
            syllables=_clean_syllables(d.get("syllables")),
        )

    def syllable_spans(self) -> list[tuple[str, float, float]]:
        """(text, start, end) per syllable on the track timeline.

        The first syllable starts where the word does whatever its fraction
        says, the last ends where the word ends, and each ends where the next
        begins - the same tiling the karaoke sweep draws.
        """
        if len(self.syllables) < 2:
            return [(self.text, self.start, self.end)]
        span = self.end - self.start
        starts = [self.start + float(s["at"]) * span for s in self.syllables]
        starts[0] = self.start
        ends = starts[1:] + [self.end]
        return [(s["text"], a, b) for s, a, b in zip(self.syllables, starts, ends)]


def _clean_syllables(raw) -> list[dict]:
    """Syllables as saved, or nothing if they are not the shape they must be.

    Fractions must start at 0, rise, and stay below 1; anything else is a
    file written by something that did not understand them, and an empty list
    (one sweep for the word) is the safe reading of it.
    """
    if not isinstance(raw, list) or len(raw) < 2:
        return []
    out = []
    previous = -1.0
    for item in raw:
        try:
            text, at = str(item["text"]), float(item["at"])
        except (KeyError, TypeError, ValueError):
            return []
        if not text or at <= previous or not 0.0 <= at < 1.0:
            return []
        out.append({"text": text, "at": at})
        previous = at
    if out[0]["at"] != 0.0:
        return []
    return out


@dataclass
class TimedLine:
    index: int
    section: int
    text: str
    start: float = 0.0
    end: float = 0.0
    words: list[Word] = field(default_factory=list)
    source: str = "unaligned"
    locked: bool = False
    flagged: bool = False
    score: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def normalize_words(self) -> None:
        """Order the word spans inside the line, without closing the gaps.

        A word ends where the singer stops, not where the next word starts:
        lines hold rests in the middle of them, and both aligners measure one.
        So the invariant is an ordering, not a tiling::

            line.start == w[0].start <= w[0].end <= w[1].start <= ...
            ... <= w[-1].end == line.end

        This used to flatten every end onto the next start, because enhanced
        LRC carries one timestamp per word and cannot encode a rest. That is a
        limit on one export, and enforcing it here imposed it on everything -
        including the karaoke renderer, which has always had a branch for a
        held rest (see video/karaoke.py) that could never fire. On the sample
        track it stretched one outro word across 10.6 s of silence.

        An end that carries no information - zero-length, or before its own
        start, which is what a degenerate aligner emits - still falls back to
        the next word's start, since that is the only other thing known about
        where the word stops. A *measured* end is now believed.
        """
        if not self.words or self.end <= self.start:
            return
        # Word 0's start *is* the line start - the UI has always enforced this
        # and every export assumes it, but this side only clamped it upwards,
        # so a project could round-trip with the word LRC starting later than
        # the line LRC and the UI quietly disagreeing with the file on disk.
        self.words[0].start = self.start
        previous = self.start
        for w in self.words:
            w.start = min(max(w.start, previous), self.end)
            previous = w.start
        # Ends come second, so each one can be held to the next word's start -
        # which is now a ceiling rather than an assignment.
        for w, nxt in zip(self.words, self.words[1:]):
            w.end = nxt.start if w.end <= w.start else min(w.end, nxt.start)
        # The line's span is exactly its sung extent, so the last word closes
        # it. Every aligner already reports the line end as that word's end.
        self.words[-1].end = self.end

    def retime(self, start: float, end: float) -> None:
        """Move the line, rescaling word timings proportionally into the new span.

        Line-level edits are what the UI exposes; words ride along so the
        word-level exports stay coherent without word-by-word editing. Rests
        between words scale with everything else rather than being closed up.
        """
        start = max(0.0, float(start))
        end = max(start + 0.05, float(end))

        old_start, old_end = self.start, self.end
        old_span = old_end - old_start

        if self.words and old_span > 1e-6:
            scale = (end - start) / old_span
            for w in self.words:
                w.start = start + (w.start - old_start) * scale
                w.end = start + (w.end - old_start) * scale
        elif self.words:
            # Degenerate previous span: distribute words evenly.
            step = (end - start) / len(self.words)
            for i, w in enumerate(self.words):
                w.start = start + i * step
                w.end = start + (i + 1) * step

        self.start, self.end = start, end
        self.normalize_words()

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "section": self.section,
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "words": [w.to_dict() for w in self.words],
            "source": self.source,
            "locked": self.locked,
            "flagged": self.flagged,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TimedLine":
        line = cls(
            index=int(d["index"]),
            section=int(d["section"]),
            text=d["text"],
            start=float(d.get("start", 0.0)),
            end=float(d.get("end", 0.0)),
            words=[Word.from_dict(w) for w in d.get("words", [])],
            source=d.get("source", "unaligned"),
            locked=bool(d.get("locked", False)),
            flagged=bool(d.get("flagged", False)),
            score=d.get("score", {}),
        )
        line.normalize_words()
        return line


@dataclass
class Project:
    audio_path: str
    lyrics_path: str
    duration: float
    sections: list[Section]
    lines: list[TimedLine]
    workdir: str = ""
    stem_path: str = ""
    scorecard: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    # ---------- construction ----------

    @classmethod
    def from_lyrics(
        cls,
        lyrics: Lyrics,
        audio_path: Path | str,
        lyrics_path: Path | str,
        duration: float,
        workdir: Path | str = "",
    ) -> "Project":
        lines = [
            TimedLine(index=ln.index, section=ln.section, text=ln.text)
            for ln in lyrics.lines
        ]
        return cls(
            audio_path=str(audio_path),
            lyrics_path=str(lyrics_path),
            duration=duration,
            sections=lyrics.sections,
            lines=lines,
            workdir=str(workdir),
        )

    # ---------- helpers ----------

    def section_lines(self, section_index: int) -> list[TimedLine]:
        return [ln for ln in self.lines if ln.section == section_index]

    def aligned_lines(self) -> list[TimedLine]:
        return [ln for ln in self.lines if ln.end > ln.start]

    def insert_line(self, after_index: int, line: TimedLine) -> TimedLine:
        """Insert a line after `after_index`, renumbering everything downstream.

        Line index *is* position here - the UI keys its review queue, its todo
        marks and its undo snapshots off it - so an insertion has to renumber
        the tail, rebuild the sections' membership lists and shift every
        index-keyed table in `meta` in one go, or those things quietly start
        pointing at the wrong lyrics.
        """
        at = max(0, min(len(self.lines), after_index + 1))
        self.lines.insert(at, line)
        for i, ln in enumerate(self.lines):
            ln.index = i
        members: dict[int, list[int]] = {}
        for ln in self.lines:
            members.setdefault(ln.section, []).append(ln.index)
        for section in self.sections:
            section.line_indices = members.get(section.index, [])
        self._shift_meta(at)
        return line

    def _shift_meta(self, at: int) -> None:
        """Renumber the index-keyed evidence in `meta` to match an insertion.

        Both aligners' raw spans, the round-trip's per-line observations and
        the audit's queue, proposals and repairs are stored by line index.
        Leaving them behind after an insertion does not fail loudly - it
        silently scores every line after the new one against its neighbour's
        evidence, which reads as the whole back half of the song having come
        loose. Found exactly that way.
        """
        def shift(i: int) -> int:
            return i + 1 if i >= at else i

        def renumber(table: dict) -> dict:
            out = {}
            for key, value in table.items():
                try:
                    i = int(key)
                except (TypeError, ValueError):
                    out[key] = value
                    continue
                out[str(shift(i))] = value
            return out

        aligners = self.meta.get("aligners")
        if isinstance(aligners, dict):
            for name, table in aligners.items():
                if isinstance(table, dict):
                    aligners[name] = renumber(table)

        rt = self.meta.get("roundtrip")
        if isinstance(rt, dict) and isinstance(rt.get("per_line"), dict):
            rt["per_line"] = renumber(rt["per_line"])

        audit = self.meta.get("audit")
        if isinstance(audit, dict):
            for key, field_name in (("queue", "line"), ("repairs", "line"),
                                    ("additions", "after_line")):
                for item in audit.get(key) or []:
                    if isinstance(item, dict) and field_name in item:
                        item[field_name] = shift(int(item[field_name]))
            if isinstance(audit.get("line_proposals"), dict):
                audit["line_proposals"] = renumber(audit["line_proposals"])

    def normalize_words(self) -> int:
        """Apply TimedLine.normalize_words across the project.

        Called on every export so the word LRC the UI shows and the one on disk
        cannot drift apart.
        """
        for line in self.lines:
            line.normalize_words()
        return len(self.lines)

    def enforce_monotonic(self, min_gap: float = 0.0) -> int:
        """Clamp overlaps so line N never starts before line N-1 ends.

        Returns the number of lines adjusted. Locked lines are left alone.
        """
        fixed = 0
        previous_end = 0.0
        for line in self.lines:
            if line.end <= line.start:
                continue
            if line.start < previous_end + min_gap and not line.locked:
                new_start = previous_end + min_gap
                if new_start < line.end - 0.05:
                    line.retime(new_start, line.end)
                    fixed += 1
            previous_end = max(previous_end, line.end)
        return fixed

    # ---------- persistence ----------

    def to_dict(self) -> dict:
        return {
            "version": SCHEMA_VERSION,
            "audio_path": self.audio_path,
            "lyrics_path": self.lyrics_path,
            "duration": round(self.duration, 3),
            "workdir": self.workdir,
            "stem_path": self.stem_path,
            "sections": [s.to_dict() for s in self.sections],
            "lines": [ln.to_dict() for ln in self.lines],
            "scorecard": self.scorecard,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        return cls(
            audio_path=d["audio_path"],
            lyrics_path=d["lyrics_path"],
            duration=float(d["duration"]),
            sections=[
                Section(
                    index=s["index"],
                    name=s["name"],
                    note=s.get("note", ""),
                    raw=s.get("raw", ""),
                    line_indices=list(s.get("line_indices", [])),
                )
                for s in d["sections"]
            ],
            lines=[TimedLine.from_dict(x) for x in d["lines"]],
            workdir=d.get("workdir", ""),
            stem_path=d.get("stem_path", ""),
            scorecard=d.get("scorecard", {}),
            meta=d.get("meta", {}),
        )

    def save(self, path: Path | str | None = None) -> Path:
        target = Path(path) if path else Path(self.workdir) / "project.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return target

    @classmethod
    def load(cls, path: Path | str) -> "Project":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
