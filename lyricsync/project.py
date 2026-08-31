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

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "prob": round(self.prob, 4),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Word":
        return cls(
            text=d["text"],
            start=float(d["start"]),
            end=float(d["end"]),
            prob=float(d.get("prob", 1.0)),
        )


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
        """Make the word spans contiguous: a word ends where the next begins.

        The UI edits word *starts* only - enhanced LRC encodes nothing else, and
        deriving ends makes gaps and overlaps unrepresentable. Whisper's raw
        ends encode small inter-word pauses; flattening them is the accepted
        cost, since every consumer (exports, scorer) keys off starts.
        """
        if not self.words or self.end <= self.start:
            return
        previous = self.start
        for w in self.words:
            w.start = min(max(w.start, previous), self.end)
            previous = w.start
        for a, b in zip(self.words, self.words[1:]):
            a.end = b.start
        self.words[-1].end = self.end

    def retime(self, start: float, end: float) -> None:
        """Move the line, rescaling word timings proportionally into the new span.

        Line-level edits are what the UI exposes; words ride along so the
        word-level exports stay coherent without word-by-word editing.
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
        the tail and rebuild the sections' membership lists in one go, or those
        three things quietly start pointing at the wrong lyrics.
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

        Both aligners' raw spans and the round-trip's per-line observations are
        stored as {line index: ...}. Leaving them behind after an insertion does
        not fail loudly - it silently scores every line after the new one
        against its neighbour's evidence, which reads as the whole back half of
        the song having come loose. Found exactly that way.
        """
        def renumber(table: dict) -> dict:
            out = {}
            for key, value in table.items():
                try:
                    i = int(key)
                except (TypeError, ValueError):
                    out[key] = value
                    continue
                out[str(i + 1 if i >= at else i)] = value
            return out

        aligners = self.meta.get("aligners")
        if isinstance(aligners, dict):
            for name, table in aligners.items():
                if isinstance(table, dict):
                    aligners[name] = renumber(table)

        rt = self.meta.get("roundtrip")
        if isinstance(rt, dict) and isinstance(rt.get("per_line"), dict):
            rt["per_line"] = renumber(rt["per_line"])

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
