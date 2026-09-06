"""The voicing track's plumbing, with the model stubbed out.

Silero itself is measured on the bench, not here. What is pinned here is what
its probability does and does not touch: `active` stays the energy gate (the
bench is why - see vad.analyse), `sung` ANDs the two at VOICED, and both fall
back to the energy gate alone when the model is absent or switched off.
Skipped where numpy is missing, like the other numpy-backed tests.
"""

import unittest
from unittest import mock

try:
    import numpy as np
except ImportError:  # pragma: no cover - CI has no numpy
    np = None


def tone(seconds, sr=16000, level=0.3):
    t = np.arange(int(seconds * sr)) / sr
    return (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


@unittest.skipIf(np is None, "needs numpy")
class VoicingGate(unittest.TestCase):
    def setUp(self):
        from song import vad

        self.vad = vad
        # 1 s of silence, 2 s of tone, 1 s of silence: the energy gate is on
        # for the middle two seconds.
        self.samples = np.concatenate([np.zeros(16000, np.float32), tone(2.0),
                                       np.zeros(16000, np.float32)])

    def test_without_the_model_active_is_the_energy_gate(self):
        with mock.patch.object(self.vad, "voicing", return_value=None):
            act = self.vad.analyse(self.samples, 16000)
        self.assertIsNone(act.voiced)
        np.testing.assert_array_equal(act.active, act.loud)
        self.assertGreater(act.coverage(1.2, 2.8), 0.95)

    def test_switched_off_the_model_is_not_consulted(self):
        with mock.patch.object(self.vad, "voicing", side_effect=AssertionError("called")):
            act = self.vad.analyse(self.samples, 16000, voicing_model=False)
        self.assertIsNone(act.voiced)

    def test_the_model_never_touches_active_and_only_takes_frames_from_sung(self):
        # The model says the second half of the tone is not a voice.
        def fake(samples, sr, hop, n):
            p = np.ones(n, np.float32)
            p[int(2.0 / hop):] = 0.0
            return p

        with mock.patch.object(self.vad, "voicing", side_effect=fake):
            act = self.vad.analyse(self.samples, 16000)
        self.assertIsNotNone(act.voiced)
        np.testing.assert_array_equal(act.active, act.loud)     # the gate is unchanged
        self.assertGreater(act.coverage(2.2, 2.8), 0.95)         # loud counts as active
        sung = act.sung
        self.assertTrue(sung[int(1.5 / act.hop)])                # loud and voiced
        self.assertFalse(sung[int(2.5 / act.hop)])               # loud, not voiced
        self.assertFalse(sung[int(0.5 / act.hop)])               # voiced, not loud

    def test_the_threshold_is_the_documented_one(self):
        def fake(samples, sr, hop, n):
            p = np.full(n, self.vad.VOICED, np.float32)     # exactly at it
            p[int(2.0 / hop):] = self.vad.VOICED - 0.01     # just under
            return p

        with mock.patch.object(self.vad, "voicing", side_effect=fake):
            act = self.vad.analyse(self.samples, 16000)
        self.assertTrue(act.sung[int(1.5 / act.hop)])
        self.assertFalse(act.sung[int(2.5 / act.hop)])

    def test_without_the_model_sung_is_the_energy_gate(self):
        with mock.patch.object(self.vad, "voicing", return_value=None):
            act = self.vad.analyse(self.samples, 16000)
        np.testing.assert_array_equal(act.sung, act.active)


@unittest.skipIf(np is None, "needs numpy")
class VoicingFunction(unittest.TestCase):
    def test_an_unsupported_rate_returns_none_rather_than_guessing(self):
        from song import vad

        try:
            import silero_vad  # noqa: F401
        except ImportError:
            self.skipTest("silero_vad not installed")
        self.assertIsNone(vad.voicing(tone(1.0, sr=22050), 22050, 0.01, 100))

    def test_the_probability_lands_on_the_envelopes_frames(self):
        from song import vad

        try:
            import silero_vad  # noqa: F401
        except ImportError:
            self.skipTest("silero_vad not installed")
        samples = np.concatenate([np.zeros(16000, np.float32), tone(1.0)])
        p = vad.voicing(samples, 16000, 0.01, 200)
        self.assertEqual(p.shape, (200,))
        self.assertTrue(np.all((p >= 0) & (p <= 1)))


if __name__ == "__main__":
    unittest.main()
