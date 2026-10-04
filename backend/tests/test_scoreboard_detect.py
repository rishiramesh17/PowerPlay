"""
Tests for the scoreboard wrapped as a fusion detector.

It is the opposite shape to the vision detector: near-certain a ball was bowled,
vague about when. Both halves of that have to survive into the signals, because
fusion uses confidence and timing precision for different things -- and getting
them the wrong way round lets the surer detector drag the timestamp away from
the more precise one.
"""

import pytest

from processing import scoreboard_detect as sd
from processing.scoreboard import Gap, Timeline


def _row(t, runs, balls, innings=0):
    return {"t": float(t), "runs": runs, "wickets": 0, "balls": balls, "innings": innings}


def test_each_counter_increment_becomes_one_signal():
    tl = Timeline(rows=[_row(0, 10, 6), _row(3, 11, 7), _row(6, 11, 8)], parse_rate=1.0)
    sigs = sd.signals_from_timeline(tl)
    assert len(sigs) == 2
    assert all(s.detector == "scoreboard" for s in sigs)


def test_a_signal_is_shifted_back_by_the_measured_lag():
    """
    The counter ticks when the operator updates it, not when the ball is bowled.
    Reporting the tick as the delivery time would be wrong by a measured 3-11s.
    """
    tl = Timeline(rows=[_row(100, 10, 6), _row(103, 11, 7)], parse_rate=1.0)
    sig = sd.signals_from_timeline(tl)[0]
    assert sig.t == pytest.approx(103.0 - sd.SCOREBOARD_LAG_SEC)
    assert sig.evidence["tick_t"] == 103.0, "the raw tick stays recoverable"


def test_it_is_confident_about_the_event_and_vague_about_the_moment():
    """The whole reason it is worth fusing with a motion detector."""
    tl = Timeline(rows=[_row(0, 10, 6), _row(3, 11, 7)], parse_rate=1.0)
    sig = sd.signals_from_timeline(tl)[0]
    # High, but capped at the lower bound of the interval around a perfect 30/30
    # against an independent scorecard -- a flawless small sample does not license
    # claiming certainty.
    assert 0.85 < sig.confidence < 1.0
    # Vague about the moment relative to a motion detector (~0.4s), which is the
    # comparison that matters -- not vague in absolute terms. Measurement brought
    # this down from a guessed 4.0 to 2.2, and that is a real gain: it is the
    # difference between a clip that starts on the run-up and one that does not.
    assert sig.time_sigma > 4 * 0.4


def test_no_signal_is_emitted_across_an_innings_break():
    """The new side starting at ball 1 is not the old side bowling another ball."""
    tl = Timeline(
        rows=[_row(0, 150, 118, innings=0), _row(3, 4, 1, innings=1)], parse_rate=1.0
    )
    assert sd.signals_from_timeline(tl) == []


def test_deliveries_hidden_by_occlusion_are_still_reported():
    """
    The counter keeps running behind a graphic, so a jump proves the balls
    happened. Dropping them would lose real deliveries the board can prove.
    """
    tl = Timeline(rows=[], gaps=[Gap(start=100.0, end=200.0, missed_balls=3)],
                  parse_rate=0.8)
    sigs = sd.signals_from_timeline(tl)
    assert len(sigs) == 3
    assert all(100.0 < s.t < 200.0 for s in sigs)


def test_occluded_deliveries_admit_they_are_badly_timed():
    """
    The board proves the count and says nothing about spacing, so the
    uncertainty must be as wide as the gap. Anything tighter would let a guess
    outrank a detector that actually saw the moment.
    """
    tl = Timeline(rows=[], gaps=[Gap(start=100.0, end=200.0, missed_balls=2)],
                  parse_rate=0.8)
    for s in sd.signals_from_timeline(tl):
        assert s.time_sigma >= 50.0
        assert s.confidence < sd.DELIVERY_CONFIDENCE
        assert s.evidence["occluded"] == 1.0


