"""
Tests for scoreboard reading and its failure guards.

The scoreboard is the most reliable signal measured so far -- it identified
every delivery in a window where vision found 18 of 29 -- which is exactly why
its failures have to be loud. A board that has quietly stopped updating is
indistinguishable from a quiet passage of play, and every rule here exists
because some version of that produced confident, wrong numbers with no error.
"""

import pytest

from processing import scoreboard as sb


def _s(t, runs=None, wickets=None, balls=None):
    return {"t": float(t), "runs": runs, "wickets": wickets, "balls": balls}


def _run(start, n, step=3.0, runs=50, balls=30):
    """A stretch of identical readable samples."""
    return [_s(start + i * step, runs, 0, balls) for i in range(n)]


# --- layout parsing, against strings OCR actually produced -------------------

@pytest.mark.parametrize("text,expected", [
    ("SLA V BRO 91 - 3 12.1 OVERS", (91, 3, 73, "criccenter")),
    ("SLA V BRO 66 I 2 10.0 OVERS", (66, 2, 60, "criccenter")),
    # The separator read as a digit. Treating it as optional let this match at
    # the second 2 and report a score of 2.
    ("SLA V BRO 66 2 2 10.0 OVERS", (66, 2, 60, "criccenter")),
    ("MPT 80/0 RR 16.55 OVERS 4.5", (80, 0, 29, "cricclubs")),
    # Decimal lost by OCR: "3.1" -> "31", "4.0" -> "4".
    ("MPT 46/0 RR 14.53 OVERS 31", (46, 0, 19, "cricclubs")),
    ("MPT 60/0 RR I5.00 OVERS 4", (60, 0, 24, "cricclubs")),
])
def test_both_vendor_layouts_parse(text, expected):
    assert sb.parse_scoreboard(text) == expected


def test_unreadable_text_returns_none_rather_than_a_guess():
    assert sb.parse_scoreboard("") is None
    assert sb.parse_scoreboard("METROPLEX TRACERS VS ALL STARS") is None


def test_an_impossible_ball_count_is_rejected():
    """Seventh ball of an over does not exist, so the reading is a misread."""
    assert sb.parse_overs("4", "7") is None
    assert sb.parse_overs("4", "5") == 29


def test_a_missing_decimal_is_recovered_only_when_unambiguous():
    assert sb.parse_overs("31", None) == 19     # 3.1
    assert sb.parse_overs("4", None) == 24      # 4.0
    assert sb.parse_overs("123", None) == 75    # 12.3
    # Rejected, not guessed: the trailing digit cannot be a ball number, and
    # reading it as a whole over count would be absurd for a limited-overs game.
    assert sb.parse_overs("48", None) is None   # 4.8
    assert sb.parse_overs("129", None) is None  # 12.9


# --- occlusion: gaps carry the count of what they hid ------------------------

def test_a_gap_reports_how_many_deliveries_it_hid():
    """
    The counter keeps running behind the graphic, so its jump says exactly how
    many balls went unseen. That turns "find the deliveries" into "place three
    known deliveries", which is a far easier target for a weaker detector.
    """
    samples = (_run(0, 4, runs=50, balls=30)
               + [_s(12), _s(15), _s(18), _s(21)]
               + _run(24, 4, runs=62, balls=33))
    tl = sb.build_timeline(samples, step=3.0)
    assert len(tl.gaps) == 1
    assert tl.gaps[0].missed_balls == 3


def test_a_single_bad_frame_is_not_an_occlusion():
    samples = _run(0, 4) + [_s(12)] + _run(15, 4)
    assert sb.build_timeline(samples, step=3.0).gaps == []


def test_an_unbounded_gap_admits_it_cannot_count():
    """Nothing readable after the gap means the count is unknown, not zero."""
    samples = _run(0, 4) + [_s(12), _s(15), _s(18), _s(21)]
    tl = sb.build_timeline(samples, step=3.0)
    assert len(tl.gaps) == 1 and tl.gaps[0].missed_balls is None


# --- staleness: the failure that is otherwise silent -------------------------

def test_a_frozen_counter_is_reported():
    """
    The dangerous case. The graphic renders perfectly and the counter never
    moves, so there is no missing data and no error -- only a match that
    appears not to have happened.
    """
    samples = _run(0, 200, step=3.0, runs=50, balls=30)   # 600s, never advances
    tl = sb.build_timeline(samples, step=3.0)
    assert tl.stale, "a counter frozen for 600s must be reported"
    assert not tl.trustworthy


def test_normal_play_is_not_called_stale():
    """Real gaps between deliveries run 32-46s; that must not trip the guard."""
    samples = []
    for ball in range(20):
        samples += _run(ball * 45.0, 15, step=3.0, runs=50 + ball * 4, balls=30 + ball)
    tl = sb.build_timeline(samples, step=3.0)
    assert tl.stale == []
    assert tl.trustworthy


def test_trustworthy_requires_both_a_live_counter_and_a_readable_board():
    live = sb.Timeline(rows=[_s(0, 1, 0, 1)], parse_rate=0.9)
    assert live.trustworthy
    assert not sb.Timeline(rows=[_s(0, 1, 0, 1)], parse_rate=0.2).trustworthy
    assert not sb.Timeline(rows=[_s(0, 1, 0, 1)], parse_rate=0.9,
                           stale=[(0.0, 600.0)]).trustworthy


# --- cleaning rules, each one a bug that shipped -----------------------------

def test_the_scoreboard_never_runs_backwards_mid_innings():
    rows = sb.build_timeline(
        [_s(0, 116, 0, 100), _s(3, 16, 0, 101), _s(6, 118, 0, 102)], step=3.0
    ).rows
    assert [r["runs"] for r in rows] == [116, 118]


def test_an_innings_reset_survives_instead_of_ending_the_scan():
    """
    Reading a legitimate reset as "backwards" stranded the baseline at the first
    innings' closing score, so every later sample was discarded too -- 110
    deliveries, all from innings one, and no error anywhere.
    """
    samples = [_s(0, 150, 0, 118), _s(3, 155, 0, 120)] + [
        _s(6 + i * 3, i, 0, i) for i in range(8)
    ]
    rows = sb.build_timeline(samples, step=3.0).rows
    assert {r["innings"] for r in rows} == {0, 1}


def test_a_one_frame_low_reading_does_not_start_an_innings():
    """A misread lasts one sample; a real break lasts minutes."""
    samples = [_s(0, 90, 0, 70), _s(3, 2, 0, 2)] + _run(6, 6, runs=92, balls=71)
    rows = sb.build_timeline(samples, step=3.0).rows
    assert {r["innings"] for r in rows} == {0}
