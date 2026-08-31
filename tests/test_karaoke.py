"""The .ass karaoke file: timestamps, and the \\kf durations under them.

libass will happily render a syntactically perfect file whose sweep is a
quarter-second behind the singer, and nothing in the pipeline notices. So the
arithmetic is pinned here: what the timestamps look like, that the durations
land on the word boundaries the project already agreed on, and that they still
do after a hundred words of rounding.
"""

import re
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
    """Every karaoke tag in a dialogue line, as (kind, centiseconds).

    Matched anywhere in an override block, because a word's block also carries
    the reset, the blur and the swell, and the order of those is not the point.
    """
    return [("kf" if sweep else "k", int(value))
            for sweep, value in re.findall(r"\\k(f?)(\d+)", event)]


def spoken(event: str) -> str:
    """An event's text with every override block taken out.

    Nine commas in before the text starts, and the text may hold commas of its
    own, so the split has to be counted rather than searched for.
    """
    return re.sub(r"\{[^}]*\}", "", event.split(",", 9)[9])


def events(text: str, style: str = "Lyric") -> list[str]:
    """The dialogue lines for one layer. Every lyric line writes two: the words,
    and the soft shadow underneath them."""
    return [ln for ln in text.splitlines()
            if ln.startswith("Dialogue:") and f",{style}," in ln]


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

    def test_a_line_with_no_words_is_plain_text_with_no_karaoke(self):
        ln = TimedLine(index=0, section=0, text="hummed", start=5.0, end=7.0)
        self.assertEqual(spoken("x,x,x,x,x,x,x,x,x," + karaoke.karaoke_text(ln, 500)),
                         "hummed")

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


class TheWordBeingSung(unittest.TestCase):
    """It fills in the accent, then hands itself back to ink."""

    def test_every_word_resets_first(self):
        # Without \r a transform on word one is still in force when word two is
        # drawn, and word two sweeps in the colour word one settled to.
        ln = line(0, "one two three", 10.0, 13.0)
        text = karaoke.karaoke_text(ln, 1000)
        self.assertEqual(text.count("\\r"), 3)
        for chunk in text.split("{")[1:]:
            if "\\kf" in chunk:
                self.assertTrue(chunk.startswith("\\r"), chunk)

    def test_the_sweep_goes_to_the_accent_and_the_settle_takes_it_to_ink(self):
        # \kf only has two states. The third - already sung - is one transform
        # per word, and it is the one that leaves a single word lit.
        style = [ln for ln in karaoke.build(project(line(0, "one two", 40.0, 43.0)))
                 .splitlines() if ln.startswith("Style: Lyric")][0]
        self.assertEqual(style.split(",")[3], karaoke.colour(karaoke.ACCENT))
        self.assertIn(karaoke.tag_colour(karaoke.INK), karaoke.settle(100))

    def test_the_accent_leaves_after_the_word_ends_not_before(self):
        ln = line(0, "alpha", 10.0, 11.0)
        start, _ = re.findall(r"\\t\((\d+),(\d+),\\1c",
                             karaoke.karaoke_text(ln, 1000))[0]
        self.assertGreaterEqual(int(start), 100)     # the word runs 0..100 ms in

    def test_the_settle_never_starts_before_its_own_event(self):
        # A line is drawn again in the slot above while the next one is sung,
        # and there every word ended before the event began.
        self.assertNotIn("(-", karaoke.settle(-400))

    def test_the_slot_state_is_repeated_in_every_word(self):
        # \r drops it, so each block has to say it again or only the first word
        # is the size and opacity of the slot it is in.
        ln = line(0, "one two three", 10.0, 13.0)
        text = karaoke.karaoke_text(ln, 1000, "\\fscx82\\fscy82")
        self.assertEqual(text.count("\\fscx82"), 3)


class ThreeLinesThatMove(unittest.TestCase):
    """The one being sung, with the one before and the one after either side."""

    def setUp(self):
        self.lines = [line(i, f"line {i} here", 10.0 + i * 5, 13.0 + i * 5)
                      for i in range(5)]
        self.text = karaoke.build(project(*self.lines))
        self.spans = karaoke.windows(project(*self.lines))

    def during(self, index):
        """Every event drawn while line `index` is the one being sung."""
        start = karaoke.ass_time(karaoke.centis(self.spans[index][0]))
        return [e for e in self.text.splitlines()
                if e.startswith("Dialogue:") and e.split(",")[1] == start]

    def arrives_at(self, event):
        r"""The y the event's \move ends at."""
        return int(re.search(r"\\move\(\d+,\d+,\d+,(\d+),", event).group(1))

    def test_the_middle_of_a_song_draws_four_lines_and_shows_three(self):
        # Four arrive; the fourth arrives at the stop above the frame's own,
        # which is how the line that has been read leaves.
        shown = self.during(2)
        self.assertEqual(len(shown), 4)
        arrivals = sorted(self.arrives_at(e) for e in shown)
        self.assertEqual(arrivals, sorted(karaoke.PLAY_H - slot for slot in (
            karaoke.SLOT_NEXT, karaoke.SLOT_NOW,
            karaoke.SLOT_PREV, karaoke.SLOT_OUT)))

    def test_the_neighbours_are_the_neighbours(self):
        shown = {self.arrives_at(e): spoken(e) for e in self.during(2)}
        for slot, text in ((karaoke.SLOT_PREV, "line 1 here"),
                           (karaoke.SLOT_NOW, "line 2 here"),
                           (karaoke.SLOT_NEXT, "line 3 here")):
            self.assertEqual(shown[karaoke.PLAY_H - slot], text)

    def test_every_line_on_screen_moves_at_every_change(self):
        # Moving only the ones that change slot leaves two of them sitting
        # almost on top of each other for the length of the move.
        for event in self.during(2):
            leaving, arriving = re.search(
                r"\\move\(\d+,(\d+),\d+,(\d+),", event).groups()
            self.assertNotEqual(leaving, arriving)

    def test_only_the_line_being_sung_is_swept(self):
        # A neighbour drawn with karaoke tags has every word already over or
        # not yet begun, so it fills to the accent and walks back to ink - a
        # line that has finished being sung relights as it leaves.
        for event in self.during(2):
            if spoken(event) != "line 2 here":
                self.assertNotIn("\\kf", event)

    def test_nothing_fades_except_the_two_ends_of_the_song(self):
        # Everything in between arrives from the invisible stop below and
        # leaves by the invisible one above, so it needs no fade of its own.
        faded = [e for e in self.text.splitlines() if "\\fad(" in e]
        self.assertIn("line 0 here", spoken(faded[0]))
        self.assertIn("line 4 here", spoken(faded[-1]))
        last = karaoke.ass_time(karaoke.centis(self.spans[-1][1]))
        for event in self.text.splitlines():
            if event.startswith("Dialogue:") and "\\fad(" not in event:
                self.assertNotEqual(event.split(",")[2], last)


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
        self.assertNotIn("never aligned", self.text)
        self.assertEqual(
            len({spoken(e) for e in self.text.splitlines()
                 if e.startswith("Dialogue:")}), 2)

    def test_secondary_is_the_unsung_colour_and_differs_from_primary(self):
        style = [ln for ln in self.text.splitlines() if ln.startswith("Style:")][0]
        primary, secondary = style.split(",")[3:5]
        self.assertNotEqual(primary, secondary)


if __name__ == "__main__":
    unittest.main()
