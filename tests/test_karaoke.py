"""The .ass karaoke file: timestamps, and the \\kf durations under them.

libass will happily render a syntactically perfect file whose sweep is a
quarter-second behind the singer, and nothing in the pipeline notices. So the
arithmetic is pinned here: what the timestamps look like, that the durations
land on the word boundaries the project already agreed on, and that they still
do after a hundred words of rounding.
"""

import unittest

from song.parse_lyrics import Section
from song.project import Project, TimedLine, Word
from song.video import karaoke


def line(index, text, start, end, section=0):
    """A line whose words split its span evenly - the invariant project.py enforces."""
    parts = text.split()
    step = (end - start) / len(parts)
    return TimedLine(
        index=index, section=section, text=text, start=start, end=end,
        words=[Word(w, start + i * step, start + (i + 1) * step)
               for i, w in enumerate(parts)],
    )


def project(*lines, duration=300.0):
    return Project(
        audio_path="a.wav", lyrics_path="l.txt", duration=duration,
        sections=[Section(index=0, name="Verse",
                          line_indices=[ln.index for ln in lines])],
        lines=list(lines),
    )


def durations(event: str) -> list[tuple[str, int]]:
    """Every karaoke tag in a dialogue line, as (kind, centiseconds)."""
    out = []
    for chunk in event.split("{")[1:]:
        tag = chunk.split("}")[0]
        kind = "kf" if tag.startswith("\\kf") else "k"
        out.append((kind, int(tag[3:] if kind == "kf" else tag[2:])))
    return out


def events(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith("Dialogue:")]


class Timestamps(unittest.TestCase):
    def test_ass_time_is_h_mm_ss_hundredths(self):
        self.assertEqual(karaoke.ass_time(0), "0:00:00.00")
        self.assertEqual(karaoke.ass_time(550), "0:00:05.50")
        self.assertEqual(karaoke.ass_time(372550), "1:02:05.50")

    def test_hours_are_one_digit_not_zero_padded(self):
        # ASS wants H:MM:SS.cc, and a player that gets 01:02:05.50 may drop the cue.
        self.assertTrue(karaoke.ass_time(372550).startswith("1:"))

    def test_centiseconds_round_rather_than_truncate(self):
        self.assertEqual(karaoke.centis(1.006), 101)
        self.assertEqual(karaoke.centis(1.004), 100)

    def test_negative_times_are_clamped_to_zero(self):
        self.assertEqual(karaoke.centis(-3.0), 0)
        self.assertEqual(karaoke.ass_time(-5), "0:00:00.00")


class Colours(unittest.TestCase):
    def test_ass_stores_colour_backwards_and_alpha_as_transparency(self):
        self.assertEqual(karaoke.colour(0xFF8000), "&H000080FF")
        self.assertEqual(karaoke.colour(0xFFFFFF, 0x80), "&H80FFFFFF")


