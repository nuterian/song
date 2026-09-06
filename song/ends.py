"""Where a word ends, read off the vocal stem's envelope.

Word ends were the least trusted number in the file: both aligners measure
one, nothing refined it, and against gold the shipped ends ran 70 ms late at
the median with 7 of the 10 real rests closed. This module is the rule that
reads the end off the stem. It is deliberately stdlib-only - a list of
envelope values in dB and a hop in seconds - so the rule is pinned by tests
that run with nothing installed; `vad.VocalActivity.word_end` is the thin
wrapper that hands it a slice of the real envelope.

The rule, and why it is shaped this way (all measured on the gold set):

- The threshold is relative to the *word's own peak*, not a global gate. A
  quiet verse word and a belted chorus word have different floors, and the
  VAD gate is fooled by reverb and pads that sit 20 dB under the voice.
- It scans *backwards* from the next word's start. A forward scan that stops
  at the first long dip mistakes the stop closures inside "Silver", "becomes"
  and "electric" (100-150 ms of near silence) for rests, and no dip length
  separates those from a real rest, which can be 150 ms. What separates them
  is position: a rest is adjacent to the next word. Backward: median end error
  30 ms, p90 110 ms, 9 of 10 rests kept, on true starts. Forward with a
  120 ms bridge: p90 134 ms and only 8 rests.
- A short blob of energy right before the next word's start, separated from
  the word by a dip, is the next word's consonant (or a breath) and is skipped.
  60 ms is the size of a plosive burst; at 100 ms it starts eating the tails
  of real words.
- 12 dB below the peak. 8 dB is the gold convention for a fading held note
  and gives the smaller bias, but its p90 is 40 ms worse because vibrato dips
  cross it; 15 dB closes rests the singer took.

What it cannot do, measured: an end is only as good as the aligned starts on
either side of it. On true starts the rule is at 30 ms; on the project's own
starts it is at 127 ms, because a next start that is 100 ms late puts the next
word's vowel inside the window, and a word that starts inside the previous
word's held note has the wrong peak. That is item 3's problem, not this one's.
Hence the guard in `word_end`: the rule may always shorten (the envelope
saying the voice stopped is strong evidence) but may only lengthen across
frames that stay above threshold - the aligner being cautious about a tail on
continuous vocal - never across a dip. Without the guard, "wild" on the sample
track ran 1.2 s into "emotion" because the aligner had put "emotion" a second
late, and the outro "Gravity" swallowed the soft phrase after it.

Deliberately not implemented: reading an unvoiced final fricative back into
the word. "becomes" loses its final "s" (200 ms at -35 dB, under any
peak-relative threshold) and "beats" its "ts". That needs a noisiness measure,
which is item 2's spectral flatness, not more envelope.
"""

from __future__ import annotations

from typing import Sequence

# dB below the word's own peak that counts as the voice having stopped.
DROP_DB = 12.0
# A run of above-threshold frames this short, right before the next word and
# separated from this word by a dip, is the next word's consonant.
BLOB = 0.06
# A window with fewer frames than this has nothing to say.
MIN_FRAMES = 2


def settle(env: Sequence[float], hop: float, drop_db: float = DROP_DB, blob: float = BLOB) -> float:
    """The offset, in seconds from the window start, at which the voice stops.

    `env` is the envelope in dB from the word's start up to the next word's
    start (or the line end). Returns a value in (0, len(env) * hop]; a window
    that never falls below threshold ends at its limit - the words are shut.
    """
    n = len(env)
    if n < MIN_FRAMES:
        return n * hop
    threshold = max(env) - drop_db
    j = n - 1
    while j >= 0 and env[j] < threshold:
        j -= 1
    if j < 0:
        return hop
    if blob > 0:
        # How long is the run of voice that ends at j, and is it a fragment
        # separated from the word by a dip?
        k = j
        while k >= 0 and env[k] >= threshold:
            k -= 1
        if 0 <= k and (j - k) * hop < blob:
            m = k
            while m >= 0 and env[m] < threshold:
                m -= 1
            if m >= 0:
                j = m
    return (j + 1) * hop


def word_end(
    env: Sequence[float],
    hop: float,
    current: float | None = None,
    drop_db: float = DROP_DB,
    blob: float = BLOB,
) -> float:
    """`settle`, guarded against a wrong neighbour.

    `current` is the offset of the end the aligner reported. The rule may pull
    it earlier freely; it may push it later only while every frame between the
    old end and the new one stays above threshold, so a next word placed late
    cannot hand its vowel to this one.
    """
    proposed = settle(env, hop, drop_db, blob)
    if current is None or proposed <= current:
        return proposed
    if len(env) < MIN_FRAMES:
        return current
    threshold = max(env) - drop_db
    a = max(0, int(current / hop))
    b = min(len(env), int(proposed / hop))
    if any(v < threshold for v in env[a:b]):
        return current
    return proposed
