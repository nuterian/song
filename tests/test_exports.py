"""Timestamp formatting, and the contiguity every export keys off.

These files are the product. A format slip here is invisible until a player
shows the wrong line.
"""

import tempfile
import unittest
from pathlib import Path

from lyricsync import exports
from lyricsync.parse_lyrics import Section
from lyricsync.project import Project, TimedLine, Word


def sample():
    def ln(i, text, start, end):
        n = len(text.split())
        step = (end - start) / n
        return TimedLine(
            index=i, section=0, text=text, start=start, end=end,
            words=[Word(t, start + k * step, start + (k + 1) * step)
                   for k, t in enumerate(text.split())],
        )
    return Project(
        audio_path="a.wav", lyrics_path="l.txt", duration=200.0,
        sections=[Section(index=0, name="Verse", line_indices=[0, 1])],
        lines=[ln(0, "First line here", 5.5, 9.25),
               ln(1, "Second line here", 65.0, 3725.5)],   # crosses an hour
    )


class Timestamps(unittest.TestCase):
    def test_lrc_is_mm_ss_hundredths(self):
        self.assertEqual(exports._lrc_time(5.5), "[00:05.50]")
        self.assertEqual(exports._lrc_time(65.0), "[01:05.00]")

    def test_srt_is_hh_mm_ss_comma_millis(self):
        self.assertEqual(exports._srt_time(5.5), "00:00:05,500")
        self.assertEqual(exports._srt_time(3725.5), "01:02:05,500")

    def test_vtt_uses_a_dot_for_millis(self):
        self.assertEqual(exports._vtt_time(3725.5), "01:02:05.500")

    def test_negative_times_are_clamped_to_zero(self):
        for fn in (exports._lrc_time, exports._srt_time, exports._vtt_time):
            self.assertNotIn("-", fn(-3.0))


class WritesEveryFormat(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.written = exports.write_all(sample(), self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_all_four_formats_land(self):
        self.assertEqual(set(self.written), {"lrc", "enhanced_lrc", "srt", "vtt", "json"})
        for path in self.written.values():
            self.assertTrue(Path(path).exists(), path)

    def test_lrc_has_one_timestamp_per_line(self):
        text = Path(self.written["lrc"]).read_text()
        self.assertIn("[00:05.50]First line here", text)

    def test_word_lrc_carries_a_stamp_per_word(self):
        text = Path(self.written["enhanced_lrc"]).read_text()
        self.assertEqual(text.count("<"), 6)      # 3 words x 2 lines

    def test_vtt_starts_with_its_magic_header(self):
        self.assertTrue(Path(self.written["vtt"]).read_text().startswith("WEBVTT"))

    def test_srt_cues_are_numbered_from_one(self):
        first = Path(self.written["srt"]).read_text().lstrip().split("\n")[0]
        self.assertEqual(first, "1")

    def test_export_normalizes_words_on_the_way_out(self):
        # The UI edits starts only; ends are derived. Export must not ship a
        # gap between a word's end and the next word's start.
        import json
        data = json.loads(Path(self.written["json"]).read_text())
        for line in data["lines"]:
            ws = line["words"]
            self.assertEqual(ws[0]["start"], line["start"])
            self.assertEqual(ws[-1]["end"], line["end"])
            for a, b in zip(ws, ws[1:]):
                self.assertEqual(a["end"], b["start"])


class UntimedLinesAreSkipped(unittest.TestCase):
    def test_a_line_with_no_span_never_reaches_a_caption(self):
        p = sample()
        p.lines.append(TimedLine(index=2, section=0, text="Never aligned", start=0.0, end=0.0))
        with tempfile.TemporaryDirectory() as d:
            written = exports.write_all(p, d)
            self.assertNotIn("Never aligned", Path(written["srt"]).read_text())


if __name__ == "__main__":
    unittest.main()
