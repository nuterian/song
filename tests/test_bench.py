"""The bench's arithmetic, pinned on a synthetic gold/candidate pair.

The bench is the floor every later measurement stands on, so its own numbers
have to be beyond argument: a median that is really a mean, a percentile that
interpolates, or a rest counted between lines rather than inside one would
move every delta in the plan file without anyone noticing. Each test here
builds the smallest project that exercises one rule and checks the number by
hand.
"""

import math
import unittest

from song import bench
from song.parse_lyrics import Section
from song.project import Project, TimedLine, Word


def line(index, text, spans, score=None):
    """A line whose words sit at the given (start, end) spans."""
    words = [Word(t, s, e) for t, (s, e) in zip(text.split(), spans)]
    ln = TimedLine(index=index, section=0, text=text,
                   start=spans[0][0], end=spans[-1][1], words=words)
    if score is not None:
        ln.score = {"total": score}
    return ln


def project(*lines):
    return Project(
        audio_path="a.wav", lyrics_path="l.txt", duration=100.0,
        sections=[Section(index=0, name="Verse",
                          line_indices=[ln.index for ln in lines])],
        lines=list(lines),
    )


class Statistics(unittest.TestCase):
    def test_median_of_odd_and_even_lists(self):
        self.assertEqual(bench.median([3.0, 1.0, 2.0]), 2.0)
        self.assertEqual(bench.median([4.0, 1.0, 3.0, 2.0]), 2.5)
        self.assertTrue(math.isnan(bench.median([])))

    def test_percentile_is_nearest_rank_not_interpolated(self):
        values = [float(i) for i in range(1, 11)]     # 1..10
        self.assertEqual(bench.percentile(values, 0.9), 9.0)
        self.assertEqual(bench.percentile(values, 0.5), 5.0)
        self.assertEqual(bench.percentile([7.0], 0.9), 7.0)

    def test_distribution_reports_absolute_spread_and_signed_bias(self):
        d = bench.distribution([0.04, -0.06, 0.12, 0.30])
        self.assertEqual(d["n"], 4)
        self.assertEqual(d["median"], 0.09)              # of |x|: .04 .06 .12 .30
        self.assertEqual(d["max"], 0.30)
        self.assertEqual(d["bias"], 0.08)                # of signed: -.06 .04 .12 .30
        self.assertEqual(d["within"]["50ms"], 25.0)
        self.assertEqual(d["within"]["100ms"], 50.0)
        self.assertEqual(d["within"]["200ms"], 75.0)

    def test_a_value_exactly_on_a_threshold_counts_as_within(self):
        d = bench.distribution([0.05, 0.1, 0.2])
        self.assertEqual(d["within"]["50ms"], round(100 / 3, 1))
        self.assertEqual(d["within"]["200ms"], 100.0)


class Pairing(unittest.TestCase):
    def test_words_pair_by_position_only(self):
        gold = project(line(0, "a b", [(1.0, 1.4), (1.5, 2.0)]))
        cand = project(line(0, "a b", [(1.1, 1.4), (1.6, 2.0)]))
        pairs, unpaired = bench.pair(gold, cand)
        self.assertEqual([k for _, _, k in pairs], [0, 1])
        self.assertEqual(unpaired, [])

    def test_a_word_count_mismatch_is_reported_not_guessed(self):
        gold = project(line(0, "a b c", [(1.0, 1.4), (1.5, 2.0), (2.0, 2.5)]))
        cand = project(line(0, "a b", [(1.1, 1.4), (1.6, 2.0)]))
        pairs, unpaired = bench.pair(gold, cand)
        self.assertEqual(pairs, [])
        self.assertEqual(unpaired[0]["line"], 0)
        self.assertIn("3 words in gold, 2 in candidate", unpaired[0]["why"])

    def test_an_untimed_line_on_either_side_is_unpaired(self):
        gold = project(line(0, "a b", [(1.0, 1.4), (1.5, 2.0)]),
                       TimedLine(index=1, section=0, text="c d"))
        cand = project(TimedLine(index=0, section=0, text="a b"),
                       line(1, "c d", [(3.0, 3.4), (3.5, 4.0)]))
        pairs, unpaired = bench.pair(gold, cand)
        self.assertEqual(pairs, [])
        self.assertEqual({u["line"]: u["why"] for u in unpaired},
                         {0: "not timed in candidate", 1: "not timed in gold"})


