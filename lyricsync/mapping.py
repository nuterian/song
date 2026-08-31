"""Map a flat sequence of aligned words back onto lyric lines.

Forced aligners return words for the whole passage; the exporters need to know
which words belong to which lyric line. Segment boundaries reported by the
aligner are unreliable, so the mapping is done on a normalized character
stream, which is exact whenever the aligner consumed the text we gave it.
"""

from __future__ import annotations

from difflib import SequenceMatcher


def _char_stream(chunks: list[str]) -> tuple[str, list[int]]:
    """Concatenate alphanumerics of each chunk, tracking the owning chunk index."""
    chars: list[str] = []
    owners: list[int] = []
    for i, chunk in enumerate(chunks):
        for c in chunk.lower():
            if c.isalnum():
                chars.append(c)
                owners.append(i)
    return "".join(chars), owners


def map_words_to_lines(
    word_texts: list[str], line_texts: list[str], strict: bool = False
) -> list[int | None]:
    """For each word, the index of the lyric line it belongs to.

    With `strict`, words that share no characters with the lyrics stay None
    instead of inheriting a neighbour's line. Forced alignment wants every word
    placed; matching a free transcription against the lyrics wants only the
    words that genuinely matched.
    """
    if not word_texts:
        return []

    w_stream, w_owner = _char_stream(word_texts)
    l_stream, l_owner = _char_stream(line_texts)

    if not w_stream or not l_stream:
        return [None] * len(word_texts)

    # Character position in the word stream -> position in the line stream.
    pos_map: dict[int, int] = {}
    if w_stream == l_stream:
        pos_map = {i: i for i in range(len(w_stream))}
    else:
        matcher = SequenceMatcher(None, w_stream, l_stream, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for offset in range(i2 - i1):
                    pos_map[i1 + offset] = j1 + offset

    # Each word takes the line owning the majority of its mapped characters.
    votes: list[dict[int, int]] = [{} for _ in word_texts]
    for char_pos, word_index in enumerate(w_owner):
        line_pos = pos_map.get(char_pos)
        if line_pos is None:
            continue
        line_index = l_owner[line_pos]
        votes[word_index][line_index] = votes[word_index].get(line_index, 0) + 1

    result: list[int | None] = []
    for tally in votes:
        result.append(max(tally, key=tally.get) if tally else None)

    if strict:
        return result

    # Unmatched words inherit the previous word's line so nothing is orphaned.
    last: int | None = None
    for i, line_index in enumerate(result):
        if line_index is None:
            result[i] = last
        else:
            last = line_index

    # Then fill any leading gap from the first known assignment.
    first_known = next((x for x in result if x is not None), None)
    if first_known is not None:
        for i, line_index in enumerate(result):
            if line_index is None:
                result[i] = first_known
            else:
                break

    return result


def group_by_line(
    word_texts: list[str], line_texts: list[str]
) -> list[list[int]]:
    """Word indices per line, in order."""
    assignment = map_words_to_lines(word_texts, line_texts)
    groups: list[list[int]] = [[] for _ in line_texts]
    for word_index, line_index in enumerate(assignment):
        if line_index is not None and 0 <= line_index < len(groups):
            groups[line_index].append(word_index)
    return groups