def test_a_gap_that_hid_nothing_produces_nothing():
    tl = Timeline(rows=[], gaps=[Gap(start=100.0, end=140.0, missed_balls=0)],
                  parse_rate=0.9)
    assert sd.signals_from_timeline(tl) == []


def test_an_uncountable_gap_produces_nothing():
    """missed_balls is None when nothing readable bounds the gap. Not zero."""
    tl = Timeline(rows=[], gaps=[Gap(start=100.0, end=140.0, missed_balls=None)],
                  parse_rate=0.9)
    assert sd.signals_from_timeline(tl) == []


# --- the detector wrapper ----------------------------------------------------

def _samples(n, step=3.0, advance_every=10):
    out = []
    balls = 6
    for i in range(n):
        if i and i % advance_every == 0:
            balls += 1
        out.append({"t": i * step, "runs": 10 + balls, "wickets": 0, "balls": balls})
    return out


def test_the_detector_requires_a_scoreboard():
    assert sd.make_detector([], step=3.0).requires == ("scoreboard",)


def test_it_abstains_rather_than_reporting_from_a_frozen_board():
    """
    A stalled graphics system renders perfectly and never increments. There is
    no missing data and no error -- reporting "no deliveries" from it would be
    the worst available answer, so it declines to judge instead.
    """
    frozen = [{"t": i * 3.0, "runs": 50, "wickets": 0, "balls": 30} for i in range(200)]
    assert sd.make_detector(frozen, step=3.0).run() is None


def test_it_reports_normally_from_a_healthy_board():
    out = sd.make_detector(_samples(120), step=3.0).run()
    assert out is not None and len(out) > 0


def test_counting_is_calibrated_and_timing_is_measured_separately():
    """
    Calibration is per-claim, not per-detector.

    Counting was measured at 30/30 against a CricClubs scorecard kept by a human
    scorer, independent of the graphics this parses. Timing came later and from
    elsewhere -- 15 hand-labelled releases -- and is reported through time_sigma
    rather than folded into the same number.
    """
    assert sd.make_detector([], step=3.0).calibrated is True
    assert sd.SCOREBOARD_TIME_SIGMA == 2.2


def test_a_tick_after_a_blackout_is_treated_as_a_different_regime():
    """
    Measured, not assumed: ticks with the board continuously visible trail the
    ball by 10.1s +/- 2.2s; ticks where it had gone dark trail by 21.5s +/- 10.0s,
    because what we see is the board REAPPEARING after a replay. Permutation test
    on occlusion gave p = 0.005; on outcome, p = 0.19.
    """
    assert sd.OCCLUDED_TICK_LAG_SEC > sd.SCOREBOARD_LAG_SEC
    assert sd.OCCLUDED_TICK_TIME_SIGMA > sd.SCOREBOARD_TIME_SIGMA

    from processing.scoreboard import Gap
    tl = Timeline(rows=[_row(0, 10, 6), _row(30, 11, 7)],
                  gaps=[Gap(start=12.0, end=30.0, missed_balls=0)], parse_rate=1.0)
    sig = next(s for s in sd.signals_from_timeline(tl, step=3.0)
               if s.evidence.get("tick_t") == 30.0)
    assert sig.evidence["after_blackout"] == 1.0
    assert sig.time_sigma == sd.OCCLUDED_TICK_TIME_SIGMA
    assert sig.t == 30.0 - sd.OCCLUDED_TICK_LAG_SEC


def test_timing_uncertainty_always_lets_a_real_timer_win():
    """
    The board must never drag a fused timestamp away from a detector that knows
    the moment. The run-up localizer reports sigma around 0.4s, so both of the
    board's regimes have to stay far above that for inverse-variance weighting
    to do its job.
    """
    assert sd.SCOREBOARD_TIME_SIGMA > 4 * 0.4
    assert sd.OCCLUDED_TICK_TIME_SIGMA > 4 * 0.4
