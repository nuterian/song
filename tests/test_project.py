"""The word-timing model's invariants.

A word's end *is* the next word's start, so the whole editing model rests on
staying contiguous. Every one of these held only because something enforced it;
each test is here because breaking it produces a caption file that looks fine
and plays wrong.
"""

import unittest

from lyricsync.project import Project, TimedLine, Word
from lyricsync.parse_lyrics import Section


def line(index=0, section=0, text="a b c", start=1.0, end=4.0, starts=(1.0, 2.0, 3.0)):
    return TimedLine(
        index=index, section=section, text=text, start=start, end=end,
        words=[Word(text=t, start=s, end=s) for t, s in zip(text.split(), starts)],
    )


def contiguous(ln: TimedLine) -> bool:
    """The invariant every export and the karaoke highlight depend on."""
    if not ln.words:
        return True
    return (
        ln.words[0].start == ln.start
        and ln.words[-1].end == ln.end
        and all(a.end == b.start for a, b in zip(ln.words, ln.words[1:]))
    )


class NormalizeWords(unittest.TestCase):
    def test_ends_are_derived_from_the_next_start(self):
        ln = line()
        ln.normalize_words()
        self.assertTrue(contiguous(ln))
        self.assertEqual([w.end for w in ln.words], [2.0, 3.0, 4.0])

    def test_word_zero_is_pinned_to_the_line_start(self):
        ln = line(starts=(1.9, 2.0, 3.0))
        ln.normalize_words()
        self.assertEqual(ln.words[0].start, ln.start)

    def test_a_start_before_its_predecessor_is_clamped_forward(self):
        ln = line(starts=(1.0, 3.0, 2.0))   # third word starts before the second
        ln.normalize_words()
        self.assertTrue(contiguous(ln))
        self.assertEqual([w.start for w in ln.words], sorted(w.start for w in ln.words))

    def test_a_start_past_the_line_end_is_clamped_back(self):
        ln = line(starts=(1.0, 2.0, 99.0))
        ln.normalize_words()
        self.assertTrue(contiguous(ln))
        self.assertLessEqual(ln.words[-1].start, ln.end)

    def test_a_line_with_no_words_is_left_alone(self):
        ln = TimedLine(index=0, section=0, text="", start=1.0, end=2.0, words=[])
        ln.normalize_words()
        self.assertEqual(ln.words, [])


class Retime(unittest.TestCase):
    def test_words_ride_along_proportionally(self):
        ln = line(start=0.0, end=3.0, starts=(0.0, 1.0, 2.0))
        ln.retime(10.0, 16.0)                       # twice as long, moved
        self.assertEqual(ln.start, 10.0)
        self.assertEqual(ln.end, 16.0)
        self.assertEqual([w.start for w in ln.words], [10.0, 12.0, 14.0])
        self.assertTrue(contiguous(ln))

    def test_a_degenerate_span_spreads_words_evenly(self):
        ln = line(start=5.0, end=5.0, starts=(5.0, 5.0, 5.0))
        ln.retime(0.0, 3.0)
        self.assertEqual([w.start for w in ln.words], [0.0, 1.0, 2.0])
        self.assertTrue(contiguous(ln))

    def test_a_line_can_never_be_retimed_to_zero_length(self):
        ln = line()
        ln.retime(4.0, 4.0)
        self.assertGreater(ln.end, ln.start)


class InsertLine(unittest.TestCase):
    """Inserting renumbers everything keyed by line index.

    This is the regression test for a bug that did not fail loudly: the two
    aligners' raw spans and the round-trip's per-line observations are stored
    as {line index: ...}, and leaving them behind after an insertion scored
    every later line against its neighbour's evidence.
    """

    def setUp(self):
        self.p = Project(
            audio_path="a.wav", lyrics_path="l.txt", duration=30.0,
            sections=[Section(index=0, name="Verse", line_indices=[0, 1]),
                      Section(index=1, name="Chorus", line_indices=[2])],
            lines=[line(0, 0, start=0.0, end=3.0, starts=(0.0, 1.0, 2.0)),
                   line(1, 0, start=3.0, end=6.0, starts=(3.0, 4.0, 5.0)),
                   line(2, 1, start=9.0, end=12.0, starts=(9.0, 10.0, 11.0))],
            meta={
                "aligners": {"ctc": {"0": [0.0, 3.0], "1": [3.0, 6.0], "2": [9.0, 12.0]}},
                "roundtrip": {"per_line": {"0": {"start": 0.0}, "1": {"start": 3.0},
                                           "2": {"start": 9.0}}},
            },
        )
        self.new = line(99, 0, text="x y", start=6.5, end=8.0, starts=(6.5, 7.2))
        self.p.insert_line(1, self.new)          # goes in at position 2

    def test_indices_are_position(self):
        self.assertEqual([ln.index for ln in self.p.lines], [0, 1, 2, 3])

    def test_the_new_line_lands_where_asked(self):
        self.assertIs(self.p.lines[2], self.new)
        self.assertEqual(self.p.lines[2].index, 2)

    def test_section_membership_is_rebuilt(self):
        self.assertEqual(self.p.sections[0].line_indices, [0, 1, 2])
        self.assertEqual(self.p.sections[1].line_indices, [3])

    def test_aligner_spans_follow_their_lines(self):
        ctc = self.p.meta["aligners"]["ctc"]
        self.assertEqual(ctc["0"], [0.0, 3.0])    # before the insert: unmoved
        self.assertEqual(ctc["1"], [3.0, 6.0])
        self.assertEqual(ctc["3"], [9.0, 12.0])   # was "2", shifted up
        self.assertNotIn("2", ctc)                # the new line has no aligner opinion

    def test_roundtrip_observations_follow_their_lines(self):
        per_line = self.p.meta["roundtrip"]["per_line"]
        self.assertEqual(per_line["1"]["start"], 3.0)
        self.assertEqual(per_line["3"]["start"], 9.0)
        self.assertNotIn("2", per_line)

    def test_inserting_at_the_end_appends(self):
        p = self.p
        p.insert_line(len(p.lines) - 1, line(99, 1, start=20.0, end=22.0, starts=(20.0, 21.0, 21.5)))
        self.assertEqual([ln.index for ln in p.lines], [0, 1, 2, 3, 4])
        self.assertEqual(p.sections[1].line_indices, [3, 4])


class RoundTripsThroughJson(unittest.TestCase):
    def test_a_project_survives_to_dict_and_back(self):
        p = Project(
            audio_path="a.wav", lyrics_path="l.txt", duration=30.0,
            sections=[Section(index=0, name="Verse", line_indices=[0])],
            lines=[line(0, 0)],
        )
        back = Project.from_dict(p.to_dict())
        self.assertEqual(back.duration, p.duration)
        self.assertEqual(back.lines[0].text, p.lines[0].text)
        self.assertTrue(contiguous(back.lines[0]))


if __name__ == "__main__":
    unittest.main()
