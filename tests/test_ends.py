"""The word-end rule, pinned on synthetic envelopes.

Each envelope is a list of dB values at a 10 ms hop, shaped like one thing the
stem does: a word shut against the next, a rest, a stop closure inside a word,
a plosive burst belonging to the next word. The numbers here are the ones the
rule was chosen on (see song/ends.py); a change to them is a change to every
word end in every export.
"""

import unittest

from song import ends

HOP = 0.01


def env(*runs):
    """(dB, seconds) pairs -> a flat list of frames."""
    out = []
    for level, seconds in runs:
        out += [level] * int(round(seconds / HOP))
    return out


class Settle(unittest.TestCase):
    def test_a_word_shut_against_the_next_ends_at_the_limit(self):
        e = env((-20.0, 0.5))
        self.assertAlmostEqual(ends.settle(e, HOP), 0.5)

    def test_a_rest_ends_the_word_where_the_voice_stops(self):
        e = env((-20.0, 0.4), (-45.0, 0.3))
        self.assertAlmostEqual(ends.settle(e, HOP), 0.4)

    def test_the_threshold_is_relative_to_the_words_own_peak(self):
        # A quiet word: -40 dB throughout, falling to -55. A global gate at
        # -49 would call the whole tail silence; the rule ends at the fall.
        e = env((-40.0, 0.3), (-55.0, 0.2))
        self.assertAlmostEqual(ends.settle(e, HOP), 0.3)
        # ...and a dip that stays within 12 dB of the peak is still the word.
        e = env((-20.0, 0.3), (-30.0, 0.2))
        self.assertAlmostEqual(ends.settle(e, HOP), 0.5)

    def test_a_stop_closure_inside_the_word_is_not_a_rest(self):
        # "becomes": voice, 120 ms of closure, voice again up to the next word.
        e = env((-20.0, 0.3), (-40.0, 0.12), (-20.0, 0.4))
        self.assertAlmostEqual(ends.settle(e, HOP), 0.82)

    def test_the_next_words_plosive_burst_is_skipped(self):
        # Word, a 200 ms rest, then a 40 ms burst that the aligner left on this
        # side of the boundary: the word ended before the rest.
        e = env((-20.0, 0.4), (-45.0, 0.2), (-18.0, 0.04))
        self.assertAlmostEqual(ends.settle(e, HOP), 0.4)

    def test_a_blob_as_long_as_a_syllable_is_kept(self):
        e = env((-20.0, 0.4), (-45.0, 0.2), (-18.0, 0.08))
        self.assertAlmostEqual(ends.settle(e, HOP), 0.68)

    def test_a_burst_with_no_dip_before_it_is_part_of_the_word(self):
        e = env((-20.0, 0.4), (-18.0, 0.04))
        self.assertAlmostEqual(ends.settle(e, HOP), 0.44)

    def test_a_window_that_is_all_below_threshold_cannot_happen_but_is_safe(self):
        # max(env) - drop is always <= max(env), so at least the peak frame
        # is above; the degenerate one-frame window returns its own length.
        self.assertAlmostEqual(ends.settle([-30.0], HOP), HOP)
        self.assertEqual(ends.settle([], HOP), 0.0)


class Guard(unittest.TestCase):
    def test_shortening_is_always_allowed(self):
        e = env((-20.0, 0.4), (-45.0, 0.6))
        self.assertAlmostEqual(ends.word_end(e, HOP, current=1.0), 0.4)

    def test_lengthening_across_continuous_voice_is_allowed(self):
        # The aligner stopped the word at 0.25 s on continuous vocal (slop).
        e = env((-20.0, 0.5))
        self.assertAlmostEqual(ends.word_end(e, HOP, current=0.25), 0.5)

    def test_lengthening_across_a_dip_is_refused(self):
        # "wild" -> "emotion", with "emotion" aligned a second late: the window
        # holds both words and the closure between them. The rule would say
        # the end is at the limit; the guard keeps the aligner's own end.
        e = env((-20.0, 0.7), (-35.0, 0.05), (-18.0, 1.0))
        self.assertAlmostEqual(ends.word_end(e, HOP, current=0.7), 0.7)

    def test_no_current_end_means_no_guard(self):
        e = env((-20.0, 0.7), (-35.0, 0.05), (-18.0, 1.0))
        self.assertAlmostEqual(ends.word_end(e, HOP), 1.75)


if __name__ == "__main__":
    unittest.main()
