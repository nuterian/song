"""The alignment pipeline: a coarse-to-fine cascade behind a quality gate.

Why it is shaped this way
-------------------------
Whisper forced-alignment run over a whole song desynchronizes: a 4-bar
instrumental is longer than its 30-second attention window, and once it loses
the thread the rest of the track slides. Measured on the sample track, a global
Whisper pass put the closing line at 2:37 in a 4:46 song.

CTC forced alignment does not have that failure mode - it emits per-frame
probabilities and finds one globally optimal path, so instrumental stretches are
simply absorbed as blanks. But it is coarser at word edges.

So: CTC anchors the structure over the whole track, then Whisper refines inside
each section on a short crop, where it is both accurate and precise. The two
outputs stay pristine and their disagreement is the benchmark; a separate
best-of merge decides what actually ships.

Both aligners are *told* the lyrics, so both can be confidently wrong in the
same place, and their agreement cannot say which of two candidates is right. A
third pass transcribes the vocal blind - told nothing - and where it heard each
line is what adjudicates the merge.

    parse -> separate -> transcribe blind (independent evidence)
                            |
                            v
                       anchor (CTC, whole track)
                            |
                            v
                       refine (Whisper, per-section crop)
                            |
                            v
              merge (best-supported candidate per line) -> polish -> score
                            |                                          |
                            +------------ retry failing sections <-----+
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .. import parse_lyrics, vad
from . import roundtrip
from .whisper import DEFAULT_MODEL, LineTiming, align_lines, load_aligner
from .ctc import align_lines_ctc
from ..audio import TARGET_SR, load_mono, probe_duration
from ..project import Project, slugify
from .score import GATE, Scorecard, format_report, gate_failures, score_project
from .separate import separate_vocals


@dataclass
class Config:
    whisper_model: str = DEFAULT_MODEL
    whisper_model_retry: str = "large-v3-turbo"
    device: str = "cpu"
    demucs_model: str = "htdemucs"
    demucs_device: str = "cpu"
    crop_pad: float = 2.0
    crop_pad_retry: float = 5.0
    max_iterations: int = 2
    skip_separation: bool = False
    roundtrip_model: str = "medium"
    use_roundtrip: bool = True
    gate: dict = field(default_factory=lambda: dict(GATE))


Progress = Callable[[str], None]

# How far either side of the anchor to look for a line in the blind transcript.
# Comfortably wider than the anchor's observed error, far narrower than the gap
# between two repeats of the same chorus.
RT_WINDOW = 6.0

# A candidate this degenerate is a broken alignment, not a fast line.
MAX_WORDS_PER_SECOND = 12.0
MIN_LINE_DURATION = 0.25


# ---------------------------------------------------------------- evidence


def _acoustic_score(
    timing: LineTiming,
    activity: vad.VocalActivity,
    rt: "roundtrip.RoundTrip | None" = None,
) -> float:
    """How well a candidate placement is supported by evidence outside itself.

    Deliberately excludes cross-aligner agreement: agreement is symmetric, so it
    says a line is uncertain but cannot say which candidate is right. The blind
    transcription can, and gets the largest single weight when it has an opinion.
    """
    from .score import _ramp

    duration = timing.end - timing.start
    if duration <= 0:
        return 0.0

    coverage = activity.coverage(timing.start, timing.end)
    onset_distance = activity.nearest_onset(timing.start)
    density = len(timing.words) / duration if timing.words else 0.0

    if density < 1.0:
        density_term = _ramp(density, good=1.0, bad=0.25)
    elif density > 5.5:
        density_term = _ramp(density, good=5.5, bad=11.0)
    else:
        density_term = 1.0

    parts = {
        "coverage": (0.45, _ramp(coverage, good=0.65, bad=0.15)),
        "onset": (0.22, _ramp(onset_distance, good=0.12, bad=0.7)),
        "density": (0.15, density_term),
        "prob": (0.18, _ramp(timing.mean_prob, good=0.6, bad=0.05)),
    }

    support = rt.support(timing.line_index, timing.start, timing.end) if rt else None
    if support is not None:
        parts["roundtrip"] = (0.55, support)

    total_weight = sum(w for w, _ in parts.values())
    return sum(w * v for w, v in parts.values()) / total_weight


def _section_span(
    section_line_indices: list[int],
    timings: dict[int, LineTiming],
    pad: float,
    duration: float,
) -> tuple[float, float] | None:
    spans = [
        timings[i] for i in section_line_indices if i in timings and timings[i].end > timings[i].start
    ]
    if not spans:
        return None
    start = max(0.0, min(s.start for s in spans) - pad)
    end = min(duration, max(s.end for s in spans) + pad)
    return (start, end) if end > start + 0.5 else None


def _refine_sections(
    samples: np.ndarray,
    lyrics: parse_lyrics.Lyrics,
    anchor: dict[int, LineTiming],
    sections: list[int],
    model_name: str,
    device: str,
    pad: float,
    duration: float,
    progress: Progress,
    also_ctc: bool = False,
) -> dict[str, dict[int, LineTiming]]:
    """Re-align the given sections on short crops guided by the anchor."""
    out: dict[str, dict[int, LineTiming]] = {"whisper": {}}
    if also_ctc:
        out["ctc_local"] = {}

    model = load_aligner(model_name, device)

    for section_index in sections:
        section = lyrics.sections[section_index]
        span = _section_span(section.line_indices, anchor, pad, duration)
        if span is None:
            continue
        start, end = span
        crop = samples[int(start * TARGET_SR) : int(end * TARGET_SR)]
        texts = [lyrics.lines[i].text for i in section.line_indices]

        progress(
            f"    refining {section.name} [{start:6.1f}-{end:6.1f}s] "
            f"({len(texts)} lines)"
        )
        try:
            for timing in align_lines(
                crop,
                texts,
                line_indices=section.line_indices,
                model=model,
                offset=start,
            ):
                out["whisper"][timing.line_index] = timing
        except Exception as exc:  # a bad crop must not sink the whole run
            progress(f"      whisper refine failed: {exc}")

        if also_ctc:
            try:
                for timing in align_lines_ctc(
                    crop,
                    texts,
                    line_indices=section.line_indices,
                    device=device,
                    offset=start,
                ):
                    out["ctc_local"][timing.line_index] = timing
            except Exception as exc:
                progress(f"      local ctc refine failed: {exc}")

    return out


def _merge(
    project: Project,
    candidates: dict[str, dict[int, LineTiming]],
    activity: vad.VocalActivity,
    only: set[int] | None = None,
    bias: dict[str, float] | None = None,
    rt: "roundtrip.RoundTrip | None" = None,
) -> dict[int, str]:
    """Adopt, per line, the candidate with the strongest acoustic support."""
    bias = bias or {"whisper": 0.02, "ctc_local": 0.01, "ctc": 0.0}
    chosen: dict[int, str] = {}

    for line in project.lines:
        if only is not None and line.index not in only:
            continue
        if line.locked:
            continue

        usable, degenerate = [], []
        for name, timings in candidates.items():
            timing = timings.get(line.index)
            if timing is None or timing.end <= timing.start:
                continue
            span = timing.end - timing.start
            words = len(timing.words) or 1
            if span < MIN_LINE_DURATION or words / span > MAX_WORDS_PER_SECOND:
                degenerate.append((name, timing))
            else:
                usable.append((name, timing))

        # Only fall back to a collapsed candidate if there is nothing sane.
        pool = usable or degenerate

        best_name, best_timing, best_value = None, None, -1.0
        for name, timing in pool:
            value = _acoustic_score(timing, activity, rt) + bias.get(name, 0.0)
            if value > best_value:
                best_name, best_timing, best_value = name, timing, value

        if best_timing is None:
            continue

        line.words = list(best_timing.words)
        line.start = best_timing.start
        line.end = best_timing.end
        line.source = best_name
        chosen[line.index] = best_name

    return chosen


def _polish(project: Project, activity: vad.VocalActivity) -> None:
    """Trim spans onto real singing, snap starts to onsets, fix ordering."""
    for line in project.lines:
        if line.end <= line.start or line.locked:
            continue

        start, end = activity.trim(line.start, line.end)
        snapped = activity.snap_to_onset(start, max_shift=0.25)
        if snapped < end - 0.2:
            start = snapped
        if end > start + 0.2:
            line.retime(start, end)

    project.enforce_monotonic()


# ---------------------------------------------------------------- the loop


def run(
    audio_path: Path | str,
    lyrics_path: Path | str,
    workdir: Path | str | None = None,
    config: Config | None = None,
    progress: Progress = print,
) -> tuple[Project, Scorecard]:
    config = config or Config()
    audio_path = Path(audio_path)
    lyrics_path = Path(lyrics_path)
    workdir = Path(workdir or Path("workdir") / slugify(audio_path.stem))
    workdir.mkdir(parents=True, exist_ok=True)

    started = time.time()

    progress(f"[1/6] parsing {lyrics_path.name}")
    lyrics = parse_lyrics.parse_file(lyrics_path)
    duration = probe_duration(audio_path)
    progress(
        f"      {len(lyrics.lines)} lines in {len(lyrics.sections)} sections; "
        f"track {duration:.1f}s"
    )

    if config.skip_separation:
        stem_path = audio_path
        progress("[2/6] separation skipped; aligning against the full mix")
    else:
        progress("[2/6] isolating vocals (demucs)")
        stem_path = separate_vocals(
            audio_path,
            workdir,
            model=config.demucs_model,
            device=config.demucs_device,
        )
        progress(f"      stem: {stem_path}")

    samples, _ = load_mono(stem_path, TARGET_SR)

    progress("[3/6] analysing vocal activity")
    activity = vad.analyse(samples, TARGET_SR)
    active_ratio = float(np.mean(activity.active))
    progress(
        f"      vocal present {active_ratio:.0%} of track, "
        f"{len(activity.onsets)} onsets, gate {activity.threshold_db:.1f} dB"
    )

    project = Project.from_lyrics(lyrics, audio_path, lyrics_path, duration, workdir)
    project.stem_path = str(stem_path)

    texts = [ln.text for ln in lyrics.lines]
    indices = [ln.index for ln in lyrics.lines]

    progress("[4/7] anchoring structure (wav2vec2 CTC, whole track)")
    anchor_list = align_lines_ctc(samples, texts, line_indices=indices, device=config.device)
    anchor = {t.line_index: t for t in anchor_list}
    progress(f"      anchored {sum(1 for t in anchor_list if t.end > t.start)} lines")

    rt = None
    if config.use_roundtrip:
        progress("[5/7] blind transcription for independent corroboration")
        try:
            # Search each line only near where the anchor put it. The anchor is
            # reliable about structure even when it is loose about edges, and a
            # window keeps a repeated chorus from matching the wrong repeat.
            windows = {
                t.line_index: (t.start - RT_WINDOW, t.end + RT_WINDOW)
                for t in anchor_list
                if t.end > t.start
            }
            rt = roundtrip.observe(
                samples,
                texts,
                windows=windows,
                line_indices=indices,
                model_size=config.roundtrip_model,
                device=config.device,
            )
            heard = sum(1 for o in rt.per_line.values() if o.trustworthy)
            progress(
                f"      transcribed {len(rt.words)} words; "
                f"independently located {heard}/{len(texts)} lines"
            )
        except Exception as exc:
            progress(f"      round-trip unavailable ({exc}); continuing without it")
            rt = None

    progress(f"[6/7] refining per section (whisper {config.whisper_model})")
    refined = _refine_sections(
        samples,
        lyrics,
        anchor,
        sections=[s.index for s in lyrics.sections],
        model_name=config.whisper_model,
        device=config.device,
        pad=config.crop_pad,
        duration=duration,
        progress=progress,
    )

    candidates: dict[str, dict[int, LineTiming]] = {"ctc": anchor, **refined}

    # The honest benchmark: disagreement between the two pristine, independent
    # aligners - never between the merge and one of its own inputs.
    pristine = {"ctc": anchor, "whisper": dict(refined.get("whisper", {}))}

    _merge(project, candidates, activity, rt=rt)
    _polish(project, activity)

    card = score_project(
        project, activity, reference=anchor, deltas=_deltas(pristine), rt=rt
    )

    progress("[7/7] quality gate")
    failures = gate_failures(card, config.gate)
    iteration = 0

    # Repair is driven by weak *lines*, not only by a failing track gate. A
    # track can clear every aggregate threshold while still holding one badly
    # placed line, and that line is exactly what a viewer notices. The gate
    # answers "is something systemically wrong?"; the flags answer "which lines
    # can still be improved?", and both are reasons to try again.
    while (failures or card.flagged) and iteration < config.max_iterations:
        iteration += 1
        if failures:
            progress(f"      gate failed: {'; '.join(failures)}")
        else:
            progress(
                f"      gate passed, but {card.n_flagged} line(s) still weak - "
                f"attempting repair"
            )

        failing_sections = sorted(
            {project.lines[i].section for i in card.flagged if i < len(project.lines)}
        )
        if not failing_sections:
            progress("      no section-level cause to retry; stopping")
            break

        before = {i: (project.lines[i].start, project.lines[i].end) for i in card.flagged}

        names = ", ".join(lyrics.sections[s].name for s in failing_sections)
        model_name = (
            config.whisper_model_retry if iteration == 1 else config.whisper_model
        )
        pad = config.crop_pad_retry * iteration
        progress(
            f"      retry {iteration}: re-aligning [{names}] "
            f"with whisper {model_name}, pad {pad:.0f}s, plus local CTC"
        )

        retry = _refine_sections(
            samples,
            lyrics,
            anchor,
            sections=failing_sections,
            model_name=model_name,
            device=config.device,
            pad=pad,
            duration=duration,
            progress=progress,
            also_ctc=True,
        )

        retry_candidates = dict(candidates)
        for name, timings in retry.items():
            merged_source = dict(retry_candidates.get(name, {}))
            merged_source.update(timings)
            retry_candidates[f"{name}_r{iteration}"] = timings
            retry_candidates[name] = merged_source

        flagged_lines = set(card.flagged)
        _merge(project, retry_candidates, activity, only=flagged_lines, rt=rt)
        _polish(project, activity)

        for line_index, timing in retry.get("whisper", {}).items():
            pristine["whisper"][line_index] = timing

        candidates = retry_candidates
        card = score_project(
            project, activity, reference=anchor, deltas=_deltas(pristine), rt=rt
        )
        failures = gate_failures(card, config.gate)

        moved = sum(
            1
            for i, span in before.items()
            if abs(project.lines[i].start - span[0]) > 0.02
            or abs(project.lines[i].end - span[1]) > 0.02
        )
        progress(
            f"      retry {iteration}: {moved} line(s) improved, "
            f"{card.n_flagged} still weak"
        )
        # Another identical pass would spend minutes to change nothing.
        if moved == 0:
            progress("      no candidate beat what was already chosen; stopping")
            break

    if failures:
        progress(f"      gate failing: {'; '.join(failures)}")
        progress("      flagged lines are marked for manual review in the UI")
    elif card.flagged:
        progress(
            f"      gate passed; {card.n_flagged} line(s) remain uncertain and "
            f"are flagged for review"
        )
    else:
        progress("      gate passed, no lines flagged")

    project.scorecard = card.to_dict()
    # Keep the independent evidence with the project so `song score` can
    # re-benchmark manual edits without re-running any model.
    project.meta["aligners"] = {
        name: {
            str(i): [round(t.start, 3), round(t.end, 3)]
            for i, t in timings.items()
            if t.end > t.start
        }
        for name, timings in pristine.items()
    }
    project.meta["roundtrip"] = rt.to_dict() if rt else None
    project.meta.update(
        {
            "iterations": iteration,
            "whisper_model": config.whisper_model,
            "demucs_model": None if config.skip_separation else config.demucs_model,
            "roundtrip_model": config.roundtrip_model if rt else None,
            "elapsed_seconds": round(time.time() - started, 1),
            "gate_failures": failures,
        }
    )
    project.save(workdir / "project.json")

    progress(f"      done in {time.time() - started:.0f}s")
    return project, card


def _deltas(
    pristine: dict[str, dict[int, LineTiming]]
) -> dict[int, tuple[float, float]]:
    """Per-line |start| and |end| disagreement between the two aligner families."""
    a = pristine.get("ctc", {})
    b = pristine.get("whisper", {})
    out: dict[int, tuple[float, float]] = {}
    for index, left in a.items():
        right = b.get(index)
        if right is None or left.end <= left.start or right.end <= right.start:
            continue
        out[index] = (abs(left.start - right.start), abs(left.end - right.end))
    return out


def rescore(
    project: Project,
    activity=None,
    samples: np.ndarray | None = None,
    progress: Progress = print,
) -> Scorecard:
    """Re-run the benchmark against whatever timings the project now holds.

    Used after manual edits, so the scorecard measures the file that actually
    ships rather than only the automatic pass. The stored aligner outputs and
    transcription observations mean this needs no models and runs in seconds -
    the only other cost is decoding and analysing the stem, which a caller
    holding one already (the server keeps one per open track) can pass straight
    in via `activity`/`samples` rather than paying for another ffmpeg decode and
    VAD pass on every click.
    """
    stem = project.stem_path or project.audio_path
    if activity is None:
        if samples is None:
            samples, _ = load_mono(stem, TARGET_SR)
        activity = vad.analyse(samples, TARGET_SR)

    stored = project.meta.get("aligners") or {}
    reference = {
        int(i): LineTiming(line_index=int(i), start=span[0], end=span[1])
        for i, span in (stored.get("ctc") or {}).items()
    }

    # For lines nobody touched, the honest disagreement is still the one
    # between the two pristine aligners. For edited lines, compare the human's
    # timing directly against the independent aligner.
    frozen: dict[int, tuple[float, float]] = {}
    whisper = stored.get("whisper") or {}
    for key, span in (stored.get("ctc") or {}).items():
        other = whisper.get(key)
        index = int(key)
        if other is None or index >= len(project.lines):
            continue
        if project.lines[index].source == "manual":
            continue
        frozen[index] = (abs(span[0] - other[0]), abs(span[1] - other[1]))

    card = score_project(
        project,
        activity,
        reference=reference,
        deltas=frozen or None,
        rt=roundtrip.RoundTrip.from_dict(project.meta.get("roundtrip")),
    )
    project.scorecard = card.to_dict()
    return card


__all__ = ["Config", "run", "rescore", "format_report"]
