"""
Read a broadcast scoreboard, and know when it cannot be trusted.

Measured across three broadcasts, the scoreboard is by a wide margin the most
reliable source of what happened: it identified every delivery in a window where
the vision detector found 18 of 29. That makes it the natural spine of the
pipeline -- but only if its failures are visible, because a scoreboard that has
quietly stopped updating looks exactly like a quiet passage of play.

So this module reports two things, always together: what it read, and where it
could not read. The gaps are not an error condition to be swallowed; they are
the input to whatever fills them. When the board reappears, the ball counter has
usually jumped, which says precisely how many deliveries went unseen -- turning
"find the deliveries" into "place three known deliveries in this 90-second
window", a far easier problem for a weaker detector to take on.

The parsing rules here are scar tissue. Each one is a bug that produced
confident, plausible, wrong numbers with no error raised.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

#: No limited-overs innings runs longer than this, so a larger "over number" is
#: a misread rather than a match.
MAX_OVERS = 50

#: A batting side's score never falls, and no single delivery yields more than 7
#: (six plus an overthrow). Anything outside that is an OCR misread, not cricket.
MAX_RUNS_PER_BALL = 7

#: How far the ball counter must fall to count as an innings change rather than
#: a misread digit, and where it must land. A new innings starts near zero; a
#: garbled reading of "11.4 OVERS" does not.
RESET_BALL_DROP = 12
RESET_BALL_CEILING = 12

#: Consecutive low readings required before believing an innings actually
#: changed. A real break lasts minutes -- dozens of samples; a misread lasts one.
#: Without this, a single bad frame at ball 60 split one innings into three.
RESET_CONFIRM_SAMPLES = 5

#: Consecutive unreadable samples before a span is called an occlusion rather
#: than a single bad frame. Replays and full-screen graphics cover the board for
#: seconds at a time; measured parse rate on a professional broadcast was 72%,
#: against 92% on a simpler one -- better production hides the board MORE.
OCCLUSION_MIN_SAMPLES = 3

#: How long the counter may sit unchanged, in seconds, before the board is
#: called stale. Measured median gaps between deliveries are 32-46s and the
#: slowest tenth around 70s, so this is several balls' worth of nothing.
#:
#: This is the guard that matters most. Every other failure here is loud; a
#: frozen graphics system is silent, and a stalled counter is indistinguishable
#: from a quiet match unless something is explicitly watching for it.
STALE_AFTER_SEC = 300.0


@dataclass(frozen=True)
class ScoreboardLayout:
    """One broadcaster's way of writing the score."""

    name: str
    pattern: "re.Pattern[str]"
    #: Group indices for runs, wickets, whole overs, fractional overs.
    groups: Tuple[int, int, int, int]


LAYOUTS: Tuple[ScoreboardLayout, ...] = (
    # "SLA V BRO 91 - 3  12.1 OVERS" (CricCenter: MLC U21, college cricket).
    #
    # The separator is one glyph and OCR renders it as -, I, ~, O, C, F and
    # sometimes a digit, so it is matched as a single throwaway token and the
    # match is anchored on the rigid "N.N OVERS" tail. Making it optional once
    # let "66 2 2 10.0 OVERS" match at the second 2 and report a score of 2,
    # alternating with the correct parse every few seconds.
    ScoreboardLayout(
        "criccenter",
        re.compile(r"(\d{1,3})\s*\S?\s*(\d)\s+(\d{1,2})\s*[.,]\s*(\d)\s*OVERS", re.I),
        (1, 2, 3, 4),
    ),
    # "MPT 80/0 RR 16.55 OVERS 4.5" (CricClubs: Minor League Cricket).
    #
    # Runs and overs sit on separate rows with a run rate between them, so the
    # gap is matched permissively -- it contains digits, which a \D run cannot
    # cross.
    ScoreboardLayout(
        "cricclubs",
        re.compile(r"(\d{1,3})\s*/\s*(\d).{0,40}?OVERS\s*(\d{1,3})(?:\s*[.,]\s*(\d))?", re.I),
        (1, 2, 3, 4),
    ),
)


def parse_overs(whole: str, frac: Optional[str]) -> Optional[int]:
    """
    Turn an over reading into a count of legal deliveries.

    The decimal point is the first thing OCR loses at this size -- "3.1" comes
    back as "31" and "4.0" as "4" -- so when it is missing the last digit is
    treated as balls-within-the-over, which is only valid for 0-5. A reading
    that cannot be interpreted that way is rejected rather than guessed at.
    """
    if frac is not None:
        balls = int(frac)
        return int(whole) * 6 + balls if balls <= 5 else None
    if len(whole) == 1:
        return int(whole) * 6
    over, balls = int(whole[:-1]), int(whole[-1])
    if balls <= 5 and over <= MAX_OVERS:
        return over * 6 + balls
    return None


def parse_scoreboard(flat: str) -> Optional[Tuple[int, int, int, str]]:
    """First layout that reads this text: (runs, wickets, balls, layout name)."""
    for layout in LAYOUTS:
        m = layout.pattern.search(flat)
        if not m:
            continue
        gr, gw, go, gf = layout.groups
        balls = parse_overs(m.group(go), m.group(gf))
        if balls is None:
            continue
        return int(m.group(gr)), int(m.group(gw)), balls, layout.name
    return None


def is_innings_reset(last: dict, cur: dict) -> bool:
    """
    A genuine innings change, as opposed to a one-off OCR misread.

    Both counters must fall together and land near zero. Requiring *both* is
    what separates a reset from a transposed digit, which moves one field only.
    """
    return (
        cur["balls"] < last["balls"] - RESET_BALL_DROP
        and cur["runs"] < last["runs"]
        and cur["balls"] <= RESET_BALL_CEILING
    )


