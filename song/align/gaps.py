"""Lines that are sung but missing from the lyrics file.

A lyrics `.txt` is written by hand, and hands drop things - most often a chorus
repeat or a post-chorus tag, because they are the lines a writer already typed
three times. The aligner cannot notice: it is *told* the lyrics and consumes
them in order, so a missing line does not produce an error, it produces a
silence where nobody looks. On the sample track that is 45.8 seconds between the
first chorus and verse 2, with a clearly sung line inside it.

The evidence needed to catch this is already computed and thrown away. The
round-trip pass transcribes the whole vocal stem blind and matches the words
back to known lines; whatever no line claims is, by construction, something
that was sung and is not in the lyrics as timed. See RoundTrip.unmatched.

The hard part is not finding candidates, it is refusing bad ones. A vocal stem
carries pads, "ooh"s and reverb tails, and Whisper will hallucinate "Thank you."
over a fade. So a candidate has to clear four independent tests at once, and on
the sample track exactly one stretch of audio does - the right one.

Deliberately *not* implemented: proposing text that matches nothing in the
lyrics. A transcription confident enough to trust for that is also confident
enough to be wrong in a way nobody would catch by ear, and approving it means
proofreading a machine rather than confirming what you just heard. Every
proposal here is a line you already wrote, heard somewhere you did not write it.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from ..parse_lyrics import tokenize
from ..project import Project, TimedLine, Word

# A gap needs this much vocal-active audio in it before it is worth listening to.
MIN_VOCAL = 2.0
# Fewer words than this is a bleed off a neighbour, not a line.
MIN_WORDS = 3
# Mean word probability. The real candidate on the sample track scores 0.89;
# the best false positive scores 0.60, and the hallucinations 0.29 and 0.50.
MIN_PROB = 0.60
# Similarity to an existing lyric line. The real one is an exact 1.00; the best
# false positive is 0.50, so there is a wide, empty valley to put this in.
MIN_MATCH = 0.80
# ...and it has to be most of that line, not a two-word prefix of it.
MIN_COVERAGE = 0.60
# How far outside the gap a word may sit before it is treated as bleed from the
# neighbouring line rather than something sung in the hole between them.
STRADDLE = 0.25


@dataclass
class Candidate:
    """A line the lyrics do not have, heard in a hole between two that they do."""

    after_line: int
    section: int
    start: float
    end: float
    text: str                       # an existing line's text, never invented
    like_line: int                  # the line it repeats
    repeats: int                    # how many times that text already appears
    heard: str                      # what the transcription actually said
    confidence: float
    match: float
    starts: list[float] = field(default_factory=list)
    dismissed: bool = False

    @property
    def id(self) -> str:
        """Stable across renumbering: where it was heard, not what it follows."""
        return f"{self.start:.2f}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "after_line": self.after_line,
            "section": self.section,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "like_line": self.like_line,
            "repeats": self.repeats,
            "heard": self.heard,
            "confidence": round(self.confidence, 3),
            "match": round(self.match, 3),
            "starts": [round(t, 3) for t in self.starts],
            "dismissed": self.dismissed,
        }


def _vocal_seconds(activity, a: float, b: float) -> float:
    """How much of [a, b] the vocal stem is actually sounding in."""
    if activity is None or b <= a:
        return max(0.0, b - a)
    return float(activity.coverage(a, b)) * (b - a)


def _gaps(project: Project) -> list[tuple[float, float, int, int]]:
    """(start, end, after_line, section) for every hole between timed lines."""
    lines = sorted(project.aligned_lines(), key=lambda ln: ln.start)
    out = []
    for a, b in zip(lines, lines[1:]):
        if b.start > a.end:
            out.append((a.end, b.start, a.index, a.section))
    if lines and project.duration > lines[-1].end:
        last = lines[-1]
        out.append((last.end, project.duration, last.index, last.section))
    return out


def _distinct(project: Project) -> dict[str, list[int]]:
    """Every distinct lyric line, and which line indices carry it."""
    out: dict[str, list[int]] = {}
    for line in project.lines:
        key = " ".join(tokenize(line.text))
        if key:
            out.setdefault(key, []).append(line.index)
    return out


def _best_match(heard: str, distinct: dict[str, list[int]]):
    key = " ".join(tokenize(heard))
    best, score = None, 0.0
    for candidate, indices in distinct.items():
        ratio = difflib.SequenceMatcher(None, key, candidate).ratio()
        if ratio > score:
            score, best = ratio, (candidate, indices)
    if best is None:
        return None
    # How much of the matched line was actually heard - a two-word prefix of a
    # five-word chorus is a bleed, not a repeat of it.
    coverage = len(tokenize(heard)) / max(1, len(tokenize(best[0])))
    return best[0], best[1], score, coverage


def find(
    project: Project,
    activity=None,
    words: list[Word] | None = None,
    dismissed: set | None = None,
) -> list[Candidate]:
    """Candidate lines for the holes in `project`, from blind-transcribed words.

    `words` is the round-trip pass's leftovers - anything it heard that no line
    claimed. Callers that have no saved round-trip transcribe the gaps
    themselves and pass the result in; see `transcribe_gaps`.
    """
    if not words:
        return []
    dismissed = dismissed or set()
    distinct = _distinct(project)
    out: list[Candidate] = []

    for start, end, after, section in _gaps(project):
        if _vocal_seconds(activity, start, end) < MIN_VOCAL:
            continue

        # Strictly inside the hole: a word hanging over a neighbour's boundary
        # is that neighbour's lead-in, which is a timing question, not a
        # missing line. On the sample track this is what rejects "You're my"
        # bleeding out of the chorus at 1:03.
        inside = [
            w for w in words
            if w.start >= start - STRADDLE and w.end <= end + STRADDLE
        ]
        if len(inside) < MIN_WORDS:
            continue

        confidence = sum(w.prob for w in inside) / len(inside)
        if confidence < MIN_PROB:
            continue

        heard = " ".join(w.text for w in inside)
        found = _best_match(heard, distinct)
        if found is None:
            continue
        text_key, indices, ratio, coverage = found
        if ratio < MIN_MATCH or coverage < MIN_COVERAGE:
            continue

        like = project.lines[indices[0]]
        out.append(
            Candidate(
                after_line=after,
                section=section,
                start=inside[0].start,
                end=inside[-1].end,
                text=like.text,
                like_line=like.index,
                repeats=len(indices),
                heard=heard,
                confidence=confidence,
                match=ratio,
                starts=_starts(inside, like, inside[0].start, inside[-1].end),
            )
        )
        out[-1].dismissed = out[-1].id in dismissed
    return out


def _starts(heard_words, like: TimedLine, start: float, end: float) -> list[float]:
    """Word starts for the proposed line.

    When the transcription heard exactly as many words as the line has, its own
    timings are the best evidence there is. Otherwise the words are spread
    evenly across the heard span - honest about knowing only where the line is,
    not where each syllable in it fell. Either way the new line joins the
    timing queue like any other, so an ear gets the last word.
    """
    n = len(like.words) or len(heard_words)
    if len(heard_words) == n:
        return [w.start for w in heard_words]
    step = (end - start) / max(1, n)
    return [start + i * step for i in range(n)]


def build_line(project: Project, cand: dict) -> TimedLine:
    """Turn an accepted candidate into a line ready to insert."""
    texts = [w for w in cand["text"].split() if w]
    starts = list(cand.get("starts") or [])
    start, end = float(cand["start"]), float(cand["end"])
    if len(starts) != len(texts):
        step = (end - start) / max(1, len(texts))
        starts = [start + i * step for i in range(len(texts))]

    words = [
        Word(text=t, start=s, end=(starts[i + 1] if i + 1 < len(starts) else end),
             prob=float(cand.get("confidence", 0.0)))
        for i, (t, s) in enumerate(zip(texts, starts))
    ]
    line = TimedLine(
        index=int(cand["after_line"]) + 1,
        section=int(cand["section"]),
        text=cand["text"],
        start=min(start, starts[0] if starts else start),
        end=end,
        words=words,
        source="added",
    )
    line.normalize_words()
    return line


def transcribe_gaps(
    project: Project,
    samples,
    activity=None,
    model_size: str = "medium",
    device: str = "cpu",
    progress=None,
) -> list[Word]:
    """Blind-transcribe only the holes, for projects with no saved round-trip.

    A full re-transcription would cost minutes; the holes are a fraction of the
    track. Projects aligned after this feature landed carry the words already
    and never reach here.
    """
    from ..audio import TARGET_SR
    from .roundtrip import transcribe

    say = progress or (lambda *_: None)
    holes = [
        g for g in _gaps(project)
        if _vocal_seconds(activity, g[0], g[1]) >= MIN_VOCAL
    ]
    out: list[Word] = []
    for n, (start, end, _after, _sec) in enumerate(holes, 1):
        say(f"  [{n}/{len(holes)}] listening to {start:.1f}s-{end:.1f}s")
        a = max(0.0, start - 0.3)
        clip = samples[int(a * TARGET_SR) : int(min(project.duration, end + 0.3) * TARGET_SR)]
        if len(clip) < TARGET_SR // 2:
            continue
        try:
            heard = transcribe(clip, model_size=model_size, device=device)
        except Exception:
            continue
        for w in heard:
            out.append(Word(text=w.text, start=w.start + a, end=w.end + a, prob=w.prob))
    return out