class KaraokeDurations(unittest.TestCase):
    def test_the_sweep_starts_where_the_first_word_does(self):
        ln = line(0, "one two three", 10.0, 13.0)
        text = karaoke.karaoke_text(ln, karaoke.centis(10.0 - karaoke.LEAD_IN))
        self.assertEqual(durations(text)[0], ("k", karaoke.centis(karaoke.LEAD_IN)))

    def test_a_line_that_starts_on_its_event_gets_no_lead_in_wait(self):
        ln = line(0, "one two", 4.0, 6.0)
        self.assertEqual(durations(karaoke.karaoke_text(ln, 400))[0][0], "kf")

    def test_every_word_gets_its_own_sweep(self):
        ln = line(0, "one two three four", 10.0, 14.0)
        sweeps = [d for kind, d in durations(karaoke.karaoke_text(ln, 1000)) if kind == "kf"]
        self.assertEqual(sweeps, [100, 100, 100, 100])

    def test_the_space_between_words_costs_no_time(self):
        # Charge it to either neighbour and one of them finishes early or starts
        # late by a fraction of the space's width - visible on a fast run.
        ln = line(0, "one two three", 10.0, 13.0)
        text = karaoke.karaoke_text(ln, 1000)
        spacers = [d for kind, d in durations(text) if kind == "k"]
        self.assertEqual(spacers, [0, 0])
        self.assertIn("{\\k0} ", text)

    def test_durations_do_not_drift_over_a_long_line(self):
        # Rounding each word on its own loses up to half a centisecond a time.
        # These land on .005 boundaries, which is the worst case for it.
        starts = [10.0 + i * 0.115 for i in range(101)]
        words = [Word(f"w{i}", starts[i], starts[i + 1]) for i in range(100)]
        ln = TimedLine(index=0, section=0, text=" ".join(w.text for w in words),
                       start=starts[0], end=starts[-1], words=words)
        total = sum(d for _, d in durations(karaoke.karaoke_text(ln, karaoke.centis(10.0))))
        self.assertEqual(total, karaoke.centis(ln.end) - karaoke.centis(ln.start))

    def test_word_positions_match_the_project_to_the_centisecond(self):
        ln = line(0, "alpha beta gamma delta", 61.37, 65.02)
        start_cs = karaoke.centis(61.37 - karaoke.LEAD_IN)
        at = start_cs
        seen = []
        for kind, value in durations(karaoke.karaoke_text(ln, start_cs)):
            if kind == "kf":
                seen.append(at)
            at += value
        self.assertEqual(seen, [karaoke.centis(w.start) for w in ln.words])


class AwkwardLines(unittest.TestCase):
    def test_a_single_word_line_is_one_sweep(self):
        ln = line(0, "gravity", 5.0, 6.5)
        self.assertEqual(
            durations(karaoke.karaoke_text(ln, 500)), [("kf", 150)]
        )

    def test_a_zero_length_word_sweeps_instantly_and_steals_no_time(self):
        words = [Word("a", 5.0, 5.4), Word("b", 5.4, 5.4), Word("c", 5.4, 6.0)]
        ln = TimedLine(index=0, section=0, text="a b c", start=5.0, end=6.0, words=words)
        sweeps = [d for kind, d in durations(karaoke.karaoke_text(ln, 500)) if kind == "kf"]
        self.assertEqual(sweeps, [40, 0, 60])

    def test_a_line_with_no_words_is_plain_text_with_no_tags(self):
        ln = TimedLine(index=0, section=0, text="hummed", start=5.0, end=7.0)
        self.assertEqual(karaoke.karaoke_text(ln, 500), "hummed")

    def test_word_starts_that_run_backwards_never_emit_a_negative_wait(self):
        # libass reads a negative \k as an enormous positive one, so the line
        # would freeze unfilled rather than fail.
        words = [Word("a", 5.0, 5.5), Word("b", 4.0, 4.2), Word("c", 5.5, 6.0)]
        ln = TimedLine(index=0, section=0, text="a b c", start=5.0, end=6.0, words=words)
        self.assertTrue(all(d >= 0 for _, d in durations(karaoke.karaoke_text(ln, 500))))

    def test_braces_in_a_lyric_cannot_open_an_override_block(self):
        self.assertNotIn("{", karaoke.escape("a {\\an8} b"))
        self.assertNotIn("\\", karaoke.escape("a {\\an8} b"))