class Comparison(unittest.TestCase):
    def setUp(self):
        self.gold = project(
            line(0, "a b c", [(1.0, 1.4), (1.5, 2.0), (2.0, 2.5)]),
            line(1, "d e", [(4.0, 4.5), (5.0, 5.5)]),
        )
        self.cand = project(
            # a: +0.10 start, 0 end; b: -0.05 / +0.02; c: +0.02 / +0.30
            line(0, "a b c", [(1.1, 1.4), (1.45, 2.02), (2.02, 2.8)], score=95.0),
            # d: 0 / +0.4 (closes the rest); e: -0.1 / 0
            line(1, "d e", [(4.0, 4.9), (4.9, 5.5)], score=60.0),
        )

    def test_start_and_end_errors_are_candidate_minus_gold(self):
        r = bench.compare(self.gold, self.cand)
        self.assertEqual(r["n_words"], 5)
        self.assertEqual(r["n_lines"], 2)
        starts = sorted(w["start"] for w in r["worst"])
        self.assertEqual(starts, [-0.1, -0.05, 0.0, 0.02, 0.1])
        self.assertEqual(r["start"]["median"], 0.05)
        self.assertEqual(r["end"]["max"], 0.4)

    def test_line_starts_are_first_words_and_line_ends_are_last_words(self):
        r = bench.compare(self.gold, self.cand)
        self.assertEqual(r["line_start"]["n"], 2)
        self.assertEqual(r["line_start"]["max"], 0.1)     # 'a' +0.10, 'd' 0
        self.assertEqual(r["line_end"]["n"], 2)
        self.assertEqual(r["line_end"]["max"], 0.3)       # 'c' +0.30, 'e' 0

    def test_errors_split_by_the_candidates_line_score(self):
        r = bench.compare(self.gold, self.cand)
        self.assertEqual(r["by_score"]["90+"]["start"]["n"], 3)
        self.assertEqual(r["by_score"]["70-90"]["start"]["n"], 0)
        self.assertEqual(r["by_score"]["<70"]["start"]["n"], 2)
        self.assertEqual(r["by_score"]["<70"]["end"]["max"], 0.4)

    def test_the_worst_words_come_first(self):
        r = bench.compare(self.gold, self.cand)
        self.assertEqual(r["worst"][0]["text"], "d")     # |0.4| end error
        self.assertEqual(r["worst"][1]["text"], "c")     # |0.3|

    def test_an_unscored_candidate_falls_in_the_lowest_bucket(self):
        self.assertEqual(bench.bucket_of(TimedLine(index=0, section=0, text="x")), "<70")


class Rests(unittest.TestCase):
    def test_kept_closed_and_invented(self):
        gold = project(
            # rests after a (0.2) and after c (0.5); b-c shut
            line(0, "a b c d", [(1.0, 1.3), (1.5, 2.0), (2.0, 2.5), (3.0, 3.4)]),
        )
        cand = project(
            # keeps the one after a (0.16), closes the one after c, invents one after b
            line(0, "a b c d", [(1.0, 1.3), (1.46, 1.9), (2.1, 2.9), (2.9, 3.4)]),
        )
        r = bench.compare(gold, cand)["rests"]
        self.assertEqual(r["in_gold"], 2)
        self.assertEqual([e["after"] for e in r["kept"]], [0])
        self.assertEqual([e["after"] for e in r["closed"]], [2])
        self.assertEqual([e["after"] for e in r["invented"]], [1])

    def test_a_gap_below_the_rest_threshold_is_not_a_rest_on_either_side(self):
        gold = project(line(0, "a b", [(1.0, 1.4), (1.5, 2.0)]))      # 0.10 gap
        cand = project(line(0, "a b", [(1.0, 1.36), (1.5, 2.0)]))     # 0.14 gap
        r = bench.compare(gold, cand)["rests"]
        self.assertEqual((r["in_gold"], r["kept"], r["closed"], r["invented"]),
                         (0, [], [], []))

    def test_a_gap_exactly_at_the_threshold_is_a_rest(self):
        gold = project(line(0, "a b", [(1.0, 1.35), (1.5, 2.0)]))     # 0.15
        cand = project(line(0, "a b", [(1.0, 1.35), (1.5, 2.0)]))
        r = bench.compare(gold, cand)["rests"]
        self.assertEqual((r["in_gold"], len(r["kept"])), (1, 1))

    def test_the_space_between_lines_is_never_a_rest(self):
        gold = project(line(0, "a", [(1.0, 1.5)]), line(1, "b", [(3.0, 3.5)]))
        cand = project(line(0, "a", [(1.0, 1.5)]), line(1, "b", [(3.0, 3.5)]))
        self.assertEqual(bench.compare(gold, cand)["rests"]["in_gold"], 0)


class Report(unittest.TestCase):
    def test_the_report_carries_the_headline_numbers_and_the_unpaired_lines(self):
        gold = project(line(0, "a b", [(1.0, 1.4), (1.5, 2.0)]),
                       line(1, "c d e", [(3.0, 3.4), (3.5, 4.0), (4.0, 4.5)]))
        cand = project(line(0, "a b", [(1.1, 1.4), (1.5, 2.0)], score=80.0),
                       line(1, "c d", [(3.0, 3.4), (3.5, 4.5)], score=80.0))
        text = bench.format_report(bench.compare(gold, cand), "gold", "cand")
        self.assertIn("paired words             2 over 1 lines  (1 line(s) unpaired)", text)
        self.assertIn("3 words in gold, 2 in candidate", text)
        self.assertIn("word starts", text)
        self.assertIn("rests (gap >= 150ms) in gold 0", text)

    def test_an_empty_comparison_does_not_crash_the_report(self):
        text = bench.format_report(bench.compare(project(), project()))
        self.assertIn("(no words)", text)

    def test_the_default_gold_path_is_keyed_on_the_audio_name(self):
        p = project()
        p.audio_path = "examples/Gravity in Motion.wav"
        self.assertEqual(str(bench.default_gold(p)),
                         "examples/gold/gravity-in-motion.project.json")


if __name__ == "__main__":
    unittest.main()
