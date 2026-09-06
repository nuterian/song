"""Every review decision is a label. Keep it.

The audit queues words by four hand-written rules and Whisper's probability,
which is 38-of-177 noisy on the sample track; the reviewer then accepts,
keeps, adjusts, or drags a bound. Each of those is a human saying "this
word was right" or "this word was wrong, by this much" - the only labels
this project will ever get for free. This module writes them down, with
the word's features as they were at the time, so that once a few hundred
exist across several tracks a logistic regression can rank the queue by
"the human changed this" instead of by rule severity.

Scaffolding only, on purpose: one JSONL file per workdir, append-only, and a
write that never raises - a save must not fail because a log did. The model
waits for the data. Nothing here is read back by the app yet.

What a record holds: who asked (`source`: the review card or the timeline),
what happened (`action`, `bound`, `before`, `after`), and the features -
the audit's disagreement for that word if the audit ran, the aligner's
probability, distance to the nearest onset, envelope level and voicing at
the start, duration against syllable count, position in the line, the
line's score and its section's repeat index. All of it is inspectable, and
the coefficients of anything fitted on it will be too.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import syllables
from .project import Project

FILENAME = "decisions.jsonl"


def features(project: Project, activity, line_index: int, word_index: int,
             audit: dict | None = None) -> dict:
    """The word's features at decision time. Missing evidence is left out."""
    out: dict = {}
    if not 0 <= line_index < len(project.lines):
        return out
    line = project.lines[line_index]
    if not 0 <= word_index < len(line.words):
        return out
    word = line.words[word_index]
    n = len(line.words)
    duration = max(0.0, word.end - word.start)
    count = syllables.count(word.text)
    out.update({
        "prob": round(float(word.prob), 4),
        "duration": round(duration, 3),
        "syllables": count,
        "seconds_per_syllable": round(duration / count, 3),
        "position": round(word_index / max(1, n - 1), 3) if n > 1 else 0.0,
        "first": word_index == 0,
        "last": word_index == n - 1,
        "line_score": (line.score or {}).get("total"),
        "line_source": line.source,
        "gap_before": None if word_index == 0
        else round(word.start - line.words[word_index - 1].end, 3),
        "gap_after": None if word_index == n - 1
        else round(line.words[word_index + 1].start - word.end, 3),
    })
    # How many earlier sections carry the same name: the chorus's repeat index.
    name = next((s.name for s in project.sections if s.index == line.section), None)
    if name is not None:
        out["repeat_index"] = sum(
            1 for s in project.sections if s.name == name and s.index < line.section
        )
    if activity is not None:
        try:
            out["onset_distance"] = round(float(activity.nearest_onset(word.start)), 3)
            frame = min(len(activity.db) - 1, max(0, int(word.start / activity.hop)))
            out["db_at_start"] = round(float(activity.db[frame]), 1)
            if getattr(activity, "voiced", None) is not None:
                out["voiced_at_start"] = round(float(activity.voiced[frame]), 3)
            out["coverage"] = round(float(activity.coverage(word.start, word.end)), 3)
        except Exception:      # a feature is never worth losing the record
            pass
    if audit:
        proposal = (audit.get("line_proposals") or {}).get(str(line_index))
        if proposal and len(proposal.get("starts", [])) == n:
            out["disagreement"] = round(float(proposal["starts"][word_index]) - word.start, 3)
    return out


def record(workdir: Path | str, entry: dict) -> bool:
    """Append one decision. Returns False, and raises nothing, on any failure."""
    try:
        path = Path(workdir) / FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = dict(entry)
        entry.setdefault("at", round(time.time(), 3))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def load(workdir: Path | str) -> list[dict]:
    """Every decision recorded for a workdir; a corrupt line is skipped."""
    path = Path(workdir) / FILENAME
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out
