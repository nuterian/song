"""Syllable placement from the onset-strength envelope, on a synthetic stem.

Skipped where numpy is absent. The text rule is pinned in test_syllables.py;
what this covers is where the cuts land: at the strongest peaks inside the
word, clear of its edges, spread evenly when the envelope offers nothing.
"""

import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from song.parse_lyrics import Section
from song.project import Project, TimedLine, Word


def activity(strength, hop=0.01):
    from song.vad import VocalActivity

    n = len(strength)
    db = np.full(n, -20.0, dtype=np.float32)
    return VocalActivity(times=np.arange(n) * hop, db=db, active=db > -40, hop=hop,
                         onsets=np.array([]), threshold_db=-40.0,
                         strength=np.asarray(strength, dtype=np.float32))


def project(*words):
    line = TimedLine(index=0, section=0, text=" ".join(w.text for w in words),
                     start=words[0].start, end=words[-1].end, words=list(words))
    return Project(audio_path="a.wav", lyrics_path="l.txt", duration=10.0,
                   sections=[Section(index=0, name="V", line_indices=[0])], lines=[line])


@unittest.skipIf(np is None, "needs numpy")
class SettleSyllables(unittest.TestCase):
    def test_cuts_land_on_the_strongest_peaks_inside_the_word(self):
        from song.align.pipeline import settle_syllables

        s = np.zeros(300)
        s[131] = 5.0            # 1.31 s: the strongest
        s[160] = 3.0            # 1.60 s: the second
        s[145] = 1.0            # a weaker one between them
        s[101] = 9.0            # at the word's very edge: ignored
        p = project(Word("gravity", 1.0, 2.0))
        self.assertEqual(settle_syllables(p, activity(s)), 1)
        syl = p.lines[0].words[0].syllables
        self.assertEqual([x["text"] for x in syl], ["gra", "vi", "ty"])
        self.assertEqual([x["at"] for x in syl], [0.0, 0.31, 0.6])

    def test_peaks_too_close_together_are_not_both_taken(self):
        from song.align.pipeline import settle_syllables

        s = np.zeros(300)
        s[131] = 5.0
        s[134] = 4.0            # 30 ms from the first: skipped
        s[170] = 1.0
        p = project(Word("gravity", 1.0, 2.0))
        settle_syllables(p, activity(s))
        self.assertEqual([x["at"] for x in p.lines[0].words[0].syllables], [0.0, 0.31, 0.7])

    def test_a_flat_envelope_spreads_the_cuts_evenly(self):
        from song.align.pipeline import settle_syllables

        p = project(Word("gravity", 1.0, 2.0))
        settle_syllables(p, activity(np.zeros(300)))
        ats = [x["at"] for x in p.lines[0].words[0].syllables]
        self.assertEqual(len(ats), 3)
        self.assertEqual(ats[0], 0.0)
        self.assertTrue(0.25 < ats[1] < 0.55 < ats[2] < 0.8)

    def test_one_syllable_and_very_short_words_get_none(self):
        from song.align.pipeline import settle_syllables

        s = np.zeros(300); s[131] = 5.0
        p = project(Word("in", 1.0, 2.0), Word("gravity", 2.0, 2.08))
        self.assertEqual(settle_syllables(p, activity(s)), 0)
        self.assertEqual([w.syllables for w in p.lines[0].words], [[], []])

    def test_no_strength_envelope_means_no_syllables(self):
        from song.align.pipeline import settle_syllables

        act = activity(np.zeros(300))
        act.strength = None
        p = project(Word("gravity", 1.0, 2.0))
        self.assertEqual(settle_syllables(p, act), 0)

    def test_the_result_survives_the_file_and_rescales_with_the_word(self):
        from song.align.pipeline import settle_syllables

        s = np.zeros(300); s[131] = 5.0; s[160] = 3.0
        p = project(Word("gravity", 1.0, 2.0))
        settle_syllables(p, activity(s))
        back = Project.from_dict(p.to_dict())
        back.lines[0].retime(5.0, 7.0)
        spans = back.lines[0].words[0].syllable_spans()
        self.assertAlmostEqual(spans[1][1], 5.62)
        self.assertAlmostEqual(spans[2][1], 6.2)


if __name__ == "__main__":
    unittest.main()
