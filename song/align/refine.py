"""Deterministic word-level audit, repair and second-opinion proposals.

The premise, measured on the sample track: of 177 words, roughly two thirds have
two independent aligners agreeing to within 150 ms — those are almost certainly
right and should never cost a human a second look. A handful are *provably*
wrong: a sung word cannot last zero seconds, cannot start where the vocal stem is
silent, and cannot start before the word in front of it. Those get repaired here
without asking. What is left over is genuinely ambiguous — two plausible
timings — and no heuristic settles it honestly, so it goes to a human as an A/B
listening choice with a concrete alternative attached.

Deliberately *not* implemented: blind snap-to-nearest-onset. On the sample track
41% of word starts have more than one detected onset within +/-150 ms, so
snapping is a coin flip dressed up as a fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..audio import TARGET_SR, load_mono
from ..project import Project, TimedLine

# A sung word shorter than this is a degenerate timestamp, not a word.
MIN_REAL_WORD = 0.05
# Padding around a line when re-aligning it on its own, so the acoustic model
# sees the attack of the first word and the release of the last.
LINE_PAD = 0.35

# Two aligners this far apart disagree about something that matters; below it,
# the difference is smaller than the ear can place anyway.
DISAGREE = 0.20
# Whisper token confidence below this is a genuine "not sure what I heard".
LOW_PROB = 0.35
# No detected vocal onset within this of a word start is suspicious on its own.
ONSET_FAR = 0.25


@dataclass
class Issue:
    """One word a human should judge, with a concrete alternative to judge against."""

    line: int
    word: int
    text: str
    context: str
    current: float
    proposed: float | None
    reasons: list[str] = field(default_factory=list)
    severity: int = 1
    # "word" when the alternative fits between this word's neighbours; "line"
    # when the second aligner puts it outside the line entirely, which is a
    # statement about the line's own placement, not about one boundary.
    scope: str = "word"

    @property
    def delta(self) -> float:
        return 0.0 if self.proposed is None else self.proposed - self.current

    def to_dict(self) -> dict:
        return {
            "line": self.line,
            "word": self.word,
            "text": self.text,
            "context": self.context,
            "current": round(self.current, 3),
            "proposed": None if self.proposed is None else round(self.proposed, 3),
            "delta": round(self.delta, 3),
            "reasons": self.reasons,
            "severity": self.severity,
            "scope": self.scope,
        }


@dataclass
class Repair:
    """A change made without asking, because the previous value was impossible."""

    line: int
    word: int
    text: str
    was: float
    now: float
    why: str

    def to_dict(self) -> dict:
        return {
            "line": self.line,
            "word": self.word,
            "text": self.text,
            "was": round(self.was, 3),
            "now": round(self.now, 3),
            "why": self.why,
        }


def _context(line: TimedLine, index: int) -> str:
    """The line with the word in question bracketed, for showing in the UI."""
    parts = [w.text for w in line.words]
    if 0 <= index < len(parts):
        parts[index] = f"⸤{parts[index]}⸥"
    return " ".join(parts)


def _syllables(word: str) -> int:
    groups = re.findall(r"[aeiouy]+", word.lower())
    return max(1, len(groups))


# ---------------------------------------------------------------- proposals


def propose_words(
    stem: np.ndarray,
    line: TimedLine,
    device: str = "cpu",
    pad: float = LINE_PAD,
) -> list | None:
    """Re-align one line's words against only that line's audio, via CTC.

    Constraining forced alignment to a single line is what makes this a useful
    second opinion rather than a rerun: the search space is a few seconds of
    audio and a handful of known words, so it cannot drift the way a whole-track
    pass can. Returns None when the aligner cannot place the words.
    """
    from .ctc import align_lines_ctc

    if line.end <= line.start or not line.words:
        return None

    total = len(stem) / TARGET_SR
    a = max(0.0, line.start - pad)
    b = min(total, line.end + pad)
    clip = stem[int(a * TARGET_SR) : int(b * TARGET_SR)]
    if len(clip) < TARGET_SR // 4:
        return None

    try:
        out = align_lines_ctc(clip, [line.text], [line.index], device=device, offset=a)
    except Exception:
        return None

    if not out or not out[0].words:
        return None
    words = out[0].words
    # Only comparable word-for-word when the tokenizer agreed on the count.
    return words if len(words) == len(line.words) else None


# ---------------------------------------------------------------- repairs


def repair_line(line: TimedLine, activity) -> list[Repair]:
    """Remove impossible states from one line. Never claims to know the truth.

    Each rule fires only on a value that could not have been right under any
    reading of the audio, so nothing defensible is ever overwritten.
    """
    words = line.words
    if not words or line.end <= line.start:
        return []

    fixed: list[Repair] = []
    n = len(words)

    # 1. Runs of identical/zero-length starts: spread them across the space
    #    actually available between their surviving neighbours. This does not
    #    assert where the words are, only that they cannot all be at one instant.
    i = 0
    while i < n:
        j = i
        while j + 1 < n and words[j + 1].start - words[j].start < MIN_REAL_WORD:
            j += 1
        if j > i:
            lo = words[i].start
            hi = words[j + 1].start if j + 1 < n else line.end
            count = j - i + 1
            step = (hi - lo) / count          # leaves the last one its own slice
            if step >= MIN_REAL_WORD:
                for k in range(i, j + 1):
                    was, now = words[k].start, lo + (k - i) * step
                    if abs(now - was) > 1e-6:
                        words[k].start = now
                        fixed.append(Repair(line.index, k, words[k].text, was, now,
                                            "zero-length word: a sung word cannot last 0 s"))
        i = j + 1

    # 2. Monotonicity: a word cannot begin before the one in front of it.
    for k in range(1, n):
        if words[k].start < words[k - 1].start + MIN_REAL_WORD:
            was = words[k].start
            now = min(words[k - 1].start + MIN_REAL_WORD, line.end)
            if abs(now - was) > 1e-6:
                words[k].start = now
                fixed.append(Repair(line.index, k, words[k].text, was, now,
                                    "out of order: started before the previous word"))

    # 3. Internal starts sitting in stem silence: pull to the next moment the
    #    vocal is actually sounding. Word 0's start is the line start, so it is
    #    left to line-level tools rather than silently moving the line.
    if activity is not None:
        for k in range(1, n):
            t = words[k].start
            if activity.coverage(t, t + 0.03) > 0:
                continue
            nxt = _next_active(activity, t, limit=words[k + 1].start if k + 1 < n else line.end)
            if nxt is not None and abs(nxt - t) > 1e-6:
                words[k].start = nxt
                fixed.append(Repair(line.index, k, words[k].text, t, nxt,
                                    "started in silence: the vocal stem is not sounding there"))

    if fixed:
        line.source = "manual"
    line.normalize_words()
    return fixed


def _next_active(activity, t: float, limit: float) -> float | None:
    """First moment at or after `t` where the vocal is active, before `limit`."""
    if limit <= t:
        return None
    hop = activity.hop
    i = int(t / hop)
    stop = min(len(activity.active), int(limit / hop))
    while i < stop:
        if activity.active[i]:
            return round(i * hop, 3)
        i += 1
    return None


# ---------------------------------------------------------------- audit


def audit_line(line: TimedLine, proposal, activity, onsets: np.ndarray) -> list[Issue]:
    """Words in this line a human should judge, with the CTC alternative attached."""
    issues: list[Issue] = []
    words = line.words
    for k, w in enumerate(words):
        reasons: list[str] = []
        severity = 0
        proposed = None

        scope = "word"
        if proposal is not None:
            alt = proposal[k].start
            gap = abs(alt - w.start)
            if gap >= DISAGREE:
                proposed = alt
                severity += 2 if gap >= 0.5 else 1
                reasons.append(f"the two aligners disagree by {gap:.2f}s")
                # Accepting a value the word-level clamps would have to drag
                # back into range would be a lie about what the button does.
                lo = words[k - 1].start + MIN_REAL_WORD if k else line.start
                hi = (words[k + 1].start if k + 1 < len(words) else line.end) - MIN_REAL_WORD
                if not (lo <= alt <= hi):
                    scope = "line"
                    reasons.append(
                        "this lands outside the line, so the whole line looks misplaced"
                    )

        if w.prob < LOW_PROB:
            severity += 1
            reasons.append(f"the aligner was unsure it heard this word ({w.prob:.0%})")

        if len(onsets):
            d = float(np.abs(onsets - w.start).min())
            if d > ONSET_FAR:
                severity += 1
                reasons.append(f"no vocal attack within {d*1000:.0f} ms of this start")

        duration = w.end - w.start
        if duration > 1.6 and _syllables(w.text) <= 2:
            severity += 1
            reasons.append(f"held for {duration:.1f}s, long for a {_syllables(w.text)}-syllable word")

        # Only queue words we can offer a real choice about; the rest stay as a
        # quiet inline mark so the queue is always a clean A/B decision.
        if proposed is not None and reasons:
            issues.append(
                Issue(line.index, k, w.text, _context(line, k),
                      w.start, proposed, reasons, severity, scope)
            )
    return issues


# ---------------------------------------------------------------- driver


def run(
    project: Project,
    stem_path: Path | str,
    activity=None,
    samples: np.ndarray | None = None,
    device: str = "cpu",
    progress=None,
) -> dict:
    """Repair what is provably wrong, then queue what genuinely needs an ear.

    `samples` lets a caller that has already decoded the stem (the server keeps
    one in memory per open track; the CLI loads one to build `activity`) hand
    it straight in, instead of this function silently re-decoding the same
    file through another ffmpeg subprocess.
    """
    say = progress or (lambda *_: None)

    stem = samples if samples is not None else load_mono(stem_path, TARGET_SR)[0]
    onsets = np.asarray(activity.onsets if activity is not None else [], dtype=float)

    repairs: list[Repair] = []
    issues: list[Issue] = []
    line_proposals: dict[int, dict] = {}
    verified = 0
    lines = [ln for ln in project.lines if ln.end > ln.start and ln.words]

    for n, line in enumerate(lines, 1):
        say(f"  [{n}/{len(lines)}] line {line.index}")
        repairs += repair_line(line, activity)
        proposal = propose_words(stem, line, device=device)
        if proposal is not None:
            line_proposals[line.index] = {
                "start": round(proposal[0].start, 3),
                "end": round(proposal[-1].end, 3),
                "starts": [round(w.start, 3) for w in proposal],
            }
        found = audit_line(line, proposal, activity, onsets)
        issues += found
        if proposal is not None:
            flagged = {i.word for i in found}
            verified += sum(1 for k in range(len(line.words)) if k not in flagged)

    issues.sort(key=lambda i: (-i.severity, -abs(i.delta)))
    total_words = sum(len(ln.words) for ln in lines)
    return {
        "n_words": total_words,
        "n_verified": verified,
        "repairs": [r.to_dict() for r in repairs],
        "queue": [i.to_dict() for i in issues],
        "line_proposals": {str(k): v for k, v in line_proposals.items()},
    }
