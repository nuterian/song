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
from .score import GATE, Scorecard, evidence, format_report, gate_failures, score_project
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
    # Both default on; off is for benchmarking one against the other, and is
    # not exposed on the command line for that reason.
    settle_ends: bool = True
    use_voicing: bool = True


Progress = Callable[[str], None]

# How far either side of the anchor to look for a line in the blind transcript.
# Comfortably wider than the anchor's observed error, far narrower than the gap
# between two repeats of the same chorus.
RT_WINDOW = 6.0

# A candidate this degenerate is a broken alignment, not a fast line.
MAX_WORDS_PER_SECOND = 12.0
MIN_LINE_DURATION = 0.25


# ---------------------------------------------------------------- evidence


# How the merge weighs a candidate's evidence. The blind transcription gets
# the largest single weight when it has an opinion, because it is the only
# signal that can say which of two candidates is right.
MERGE_WEIGHTS = {
    "coverage": 0.45, "onset": 0.22, "density": 0.15, "confidence": 0.18,
    "roundtrip": 0.55,
}


def _support(timing: LineTiming, activity: vad.VocalActivity, rt=None) -> float:
    """How well a candidate placement is backed by evidence outside itself."""
    parts, _ = evidence(
        activity, timing.start, timing.end, len(timing.words), timing.mean_prob,
        rt, timing.line_index,
    )
    weight = sum(MERGE_WEIGHTS[k] for k in parts)
    return sum(MERGE_WEIGHTS[k] * v for k, v in parts.items()) / weight


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
    rt: "roundtrip.RoundTrip | None" = None,
) -> dict[int, str]:
    """Adopt, per line, the candidate with the strongest acoustic support."""
    # A nudge toward the finer aligner when the evidence cannot separate them.
    bias = {"whisper": 0.02, "ctc_local": 0.01}
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
            value = _support(timing, activity, rt) + bias.get(name, 0.0)
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


def settle_syllables(project: Project, activity: vad.VocalActivity) -> int:
    """Place each word's syllables at the strongest onsets inside it.

    The plan expected to take this from the CTC aligner, which times every
    character. Measured against 38 syllable onsets placed by eye on the
    sample track, its character spikes land 154 ms off at the median - worse
    than dividing the word evenly (87 ms) - because on a held sung vowel the
    model emits the vowel once and bunches the remaining letters at the next
    attack: "gravity" comes out g-r-a at 65.0 s and v-i-t-y at 66.0-66.4,
    with the "t" closure audibly at 65.45. So the fractions come from the
    stem instead: for a word of n syllables, the n-1 strongest peaks of the
    onset-strength envelope inside it, at least 60 ms apart and 120 ms clear
    of the word's own edges. On the same 38: 60 ms median and 77% within
    100 ms when the word's bounds are right, 70 ms and 54% on the project's
    own bounds - a word that runs 300 ms into the next has the next word's
    attack as its strongest peak, which is what the wide margin is for (at
    50 ms the project number is 100 ms). Where too few peaks exist the rest
    are spread evenly, which on its own measures 87 ms.

    Fractions of the word, so they follow every later edit; see
    Word.syllables. Returns the number of words given syllables.
    """
    from .. import syllables as syl

    if activity.strength is None:
        return 0
    given = 0
    hop = activity.hop
    for line in project.lines:
        if line.end <= line.start:
            continue
        for word in line.words:
            parts = syl.split(word.text)
            span = word.end - word.start
            if len(parts) < 2 or span <= 0.1:
                word.syllables = []
                continue
            a = int((word.start + SYLLABLE_EDGE) / hop)
            b = int((word.end - SYLLABLE_EDGE) / hop)
            cuts = _strongest_peaks(activity.strength, a, b, len(parts) - 1, int(SYLLABLE_APART / hop))
            if len(cuts) < len(parts) - 1:
                cuts = _fill_evenly(cuts, a, b, len(parts) - 1)
            ats = [0.0] + [round(min(max((c * hop - word.start) / span, 0.001), 0.999), 3) for c in cuts]
            for k in range(1, len(ats)):
                ats[k] = max(ats[k], ats[k - 1] + 0.001)
            if ats[-1] >= 1.0:
                word.syllables = []
                continue
            word.syllables = [{"text": t, "at": at} for t, at in zip(parts, ats)]
            given += 1
    return given


# Syllable cuts stay this far from the word's edges - a syllable shorter than
# this at a word's edge is not a sweep anyone sees, and the next word's attack
# sits inside a late end - and this far from each other.
SYLLABLE_EDGE = 0.12
SYLLABLE_APART = 0.06


