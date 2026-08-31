"""Parsing the one file a user writes by hand.

Section headers are the only syntax in the input, so getting them wrong is the
most likely way a first run goes sideways: a header parsed as a lyric becomes a
line the aligner hunts for in the audio and never hears.
"""

import unittest

from lyricsync.parse_lyrics import Section, parse, tokenize


LYRICS = """Verse 1 (8 bars, pulsing bass)
Light breaks through the skyline haze,
Feet find rhythm in endless maze,

[Chorus]
You're my gravity in motion,
Spinning worlds in slow explosion,

Bridge:
In the silence after heat.
"""


class HeaderForms(unittest.TestCase):
    def setUp(self):
        self.lyrics = parse(LYRICS)

    def test_all_three_header_spellings_are_structure_not_lyrics(self):
        texts = [ln.text for ln in self.lyrics.lines]
        for header in ("Verse 1", "[Chorus]", "Chorus", "Bridge:", "Bridge"):
            self.assertNotIn(header, texts)
        self.assertEqual(len(self.lyrics.lines), 5)

    def test_sections_are_named_in_order(self):
        self.assertEqual([s.name for s in self.lyrics.sections],
                         ["Verse 1", "Chorus", "Bridge"])

    def test_a_parenthesised_note_is_kept_off_the_name(self):
        self.assertEqual(self.lyrics.sections[0].name, "Verse 1")
        self.assertEqual(self.lyrics.sections[0].note, "8 bars, pulsing bass")

    def test_lines_are_numbered_from_zero_and_carry_their_section(self):
        self.assertEqual([ln.index for ln in self.lyrics.lines], [0, 1, 2, 3, 4])
        self.assertEqual([ln.section for ln in self.lyrics.lines], [0, 0, 1, 1, 2])

    def test_each_section_knows_its_own_lines(self):
        self.assertEqual([s.line_indices for s in self.lyrics.sections],
                         [[0, 1], [2, 3], [4]])

    def test_plain_text_is_the_sung_lines_only(self):
        self.assertEqual(self.lyrics.plain_text.splitlines(),
                         [ln.text for ln in self.lyrics.lines])


class LinesThatOnlyLookLikeHeaders(unittest.TestCase):
    """The parser has to be shy: a short lyric must not become structure."""

    def test_a_short_lyric_is_not_a_header(self):
        lyrics = parse("[Chorus]\nStill in motion\nGravity in motion.\n")
        self.assertEqual(len(lyrics.lines), 2)

    def test_a_bare_header_ending_in_sentence_punctuation_is_a_lyric(self):
        # "Bridge." reads as a line; only "Bridge" or "[Bridge]" is structure.
        lyrics = parse("[Verse]\nSomething.\nBridge.\n")
        self.assertEqual([ln.text for ln in lyrics.lines], ["Something.", "Bridge."])

    def test_every_spelling_the_readme_promises(self):
        for raw, name in (
            ("[Verse 1]", "Verse 1"),
            ("Chorus:", "Chorus"),
            ("(Bridge)", "Bridge"),
            ("Verse 1 (8 bars, pulsing bass)", "Verse 1"),
            ("Final Chorus", "Final Chorus"),
            ("Pre-Chorus", "Pre-Chorus"),
        ):
            lyrics = parse(f"{raw}\nA line here.\n")
            self.assertEqual([s.name for s in lyrics.sections], [name], raw)


class EmptySectionsAreDropped(unittest.TestCase):
    """A header with nothing under it is removed, and the rest renumbered.

    Downstream, section index is position in the list, so dropping one without
    remapping every line's `section` would silently reattach lyrics to the
    wrong heading.
    """

    def setUp(self):
        self.lyrics = parse(
            "[Intro]\n\n[Verse 1]\nA line here.\n\n(Instrumental)\n\n"
            "[Chorus]\nAnother line.\n"
        )

    def test_only_sections_with_lyrics_survive(self):
        self.assertEqual([s.name for s in self.lyrics.sections], ["Verse 1", "Chorus"])

    def test_surviving_sections_are_renumbered_contiguously(self):
        self.assertEqual([s.index for s in self.lyrics.sections], [0, 1])

    def test_lines_still_point_at_the_right_heading(self):
        for line in self.lyrics.lines:
            self.assertEqual(self.lyrics.section_of(line.index).name,
                             "Verse 1" if line.index == 0 else "Chorus")


class UnheadedLyricsStillParse(unittest.TestCase):
    def test_a_file_with_no_headers_gets_one_default_section(self):
        lyrics = parse("First line\nSecond line\n")
        self.assertEqual(len(lyrics.sections), 1)
        self.assertEqual(lyrics.sections[0].name, "Lyrics")
        self.assertEqual(lyrics.sections[0].line_indices, [0, 1])


class Tokenizing(unittest.TestCase):
    def test_apostrophes_are_kept_and_other_punctuation_dropped(self):
        self.assertEqual(tokenize("You're my gravity, in motion..."),
                         ["You're", "my", "gravity", "in", "motion"])

    def test_curly_and_straight_apostrophes_agree(self):
        # The lyrics file is typed by a human; a smart quote must not make a
        # word stop matching the same word from an aligner.
        self.assertEqual(tokenize("You’re my"), tokenize("You're my"))

    def test_an_ellipsis_character_matches_three_dots(self):
        self.assertEqual(tokenize("motion…"), tokenize("motion..."))

    def test_whitespace_only_text_yields_no_tokens(self):
        self.assertEqual(tokenize("   "), [])


class NonVocalHint(unittest.TestCase):
    def test_a_section_named_for_an_instrumental_is_flagged(self):
        self.assertFalse(Section(index=0, name="Instrumental").is_vocal_hint)
        self.assertFalse(Section(index=0, name="Guitar Solo").is_vocal_hint)
        self.assertTrue(Section(index=0, name="Verse 1").is_vocal_hint)


if __name__ == "__main__":
    unittest.main()
