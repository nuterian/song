"""Matching a free transcription's words back onto known lyrics.

This is what makes a repeated chorus resolvable: matching is order-preserving
over a character stream, so the fourth "You're my gravity in motion" attaches to
the fourth occurrence rather than the first.
"""

import unittest

from song.align.mapping import map_words_to_lines


LINES = ["You're my gravity in motion",
         "Spinning worlds in slow explosion",
         "You're my gravity in motion"]


class OrderIsPreserved(unittest.TestCase):
    def test_identical_streams_map_one_to_one(self):
        words = " ".join(LINES).split()
        got = map_words_to_lines(words, LINES)
        self.assertEqual(got, [0] * 5 + [1] * 5 + [2] * 5)

    def test_a_repeated_line_attaches_by_position_not_by_text(self):
        words = " ".join(LINES).split()
        got = map_words_to_lines(words, LINES)
        # The last five words are the *same text* as the first five.
        self.assertEqual(got[-5:], [2, 2, 2, 2, 2])

    def test_a_missing_word_does_not_derail_the_rest(self):
        words = " ".join(LINES).replace("Spinning ", "").split()
        got = map_words_to_lines(words, LINES)
        self.assertEqual(got[0], 0)
        self.assertEqual(got[-1], 2)
        self.assertEqual(sorted(set(got)), [0, 1, 2])


class StrictMode(unittest.TestCase):
    """Strict is for a blind transcription: only genuine matches get a line."""

    def test_foreign_words_stay_unassigned(self):
        got = map_words_to_lines(["zzz", "qqq"], LINES, strict=True)
        self.assertEqual(got, [None, None])

    def test_lenient_mode_lets_a_stray_word_inherit_its_neighbours(self):
        # Forced alignment wants every word placed, so a mis-heard word sitting
        # between two matched ones takes their line rather than being dropped.
        words = "You're my ZZZ gravity in motion".split()
        got = map_words_to_lines(words, LINES, strict=False)
        self.assertEqual(got[2], 0)

    def test_lenient_mode_has_nothing_to_inherit_when_nothing_matches(self):
        self.assertEqual(map_words_to_lines(["zzz", "qqq"], LINES, strict=False),
                         [None, None])

    def test_real_words_still_match_in_strict_mode(self):
        got = map_words_to_lines("You're my gravity in motion".split(), LINES, strict=True)
        self.assertEqual(got, [0] * 5)


class Degenerate(unittest.TestCase):
    def test_no_words_gives_no_assignments(self):
        self.assertEqual(map_words_to_lines([], LINES), [])

    def test_no_lines_leaves_every_word_unplaced(self):
        self.assertEqual(map_words_to_lines(["a", "b"], []), [None, None])


if __name__ == "__main__":
    unittest.main()
