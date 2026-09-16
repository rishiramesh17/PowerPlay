"""
Tests for delivery segmentation (Stage 1 of the event-first pipeline).

Only the pure logic is covered here -- linking, clustering and the dataclass
contract. The parts that need a decoder and a YOLO model are exercised against
real footage instead, because a synthetic video cannot reproduce the thing they
actually have to survive: broadcast framing that drifts with zoom.

The behaviours pinned below are the ones that were measured wrong first time:
  1. a fast mover has to be detectable *relative* to the crowd, not by an
     absolute speed, because the measured run-up peak was 1.04 body-lengths/sec
     against an assumed floor of 1.2 -- the real delivery scored as nothing;
  2. shot membership has to be by distance, not k-means label, because a six
     landed 3.23 from the dominant centroid while accepted shots sat at 3.57.
"""

import numpy as np
import pytest

from processing import delivery_detect as dd


def _walk(n, start_x, dx, y=0.5, h=0.3):
    """A track moving at a constant dx per frame."""
    return [(start_x + dx * i, y, h) for i in range(n)]


def test_region_duration_is_the_span():
    assert dd.Region(10.0, 25.5).duration == pytest.approx(15.5)


def test_delivery_reports_localization_from_its_estimate():
    located = dd.Delivery(dd.Region(0.0, 10.0), dd.ReleaseEstimate(4.2, 1.0, 5.0, 0.0))
    missed = dd.Delivery(dd.Region(0.0, 10.0), dd.ReleaseEstimate(None, 0.3, 1.1, 0.0))
    assert located.localized and located.release_t == pytest.approx(4.2)
    assert not missed.localized and missed.release_t is None


def test_a_stationary_crowd_links_into_one_track_each():
    """Five people standing still must not generate spurious extra tracks."""
    people = [(0.1 * i, 0.5, 0.3) for i in range(5)]
    tracks = dd._link_tracks([people] * 6)
    assert len(tracks) == 5
    assert all(len([p for p in t if p is not None]) == 6 for t in tracks)


def test_a_mover_stays_one_track_while_it_moves():
    """
    The run-up measurement is per-track, so a bowler who gets split into two
    tracks at the moment he accelerates is exactly the failure that hides him.
    """
    mover = _walk(6, 0.10, 0.04)
    frames = [[mover[i], (0.8, 0.5, 0.3)] for i in range(6)]
    tracks = dd._link_tracks(frames)
    assert len(tracks) == 2
    moving = max(tracks, key=lambda t: abs(t[-1][0] - t[0][0]))
    assert len([p for p in moving if p is not None]) == 6


def test_a_jump_larger_than_max_jump_breaks_the_track():
    """Linking must not teleport an identity across the frame between frames."""
    frames = [[(0.1, 0.5, 0.3)], [(0.9, 0.5, 0.3)]]
    tracks = dd._link_tracks(frames, max_jump=0.08)
    assert len(tracks) == 2


def test_kmeans_separates_well_isolated_groups():
    pts = np.array([[0.0, 0.0], [0.1, 0.1], [0.0, 0.1], [9.0, 9.0], [9.1, 9.0]])
    labels = dd._kmeans(pts, k=2)
    assert labels[0] == labels[1] == labels[2]
    assert labels[3] == labels[4]
    assert labels[0] != labels[3]


def test_kmeans_is_deterministic():
    """Region proposals must not change between runs on the same footage."""
    pts = np.random.default_rng(0).normal(size=(40, 6))
    assert np.array_equal(dd._kmeans(pts, k=4), dd._kmeans(pts, k=4))


def test_region_tolerance_admits_more_than_the_bare_cluster():
    """
    Guards the boundary-losing bug: the radius must extend past the dominant
    cluster's own extent, or shots nearer the centroid than accepted members
    get dropped on a labelling technicality.
    """
    assert dd.REGION_RADIUS_TOLERANCE > 1.0


def test_prominence_is_relative_not_absolute():
    """
    A measured run-up peaked at 1.04 body-lengths/sec. Any absolute floor at or
    above that silently discards real deliveries, so the decision has to rest on
    the ratio and the absolute floor must stay well below what was observed.
    """
    assert dd.RUNUP_SPEED_FLOOR < 1.04
    assert dd.RUNUP_PROMINENCE > 1.0


def test_pitch_crew_ratio_leaves_room_for_a_missed_detection():
    """
    Headcount marks whether the camera is on the pitch. It must tolerate the
    detector dropping one person of five, while still catching the collapse to
    zero that a ball tracked to the rope produces.
    """
    assert 0.0 < dd.PITCH_CREW_RATIO < 1.0
    crew = 5
    assert 4 >= crew * dd.PITCH_CREW_RATIO  # one missed detection is still "on pitch"
    assert 0 < crew * dd.PITCH_CREW_RATIO   # an empty frame is not


# --- ground-truth builder --------------------------------------------------
# The scoreboard scanner is the only source of benchmark labels, so a silent
# gap in it corrupts every measurement taken afterwards.

from tools import build_ground_truth as gt  # noqa: E402


def _row(t, runs, balls, wickets=0):
    return {"t": t, "runs": runs, "balls": balls, "wickets": wickets}


def test_a_normal_over_is_kept_intact():
    rows = gt.clean([_row(0, 10, 6), _row(3, 14, 7), _row(6, 15, 8)])
    assert len(rows) == 3
    assert {r["innings"] for r in rows} == {0}


