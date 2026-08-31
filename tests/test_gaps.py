"""The judgement that decides whether a line gets proposed.

Finding candidates in a vocal stem is easy; refusing bad ones is the whole
job. Each case here is a shape that actually occurred on the sample track, so
a threshold that drifts fails a test rather than silently proposing "Thank you."
as a lyric.
"""

import unittest

from lyricsync import gaps
from lyricsync.parse_lyrics import Section
from lyricsync.project import Project, TimedLine, Word


CHORUS = "You're my gravity in motion,"


def project_with_a_hole():
    """Two timed lines with a 20 s hole between them, chorus text repeated."""
    def ln(index, text, start, end):
        n = len(text.split())
        step = (end - start) / n
        return TimedLine(
            index=index, section=0, text=text, start=start, end=end,
            words=[Word(t, start + i * step, start + (i + 1) * step)
                   for i, t in enumerate(text.split())],
        )
    return Project(
        audio_path="a.wav", lyrics_path="l.txt", duration=60.0,
        sections=[Section(index=0, name="Chorus", line_indices=[0, 1])],
        lines=[ln(0, CHORUS, 0.0, 5.0), ln(1, "Silver lights trace the floor,", 30.0, 35.0)],
    )


def heard(text, start, prob, gap=0.3):
    """Blind-transcription words, laid out from `start`."""
    out, t = [], start
    for w in text.split():
        out.append(Word(text=w, start=t, end=t + gap, prob=prob))
        t += gap * 2
    return out


class AlwaysVocal:
    """Stand-in for VocalActivity: the whole track is sounding."""
    def coverage(self, a, b):
        return 1.0


class Accepts(unittest.TestCase):
    def test_a_confident_exact_repeat_inside_the_hole(self):
        p = project_with_a_hole()
        found = gaps.find(p, AlwaysVocal(), heard(CHORUS, 12.0, 0.9))
        self.assertEqual(len(found), 1)
        c = found[0]
        self.assertEqual(c.text, CHORUS)          # the text you wrote, verbatim
        self.assertEqual(c.after_line, 0)
        self.assertEqual(c.like_line, 0)
        self.assertEqual(c.repeats, 1)
        self.assertAlmostEqual(c.match, 1.0)
        self.assertGreater(c.confidence, gaps.MIN_PROB)

    def test_word_starts_come_from_the_transcription_when_counts_agree(self):
        p = project_with_a_hole()
        words = heard(CHORUS, 12.0, 0.9)
        c = gaps.find(p, AlwaysVocal(), words)[0]
        self.assertEqual(c.starts, [w.start for w in words])

    def test_a_dismissal_is_remembered_by_id(self):
        p = project_with_a_hole()
        words = heard(CHORUS, 12.0, 0.9)
        first = gaps.find(p, AlwaysVocal(), words)[0]
        again = gaps.find(p, AlwaysVocal(), words, dismissed={first.id})[0]
        self.assertTrue(again.dismissed)
        self.assertEqual(again.id, first.id)


class Refuses(unittest.TestCase):
    """Every one of these is a false positive the sample track really produced."""

    def setUp(self):
        self.p = project_with_a_hole()

    def reject(self, words, why):
        self.assertEqual(gaps.find(self.p, AlwaysVocal(), words), [], why)

    def test_too_few_words_is_a_bleed_not_a_line(self):
        # "You're my" at 1:02 - the lead-in to the next line, 2 of 5 words.
        self.reject(heard("You're my", 12.0, 0.9), "2 words should not be a line")

    def test_low_confidence_is_refused(self):
        # "in motion Silver lights" at 1:54 came back at p = 0.00-0.03.
        self.reject(heard(CHORUS, 12.0, 0.2), "p=0.2 is not evidence")

    def test_text_that_matches_no_lyric_is_refused(self):
        # Whisper hallucinating over a fade.
        self.reject(heard("Thank you very much indeed", 12.0, 0.95),
                    "confident nonsense is still nonsense")

    def test_words_overhanging_a_neighbour_belong_to_that_neighbour(self):
        # Sung right up to and across the next line's start: that is the next
        # line's lead-in, which is a timing question, not a missing lyric.
        # (Words that merely *touch* the boundary within STRADDLE still count -
        # a blind transcription's edges are not that precise.)
        self.reject(heard(CHORUS, 29.4, 0.95), "overhang is a timing question")

    def test_a_hole_with_no_vocal_in_it_is_never_examined(self):
        class Silent:
            def coverage(self, a, b):
                return 0.0
        self.assertEqual(gaps.find(self.p, Silent(), heard(CHORUS, 12.0, 0.95)), [])

    def test_no_words_at_all_yields_nothing(self):
        self.assertEqual(gaps.find(self.p, AlwaysVocal(), []), [])


class ThresholdsAreOrdered(unittest.TestCase):
    """The sample track's real numbers must sit either side of each threshold."""

    def test_the_true_positive_clears_every_bar(self):
        self.assertGreater(0.89, gaps.MIN_PROB)      # measured confidence
        self.assertGreaterEqual(1.00, gaps.MIN_MATCH)
        self.assertGreaterEqual(5 / 5, gaps.MIN_COVERAGE)

    def test_the_best_false_positive_fails_at_least_one(self):
        # "You're my": p=0.60, match=0.50, coverage=2/5.
        self.assertLess(0.50, gaps.MIN_MATCH)
        self.assertLess(2 / 5, gaps.MIN_COVERAGE)


class BuildLine(unittest.TestCase):
    def test_an_accepted_candidate_becomes_a_contiguous_line(self):
        p = project_with_a_hole()
        c = gaps.find(p, AlwaysVocal(), heard(CHORUS, 12.0, 0.9))[0].to_dict()
        ln = gaps.build_line(p, c)
        self.assertEqual(ln.text, CHORUS)
        self.assertEqual(ln.source, "added")
        self.assertEqual(ln.words[0].start, ln.start)
        self.assertEqual(ln.words[-1].end, ln.end)
        self.assertTrue(all(a.end == b.start for a, b in zip(ln.words, ln.words[1:])))

    def test_a_word_count_mismatch_falls_back_to_even_spacing(self):
        p = project_with_a_hole()
        c = gaps.find(p, AlwaysVocal(), heard(CHORUS, 12.0, 0.9))[0].to_dict()
        c["starts"] = [12.0]                        # wrong length on purpose
        ln = gaps.build_line(p, c)
        self.assertEqual(len(ln.words), len(CHORUS.split()))
        self.assertTrue(all(a.end == b.start for a, b in zip(ln.words, ln.words[1:])))


if __name__ == "__main__":
    unittest.main()
