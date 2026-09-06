"""Word timing measured against a gold project, not against another model.

Every other number in this project is one model checking another: the
scorecard's "agreement" is Whisper against CTC, the round-trip is a third model
against both. That finds lines that are wrong, but it cannot say how wrong a
word is, because there is nothing under it. A gold file - one track whose
every word start and end was placed by a person - is that floor. This module
is the arithmetic between a candidate project and its gold, and it is
deliberately stdlib-only so the numbers it prints can be pinned by tests that
run with nothing installed.

What it reports, and why each thing is there:

- Per-word start error and end error, as a distribution (median, p90, max)
  and as "within 50 / 100 / 200 ms" percentages. 50 ms is about the finest a
  reviewer places a bound by ear at quarter speed; 200 ms is where a karaoke
  fill visibly leads or trails the singer.
- The same split by the candidate's own line score, so the score's calibration
  is visible: a well-calibrated score puts the large errors in the low bucket.
- Signed medians (candidate minus gold), because an aligner that is
  consistently 60 ms late is a different problem from one that scatters.
- Rests. The line model lets a word end before the next one starts; gold says
  which of those gaps were sung. For every pair of adjacent words the candidate
  either kept a gold rest, closed it, or invented one where the singer never
  stopped. This is the plan's "21-gap question" answered directly.
- First-word starts on their own, because those are the line placements: a
  line dropped four seconds late is one bad first-word start and a string of
  bad internal ones, and the structural items in the plan act on the former.

Deliberately not implemented: fuzzy pairing of words. Gold and candidate are
the same lyrics file aligned twice, so line i word k means the same syllables
in both; a project whose word count differs on a line is reported as unpaired
rather than matched by text, since a text match across a repeated chorus is
exactly the kind of quiet error this module exists to catch.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .project import Project

# A gap between two words at or above this is a rest the singer took. It is the
# karaoke renderer's MIN_REST (15 cs) in seconds, so what the bench counts as a
# rest is what the video would hold on.
REST = 0.15

# The error thresholds reported as "within N ms".
WITHIN = (0.05, 0.10, 0.20)

# Candidate line-score buckets, from the 0-100 score the pipeline assigns.
# 70 is FLAG_THRESHOLD; 90 is where the sample track's mean sits.
BUCKETS = (("90+", 90.0), ("70-90", 70.0), ("<70", -math.inf))


# ---------------------------------------------------------------- arithmetic


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile, so the answer is always a value in the list."""
    if not values:
        return math.nan
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def median(values: list[float]) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def distribution(signed: list[float]) -> dict:
    """Summary of a list of signed errors (candidate minus gold), in seconds."""
    absolute = [abs(x) for x in signed]
    return {
        "n": len(signed),
        "median": _r(median(absolute)),
        "p90": _r(percentile(absolute, 0.9)),
        "max": _r(max(absolute) if absolute else math.nan),
        "bias": _r(median(signed)),
        "within": {
            _ms(limit): _pct(sum(1 for x in absolute if x <= limit + 1e-9), len(absolute))
            for limit in WITHIN
        },
    }


def _r(x: float) -> float | None:
    return None if x != x else round(float(x), 3)


def _ms(seconds: float) -> str:
    return f"{round(seconds * 1000):d}ms"


def _pct(part: int, whole: int) -> float | None:
    return None if not whole else round(100.0 * part / whole, 1)


def bucket_of(line) -> str:
    total = float((line.score or {}).get("total", 0.0))
    for name, floor in BUCKETS:
        if total >= floor:
            return name
    return BUCKETS[-1][0]


# ---------------------------------------------------------------- pairing


def pair(gold: Project, candidate: Project) -> tuple[list[tuple], list[dict]]:
    """Match words by (line index, word index). Returns (pairs, unpaired).

    A pair is (gold line, candidate line, word index). A line whose word count
    differs between the two, or that only one side has timed, is listed in
    `unpaired` with the reason, and contributes nothing to the numbers.
    """
    pairs: list[tuple] = []
    unpaired: list[dict] = []
    by_index = {ln.index: ln for ln in candidate.lines}
    for g in gold.lines:
        c = by_index.get(g.index)
        if c is None:
            unpaired.append({"line": g.index, "why": "missing from candidate"})
            continue
        if g.end <= g.start or not g.words:
            unpaired.append({"line": g.index, "why": "not timed in gold"})
            continue
        if c.end <= c.start or not c.words:
            unpaired.append({"line": g.index, "why": "not timed in candidate"})
            continue
        if len(g.words) != len(c.words):
            unpaired.append({
                "line": g.index,
                "why": f"{len(g.words)} words in gold, {len(c.words)} in candidate",
            })
            continue
        for k in range(len(g.words)):
            pairs.append((g, c, k))
    return pairs, unpaired


# ---------------------------------------------------------------- the bench


def compare(gold: Project, candidate: Project) -> dict:
    """Everything the bench knows, as one JSON-able dict."""
    pairs, unpaired = pair(gold, candidate)

    starts: list[float] = []
    ends: list[float] = []
    first_starts: list[float] = []
    line_ends: list[float] = []
    by_bucket: dict[str, dict[str, list[float]]] = {
        name: {"start": [], "end": []} for name, _ in BUCKETS
    }
    worst: list[dict] = []

    for g, c, k in pairs:
        gw, cw = g.words[k], c.words[k]
        ds, de = cw.start - gw.start, cw.end - gw.end
        starts.append(ds)
        ends.append(de)
        if k == 0:
            first_starts.append(ds)
        if k == len(g.words) - 1:
            line_ends.append(de)
        b = by_bucket[bucket_of(c)]
        b["start"].append(ds)
        b["end"].append(de)
        worst.append({
            "line": g.index, "word": k, "text": gw.text,
            "start": round(ds, 3), "end": round(de, 3),
            "score": (c.score or {}).get("total"),
        })

    worst.sort(key=lambda w: -max(abs(w["start"]), abs(w["end"])))

    return {
        "n_words": len(pairs),
        "n_lines": len({g.index for g, _, _ in pairs}),
        "unpaired": unpaired,
        "start": distribution(starts),
        "end": distribution(ends),
        "line_start": distribution(first_starts),
        "line_end": distribution(line_ends),
        "by_score": {
            name: {"start": distribution(v["start"]), "end": distribution(v["end"])}
            for name, v in by_bucket.items()
        },
        "rests": rests(pairs),
        "worst": worst[:10],
    }