@dataclass
class Gap:
    """
    A span the scoreboard could not be read, and what it cost.

    `missed_balls` is the crucial field. The counter keeps running behind the
    graphic, so when the board returns its jump reveals exactly how many
    deliveries happened unseen. A fallback detector then has a count to satisfy
    rather than an open question, which is a much easier target.
    """

    start: float
    end: float
    #: Deliveries the counter advanced across the gap, when both edges were
    #: readable. None when nothing readable bounds the gap on one side.
    missed_balls: Optional[int]

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Timeline:
    """What the scoreboard said, and where it went quiet."""

    #: Cleaned readings, each tagged with its innings.
    rows: List[dict] = field(default_factory=list)
    gaps: List[Gap] = field(default_factory=list)
    #: Spans where the board was readable but the counter never moved.
    stale: List[Tuple[float, float]] = field(default_factory=list)
    parse_rate: float = 0.0

    @property
    def trustworthy(self) -> bool:
        """
        Whether the board can carry the pipeline on its own here.

        Deliberately conservative. A stale span means the counter stopped while
        the graphic kept rendering, which is the one failure that produces no
        error and no missing data -- only a match that appears not to have
        happened.
        """
        return not self.stale and self.parse_rate > 0.5

    def summary(self) -> str:
        bits = [f"{len(self.rows)} readings, parse rate {self.parse_rate:.0%}"]
        if self.gaps:
            missed = sum(g.missed_balls or 0 for g in self.gaps)
            bits.append(f"{len(self.gaps)} gaps hiding ~{missed} deliveries")
        if self.stale:
            bits.append(f"STALE: counter frozen in {len(self.stale)} span(s)")
        return " · ".join(bits)


def build_timeline(samples: List[dict], step: float) -> Timeline:
    """
    Clean a run of readings and report where the board failed.

    `samples` are per-timestamp dicts with `t` and either parsed `runs`/
    `wickets`/`balls` or None where OCR found nothing.
    """
    rows: List[dict] = []
    last: Optional[dict] = None
    innings = 0
    for s in samples:
        if s.get("runs") is None or s.get("balls") is None:
            continue
        if last is not None:
            balls_advanced = s["balls"] - last["balls"]
            runs_advanced = s["runs"] - last["runs"]
            if is_innings_reset(last, s) and _reset_confirmed(samples, s):
                innings += 1
            elif balls_advanced < 0 or runs_advanced < 0:
                continue  # the scoreboard never goes backwards mid-innings
            elif balls_advanced > 6 or runs_advanced > MAX_RUNS_PER_BALL * max(balls_advanced, 1):
                continue  # a jump that large is a misread, not a gap
        rows.append({**s, "innings": innings})
        last = s

    readable: Set[float] = {round(r["t"], 2) for r in rows}
    gaps = _find_gaps(samples, readable, rows, step)
    stale = _find_stale(rows)
    parse_rate = len(rows) / len(samples) if samples else 0.0

    timeline = Timeline(rows=rows, gaps=gaps, stale=stale, parse_rate=parse_rate)
    if stale:
        logger.warning("scoreboard counter frozen in %d span(s): %s", len(stale), stale)
    return timeline


def _reset_confirmed(samples: List[dict], at: dict) -> bool:
    """Does the low reading persist, or was it one bad frame?"""
    seen = 0
    for s in samples:
        if s["t"] <= at["t"] or s.get("balls") is None:
            continue
        if s["balls"] > RESET_BALL_CEILING:
            return False
        seen += 1
        if seen >= RESET_CONFIRM_SAMPLES:
            return True
    return seen > 0


def _find_gaps(
    samples: List[dict], readable: Set[float], rows: List[dict], step: float
) -> List[Gap]:
    """Runs of consecutive unreadable samples, and the deliveries they hid."""
    gaps: List[Gap] = []
    run: List[dict] = []
    for s in samples:
        if round(s["t"], 2) in readable:
            if len(run) >= OCCLUSION_MIN_SAMPLES:
                gaps.append(_close_gap(run, rows, step))
            run = []
        else:
            run.append(s)
    if len(run) >= OCCLUSION_MIN_SAMPLES:
        gaps.append(_close_gap(run, rows, step))
    return gaps


def _close_gap(run: List[dict], rows: List[dict], step: float) -> Gap:
    start, end = run[0]["t"] - step, run[-1]["t"] + step
    before = [r for r in rows if r["t"] <= start]
    after = [r for r in rows if r["t"] >= end]
    missed = None
    if before and after and after[0]["innings"] == before[-1]["innings"]:
        missed = max(0, after[0]["balls"] - before[-1]["balls"])
    return Gap(start=start, end=end, missed_balls=missed)


def _find_stale(rows: List[dict]) -> List[Tuple[float, float]]:
    """
    Spans where the board rendered fine but the ball counter never advanced.

    Distinct from a gap: there is no missing data to fill, which is exactly why
    it is dangerous. Nothing downstream would notice.
    """
    stale: List[Tuple[float, float]] = []
    if not rows:
        return stale
    anchor = rows[0]
    for row in rows[1:]:
        if row["balls"] != anchor["balls"] or row["innings"] != anchor["innings"]:
            anchor = row
            continue
        if row["t"] - anchor["t"] >= STALE_AFTER_SEC:
            if stale and stale[-1][1] >= anchor["t"]:
                stale[-1] = (stale[-1][0], row["t"])
            else:
                stale.append((anchor["t"], row["t"]))
    return stale
