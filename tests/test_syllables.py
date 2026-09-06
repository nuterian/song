"""The syllable rule, pinned on the sample track's whole vocabulary.

Counts were checked by hand, word by word. The one the rule gets wrong is
listed as wrong, so a change that fixes it shows up here as a change.
"""

import unittest

from song import syllables

# Every distinct word in examples/lyrics.txt, with its syllable count.
VOCABULARY = {
    "a": 1, "across": 2, "after": 2, "air": 1, "and": 1, "beats": 1,
    "becomes": 2, "belong": 2, "bodies": 2, "breaks": 1, "breath": 1,
    "caught": 1, "close": 1, "collide": 2, "dancers": 2, "dawn": 1,
    "devotion": 3, "dissolve": 2, "don't": 1, "draw": 1, "electric": 3,
    "emotion": 3, "endless": 2, "endlessly": 3, "every": 3, "explosion": 3,
    "fades": 1, "feels": 1, "feet": 1, "find": 1, "fire": 1, "floating": 2,
    "floor": 1, "found": 1, "glance": 1, "gravity": 3, "haze": 1,
    "hearts": 1, "heat": 1, "high": 1, "in": 1, "inside": 2, "into": 2,
    "is": 1, "just": 1, "light": 1, "lights": 1, "lost": 1, "maze": 1,
    "me": 1, "more": 1, "motion": 2, "my": 1, "night's": 1, "on": 1,
    "orbit": 2, "our": 1, "pulling": 2, "pulls": 1, "pulse": 1, "pure": 1,
    "raw": 1, "repeat": 2, "rhythm": 2, "shadow": 2, "silence": 2,
    "silver": 2, "skip": 1, "skyline": 2, "slow": 1, "sound": 1,
    "spark": 1, "spinning": 2, "still": 1, "strong": 1, "the": 1,
    "they": 1, "this": 1, "through": 1, "trace": 1, "velvet": 2, "want": 1,
    "we": 1, "when": 1, "where": 1, "wild": 1, "within": 2, "worlds": 1,
    "you're": 1, "your": 1,
    # The internal silent "e" the rule cannot see.
    "something": 2,
}
KNOWN_WRONG = {"something": 3}


class Counts(unittest.TestCase):
    def test_the_whole_vocabulary(self):
        wrong = {w: syllables.count(w) for w, n in VOCABULARY.items()
                 if syllables.count(w) != n}
        self.assertEqual(wrong, KNOWN_WRONG)

    def test_punctuation_and_case_do_not_count(self):
        self.assertEqual(syllables.count("Motion,"), 2)
        self.assertEqual(syllables.count("devotion."), 3)
        self.assertEqual(syllables.count("You're"), 1)

    def test_a_word_with_no_letters_is_one_syllable(self):
        self.assertEqual(syllables.count("..."), 1)
        self.assertEqual(syllables.count(""), 1)

    def test_the_silent_e_corrections(self):
        self.assertEqual(syllables.count("little"), 2)      # -le keeps its e
        self.assertEqual(syllables.count("pulses"), 2)      # -ses is a syllable
        self.assertEqual(syllables.count("bodies"), 2)      # -ies is one
        self.assertEqual(syllables.count("the"), 1)         # one nucleus stays


class Splits(unittest.TestCase):
    def test_single_consonants_go_with_the_following_syllable(self):
        self.assertEqual(syllables.split("gravity"), ["gra", "vi", "ty"])
        self.assertEqual(syllables.split("motion"), ["mo", "tion"])
        self.assertEqual(syllables.split("devotion"), ["de", "vo", "tion"])
        self.assertEqual(syllables.split("emotion"), ["e", "mo", "tion"])

    def test_two_consonants_split_between(self):
        self.assertEqual(syllables.split("silver"), ["sil", "ver"])
        self.assertEqual(syllables.split("velvet"), ["vel", "vet"])
        self.assertEqual(syllables.split("endless"), ["end", "less"])
        self.assertEqual(syllables.split("spinning"), ["spin", "ning"])

    def test_a_digraph_stays_whole(self):
        self.assertEqual(syllables.split("within"), ["wi", "thin"])
        self.assertEqual(syllables.split("something"), ["so", "me", "thing"])   # the known miss

    def test_three_consonants_keep_a_double_or_an_onset_together(self):
        self.assertEqual(syllables.split("endlessly"), ["end", "less", "ly"])
        self.assertEqual(syllables.split("electric"), ["e", "lec", "tric"])
        self.assertEqual(syllables.split("explosion"), ["ex", "plo", "sion"])

    def test_a_silent_e_joins_the_syllable_before_it(self):
        self.assertEqual(syllables.split("skyline"), ["sky", "line"])
        self.assertEqual(syllables.split("collide"), ["col", "lide"])
        self.assertEqual(syllables.split("silence"), ["si", "lence"])
        self.assertEqual(syllables.split("becomes"), ["be", "comes"])

    def test_one_syllable_words_are_one_chunk(self):
        for w in ("through", "you're", "night's", "haze", "strong"):
            self.assertEqual(syllables.split(w), [syllables.letters(w)])

    def test_rhythm(self):
        self.assertEqual(syllables.split("rhythm"), ["rhy", "thm"])

    def test_chunks_always_reassemble_the_letters(self):
        for w in VOCABULARY:
            self.assertEqual("".join(syllables.split(w)), syllables.letters(w))
            self.assertEqual(len(syllables.split(w)), syllables.count(w))


if __name__ == "__main__":
    unittest.main()


class Chunks(unittest.TestCase):
    def test_punctuation_and_case_ride_on_the_chunk_before_them(self):
        self.assertEqual(syllables.chunks("Gravity,", ["gra", "vi", "ty"]), ["Gra", "vi", "ty,"])
        self.assertEqual(syllables.chunk_starts("Gravity,", ["gra", "vi", "ty"]), [0, 3, 5])

    def test_an_apostrophe_inside_a_word_stays_with_its_syllable(self):
        self.assertEqual(syllables.chunks("night's", ["nights"]), ["night's"])
        self.assertEqual(syllables.chunks("don't", ["dont"]), ["don't"])

    def test_letters_that_do_not_line_up_leave_the_word_whole(self):
        self.assertIsNone(syllables.chunk_starts("gravitas", ["gra", "vi", "ty"]))
        self.assertEqual(syllables.chunks("gravitas", ["gra", "vi", "ty"]), ["gravitas"])

    def test_the_ctc_form_lines_up_with_the_lyric_form(self):
        # The aligner sees "youre"; the lyric says "You're". Same chunks.
        parts = syllables.split("you're")
        self.assertEqual(syllables.chunks("You're", parts), ["You're"])
        parts = syllables.split("devotion")
        self.assertEqual(syllables.chunks("devotion,", parts), ["de", "vo", "tion,"])