class WhatIsOnScreen(unittest.TestCase):
    """The words shown are the ones in the lyrics file, not the aligner's tokens."""

    def sung(self, text, words):
        ln = TimedLine(index=0, section=0, text=text, start=5.0, end=8.0, words=words)
        return karaoke.karaoke_text(ln, 500)

    def test_punctuation_the_aligner_stripped_is_still_shown(self):
        words = [Word("Bodies", 5.0, 6.0), Word("close", 6.0, 7.0),
                 Word("devotion", 7.0, 8.0)]
        self.assertIn("close,", self.sung("Bodies close, devotion.", words))
        self.assertIn("devotion.", self.sung("Bodies close, devotion.", words))

    def test_the_timing_still_comes_from_the_words(self):
        words = [Word("a", 5.0, 6.4), Word("b", 6.4, 8.0)]
        sweeps = [d for kind, d in durations(self.sung("a, b.", words)) if kind == "kf"]
        self.assertEqual(sweeps, [140, 160])

    def test_a_text_that_does_not_line_up_falls_back_to_the_words(self):
        # Nothing to pair against, so show the tokens that do have timings
        # rather than mis-attach the sweep to the wrong glyphs.
        words = [Word("a", 5.0, 6.5), Word("b", 6.5, 8.0)]
        out = self.sung("one two three", words)
        self.assertIn("}a", out)
        self.assertNotIn("three", out)


class Windows(unittest.TestCase):
    def test_a_line_appears_before_it_is_sung(self):
        appear, _ = karaoke.windows(project(line(0, "one two", 40.0, 43.0)))[0]
        self.assertAlmostEqual(appear, 40.0 - karaoke.LEAD_IN)

    def test_a_line_holds_after_its_last_word(self):
        _, vanish = karaoke.windows(project(line(0, "one two", 40.0, 43.0)))[0]
        self.assertAlmostEqual(vanish, 43.0 + karaoke.HOLD)

    def test_a_lead_in_never_runs_before_the_track_starts(self):
        appear, _ = karaoke.windows(project(line(0, "one two", 0.4, 2.0)))[0]
        self.assertEqual(appear, 0.0)

    def test_two_lines_are_never_on_screen_at_once(self):
        spans = karaoke.windows(project(
            line(0, "one two", 40.0, 43.0),
            line(1, "three four", 43.2, 46.0),
        ))
        self.assertLessEqual(spans[0][1], spans[1][0])

    def test_back_to_back_lines_hand_over_with_no_blank_between_them(self):
        # A gap here reads as a blink, and lines in a chorus are 80 ms apart.
        spans = karaoke.windows(project(
            line(0, "one two", 40.0, 43.0),
            line(1, "three four", 43.0, 46.0),
        ))
        self.assertEqual(spans[0][1], spans[1][0])

    def test_a_clamped_line_still_covers_every_word_it_has(self):
        spans = karaoke.windows(project(
            line(0, "one two", 40.0, 43.0),
            line(1, "three four", 43.1, 46.0),
        ))
        self.assertLessEqual(spans[0][0], 40.0)
        self.assertGreaterEqual(spans[0][1], 43.0)
        self.assertLessEqual(spans[1][0], 43.1)


class TheFile(unittest.TestCase):
    def setUp(self):
        self.text = karaoke.build(project(
            line(0, "one two", 40.0, 43.0),
            line(1, "three four", 44.0, 47.0),
            TimedLine(index=2, section=0, text="never aligned"),
        ))

    def test_it_parses_as_an_ass_script(self):
        for header in ("[Script Info]", "[V4+ Styles]", "[Events]"):
            self.assertIn(header, self.text)

    def test_the_style_declares_the_frame_the_positions_assume(self):
        self.assertIn(f"PlayResX: {karaoke.PLAY_W}", self.text)
        self.assertIn(f"PlayResY: {karaoke.PLAY_H}", self.text)

    def test_unaligned_lines_are_left_out(self):
        self.assertEqual(len(events(self.text)), 2)
        self.assertNotIn("never aligned", self.text)

    def test_every_event_ends_after_it_starts(self):
        for event in events(self.text):
            _, start, end = event.split(",", 3)[:3]
            self.assertLess(start, end)

    def test_secondary_is_the_unsung_colour_and_differs_from_primary(self):
        style = [ln for ln in self.text.splitlines() if ln.startswith("Style:")][0]
        primary, secondary = style.split(",")[3:5]
        self.assertNotEqual(primary, secondary)


if __name__ == "__main__":
    unittest.main()