def test_the_scoreboard_never_runs_backwards_mid_innings():
    """A transposed digit moves one field only, and must be discarded."""
    rows = gt.clean([_row(0, 116, 100), _row(3, 16, 101), _row(6, 118, 102)])
    assert [r["runs"] for r in rows] == [116, 118]


def test_an_innings_reset_starts_a_new_innings_instead_of_ending_the_scan():
    """
    The bug this pins: both counters legitimately drop to zero between innings.
    Reading that as "backwards" stranded the baseline at the first innings'
    closing score, so every later sample was discarded too and the entire second
    innings vanished -- 110 deliveries, all from innings one, and no error.
    """
    rows = gt.clean(
        [_row(0, 150, 118), _row(3, 155, 120), _row(6, 0, 0), _row(9, 4, 1)]
    )
    assert len(rows) == 4, "the second innings must survive cleaning"
    assert [r["innings"] for r in rows] == [0, 0, 1, 1]


def test_scoring_events_are_not_derived_across_the_innings_break():
    """The new side starting from 0 is not the old side losing 155 runs."""
    rows = gt.clean(
        [_row(0, 150, 118), _row(3, 155, 120), _row(6, 0, 0), _row(9, 4, 1)]
    )
    deliveries, events = gt.derive(rows)
    assert all(e["delta"] <= gt.MAX_RUNS_PER_BALL for e in events)
    assert {d["innings"] for d in deliveries} == {0, 1}


def test_a_garbled_reading_is_not_mistaken_for_an_innings_reset():
    """A reset needs BOTH counters to fall and land near zero."""
    assert not gt._is_innings_reset(_row(0, 90, 70), _row(3, 95, 2))   # runs rose
    assert not gt._is_innings_reset(_row(0, 90, 70), _row(3, 80, 64))  # not near 0
    assert gt._is_innings_reset(_row(0, 90, 70), _row(3, 0, 0))


def test_boundaries_are_typed_from_the_run_delta():
    rows = gt.clean([_row(0, 10, 6), _row(3, 14, 7), _row(6, 20, 8), _row(9, 21, 9)])
    _, events = gt.derive(rows)
    assert [e["type"] for e in events] == ["FOUR", "SIX", "+1"]


def test_a_wicket_is_emitted_even_with_no_runs():
    rows = gt.clean([_row(0, 40, 30, wickets=2), _row(3, 40, 31, wickets=3)])
    _, events = gt.derive(rows)
    assert [e["type"] for e in events] == ["WICKET"]


# --- which end is the bowler running from ----------------------------------
# The striker stands opposite the bowler and faces him, so the bowling end
# decides whether his number is pointed at the camera. Getting this backwards
# would attribute every shot to the wrong batsman.


def _track(heights):
    """A track at fixed screen position whose apparent size follows `heights`."""
    return [(0.5, 0.5, h) for h in heights]


def test_a_bowler_growing_in_frame_ran_toward_the_camera():
    trend, end = dd._bowling_end(_track([0.10] * 3 + [0.20] * 3), peak_idx=5, window=3)
    assert end == "far"
    assert trend > 0


def test_a_bowler_shrinking_in_frame_ran_away_from_the_camera():
    trend, end = dd._bowling_end(_track([0.20] * 3 + [0.10] * 3), peak_idx=5, window=3)
    assert end == "near"
    assert trend < 0


def test_a_square_on_camera_reports_unknown_rather_than_guessing():
    """
    Match 1 is a wide square-on camera: the bowler runs across the view, not
    along it, so his size barely changes. A coin flip here is worse than an
    admission of ignorance, because downstream code would trust it.
    """
    trend, end = dd._bowling_end(_track([0.15, 0.152, 0.148, 0.151, 0.149, 0.15]),
                                 peak_idx=5, window=3)
    assert end is None
    assert abs(trend) < dd.END_HEIGHT_TREND


def test_too_few_observations_is_unknown_not_zero_confidence():
    assert dd._bowling_end(_track([0.2, 0.1]), peak_idx=1, window=3) == (0.0, None)


def test_a_gappy_track_still_reads_the_trend():
    """Detection drops frames; the trend must survive holes in the track."""
    track = [(0.5, 0.5, 0.10), None, (0.5, 0.5, 0.11), None,
             (0.5, 0.5, 0.19), (0.5, 0.5, 0.21)]
    _, end = dd._bowling_end(track, peak_idx=5, window=3)
    assert end == "far"


def test_striker_faces_camera_is_the_opposite_of_the_bowling_end():
    """
    Bowling from the near end puts the striker at the far end facing the camera,
    so his number is hidden. Bowling from the far end turns his back to it.
    """
    near = dd.ReleaseEstimate(1.0, 1.0, 5.0, 0.0, bowling_end="near")
    far = dd.ReleaseEstimate(1.0, 1.0, 5.0, 0.0, bowling_end="far")
    assert near.striker_faces_camera is True    # number hidden
    assert far.striker_faces_camera is False    # number readable


def test_striker_orientation_is_unknown_when_the_end_is_unknown():
    """Never assert an orientation the camera geometry cannot support."""
    est = dd.ReleaseEstimate(1.0, 1.0, 5.0, 0.0, bowling_end=None)
    assert est.striker_faces_camera is None
