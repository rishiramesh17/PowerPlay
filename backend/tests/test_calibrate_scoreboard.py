"""
Tests for the scorecard parser.

Every silent-wrong-answer bug in this project has been a parsing bug: a regex
that matched at the wrong offset, a decimal point OCR dropped, an innings reset
read as corruption. This parser now decides whether the scoreboard reader is
trusted to report alone, so a quiet mistake here propagates straight into the
pipeline's confidence in itself.
"""

import pytest

from tools.calibrate_scoreboard import (
    parse_scorecard,
    wilson_lower,
    _is_extra,
    _runs_scored,
    compare,
)


def _block(over_ball: str, desc: str, clock: str = "08:06 PM") -> str:
    return (
        f'<div class="text-md font-semibold">{over_ball}</div>'
        f'<div class="text-md text-gray-900 leading-relaxed">{desc}</div>'
        f"<span>{clock}</span>"
    )


class TestExtras:
    """Wides and no-balls are bowled but do not advance the ball counter."""

    @pytest.mark.parametrize("desc", [
        "A De Silva to S Modani WIDE",
        "A De Silva to S Modani 5 WIDES",
        "Y Kiran to J Tromp, 5 runs FOUR NO BALL",
    ])
    def test_extras_do_not_count_as_legal_deliveries(self, desc):
        assert _is_extra(desc)

    @pytest.mark.parametrize("desc", [
        "S Shaah to S Modani, 0 run",
        "S Shaah to S Modani, 6 runs SIX",
        "A De Silva to S Modani, 1 run LEG BYE",
    ])
    def test_legal_deliveries_are_not_extras(self, desc):
        assert not _is_extra(desc)

    def test_leg_bye_still_counts_as_a_ball(self):
        """
        A leg bye scores without the bat but is a legal delivery.

        Worth pinning separately: it is the one outcome that looks like an extra
        in the commentary and behaves like a normal ball in the counter.
        """
        cards = parse_scorecard(_block("12.5", "A De Silva to A Bhoje, 1 run LEG BYE"))
        assert len(cards) == 1
        assert cards[0]["runs"] == 1


class TestRuns:
    def test_plain_runs(self):
        assert _runs_scored("S Shaah to S Modani, 4 runs FOUR") == 4
        assert _runs_scored("S Shaah to S Modani, 0 run") == 0

    def test_a_wide_is_worth_one(self):
        assert _runs_scored("A De Silva to S Modani WIDE") == 1

    def test_multiple_wides_are_read_not_assumed(self):
        assert _runs_scored("A De Silva to S Modani 5 WIDES") == 5

    def test_a_no_ball_hit_for_four_already_includes_the_penalty(self):
        """The commentary sums it; adding the penalty again would inflate totals."""
        assert _runs_scored("Y Kiran to J Tromp, 5 runs FOUR NO BALL") == 5


class TestParsing:
    def test_extras_add_runs_without_advancing_the_counter(self):
        """
        The exact shape that broke the naive reading of over 4.2.

        Three entries, one legal ball: the cumulative total must include the
        extras, while the ball count must not.
        """
        markup = (
            _block("0.1", "A De Silva to S Modani WIDE")
            + _block("0.1", "A De Silva to S Modani 5 WIDES")
            + _block("0.1", "A De Silva to S Modani, 1 run")
        )
        rows = parse_scorecard(markup)
        assert [r["balls"] for r in rows] == [1]
        assert rows[0]["runs"] == 7

    def test_wickets_accumulate(self):
        markup = (
            _block("5.1", "V Suresh to S Modani, 1 run")
            + _block("5.2", "V Suresh to J Tromp OUT! CATCH Joshua Tromp c R Dar b V Suresh 32")
        )
        rows = parse_scorecard(markup)
        assert [r["wickets"] for r in rows] == [0, 1]

    def test_an_empty_page_raises_rather_than_reporting_zero_deliveries(self):
        """
        A Cloudflare challenge page parses to nothing, and so does a restyled
        scorecard. Returning an empty list would read downstream as "the reader
        missed every ball" -- a confident, plausible, wrong answer of exactly the
        kind this module exists to catch.
        """
        with pytest.raises(ValueError, match="no deliveries"):
            parse_scorecard("<html><body>Just a moment...</body></html>")


class TestWilson:
    def test_a_perfect_small_sample_does_not_license_certainty(self):
        assert wilson_lower(30, 30) == pytest.approx(0.886, abs=0.005)

    def test_the_bound_rises_with_more_evidence(self):
        assert wilson_lower(300, 300) > wilson_lower(30, 30)

    def test_it_is_always_below_the_point_estimate(self):
        for hits, n in [(1, 2), (9, 10), (29, 30), (99, 100)]:
            assert wilson_lower(hits, n) < hits / n

    def test_no_evidence_means_no_confidence(self):
        assert wilson_lower(0, 0) == 0.0


class TestCompare:
    @staticmethod
    def _truth(n):
        return [{"balls": i, "runs": i, "wickets": 0, "over_ball": f"{i//6}.{i%6}",
                 "clock": "08:00 PM", "desc": ""} for i in range(1, n + 1)]

    def test_deliveries_outside_the_observed_window_are_not_misses(self):
        """
        The reader is judged on what it was shown. Counting the rest of the match
        against it would make the analysed window length the thing measured.
        """
        rows = [{"t": float(i), "balls": i, "runs": i, "wickets": 0} for i in (5, 6, 7)]
        result = compare(rows, self._truth(50))
        assert result["window_balls"] == [5, 7]
        assert result["expected"] == 3
        assert result["recall"] == 1.0

    def test_a_skipped_ball_inside_the_window_is_a_miss(self):
        rows = [{"t": float(i), "balls": i, "runs": i, "wickets": 0} for i in (5, 6, 8)]
        result = compare(rows, self._truth(50))
        assert result["missed"] == [7]
        assert result["recall"] == pytest.approx(3 / 4)

    def test_a_ball_the_scorecard_never_recorded_is_spurious(self):
        rows = [{"t": float(i), "balls": i, "runs": i, "wickets": 0} for i in (1, 2, 3)]
        result = compare(rows, self._truth(2))
        assert result["spurious"] == [3]
        assert result["precision"] == pytest.approx(2 / 3)
