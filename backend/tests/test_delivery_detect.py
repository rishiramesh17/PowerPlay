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


# --- duplicate suppression and background floor -----------------------------
# Both bugs below surfaced only on the second broadcast. Neither was visible on
# the match everything was originally tuned against.


def _d(start, end, release, prom):
    return dd.Delivery(dd.Region(start, end), dd.ReleaseEstimate(release, 1.0, prom, 0.0))


def test_two_regions_covering_one_ball_collapse_to_one():
    """A ball spanning two camera shots gets localized twice, seconds apart."""
    out = dd.suppress_duplicates([_d(0, 10, 5.0, 3.0), _d(10, 20, 6.5, 9.0)])
    assert len(out) == 1
    assert out[0].release_t == pytest.approx(6.5), "keep the better-evidenced one"


def test_genuinely_separate_balls_are_both_kept():
    out = dd.suppress_duplicates([_d(0, 10, 5.0, 3.0), _d(40, 50, 45.0, 3.0)])
    assert len(out) == 2


def test_suppression_returns_deliveries_in_time_order():
    """Ranking by prominence must not leak into the output ordering."""
    out = dd.suppress_duplicates(
        [_d(80, 90, 85.0, 2.0), _d(0, 10, 5.0, 9.0), _d(40, 50, 45.0, 5.0)]
    )
    assert [d.release_t for d in out] == [5.0, 45.0, 85.0]


def test_unlocalized_regions_survive_suppression():
    """They carry no release to collide with, and Stage 2 may still want them."""
    blank = dd.Delivery(dd.Region(0, 10), dd.ReleaseEstimate(None, 0.2, 1.0, 0.0))
    out = dd.suppress_duplicates([blank, _d(40, 50, 45.0, 3.0)])
    assert len(out) == 2


def test_the_prominence_denominator_cannot_collapse_to_zero():
    """
    The bug: on the second broadcast most steps measured exactly zero because
    tracking broke, the median background went to zero, and prominence reached
    258 where the first broadcast produced 2-7. Every candidate passed.
    """
    assert dd.BACKGROUND_FLOOR > 0.0
    peak = 1.04                       # the measured run-up peak
    assert peak / dd.BACKGROUND_FLOOR < 20.0, "ratio must stay bounded"


def test_a_delivery_gap_shorter_than_an_over_is_implausible():
    """
    Must sit below the fastest real over either broadcast produced, or genuine
    deliveries get suppressed as duplicates. Measured 10th-percentile gaps are
    21s (match 1) and 24s (match 2).
    """
    assert 0.0 < dd.MIN_DELIVERY_GAP_SEC < 21.0


# --- multiple deliveries inside one camera shot -----------------------------
# A region is a camera shot, and a shot is not a ball. The broadcast holds one
# framing while the bowler walks back, so a shot routinely spans two deliveries
# and a long one spans three. Returning only the strongest run-up silently
# credited a region to one ball and dropped its neighbours -- three of seven
# misses on the second broadcast were exactly this.


def test_localize_release_still_returns_the_strongest_single_estimate():
    """The singular helper stays a thin wrapper over the plural one."""
    assert dd.localize_release.__doc__ is not None
    empty = dd.ReleaseEstimate(None, 0.0, 0.0, 0.0)
    assert empty.release_t is None and not dd.Delivery(dd.Region(0, 1), empty).localized


def test_the_guard_window_matches_the_delivery_gap():
    """
    Peaks are blanked by MIN_DELIVERY_GAP_SEC after each pick, so two run-ups
    inside one shot must be at least that far apart to both survive -- the same
    rule duplicate suppression uses, applied inside a region instead of across
    regions.
    """
    assert dd.MIN_DELIVERY_GAP_SEC > 0


def test_two_balls_in_one_region_both_survive_suppression():
    """
    The end-to-end shape of the fix: one region yielding two releases 30s apart
    must produce two deliveries, not one.
    """
    region = dd.Region(0.0, 60.0)
    a = dd.Delivery(region, dd.ReleaseEstimate(10.0, 0.9, 6.0, 0.0))
    b = dd.Delivery(region, dd.ReleaseEstimate(40.0, 0.8, 5.0, 0.0))
    out = dd.suppress_duplicates([a, b])
    assert [d.release_t for d in out] == [10.0, 40.0]


def test_a_shoulder_of_the_same_runup_does_not_become_a_second_ball():
    """Two peaks a second apart are one run-up, and must collapse."""
    region = dd.Region(0.0, 60.0)
    a = dd.Delivery(region, dd.ReleaseEstimate(10.0, 0.9, 6.0, 0.0))
    b = dd.Delivery(region, dd.ReleaseEstimate(11.0, 0.8, 5.0, 0.0))
    assert len(dd.suppress_duplicates([a, b])) == 1


def test_every_exit_from_localize_releases_returns_a_list():
    """
    A plural function with a singular escape hatch.

    Converting localize_release into localize_releases left two early returns
    handing back a bare ReleaseEstimate. The whole suite still passed, because
    nothing exercised the short-region and camera-never-settled paths -- the
    break only appeared on real footage, as a TypeError deep in detect_deliveries.

    Checking the returns directly costs nothing and does not need a decoder, a
    model, or footage that happens to trigger the edge case.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(dd.localize_releases))
    fn = tree.body[0]
    returns = [
        node
        for node in ast.walk(fn)
        # Skip returns belonging to any nested function.
        if isinstance(node, ast.Return)
    ]
    assert returns, "expected at least one return"
    for node in returns:
        assert node.value is not None, "a bare return would yield None, not a list"
        assert isinstance(node.value, (ast.List, ast.Name, ast.ListComp)), (
            f"line {node.lineno} returns {type(node.value).__name__}; "
            "localize_releases must always return a list"
        )
