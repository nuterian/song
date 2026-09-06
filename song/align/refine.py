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

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..audio import TARGET_SR, load_mono
from ..project import Project, TimedLine
from . import repeats

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
# A word end this far from where the envelope says the voice stopped is a
# rest's worth of error - the karaoke renderer's MIN_REST - and gets repaired.
END_SLOP = 0.15


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
    # Which bound moved. Every repair was a start until word ends were read
    # off the stem; the field is explicit so nothing downstream has to guess.
    bound: str = "start"

    def to_dict(self) -> dict:
        return {
            "line": self.line,
            "word": self.word,
            "text": self.text,
            "was": round(self.was, 3),
            "now": round(self.now, 3),
            "why": self.why,
            "bound": self.bound,
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
                        _slide(words[k], now)
                        fixed.append(Repair(line.index, k, words[k].text, was, now,
                                            "zero-length word: a sung word cannot last 0 s"))
        i = j + 1

    # 2. Monotonicity: a word cannot begin before the one in front of it.
    for k in range(1, n):
        if words[k].start < words[k - 1].start + MIN_REAL_WORD:
            was = words[k].start
            now = min(words[k - 1].start + MIN_REAL_WORD, line.end)
            if abs(now - was) > 1e-6:
                _slide(words[k], now)
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
                _slide(words[k], nxt)
                fixed.append(Repair(line.index, k, words[k].text, t, nxt,
                                    "started in silence: the vocal stem is not sounding there"))

    # 4. Ends that disagree with the stem's envelope by more than a rest:
    #    the voice stopped and the word ran on, or the aligner stopped the word
    #    on continuous vocal. song/ends.py has the rule and its guard; below
    #    END_SLOP the rule's own error (30 ms median on true starts) is not
    #    worth reporting as a repair.
    if activity is not None and hasattr(activity, "word_end"):
        for k, w in enumerate(words):
            limit = words[k + 1].start if k + 1 < n else line.end
            now = activity.word_end(w.start, limit, current=w.end)
            delta = now - w.end
            if abs(delta) >= END_SLOP:
                why = (f"ended {-delta:.2f}s after the voice stopped" if delta < 0
                       else f"stopped {delta:.2f}s before the voice did")
                fixed.append(Repair(line.index, k, w.text, w.end, now, why, bound="end"))
                w.end = now
        if words[-1].end != line.end:
            line.end = words[-1].end

    if fixed:
        line.source = "manual"
    line.normalize_words()
    return fixed


def _slide(word, now: float) -> None:
    """Move a word to a new start, carrying its length with it.

    Every repair here asserts where a word *begins*. Word ends are measured
    quantities now rather than derived ones, so a word that begins 200 ms later
    ends 200 ms later too - leaving the end behind would report a repair and
    quietly shorten the word to nothing. normalize_words holds whatever this
    produces inside the line and off its neighbours.
    """
    span = max(0.0, word.end - word.start)
    word.start = now
    word.end = now + span


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


# ---------------------------------------------------------------- repeats


def repair_from_repeats(project: Project, stem: np.ndarray, sr: int, say) -> list[Repair]:
    """Re-place an outlier rendition of a repeated lyric from a trusted sibling.

    Only fires where `repeats.transfer_pairs` says the target is an outlier and
    the source is not; measured on the sample track that is lines 8 and 18,
    and the transfer takes their start error from 140 and 493 ms to 24 and
    14 ms. The whole line moves, so it is reported once per line rather than
    once per word, with the deviation that triggered it.
    """
    fixed: list[Repair] = []
    for source, target, sdev, tdev in repeats.transfer_pairs(project):
        say(f"  line {target.index}: re-placing from its repeat, line {source.index}")
        bounds = repeats.transfer(stem, sr, source, target)
        if bounds is None:
            continue
        starts = [b[0] for b in bounds]
        if any(b <= a for a, b in zip(starts, starts[1:])):
            continue                     # the warp folded; not a placement
        was = target.start
        for w, (s, e) in zip(target.words, bounds):
            w.start, w.end = s, max(s + MIN_REAL_WORD, e)
        target.start, target.end = bounds[0][0], bounds[-1][1]
        target.normalize_words()
        target.source = "repeat"
        fixed.append(Repair(
            target.index, 0, target.words[0].text, was, target.start,
            f"its word lengths were {math.exp(tdev / len(target.words)):.2f}x off the "
            f"other renditions' on average; placed from line {source.index}", bound="line",
        ))
    if fixed:
        project.enforce_monotonic()
    return fixed


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

    The result is stored as `project.meta["audit"]` and returned. It lives in
    the project rather than beside it because its queue, proposals and repairs
    are keyed by line index, and an inserted line renumbers everything in the
    project in one place (Project.insert_line); a second file would have to be
    renumbered in lockstep, and was.

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

    # The song's own repeats first: a rendition whose word durations sit far
    # from its siblings' is re-placed from the sibling nearest their median,
    # before the per-line rules look at it. See repeats.py for the numbers.
    repairs += repair_from_repeats(project, stem, TARGET_SR, say)

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

    # Words that disagree with their own repeats, as A/B choices on the
    # boundary after them. 3 of 4 right on the sample track; the fourth is a
    # line whose two siblings are the wrong ones.
    for outlier in repeats.outliers(project):
        line = project.lines[outlier.line]
        d = outlier.issue()
        issues.append(Issue(d["line"], d["word"], line.words[d["word"]].text,
                            _context(line, d["word"]), d["current"], d["proposed"],
                            d["reasons"], d["severity"], d["scope"]))

    # A project aligned before syllables existed gets them here, off the stem.
    if activity is not None and getattr(activity, "strength", None) is not None:
        from .pipeline import settle_syllables

        settle_syllables(project, activity)

    issues.sort(key=lambda i: (-i.severity, -abs(i.delta)))
    total_words = sum(len(ln.words) for ln in lines)
    # Dismissed proposals are the user's judgement and outlive a re-run.
    previous = project.meta.get("audit") or {}
    project.meta["audit"] = {
        "n_words": total_words,
        "n_verified": verified,
        "repairs": [r.to_dict() for r in repairs],
        "queue": [i.to_dict() for i in issues],
        "line_proposals": {str(k): v for k, v in line_proposals.items()},
        "additions": [a for a in previous.get("additions", []) if a.get("dismissed")],
    }
    return project.meta["audit"]
