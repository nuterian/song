"""The accuracy benchmark.

An AI-generated song has no ground-truth timing file, so accuracy is estimated
from evidence rather than measured against a reference:

  1. Cross-aligner agreement - two unrelated model families (Whisper and
     wav2vec2 CTC) independently placing a line within a few tens of ms of each
     other is strong evidence the placement is right, and a large disagreement
     is a reliable pointer at a line a human should check.
  2. Blind-transcription corroboration - both aligners were *told* the lyrics,
     so both can be confidently wrong together. A free transcription was told
     nothing, so where it independently heard the line is the tiebreaker.
  3. Vocal coverage - the line's span should contain actual singing.
  4. Onset proximity - a line should start where a vocal onset is.
  5. Word density - syllables per second inside singing norms.
  6. Aligner confidence - mean per-word probability.

These combine into a 0-100 per-line score plus a track scorecard. The same
per-line numbers drive the review UI, so human attention goes exactly where the
benchmark says it is needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import roundtrip
from ..project import Project
from ..vad import VocalActivity

# Component weights, summing to 100.
WEIGHTS = {
    "agreement": 30.0,
    "roundtrip": 22.0,
    "coverage": 20.0,
    "onset": 12.0,
    "density": 8.0,
    "confidence": 8.0,
}

FLAG_THRESHOLD = 70.0


def _ramp(value: float, good: float, bad: float) -> float:
    """1.0 when value is at or better than `good`, 0.0 at or worse than `bad`."""
    if good == bad:
        return 1.0
    t = (value - bad) / (good - bad)
    return float(np.clip(t, 0.0, 1.0))


@dataclass
class Scorecard:
    n_lines: int = 0
    n_aligned: int = 0
    median_start_delta: float = float("nan")
    median_end_delta: float = float("nan")
    pct_within_150ms: float = 0.0
    pct_within_300ms: float = 0.0
    pct_within_500ms: float = 0.0
    mean_coverage: float = 0.0
    min_coverage: float = 0.0
    mean_score: float = 0.0
    n_corroborated: int = 0
    n_flagged: int = 0
    flagged: list[int] = field(default_factory=list)
    overlaps: int = 0
    out_of_order: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "n_lines": self.n_lines,
            "n_aligned": self.n_aligned,
            "median_start_delta": _round(self.median_start_delta),
            "median_end_delta": _round(self.median_end_delta),
            "pct_within_150ms": round(self.pct_within_150ms, 1),
            "pct_within_300ms": round(self.pct_within_300ms, 1),
            "pct_within_500ms": round(self.pct_within_500ms, 1),
            "mean_coverage": round(self.mean_coverage, 3),
            "min_coverage": round(self.min_coverage, 3),
            "mean_score": round(self.mean_score, 1),
            "n_corroborated": self.n_corroborated,
            "n_flagged": self.n_flagged,
            "flagged": list(self.flagged),
            "overlaps": self.overlaps,
            "out_of_order": self.out_of_order,
            "notes": list(self.notes),
        }
        return d


def _round(x: float) -> float | None:
    return None if x != x else round(float(x), 3)


def evidence(
    activity: VocalActivity,
    start: float,
    end: float,
    n_words: int,
    prob: float,
    rt: "roundtrip.RoundTrip | None" = None,
    line_index: int | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """What the audio and the blind transcription say about one placement.

    Everything except cross-aligner agreement, which is symmetric: it says a
    line is uncertain but cannot say which of two candidates is right. Used
    by the merge to choose between candidates and by the score to grade the
    winner, so the two can never drift apart on what "supported" means.

    Returns the terms ramped to 0..1 - `roundtrip` only when the transcription
    has an opinion - and the raw numbers behind them.
    """
    duration = max(end - start, 1e-6)
    coverage = activity.coverage(start, end)
    onset_distance = activity.nearest_onset(start)
    density = n_words / duration
    if density < 1.0:
        density_term = _ramp(density, good=1.0, bad=0.25)
    elif density > 5.5:
        density_term = _ramp(density, good=5.5, bad=11.0)
    else:
        density_term = 1.0
    parts = {
        "coverage": _ramp(coverage, good=0.65, bad=0.15),
        "onset": _ramp(onset_distance, good=0.12, bad=0.7),
        "density": density_term,
        "confidence": _ramp(prob, good=0.6, bad=0.05),
    }
    support = rt.support(line_index, start, end) if rt and line_index is not None else None
    if support is not None:
        parts["roundtrip"] = support
    raw = {
        "coverage": coverage,
        "onset_distance": onset_distance,
        "density": density,
        "prob": prob,
    }
    return parts, raw


def score_project(project: Project, activity: VocalActivity) -> Scorecard:
    """Score every line in place, set the project's scorecard, and return it.

    The evidence is the project's own: `meta["aligners"]` holds both pristine
    aligners' spans and `meta["roundtrip"]` the blind transcription's, so the
    pipeline's score and `song score` after an edit are the same computation
    on the same file. Agreement is always the disagreement between the two
    *pristine* outputs - never between the merge and one of its own inputs,
    which would report perfect agreement with itself.

    A line somebody has placed by hand has no aligner to disagree with: the
    human is the reference there, and `song bench` against a gold file is the
    thing that measures them. The agreement term drops out and the rest are
    reweighted, rather than flagging a fix because the model it corrected
    still says otherwise.
    """
    stored = project.meta.get("aligners") or {}
    ctc = stored.get("ctc") or {}
    whisper = stored.get("whisper") or {}
    rt = roundtrip.RoundTrip.from_dict(project.meta.get("roundtrip"))
    card = Scorecard(n_lines=len(project.lines))

    start_deltas: list[float] = []
    end_deltas: list[float] = []
    coverages: list[float] = []
    scores: list[float] = []

    previous_end = 0.0
    for line in project.lines:
        if line.end <= line.start:
            line.score = {"total": 0.0, "issues": ["not aligned"]}
            line.flagged = True
            continue

        card.n_aligned += 1
        issues: list[str] = []
        available = dict(WEIGHTS)

        # 1. cross-aligner agreement: both pristine spans where both exist,
        #    else the one aligner against the line as it stands. The track's
        #    disagreement figures are the aligners' benchmark and keep every
        #    line; only the hand-placed line's own score leaves the term out.
        key = str(line.index)
        ref, other = ctc.get(key), whisper.get(key)
        d_start = d_end = None
        if ref is not None and (other is not None or line.source != "manual"):
            against = other if other is not None else (line.start, line.end)
            d_start, d_end = abs(ref[0] - against[0]), abs(ref[1] - against[1])
            start_deltas.append(d_start)
            end_deltas.append(d_end)
        if d_start is None or line.source == "manual":
            available.pop("agreement")
        elif d_start > 0.75:
            issues.append(f"ctc disagrees by {d_start:.2f}s at start")

        # 2-6. everything the audio and the blind transcription can say.
        n_words = len(line.words) or len(line.text.split())
        prob = float(np.mean([w.prob for w in line.words])) if line.words else 0.0
        parts, raw = evidence(activity, line.start, line.end, n_words, prob, rt, line.index)
        if "agreement" in available:
            parts["agreement"] = _ramp(d_start, good=0.15, bad=1.2)
        if "roundtrip" in parts:
            card.n_corroborated += 1
            if parts["roundtrip"] < 0.45:
                heard = rt.per_line[line.index]
                issues.append(f"heard at {heard.start:.2f}-{heard.end:.2f}s, not here")
        else:
            available.pop("roundtrip")

        coverage = raw["coverage"]
        coverages.append(coverage)
        if coverage < 0.35:
            issues.append(f"only {coverage:.0%} vocal in span")
        gap = activity.longest_gap(line.start, line.end)
        if gap > 1.5:
            issues.append(f"{gap:.1f}s silence inside line")
        if raw["onset_distance"] > 0.6:
            issues.append(f"start {raw['onset_distance']:.2f}s from nearest vocal onset")
        if raw["density"] < 1.0:
            issues.append(f"slow: {raw['density']:.1f} words/s")
        elif raw["density"] > 5.5:
            issues.append(f"fast: {raw['density']:.1f} words/s")

        # ordering sanity
        if line.start < previous_end - 0.05:
            card.overlaps += 1
            issues.append("overlaps previous line")
        previous_end = max(previous_end, line.end)

        total_weight = sum(available.values())
        total = sum(parts[k] * available[k] for k in available) / total_weight * 100.0
        scores.append(total)

        line.score = {
            "total": round(total, 1),
            "components": {k: round(parts[k], 3) for k in available},
            "coverage": round(coverage, 3),
            "onset_distance": round(raw["onset_distance"], 3),
            "density": round(raw["density"], 2),
            "prob": round(prob, 3),
            "delta_start": _round(d_start) if d_start is not None else None,
            "delta_end": _round(d_end) if d_end is not None else None,
            "issues": issues,
        }
        line.flagged = total < FLAG_THRESHOLD

    order = [ln.start for ln in project.lines if ln.end > ln.start]
    card.out_of_order = sum(1 for a, b in zip(order, order[1:]) if b < a)

    if start_deltas:
        arr = np.array(start_deltas)
        card.median_start_delta = float(np.median(arr))
        card.pct_within_150ms = float(np.mean(arr <= 0.15) * 100)
        card.pct_within_300ms = float(np.mean(arr <= 0.30) * 100)
        card.pct_within_500ms = float(np.mean(arr <= 0.50) * 100)
    if end_deltas:
        card.median_end_delta = float(np.median(np.array(end_deltas)))
    if coverages:
        card.mean_coverage = float(np.mean(coverages))
        card.min_coverage = float(np.min(coverages))
    if scores:
        card.mean_score = float(np.mean(scores))

    card.flagged = [ln.index for ln in project.lines if ln.flagged]
    card.n_flagged = len(card.flagged)
    project.scorecard = card.to_dict()
    return card


# ---------- the quality gate ----------

# Thresholds are calibrated against what two *different* model families can
# actually achieve, not against perfection. Whisper and wav2vec2 CTC place word
# edges differently by nature, so demanding near-total agreement makes the gate
# fail on good output and retry against a target it can never reach. What the
# gate is really for is catching alignment that has gone wrong - a desynced
# pass, lines over instrumentals, lines out of order - and those all move these
# numbers a long way, not a little.
GATE = {
    "median_start_delta": 0.35,
    "pct_within_500ms": 70.0,
    "mean_coverage": 0.70,
    "mean_score": 80.0,
    "max_flagged_fraction": 0.15,
}


def gate_failures(card: Scorecard, gate: dict | None = None) -> list[str]:
    """Which gate criteria the scorecard misses (empty list == pass)."""
    gate = gate or GATE
    failures = []

    if card.median_start_delta == card.median_start_delta:  # not NaN
        if card.median_start_delta > gate["median_start_delta"]:
            failures.append(
                f"median start delta {card.median_start_delta:.3f}s "
                f"> {gate['median_start_delta']}s"
            )
    if card.pct_within_500ms < gate["pct_within_500ms"]:
        failures.append(
            f"only {card.pct_within_500ms:.0f}% of lines agree within 500ms "
            f"(want {gate['pct_within_500ms']:.0f}%)"
        )
    if card.mean_coverage < gate["mean_coverage"]:
        failures.append(
            f"mean vocal coverage {card.mean_coverage:.0%} "
            f"< {gate['mean_coverage']:.0%}"
        )
    if card.mean_score < gate["mean_score"]:
        failures.append(
            f"mean line score {card.mean_score:.1f} < {gate['mean_score']:.0f}"
        )

    # Flags mark uncertainty, not failure - some is irreducible. Only an
    # unusual *proportion* of them means the pass itself went wrong.
    allowed = max(1, int(card.n_lines * gate["max_flagged_fraction"]))
    if card.n_flagged > allowed:
        failures.append(
            f"{card.n_flagged} of {card.n_lines} lines below score "
            f"{FLAG_THRESHOLD:.0f} (tolerating {allowed})"
        )
    if card.out_of_order:
        failures.append(f"{card.out_of_order} line(s) out of order")

    return failures


def format_report(project: Project, card: Scorecard, per_line: bool = True) -> str:
    """Human-readable scorecard for the terminal."""
    lines = []
    lines.append("")
    lines.append("=" * 78)
    lines.append("ALIGNMENT SCORECARD")
    lines.append("=" * 78)

    delta = card.median_start_delta
    delta_text = "n/a" if delta != delta else f"{delta * 1000:.0f} ms"
    lines.append(f"  lines aligned            {card.n_aligned}/{card.n_lines}")
    lines.append(f"  median start disagreement {delta_text}")
    lines.append(
        f"  agreement <=150/300/500ms  "
        f"{card.pct_within_150ms:.0f}% / {card.pct_within_300ms:.0f}%"
        f" / {card.pct_within_500ms:.0f}%"
    )
    lines.append(
        f"  vocal coverage            mean {card.mean_coverage:.0%}, "
        f"min {card.min_coverage:.0%}"
    )
    lines.append(
        f"  heard independently       {card.n_corroborated}/{card.n_aligned} lines"
    )
    lines.append(f"  mean line score           {card.mean_score:.1f}/100")
    lines.append(
        f"  needs review              {card.n_flagged} line(s)"
        f"{'  ' + str(card.flagged) if card.flagged else ''}"
    )
    if card.overlaps or card.out_of_order:
        lines.append(
            f"  ordering                  {card.overlaps} overlap(s), "
            f"{card.out_of_order} out of order"
        )

    if per_line:
        lines.append("-" * 78)
        lines.append(f"  {'#':>3} {'start':>8} {'end':>8} {'score':>6}  line")
        for ln in project.lines:
            total = ln.score.get("total", 0.0)
            mark = "!" if ln.flagged else " "
            text = ln.text[:34]
            lines.append(
                f" {mark}{ln.index:>3} {ln.start:8.2f} {ln.end:8.2f} "
                f"{total:6.1f}  {text}"
            )
            for issue in ln.score.get("issues", []):
                lines.append(f"        - {issue}")

    lines.append("=" * 78)
    return "\n".join(lines)
