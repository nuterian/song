"""The generated picture: the things about it that are not a matter of taste.

Nothing here judges how it looks - that is what rendering a preview and staring
at it is for. What is pinned is the arithmetic underneath, and in particular the
two ways this file has been quietly wrong: a frame that costs twice what it
should because one scalar arrived as the wrong type, and a signal driving the
picture as a staircase instead of a curve.

Skipped rather than failed where numpy is absent, so the suite still runs in
seconds on a machine with nothing installed - see test_imports.
"""

import unittest

try:
    import numpy as np
    from song.video import scene as sc
except ImportError:                                   # pragma: no cover
    np = sc = None

from song.parse_lyrics import Section
from song.project import Project, TimedLine, Word


def _project(duration=8.0):
    words = [Word("one", 1.0, 1.6), Word("two", 1.6, 2.4)]
    line = TimedLine(index=0, section=0, text="one two", start=1.0, end=2.4,
                     words=words)
    return Project(audio_path="a.wav", lyrics_path="l.txt", duration=duration,
                   sections=[Section(index=0, name="Chorus", line_indices=[0])],
                   lines=[line])


def _inputs(duration=8.0, rate=120):
    n = int(duration * rate)
    ramp = (np.sin(np.linspace(0, 40, n)) * 0.5 + 0.5).tolist()
    analysis = {"rate": rate, "mix_peaks": ramp, "vocal_peaks": ramp[::-1]}
    beats = {"rate": rate, "meter": 4, "phase": 0,
             "beats": [round(0.5 * k, 3) for k in range(int(duration / 0.5))],
             "downbeats": [round(2.0 * k, 3) for k in range(int(duration / 2.0))],
             "low": ramp, "high": ramp[::-1]}
    return analysis, beats


@unittest.skipIf(np is None, "needs numpy")
class TheFrame(unittest.TestCase):
    def setUp(self):
        analysis, beats = _inputs()
        self.scene = sc.Scene(_project(), analysis, beats, width=64, height=36)

    def test_it_comes_back_as_planes_in_ffmpeg_s_order(self):
        # render.py feeds this straight to `-pix_fmt gbrp`. (h, w, 3) would be
        # accepted by the pipe and come out with the channels shuffled.
        frame = self.scene.frame(3.0)
        self.assertEqual(frame.shape, (3, 36, 64))
        self.assertEqual(frame.dtype, np.uint8)

    def test_a_numpy_time_gives_the_same_frame_as_a_python_one(self):
        here = self.scene.frame(3.0).copy()
        there = self.scene.frame(np.float64(3.0))
        self.assertTrue((here == there).all())

    def test_nothing_computed_from_the_time_is_left_in_float64(self):
        """The guard is about cost, and the cost is invisible in the output.

        A numpy scalar promotes every float32 array it meets, so the palette
        and the lobes get computed at double precision for the same picture:
        20.7 ms a frame became 38.9. The pixels come out the same to within a
        level, so the frame-level guard in frame() is not something a test can
        see - it is checked by timing. What is checked here is _at, which is
        where the promotion leaks in from, and which does have a visible type.

        Four other coercions were written for this and then taken out again:
        _pulse and _bar_phase were already returning Python floats through
        math.*, and _beat_glow and _trace cast back to float32 on the way out,
        so a test could not tell whether they had been removed.
        """
        at = np.float64(3.0)
        value = self.scene._at(self.scene.mix, at)
        self.assertIsInstance(value, float)
        self.assertNotIsInstance(value, np.floating)

    def test_the_envelopes_are_read_between_samples_not_at_them(self):
        # Truncating to an index makes a 120 Hz track a staircase under a frame
        # rate that does not divide it, and a step is broadband. This is what
        # the flicker at the thin ends of the trace was.
        track = np.array([0.0, 1.0], dtype=np.float32)
        quarter = self.scene._at(track, 0.25 / self.scene.rate)
        self.assertAlmostEqual(quarter, 0.25, places=5)
        self.assertIsInstance(quarter, float)
        self.assertNotIsInstance(quarter, np.floating)

    def test_reading_past_either_end_holds_rather_than_wraps(self):
        track = np.array([0.25, 0.75], dtype=np.float32)
        self.assertAlmostEqual(self.scene._at(track, -5.0), 0.25, places=5)
        self.assertAlmostEqual(self.scene._at(track, 5000.0), 0.75, places=5)

    def test_the_bar_light_is_gone_at_both_ends_of_its_own_travel(self):
        # It teleports back to the right at the downbeat. That is only safe
        # because sin^2 is zero there, and zero-sloped, so nothing is on screen
        # to teleport. A band that simply wrapped would be a step across most
        # of the frame.
        for at in (0.0, 2.0, 4.0):
            self.assertAlmostEqual(self.scene._bar_phase(at), 0.0, places=6)
        self.assertAlmostEqual(self.scene._bar_phase(3.0), 0.5, places=6)

    def test_a_track_with_no_beats_still_renders(self):
        analysis, beats = _inputs()
        beats["beats"], beats["downbeats"] = [], []
        quiet = sc.Scene(_project(), analysis, beats, width=64, height=36)
        self.assertEqual(quiet.frame(3.0).shape, (3, 36, 64))
        self.assertEqual(quiet._bar_phase(3.0), 0.0)


if __name__ == "__main__":
    unittest.main()
