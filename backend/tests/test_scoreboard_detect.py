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
    assert sig.confidence > 0.9
    assert sig.time_sigma >= 4.0


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


def test_it_is_not_marked_calibrated():
    """
    It found 29 of 29 deliveries in the one window measured -- but that window's
    ground truth came from this same reader, so the number grades it against
    itself. Calibration needs an independent source.
    """
    assert sd.make_detector([], step=3.0).calibrated is False
