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

Deliberately NOT marked calibrated. It found every delivery in the one window
measured -- but that window's ground truth was derived from this same reader, so
the number grades it against itself. Until an independent source confirms it,
`calibrated=False` stands and fusion flattens its confidence like any other
unmeasured detector.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

from .fusion import Detector, Signal
from .scoreboard import Timeline, build_timeline

logger = logging.getLogger(__name__)

#: Seconds the counter trails the ball. Hand-verified on two deliveries, where
#: releases at 4511.6s and 4528.1s were logged at 4515s and 4539s -- lags of 3.4
#: and 10.9 seconds. The wide spread is the point: a defended ball is logged
#: almost at once, while a six is only recorded once it has been tracked to the
#: rope and signalled.
#:
#: PROVISIONAL, from n=2. It shifts the reported moment, so it is wrong to treat
#: as precise -- which is what `SCOREBOARD_TIME_SIGMA` exists to declare.
SCOREBOARD_LAG_SEC = 7.0

#: How far the corrected timestamp can still be out, in seconds. Covers the
#: measured 3-11s lag spread plus the 3s OCR sampling interval. Large on
#: purpose: it is what stops the board from dragging a fused timestamp away from
#: a detector that actually knows the moment.
SCOREBOARD_TIME_SIGMA = 4.0

#: Confidence attached to a delivery the counter actually advanced through.
#: High because the counter incrementing is close to proof that a legal ball was
#: bowled -- far stronger evidence than any motion heuristic has produced.
DELIVERY_CONFIDENCE = 0.92

#: Confidence for a delivery known only because the counter jumped across an
#: occluded span. The ball certainly happened; its position inside the gap is
#: guesswork, so the timing sigma widens to the gap itself.
OCCLUDED_CONFIDENCE = 0.55


def signals_from_timeline(timeline: Timeline) -> List[Signal]:
    """
    Turn a read scoreboard into delivery signals.

    Two kinds come out. Deliveries seen directly get a timestamp corrected
    backwards by the measured lag. Deliveries known only from a counter jump
    across a gap get spread evenly through that gap, with an uncertainty as wide
    as the gap -- honest about the fact that the board can prove they happened
    and cannot say where.
    """
    signals: List[Signal] = []

    prev: Optional[dict] = None
    for row in timeline.rows:
        if (
            prev is not None
            and row["balls"] > prev["balls"]
            and row["innings"] == prev["innings"]
        ):
            signals.append(
                Signal(
                    detector="scoreboard",
                    t=row["t"] - SCOREBOARD_LAG_SEC,
                    confidence=DELIVERY_CONFIDENCE,
                    time_sigma=SCOREBOARD_TIME_SIGMA,
                    evidence={
                        "tick_t": row["t"],
                        "balls_bowled": float(row["balls"]),
                        "assumed_lag": SCOREBOARD_LAG_SEC,
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
        return signals_from_timeline(timeline)

    return Detector(
        name="scoreboard",
        run=run,
        requires=("scoreboard",),
        # See the module docstring: 29/29 is measured against ground truth this
        # same reader produced, so it grades itself. Not calibrated until an
        # independent source says so.
        calibrated=False,
    )
