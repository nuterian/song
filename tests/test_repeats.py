"""Repeats vouching for each other: the grouping, the outlier rule, the pairing.

Stdlib only; the DTW transfer itself is measured on the bench, and what is
pinned here is everything that decides whether it runs: which lines count as
renditions of each other, when a word is an outlier, and which rendition may
be a source. The numbers are the ones in song/align/repeats.py.
"""

import unittest

from song.align import repeats
from song.parse_lyrics import Section
from song.project import Project, TimedLine, Word


def line(index, section, text, start, durs, gaps=None):
    """A line whose words have the given durations, shut unless `gaps`."""
    words = []
    t = start
    gaps = gaps or [0.0] * len(durs)
    for token, d, g in zip(text.split(), durs, gaps):
        words.append(Word(token, t, t + d))
        t += d + g
    return TimedLine(index=index, section=section, text=text,
                     start=start, end=words[-1].end, words=words)


def project(sections, lines):
    return Project(
        audio_path="a.wav", lyrics_path="l.txt", duration=300.0,
        sections=[Section(index=i, name=name, line_indices=members)
                  for i, (name, members) in enumerate(sections)],
        lines=lines,
    )


def chorus(times):
    """Three choruses, two lines each, the second line a different melody."""
    lines, sections, index = [], [], 0
    for n, t in enumerate(times):
        members = []
        lines.append(line(index, n, "you're my gravity", t, [0.3, 0.4, 1.0]))
        members.append(index); index += 1
        lines.append(line(index, n, "you're my gravity", t + 3.0, [0.3, 0.4, 1.6]))
        members.append(index); index += 1
        sections.append((f"Chorus {n}", members))
    return sections, lines


class Grouping(unittest.TestCase):
    def test_renditions_group_by_text_and_position_not_text_alone(self):
        sections, lines = chorus([10.0, 60.0, 110.0])
        g = repeats.groups(project(sections, lines))
        self.assertEqual(sorted(g), [("you're my gravity", 0), ("you're my gravity", 1)])
        self.assertEqual([ln.index for ln in g[("you're my gravity", 0)]], [0, 2, 4])

    def test_fewer_than_three_renditions_is_no_group(self):
        sections, lines = chorus([10.0, 60.0])
        self.assertEqual(repeats.groups(project(sections, lines)), {})

    def test_a_rendition_with_a_different_word_count_breaks_the_group(self):
        sections, lines = chorus([10.0, 60.0, 110.0])
        lines[2].words = lines[2].words[:2]
        self.assertNotIn(("you're my gravity", 0), repeats.groups(project(sections, lines)))

    def test_punctuation_and_case_do_not_split_a_group(self):
        sections, lines = chorus([10.0, 60.0, 110.0])
        lines[2].text = "You're my Gravity,"
        self.assertEqual(len(repeats.groups(project(sections, lines))[("you're my gravity", 0)]), 3)


class Outliers(unittest.TestCase):
    def test_a_word_twice_as_long_as_agreeing_siblings_is_an_outlier(self):
        sections, lines = chorus([10.0, 60.0, 110.0])
        lines[2].words[1].end += 0.4          # "my" 0.4 -> 0.8 s
        lines[2].words[2].start += 0.4
        found = repeats.outliers(project(sections, lines))
        self.assertEqual([(o.line, o.word, o.text) for o in found], [(2, 1, "my")])
        o = found[0]
        self.assertAlmostEqual(o.median, 0.4)
        self.assertAlmostEqual(o.current, lines[2].words[2].start)
        self.assertAlmostEqual(o.proposed, lines[2].words[1].start + 0.4)

    def test_the_issue_is_on_the_boundary_after_the_word(self):
        sections, lines = chorus([10.0, 60.0, 110.0])
        lines[2].words[1].end += 0.5          # "my" 0.4 -> 0.9 s, 2.25x
        lines[2].words[2].start += 0.5
        d = repeats.outliers(project(sections, lines))[0].issue()
        self.assertEqual((d["line"], d["word"], d["scope"]), (2, 2, "word"))
        self.assertIn("2.2x as long", d["reasons"][0])
        self.assertEqual(d["severity"], 2)

    def test_a_word_under_twice_its_siblings_is_the_lower_severity(self):
        sections, lines = chorus([10.0, 60.0, 110.0])
        lines[2].words[1].end += 0.3          # 1.75x
        lines[2].words[2].start += 0.3
        self.assertEqual(repeats.outliers(project(sections, lines))[0].issue()["severity"], 1)

    def test_a_small_absolute_difference_is_not_an_outlier(self):
        sections, lines = chorus([10.0, 60.0, 110.0])
        # "you're" 0.30 -> 0.42 is 1.4x, and under ABS anyway
        lines[2].words[0].end += 0.12
        lines[2].words[1].start += 0.12
        self.assertEqual(repeats.outliers(project(sections, lines)), [])

    def test_siblings_that_disagree_with_each_other_flag_nothing(self):
        sections, lines = chorus([10.0, 60.0, 110.0])
        # Three different lengths for "my": 0.4, 0.8, 1.6. No majority.
        lines[2].words[1].end += 0.4; lines[2].words[2].start += 0.4
        lines[4].words[1].end += 1.2; lines[4].words[2].start += 1.2
        self.assertEqual(repeats.outliers(project(sections, lines)), [])

    def test_the_last_word_of_a_line_is_never_queued(self):
        sections, lines = chorus([10.0, 60.0, 110.0])
        lines[2].words[2].end += 2.0          # "gravity" held twice as long
        lines[2].end += 2.0
        self.assertEqual(repeats.outliers(project(sections, lines)), [])


class TransferPairs(unittest.TestCase):
    def test_an_outlier_rendition_is_paired_with_the_nearest_trusted_one(self):
        sections, lines = chorus([10.0, 60.0, 110.0])
        # Line 2 squeezed to half length on every word.
        for w in lines[2].words:
            w.start = 60.0 + (w.start - 60.0) / 2
            w.end = 60.0 + (w.end - 60.0) / 2
        lines[2].end = lines[2].words[-1].end
        pairs = repeats.transfer_pairs(project(sections, lines))
        self.assertEqual([(s.index, t.index) for s, t, _, _ in pairs], [(0, 2)])
        _, _, sdev, tdev = pairs[0]
        self.assertLess(sdev, repeats.TRUSTED)
        self.assertGreater(tdev, repeats.OUTLIER)

    def test_no_trusted_source_means_no_transfer(self):
        # Three renditions that each hold the median on a different word, so
        # none of them sits within TRUSTED of the group's medians.
        sections = [("Chorus 0", [0]), ("Chorus 1", [1]), ("Chorus 2", [2])]
        lines = [
            line(0, 0, "you're my gravity", 10.0, [0.3, 1.0, 1.0]),
            line(1, 1, "you're my gravity", 60.0, [0.3, 0.4, 1.6]),
            line(2, 2, "you're my gravity", 110.0, [0.3, 0.6, 2.5]),
        ]
        self.assertEqual(repeats.transfer_pairs(project(sections, lines)), [])

    def test_a_locked_line_is_never_a_target(self):
        sections, lines = chorus([10.0, 60.0, 110.0])
        for w in lines[2].words:
            w.start = 60.0 + (w.start - 60.0) / 2
            w.end = 60.0 + (w.end - 60.0) / 2
        lines[2].end = lines[2].words[-1].end
        lines[2].locked = True
        self.assertEqual(repeats.transfer_pairs(project(sections, lines)), [])


if __name__ == "__main__":
    unittest.main()