def _strongest_peaks(strength: np.ndarray, a: int, b: int, k: int, apart: int) -> list[int]:
    """Frame indices of the k largest local maxima in [a, b), `apart` frames apart."""
    a, b = max(0, a), min(len(strength), b)
    if b - a < 3 or k <= 0:
        return []
    seg = strength[a:b]
    peaks = [i for i in range(1, len(seg) - 1) if seg[i] >= seg[i - 1] and seg[i] > seg[i + 1]]
    peaks.sort(key=lambda i: -float(seg[i]))
    chosen: list[int] = []
    for i in peaks:
        if all(abs(i - c) >= apart for c in chosen):
            chosen.append(i)
        if len(chosen) == k:
            break
    return sorted(a + i for i in chosen)


def _fill_evenly(cuts: list[int], a: int, b: int, k: int) -> list[int]:
    """Top up `cuts` to k frames by spreading the rest over the largest gap."""
    cuts = list(cuts)
    while len(cuts) < k:
        bounds = [a] + cuts + [b]
        gaps = [(bounds[i + 1] - bounds[i], i) for i in range(len(bounds) - 1)]
        width, i = max(gaps)
        if width < 2:
            break
        cuts.append(bounds[i] + width // 2)
        cuts.sort()
    return cuts


def _polish(project: Project, activity: vad.VocalActivity, settle: bool = True) -> None:
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
    if settle:
        settle_word_ends(project, activity)
    settle_syllables(project, activity)


def settle_word_ends(project: Project, activity: vad.VocalActivity) -> int:
    """Read every word's end off the stem's envelope. Returns words moved.

    Runs after the line trim and the monotonic fix, so each word's window is
    bounded by the next word's start as it will ship. The last word of a line
    is bounded by the trimmed line end and can only pull it in: the VAD gate
    that trims lines is a global threshold, and a reverb tail or a pad 20 dB
    under the voice keeps it open long after the singer has stopped - line
    ends ran 155 ms late at the median against gold, p90 over a second.

    Measured on the sample track (song/ends.py has the isolation numbers):
    ends median 129 -> 127 ms, bias +70 -> +59 ms, rests kept 3 -> 5 of 10,
    8 words better by over 100 ms and 3 worse, all three next to a start the
    aligners had wrong by more than a second. Small in place because a word
    end is bounded by two starts; item 3 is what makes this rule worth 30 ms.
    """
    moved = 0
    for line in project.lines:
        if line.end <= line.start or line.locked or not line.words:
            continue
        for k, word in enumerate(line.words):
            limit = line.words[k + 1].start if k + 1 < len(line.words) else line.end
            end = activity.word_end(word.start, limit, current=word.end)
            if abs(end - word.end) > 1e-6:
                word.end = end
                moved += 1
        line.end = line.words[-1].end
        line.normalize_words()
    return moved


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
    activity = vad.analyse(samples, TARGET_SR, voicing_model=config.use_voicing)
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

    # The honest benchmark is the disagreement between the two pristine,
    # independent aligners - never between the merge and one of its own
    # inputs - so their spans go into the project before anything is scored,
    # and the score reads them from there like `song score` will later.
    _remember(project, "ctc", anchor)
    _remember(project, "whisper", refined.get("whisper", {}))
    project.meta["roundtrip"] = rt.to_dict() if rt else None

    _merge(project, candidates, activity, rt=rt)
    _polish(project, activity, settle=config.settle_ends)
    card = score_project(project, activity)

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

        for name, timings in retry.items():
            candidates[name] = {**candidates.get(name, {}), **timings}
        _remember(project, "whisper", retry.get("whisper", {}))

        _merge(project, candidates, activity, only=set(card.flagged), rt=rt)
        _polish(project, activity, settle=config.settle_ends)
        card = score_project(project, activity)
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


def _remember(project: Project, name: str, timings: dict[int, LineTiming]) -> None:
    """Keep one aligner's pristine spans in the project, by line index.

    This is what `song score` re-benchmarks manual edits against without
    re-running any model, and what the pipeline's own score reads too.
    """
    table = project.meta.setdefault("aligners", {}).setdefault(name, {})
    for index, t in timings.items():
        if t.end > t.start:
            table[str(index)] = [round(t.start, 3), round(t.end, 3)]


def rescore(
    project: Project, activity=None, samples: np.ndarray | None = None
) -> Scorecard:
    """Re-run the benchmark against whatever timings the project now holds.

    The stored aligner outputs and transcription observations mean this needs
    no models and runs in milliseconds; the only other cost is decoding and
    analysing the stem, which a caller holding one already (the server keeps
    one per open track) passes in as `activity`/`samples`.
    """
    if activity is None:
        if samples is None:
            samples, _ = load_mono(project.stem_path or project.audio_path, TARGET_SR)
        activity = vad.analyse(samples, TARGET_SR)
    return score_project(project, activity)


__all__ = ["Config", "run", "rescore", "format_report"]
