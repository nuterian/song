"""Cut a word into syllables, deterministically, with no dictionary.

The karaoke fill wants one sweep per syllable, and the CTC aligner already
times every letter; what is missing is where the syllables are. This is the
rule for that. It is stdlib-only and pinned on the sample track's whole
vocabulary (91 words) in tests/test_syllables.py, which is also where its
known miss lives.

How it counts: a vowel group (a, e, i, o, u, y) is a nucleus, then three
corrections that account for nearly every English word that fools the raw
count - a final silent "e" ("haze", "pure", "where"; not "-le"), a final
"-es" that is not a syllable ("fades", "becomes"; but "pulses", "bodies"),
and a final "-thm"/"-sm" that is one ("rhythm"). On the 91 words the raw
count is wrong on 22; with the corrections it is wrong on one, "something",
whose internal silent "e" nothing short of a dictionary catches.

How it splits: a single consonant between nuclei goes to the following
syllable ("gra-vi-ty", "mo-tion"); two split between them ("sil-ver",
"end-less"), except that a digraph ("th", "sh", "ch", "ph", "wh", "ck")
stays whole ("wi-thin"); three or more keep a doubled letter together
("end-less-ly"), else keep a legal onset together ("ex-plo-sion",
"e-lec-tric"), else split before the last consonant. This is a placement
rule, not a dictionary, and where it differs from one the cut is one
consonant off - for timing a fill, the width of one plosive.

Deliberately not implemented: pyphen. It is a pure-Python hyphenation
dictionary and would fix "something" and "explosion", but it hyphenates
rather than syllabifies, it is a dependency the stdlib-only test suite could
not exercise, and the errors it fixes are one plosive wide.
"""

from __future__ import annotations

import re

VOWELS = set("aeiouy")
DIGRAPHS = ("th", "sh", "ch", "ph", "wh", "ck")
# Two-consonant clusters English lets a syllable begin with; a three-letter
# cluster between two nuclei is cut so that one of these starts the second.
ONSETS = {
    "bl", "br", "cl", "cr", "dr", "fl", "fr", "gl", "gr", "pl", "pr", "sc",
    "sk", "sl", "sm", "sn", "sp", "st", "sw", "tr", "tw", "th", "sh", "ch",
    "ph", "wh", "wr", "kn", "qu", "dw", "gn",
}

_NUCLEUS = re.compile(r"[aeiouy]+")


def letters(word: str) -> str:
    """The word as the syllable rule sees it: lowercase letters only."""
    return re.sub(r"[^a-z]", "", word.lower())


def _nuclei(w: str) -> list[tuple[int, int]]:
    """(start, end) of each vowel group, after the silent-ending corrections."""
    spans = [(m.start(), m.end()) for m in _NUCLEUS.finditer(w)]
    if len(spans) > 1:
        last = spans[-1]
        if w.endswith("e") and not w.endswith("le") and last == (len(w) - 1, len(w)):
            spans.pop()
        elif (w.endswith("es") and last == (len(w) - 2, len(w) - 1)
              and not w.endswith(("ses", "xes", "zes", "shes", "ches"))):
            spans.pop()
    return spans


def count(word: str) -> int:
    w = letters(word)
    if not w:
        return 1
    n = len(_nuclei(w))
    if w.endswith(("thm", "sm")) and not w.endswith("ism"):
        n += 1
    return max(1, n)


def split(word: str) -> list[str]:
    """The word's letters cut into syllables; a single chunk when it is one.

    Only letters are returned - the caller lines these up against a token
    that may carry capitals and punctuation, or against the CTC aligner's
    normalised form, by letter count.
    """
    w = letters(word)
    if not w:
        return [w]
    nuclei = _nuclei(w)
    if len(nuclei) < 2:
        parts = [w]
    else:
        cuts = []
        for (_, a_end), (b_start, _) in zip(nuclei, nuclei[1:]):
            cluster = w[a_end:b_start]
            k = len(cluster)
            if k <= 1:
                cut = a_end                       # V-CV
            elif cluster[:2] in DIGRAPHS and k == 2:
                cut = a_end                       # keep "th" with what follows
            elif k >= 3:
                if cluster[0] == cluster[1]:
                    cut = a_end + 2               # end-less-ly: the double stays
                elif cluster[-2:] in ONSETS:
                    cut = b_start - 2             # ex-plo-sion, e-lec-tric
                else:
                    cut = b_start - 1             # before the last consonant
                if w[cut - 1:cut + 1] in DIGRAPHS and cluster[-2:] not in ONSETS:
                    cut -= 1
            else:
                cut = a_end + 1                   # VC-CV
            cuts.append(cut)
        parts, at = [], 0
        for cut in cuts:
            parts.append(w[at:cut])
            at = cut
        parts.append(w[at:])
    if w.endswith("thm") and len(parts[-1]) > 3:
        tail = parts.pop()
        parts += [tail[:-3], tail[-3:]]           # rhy-thm
    elif w.endswith("sm") and not w.endswith("ism") and len(parts[-1]) > 2:
        tail = parts.pop()
        parts += [tail[:-2], tail[-2:]]           # pri-sm
    return [p for p in parts if p]


def chunk_starts(text: str, parts: list[str]) -> list[int] | None:
    """Where each syllable chunk begins in `text`, which may carry capitals,
    apostrophes and punctuation the chunks do not.

    Non-letters attach to the chunk before them, so "Gravity," cut as
    ["gra", "vi", "ty"] starts at [0, 3, 5] and the comma rides on "ty".
    None when the letters do not line up, which is the caller's cue to leave
    the word whole.
    """
    if "".join(parts) != letters(text):
        return None
    starts = [0]
    need = len(parts[0])
    seen = 0
    for i, ch in enumerate(text):
        if not ch.isalpha():
            continue
        if seen == need and len(starts) < len(parts):
            starts.append(i)
            need += len(parts[len(starts) - 1])
        seen += 1
    return starts if len(starts) == len(parts) else None


def chunks(text: str, parts: list[str]) -> list[str]:
    """`text` cut where `parts` says, or whole when they do not line up."""
    starts = chunk_starts(text, parts)
    if starts is None:
        return [text]
    return [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]
