"""
The scoreboard as a delivery detector.

Measured on Minor League Cricket, the board identified 29 of 29 deliveries in a
window where the vision detector found 18. That earns it the centre of the
pipeline. What it is *not* good at is saying when: the counter ticks when the
graphics operator updates it, which trailed hand-verified deliveries by between
3 and 11 seconds.

So it reports high confidence and poor timing precision, which is the opposite
shape to the run-up localizer, and exactly why the two are worth fusing. The
board settles whether a ball was bowled; vision settles the moment.

CALIBRATED against the CricClubs ball-by-ball scorecard for this match, a record
kept by a human scorer at the ground and entirely independent of the broadcast
graphics parsed here. Over balls 8-37 the reader found 30 of 30 deliveries and
invented none. That replaces the previous figure, which was measured against
ground truth this same reader produced and therefore meant nothing.

`tools/calibrate_scoreboard.py` reproduces it.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

from .fusion import Detector, Signal
from .scoreboard import Timeline, build_timeline

logger = logging.getLogger(__name__)

#: Seconds the counter trails the ball when the board stayed visible.
#:
#: MEASURED on 15 hand-labelled releases: 9 where the board never went dark gave
#: 10.1s +/- 2.2s. This replaces 7.0, which was the midpoint of two observations
#: and 3.8s RMS wrong; 10.1 is 2.2s RMS wrong on the same deliveries.
SCOREBOARD_LAG_SEC = 10.1

#: Uncertainty on a clean tick. The measured standard deviation, not a margin
#: chosen for comfort.
SCOREBOARD_TIME_SIGMA = 2.2

#: The same two quantities when the board went dark before the tick.
#:
#: These are a different regime, not a worse case of the same one. On a boundary
#: the broadcast cuts to replay, hiding the board; what we record is it
#: REAPPEARING. Measured on the 6 such deliveries: 21.5s +/- 10.0s, against
#: 10.1s +/- 2.2s when it stayed visible. A permutation test puts occlusion at
#: p = 0.005.
#:
#: The spread is the honest part. Ten seconds of uncertainty is close to useless
#: for cutting a clip, and saying so is what lets vision carry the timing here
#: instead -- see how `time_sigma` is weighted in `fusion._fuse_cluster`.
OCCLUDED_TICK_LAG_SEC = 21.5
OCCLUDED_TICK_TIME_SIGMA = 10.0

#: Confidence attached to a delivery the counter actually advanced through.
#:
#: This is the lower bound of the 95% interval around a perfect 30/30 against an
#: independent scorecard -- not the 1.00 that was observed. A flawless run on
#: thirty deliveries is consistent with a true rate near 0.89, and quoting the
#: point estimate would reintroduce exactly the overclaiming the calibration
#: contract exists to stop. It rises as more matches are measured.
DELIVERY_CONFIDENCE = 0.886

#: Confidence for a delivery known only because the counter jumped across an
#: occluded span. The ball certainly happened; its position inside the gap is
#: guesswork, so the timing sigma widens to the gap itself.
OCCLUDED_CONFIDENCE = 0.55


def _follows_blackout(tick: float, timeline: Timeline, step: float) -> bool:
    """
    Did the board reappear at this tick after being hidden?

    This is the difference between a 10-second lag and a 21-second one, so it is
    asked per delivery rather than assumed for the match.
    """
    return any(abs(gap.end - tick) <= step + 0.1 for gap in timeline.gaps)


def signals_from_timeline(timeline: Timeline, step: float = 3.0) -> List[Signal]:
    """
    Turn a read scoreboard into delivery signals.

    Three kinds come out, and the distinction between the first two was measured
    rather than assumed. A tick while the board was continuously visible trails
    the ball by 10.1s and is good to about 2 seconds. A tick where the board had
    gone dark is the board REAPPEARING after a replay: it trails by 21.5s and is
    good to about 10, which is barely a timing claim at all. Deliveries known
    only from a counter jump across a gap get spread through it, with an
    uncertainty as wide as the gap.
    """
    signals: List[Signal] = []

    prev: Optional[dict] = None
    for row in timeline.rows:
        if (
            prev is not None
            and row["balls"] > prev["balls"]
            and row["innings"] == prev["innings"]
        ):
            dark = _follows_blackout(row["t"], timeline, step)
            lag = OCCLUDED_TICK_LAG_SEC if dark else SCOREBOARD_LAG_SEC
            sigma = OCCLUDED_TICK_TIME_SIGMA if dark else SCOREBOARD_TIME_SIGMA
            signals.append(
                Signal(
                    detector="scoreboard",
                    t=row["t"] - lag,
                    confidence=DELIVERY_CONFIDENCE,
                    time_sigma=sigma,
                    evidence={
                        "tick_t": row["t"],
                        "balls_bowled": float(row["balls"]),
                        "assumed_lag": lag,
                        "after_blackout": float(dark),
                    },
                )
            )
        prev = row

    for gap in timeline.gaps:
        if not gap.missed_balls:
            continue
        # Spread them through the gap. Nothing better is available: the counter
        # proves the count and says nothing about the spacing.
        step = gap.duration / (gap.missed_balls + 1)
        for i in range(gap.missed_balls):
            signals.append(
                Signal(
                    detector="scoreboard",
                    t=gap.start + step * (i + 1),
                    confidence=OCCLUDED_CONFIDENCE,
                    time_sigma=max(gap.duration / 2.0, SCOREBOARD_TIME_SIGMA),
                    evidence={
                        "occluded": 1.0,
                        "gap_start": gap.start,
                        "gap_end": gap.end,
                        "missed_balls": float(gap.missed_balls),
                    },
                )
            )

    signals.sort(key=lambda s: s.t)
    return signals


def make_detector(
    samples: Sequence[Dict], step: float, require_trustworthy: bool = True
) -> Detector:
    """
    Wrap a scan of the scoreboard as a fusion detector.

    `samples` are the per-timestamp OCR readings. When `require_trustworthy` is
    set the detector abstains rather than reporting anything from a board whose
    counter froze: a stalled graphics system produces no missing data and no
    error, only a match that appears not to have happened, and quietly reporting
    "no deliveries" from it would be the worst available answer.
    """

    def run() -> Optional[Sequence[Signal]]:
        timeline = build_timeline(list(samples), step=step)
        if require_trustworthy and not timeline.trustworthy:
            logger.warning("scoreboard detector abstaining: %s", timeline.summary())
            return None
        return signals_from_timeline(timeline, step=step)

    return Detector(
        name="scoreboard",
        run=run,
        requires=("scoreboard",),
        # Earned: 30/30 deliveries against an independent CricClubs scorecard.
        # Note this calibrates *counting*. The timing is separately measured
        # from 15 hand-labelled releases and reported through time_sigma, which
        # now differs per delivery depending on whether the board went dark.
        calibrated=True,
    )
