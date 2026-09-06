"""The envelope wrapper and the audit's end repair, on a synthetic stem.

Skipped rather than failed where numpy is absent, so the suite still runs in
CI with nothing installed; `tests/test_ends.py` pins the rule itself with no
numpy at all. What this adds is the plumbing: the wrapper's slicing puts the
rule's offset back on the track timeline, and the audit reports an end it
moved as an end.
"""

import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover - CI has no numpy
    np = None

from song.project import TimedLine, Word


def activity(db_runs, hop=0.01):
    """A VocalActivity with a hand-drawn envelope and nothing else."""
    from song.vad import VocalActivity

    db = []
    for level, seconds in db_runs:
        db += [level] * int(round(seconds / hop))
    db = np.array(db, dtype=np.float32)
    return VocalActivity(
        times=np.arange(len(db)) * hop, db=db, active=db > -40.0, hop=hop,
        onsets=np.array([]), threshold_db=-40.0,
    )


@unittest.skipIf(np is None, "needs numpy")
class WordEnd(unittest.TestCase):
    def test_the_offset_comes_back_on_the_track_timeline(self):
        # Silence, a word from 1.0 to 1.4, silence until the next word at 1.8.
        act = activity([(-60.0, 1.0), (-20.0, 0.4), (-60.0, 0.4), (-20.0, 0.5)])
        self.assertAlmostEqual(act.word_end(1.0, 1.8), 1.4, places=2)

    def test_a_shut_word_ends_at_the_next_start(self):
        act = activity([(-60.0, 1.0), (-20.0, 1.0)])
        self.assertAlmostEqual(act.word_end(1.0, 1.8), 1.8, places=2)

    def test_the_guard_keeps_a_current_end_across_a_dip(self):
        act = activity([(-60.0, 1.0), (-20.0, 0.4), (-40.0, 0.05), (-20.0, 0.5)])
        self.assertAlmostEqual(act.word_end(1.0, 1.95, current=1.4), 1.4, places=2)

    def test_an_empty_window_is_its_limit(self):
        act = activity([(-20.0, 1.0)])
        self.assertEqual(act.word_end(0.5, 0.5), 0.5)


@unittest.skipIf(np is None, "needs numpy")
class AuditRepairsEnds(unittest.TestCase):
    def test_a_word_that_ran_past_the_voice_is_pulled_back_and_reported(self):
        from song.align import refine

        # The voice stops at 1.4; the aligner let the word run to 1.79.
        act = activity([(-60.0, 1.0), (-20.0, 0.4), (-60.0, 0.4), (-20.0, 0.5)])
        line = TimedLine(index=3, section=0, text="a b", start=1.0, end=2.3,
                         words=[Word("a", 1.0, 1.79), Word("b", 1.8, 2.3)])
        repairs = refine.repair_line(line, act)
        ends = [r for r in repairs if r.bound == "end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual((ends[0].line, ends[0].word, ends[0].text), (3, 0, "a"))
        self.assertAlmostEqual(ends[0].was, 1.79)
        self.assertAlmostEqual(line.words[0].end, 1.4, places=2)
        self.assertIn("after the voice stopped", ends[0].why)
        self.assertEqual(ends[0].to_dict()["bound"], "end")

    def test_an_end_within_a_rest_of_the_voice_is_left_alone(self):
        from song.align import refine

        act = activity([(-60.0, 1.0), (-20.0, 0.4), (-60.0, 0.4), (-20.0, 0.5)])
        line = TimedLine(index=3, section=0, text="a b", start=1.0, end=2.3,
                         words=[Word("a", 1.0, 1.5), Word("b", 1.8, 2.3)])
        self.assertEqual([r for r in refine.repair_line(line, act) if r.bound == "end"], [])
        self.assertAlmostEqual(line.words[0].end, 1.5)

    def test_the_last_words_end_moves_the_line_end_with_it(self):
        from song.align import refine

        act = activity([(-60.0, 1.0), (-20.0, 0.4), (-60.0, 1.0)])
        line = TimedLine(index=0, section=0, text="a", start=1.0, end=2.2,
                         words=[Word("a", 1.0, 2.2)])
        refine.repair_line(line, act)
        self.assertAlmostEqual(line.end, 1.4, places=2)
        self.assertAlmostEqual(line.words[-1].end, line.end)


if __name__ == "__main__":
    unittest.main()