def rests(pairs: list[tuple]) -> dict:
    """Kept / closed / invented, over every adjacent word pair inside a line.

    Only the gap between two words of the *same* line is a rest the model can
    represent; the space between lines is not counted, because both projects
    always have it and it would drown the numbers in trivial agreement.
    """
    kept: list[dict] = []
    closed: list[dict] = []
    invented: list[dict] = []
    seen: set[int] = set()
    for g, c, _ in pairs:
        if g.index in seen:
            continue
        seen.add(g.index)
        for k in range(len(g.words) - 1):
            g_gap = g.words[k + 1].start - g.words[k].end
            c_gap = c.words[k + 1].start - c.words[k].end
            entry = {
                "line": g.index, "after": k, "text": g.words[k].text,
                "gold": round(g_gap, 3), "candidate": round(c_gap, 3),
            }
            gold_rest = g_gap >= REST - 1e-9
            cand_rest = c_gap >= REST - 1e-9
            if gold_rest and cand_rest:
                kept.append(entry)
            elif gold_rest:
                closed.append(entry)
            elif cand_rest:
                invented.append(entry)
    return {
        "in_gold": len(kept) + len(closed),
        "kept": kept,
        "closed": closed,
        "invented": invented,
    }


# ---------------------------------------------------------------- reporting


def _dist_line(label: str, d: dict) -> str:
    if not d["n"]:
        return f"  {label:<22} (no words)"
    within = "  ".join(f"<={k} {v:5.1f}%" for k, v in d["within"].items())
    return (
        f"  {label:<22} n={d['n']:<4} median {_fmt_ms(d['median'])}  "
        f"p90 {_fmt_ms(d['p90'])}  max {_fmt_ms(d['max'])}  "
        f"bias {_fmt_ms(d['bias'], signed=True)}   {within}"
    )


def _fmt_ms(seconds: float | None, signed: bool = False) -> str:
    if seconds is None:
        return "   n/a"
    ms = seconds * 1000.0
    return f"{ms:+6.0f}ms" if signed else f"{ms:5.0f}ms"


def format_report(result: dict, gold_name: str = "", candidate_name: str = "") -> str:
    lines = ["", "=" * 96, "WORD TIMING AGAINST GOLD"]
    if gold_name or candidate_name:
        lines.append(f"  {candidate_name}  vs  {gold_name}")
    lines.append("=" * 96)
    lines.append(
        f"  paired words             {result['n_words']} over {result['n_lines']} lines"
        + (f"  ({len(result['unpaired'])} line(s) unpaired)" if result["unpaired"] else "")
    )
    for u in result["unpaired"]:
        lines.append(f"      line {u['line']:>3}: {u['why']}")
    lines.append("-" * 96)
    lines.append(_dist_line("word starts", result["start"]))
    lines.append(_dist_line("word ends", result["end"]))
    lines.append(_dist_line("line starts", result["line_start"]))
    lines.append(_dist_line("line ends", result["line_end"]))
    lines.append("-" * 96)
    lines.append("  by candidate line score")
    for name, d in result["by_score"].items():
        lines.append(_dist_line(f"  {name} starts", d["start"]))
        lines.append(_dist_line(f"  {name} ends", d["end"]))
    r = result["rests"]
    lines.append("-" * 96)
    lines.append(
        f"  rests (gap >= {_ms(REST)}) in gold {r['in_gold']}: kept {len(r['kept'])}, "
        f"closed {len(r['closed'])}, invented {len(r['invented'])}"
    )
    for label, entries in (("closed", r["closed"]), ("invented", r["invented"])):
        for e in entries:
            lines.append(
                f"      {label:<8} line {e['line']:>3} after {e['text']!r:<14} "
                f"gold {e['gold']:6.3f}s  candidate {e['candidate']:6.3f}s"
            )
    if result["worst"]:
        lines.append("-" * 96)
        lines.append("  largest errors")
        for w in result["worst"]:
            lines.append(
                f"      line {w['line']:>3} word {w['word']:>2} {w['text']!r:<14} "
                f"start {w['start']:+7.3f}s  end {w['end']:+7.3f}s"
                + (f"  score {w['score']}" if w["score"] is not None else "")
            )
    lines.append("=" * 96)
    return "\n".join(lines)


def run(candidate_path: Path | str, gold_path: Path | str) -> dict:
    gold = Project.load(gold_path)
    candidate = Project.load(candidate_path)
    return compare(gold, candidate)


def default_gold(project: Project, root: Path | str = "examples/gold") -> Path:
    """`examples/gold/<track slug>.project.json`, keyed on the audio file's name.

    The workdir's name is not used: the sample track lives in two workdirs
    (one aligned before word ends were real, one after) and both are the same
    song against the same gold.
    """
    from .project import slugify

    return Path(root) / f"{slugify(Path(project.audio_path).stem)}.project.json"


def to_json(result: dict) -> str:
    return json.dumps(result, indent=1)
