"""The decision log: it round-trips, it never blocks a save, and the features
it attaches are the ones the plan lists.

Stdlib except for one numpy-backed case, skipped where numpy is absent.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from song import decisions
from song.parse_lyrics import Section
from song.project import Project, TimedLine, Word

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def project():
    words = [Word("You're", 10.0, 10.3, prob=0.9), Word("my", 10.3, 10.7, prob=0.2),
             Word("gravity", 10.8, 11.8, prob=0.7)]
    line = TimedLine(index=0, section=1, text="You're my gravity", start=10.0, end=11.8,
                     words=words, source="whisper", score={"total": 97.4})
    return Project(
        audio_path="a.wav", lyrics_path="l.txt", duration=100.0,
        sections=[Section(index=0, name="Chorus", line_indices=[]),
                  Section(index=1, name="Chorus", line_indices=[0])],
        lines=[line],
    )


class Record(unittest.TestCase):
    def test_round_trip_and_append(self):
        with tempfile.TemporaryDirectory() as wd:
            self.assertTrue(decisions.record(wd, {"line": 0, "word": 1, "action": "accept"}))
            self.assertTrue(decisions.record(wd, {"line": 0, "word": 2, "action": "keep"}))
            got = decisions.load(wd)
            self.assertEqual([g["word"] for g in got], [1, 2])
            self.assertIn("at", got[0])

    def test_a_corrupt_line_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as wd:
            decisions.record(wd, {"line": 0})
            with (Path(wd) / decisions.FILENAME).open("a") as fh:
                fh.write("{not json\n")
            decisions.record(wd, {"line": 1})
            self.assertEqual([g["line"] for g in decisions.load(wd)], [0, 1])

    def test_an_unwritable_path_returns_false_and_raises_nothing(self):
        with tempfile.TemporaryDirectory() as wd:
            blocker = Path(wd) / "file"
            blocker.write_text("")
            # A file where the workdir should be: mkdir fails, open fails.
            self.assertFalse(decisions.record(blocker / "sub", {"line": 0}))

    def test_nothing_recorded_is_an_empty_list(self):
        with tempfile.TemporaryDirectory() as wd:
            self.assertEqual(decisions.load(wd), [])


class Features(unittest.TestCase):
    def test_the_plans_features_without_audio(self):
        f = decisions.features(project(), None, 0, 1)
        self.assertEqual(f["prob"], 0.2)
        self.assertEqual(f["syllables"], 1)
        self.assertAlmostEqual(f["duration"], 0.4)
        self.assertAlmostEqual(f["position"], 0.5)
        self.assertEqual((f["first"], f["last"]), (False, False))
        self.assertEqual(f["line_score"], 97.4)
        self.assertEqual(f["repeat_index"], 1)          # the second "Chorus"
        self.assertAlmostEqual(f["gap_after"], 0.1)
        self.assertEqual(f["gap_before"], 0.0)
        self.assertNotIn("onset_distance", f)

    def test_the_audits_disagreement_is_attached_when_it_ran(self):
        audit = {"line_proposals": {"0": {"starts": [10.0, 10.5, 10.8]}}}
        f = decisions.features(project(), None, 0, 1, audit)
        self.assertAlmostEqual(f["disagreement"], 0.2)

    def test_out_of_range_indices_give_no_features(self):
        self.assertEqual(decisions.features(project(), None, 3, 0), {})
        self.assertEqual(decisions.features(project(), None, 0, 9), {})

    @unittest.skipIf(np is None, "needs numpy")
    def test_audio_features_come_from_the_activity(self):
        from song.vad import VocalActivity

        hop = 0.01
        db = np.full(2000, -20.0, dtype=np.float32)
        act = VocalActivity(times=np.arange(2000) * hop, db=db, active=db > -40, hop=hop,
                            onsets=np.array([10.25, 10.82]), threshold_db=-40.0,
                            voiced=np.full(2000, 0.9, dtype=np.float32))
        f = decisions.features(project(), act, 0, 1)
        self.assertAlmostEqual(f["onset_distance"], 0.05)
        self.assertEqual(f["db_at_start"], -20.0)
        self.assertAlmostEqual(f["voiced_at_start"], 0.9)
        self.assertEqual(f["coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()
