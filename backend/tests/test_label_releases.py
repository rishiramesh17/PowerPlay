"""
Tests for the release-labelling helper.

The output of this tool becomes the measured value of SCOREBOARD_LAG_SEC, which
shifts every reported delivery time in the pipeline. A sampling or arithmetic
mistake here does not fail loudly -- it produces a confident, precise, wrong
constant, which is the failure mode this project keeps rediscovering.
"""

import pytest

from tools.label_releases import analyse, outcome_of, stratify, LEAD_SEC


class TestOutcome:
    @pytest.mark.parametrize("delta,expected", [
        (0, "dot"), (1, "single"), (2, "two"), (4, "four"), (6, "six"),
    ])
    def test_runs_map_to_outcomes(self, delta, expected):
        assert outcome_of(delta, wicket=False) == expected

    def test_a_wicket_outranks_the_runs(self):
        """
        A wicket off which a run was taken is still a wicket.

        It is the camera's behaviour that drives the lag being measured, and the
        camera follows the dismissal.
        """
        assert outcome_of(1, wicket=True) == "wicket"
        assert outcome_of(0, wicket=True) == "wicket"

    def test_unusual_run_counts_are_labelled_not_discarded(self):
        assert outcome_of(5, wicket=False) == "+5"


class TestStratify:
    @staticmethod
    def _deliveries(spec):
        out, t = [], 0.0
        for outcome, count in spec.items():
            for _ in range(count):
                t += 40.0
                out.append({"ball": len(out) + 1, "tick_t": t,
                            "runs_delta": 0, "outcome": outcome})
        return out

    def test_rare_outcomes_are_not_crowded_out(self):
        """
        The whole hypothesis is that boundaries lag more than dots, so a sample
        of thirty singles and no sixes would be worthless however large it is.
        """
        picked = stratify(self._deliveries({"single": 40, "six": 2, "wicket": 1}), 3)
        assert {p["outcome"] for p in picked} == {"single", "six", "wicket"}

    def test_it_caps_each_bucket(self):
        picked = stratify(self._deliveries({"single": 40, "four": 40}), 3)
        assert sum(p["outcome"] == "single" for p in picked) == 3
        assert sum(p["outcome"] == "four" for p in picked) == 3

    def test_a_bucket_smaller_than_the_cap_is_taken_whole(self):
        assert len(stratify(self._deliveries({"six": 2}), 5)) == 2

    def test_output_is_ordered_by_time(self):
        picked = stratify(self._deliveries({"single": 6, "four": 6}), 3)
        assert [p["tick_t"] for p in picked] == sorted(p["tick_t"] for p in picked)

    def test_within_a_bucket_the_sample_is_spread_not_clustered(self):
        """Ten consecutive singles from one over would measure one camera moment."""
        picked = stratify(self._deliveries({"single": 30}), 3)
        times = sorted(p["tick_t"] for p in picked)
        assert max(times) - min(times) > 300.0


class TestAnalyse:
    @staticmethod
    def _labels(rows):
        return [{"outcome": o, "tick_t": tick, "release_t": rel,
                 "dark_since": None}
                for o, tick, rel in rows]

    def test_lag_is_tick_minus_release(self):
        r = analyse(self._labels([("dot", 100.0, 96.0)]))
        assert r["overall"]["mean"] == pytest.approx(4.0)

    def test_unfilled_labels_are_ignored_not_counted_as_zero(self):
        """
        A null means "I could not judge this one". Treating it as a zero lag
        would drag the constant toward zero while looking like more evidence.
        """
        rows = self._labels([("dot", 100.0, 96.0), ("six", 200.0, 190.0)])
        rows.append({"outcome": "four", "tick_t": 300.0, "release_t": None})
        assert analyse(rows)["n"] == 2

    def test_no_labels_at_all_is_an_error_not_a_result(self):
        assert "error" in analyse([{"outcome": "dot", "tick_t": 1.0, "release_t": None}])

    def test_it_reports_lag_per_outcome(self):
        r = analyse(self._labels([
            ("dot", 100.0, 97.0), ("dot", 200.0, 197.0),
            ("six", 300.0, 289.0), ("six", 400.0, 389.0),
        ]))
        assert r["by_outcome"]["dot"]["mean"] == pytest.approx(3.0)
        assert r["by_outcome"]["six"]["mean"] == pytest.approx(11.0)

    def test_cleanly_separated_groups_are_called_significant(self):
        """Dots tightly at ~3s and sixes tightly at ~11s, with enough of each."""
        rows = []
        for i in range(6):
            rows.append(("dot", 100.0 + i * 50, 100.0 + i * 50 - 3.0 - i * 0.1))
            rows.append(("six", 500.0 + i * 50, 500.0 + i * 50 - 11.0 - i * 0.1))
        dep = analyse(self._labels(rows))["outcome_dependence"]
        assert dep["significant"], dep["p_value"]

    def test_overlapping_groups_are_not_called_significant(self):
        """The guard that matters: noise must not be reported as structure."""
        rows = []
        for i, lag in enumerate([3.0, 9.0, 4.0, 11.0, 5.0, 10.0]):
            rows.append(("dot" if i % 2 else "six", 100.0 + i * 60,
                         100.0 + i * 60 - lag))
        dep = analyse(self._labels(rows))["outcome_dependence"]
        assert not dep["significant"], dep["p_value"]

    def test_a_split_into_singleton_buckets_is_not_significant(self):
        """
        Why the variance heuristic this replaced was wrong, pinned as a test.

        Six deliveries in six buckets explains 100% of the variance by
        construction. The earlier implementation reported that as structure and
        twice concluded outcome predicts lag; shuffling the labels does exactly
        as well, so the permutation test does not.
        """
        rows = [(f"out{i}", 100.0 + i * 60, 100.0 + i * 60 - lag)
                for i, lag in enumerate([3.0, 20.0, 7.0, 15.0, 5.0, 11.0])]
        dep = analyse(self._labels(rows))["outcome_dependence"]
        assert not dep["significant"], dep["p_value"]

    def test_occlusion_is_tested_alongside_outcome(self):
        """Occlusion turned out to be the real driver (p=0.005 vs p=0.19), and it
        was found only because the tool was made to ask about both."""
        rows = [{"outcome": "dot", "tick_t": 100.0 + i * 60,
                 "release_t": 100.0 + i * 60 - lag,
                 "dark_since": None if i % 2 else 10.0}
                for i, lag in enumerate([10.0, 21.0, 10.5, 22.0, 9.5, 20.5])]
        assert "occlusion_dependence" in analyse(rows)


def test_clips_start_well_before_the_largest_plausible_lag():
    """
    If the clip begins after the release, the label cannot be given at all -- and
    the delivery silently drops out of the sample. Measured lags reach 10.9s.
    """
    assert LEAD_SEC > 2 * 10.9


class TestPage:
    """
    The labelling page is where the measurement is actually taken, so the ways
    it can fail silently matter more than the ways it can look wrong.
    """

    @staticmethod
    def _rows():
        return [{"clip": "01_ball9_single.mp4", "ball": 9, "outcome": "single",
                 "runs_delta": 1, "tick_t": 90.0, "clip_start": 68.0,
                 "dark_since": None, "release_t": None}]

    def test_the_clip_list_is_inlined_not_fetched(self, tmp_path):
        """
        A page opened over file:// cannot read a sibling JSON file. Fetching
        would leave the labeller staring at an empty page with no error.
        """
        from tools.label_releases import write_page
        html = write_page(self._rows(), tmp_path).read_text()
        assert "01_ball9_single.mp4" in html
        assert "fetch(" not in html

    def test_no_placeholder_survives_substitution(self, tmp_path):
        from tools.label_releases import write_page
        html = write_page(self._rows(), tmp_path).read_text()
        assert "__ROWS__" not in html and "__LEAD__" not in html

    def test_the_page_takes_clip_start_from_the_cutter(self, tmp_path):
        """
        Release time is reconstructed as clip_start + playhead. Clip starts are
        no longer a fixed lead before the tick -- a replay can hide the board for
        over a minute -- so a page that re-derived them would offset every label
        on exactly the occluded deliveries the clips were re-cut to capture.
        """
        from tools.label_releases import write_page
        html = write_page(self._rows(), tmp_path).read_text()
        assert "const clipStart = r => r.clip_start;" in html
        assert "tick_t - LEAD" not in html

    def test_it_is_self_contained(self, tmp_path):
        """No network: the machine labelling may be offline, and a missing
        stylesheet would silently degrade the frame-stepping controls."""
        from tools.label_releases import write_page
        html = write_page(self._rows(), tmp_path).read_text()
        assert "http://" not in html and "https://" not in html


class TestDarkSince:
    """
    Finding when the board went dark is what decides where a clip begins, and
    getting it wrong is how five of the first fifteen clips opened after the ball
    had already been hit.
    """

    class _Gap:
        def __init__(self, start, end):
            self.start, self.end = start, end

        @property
        def duration(self):
            return self.end - self.start

    def test_no_occlusion_before_the_tick_reports_none(self):
        from tools.label_releases import dark_since
        assert dark_since(500.0, [self._Gap(100.0, 200.0)], 3.0) is None

    def test_a_single_gap_ending_at_the_tick_is_found(self):
        from tools.label_releases import dark_since
        assert dark_since(162.0, [self._Gap(144.0, 162.0)], 3.0) == 144.0

    def test_touching_gaps_are_chained_back_to_the_true_start(self):
        """
        The measured failure: one readable frame between occlusions splits an
        81-second blackout into three gaps. Taking only the last one placed the
        start at 498s instead of 435s, and the clip opened with the ball already
        halfway to the boundary.
        """
        from tools.label_releases import dark_since
        gaps = [self._Gap(435.0, 486.0), self._Gap(486.0, 498.0),
                self._Gap(498.0, 516.0)]
        assert dark_since(516.0, gaps, 3.0) == 435.0

    def test_an_unrelated_earlier_blackout_is_not_chained_in(self):
        """Chaining must stop at a genuine readable span, or every clip would
        begin at the start of the match."""
        from tools.label_releases import dark_since
        gaps = [self._Gap(100.0, 200.0), self._Gap(480.0, 516.0)]
        assert dark_since(516.0, gaps, 3.0) == 480.0


class TestClipWindows:
    @staticmethod
    def _gt(rows):
        return {"samples": rows}

    def test_a_clip_starts_before_the_board_went_dark(self):
        """
        The bug this was built to fix: the release precedes the cut to replay,
        which precedes the blackout, which precedes the tick. A clip led from the
        tick misses it entirely on exactly the boundaries worth clipping.
        """
        from tools.label_releases import deliveries_from, PRE_DARK_SEC
        samples = []
        for t in range(0, 600, 3):
            readable = not (435 <= t < 516)
            samples.append({"t": float(t), "runs": 40 if t < 435 else 44,
                            "wickets": 0, "balls": 10 if t < 435 else 11,
                            "layout": "cricclubs" if readable else None,
                            "raw": ""} if readable else
                           {"t": float(t), "runs": None, "wickets": None,
                            "balls": None, "layout": None, "raw": ""})
        found = deliveries_from(self._gt(samples), 3.0)
        assert found, "expected a delivery across the blackout"
        d = found[-1]
        assert d["dark_since"] is not None
        assert d["clip_start"] <= d["dark_since"] - PRE_DARK_SEC + 0.01

    def test_a_clip_never_reaches_back_past_the_previous_delivery(self):
        """
        A long blackout spanning two deliveries would otherwise produce a clip
        containing both, which cannot be labelled unambiguously.
        """
        from tools.label_releases import deliveries_from
        found = deliveries_from(self._gt([
            {"t": float(t), "runs": min(t // 60, 5), "wickets": 0,
             "balls": int(min(t // 60, 5)), "layout": "cricclubs", "raw": ""}
            for t in range(0, 420, 3)
        ]), 3.0)
        for earlier, later in zip(found, found[1:]):
            assert later["clip_start"] >= earlier["tick_t"]


class TestAutosave:
    """
    Twenty minutes of frame-stepping was lost to a page reload. Autosave is the
    fix, but it introduces a worse failure if done naively: stale browser state
    silently overwriting a correction made deliberately on disk.
    """

    @staticmethod
    def _rows(release=None):
        return [{"clip": "01_ball9_single.mp4", "ball": 9, "outcome": "single",
                 "runs_delta": 1, "tick_t": 90.0, "clip_start": 68.0,
                 "dark_since": None, "release_t": release}]

    def _key(self, tmp_path, rows):
        import re
        from tools.label_releases import write_page
        html = write_page(rows, tmp_path).read_text()
        m = re.search(r"const KEY = '(powerplay-labels-[0-9a-f]+)'", html)
        assert m, "page has no autosave key"
        return m.group(1)

    def test_the_key_is_stable_for_identical_input(self, tmp_path):
        assert self._key(tmp_path, self._rows()) == self._key(tmp_path, self._rows())

    def test_clearing_a_label_on_disk_invalidates_the_browser_copy(self, tmp_path):
        """
        The exact hazard: a label was cleared because it was measured to be
        unusable. If autosave restored it, the bad value would come back silently
        and no one would be looking for it.
        """
        assert self._key(tmp_path, self._rows(release=81.2)) != \
               self._key(tmp_path, self._rows(release=None))

    def test_recutting_clips_invalidates_the_browser_copy(self, tmp_path):
        """Labels are absolute video times, but a different clip window means the
        labeller was shown different footage."""
        moved = self._rows()
        moved[0]["clip_start"] = 40.0
        assert self._key(tmp_path, self._rows()) != self._key(tmp_path, moved)

    def test_every_mark_is_saved_not_just_the_last(self, tmp_path):
        from tools.label_releases import write_page
        html = write_page(self._rows(), tmp_path).read_text()
        assert html.count("save();") >= 3        # mark, skip button, skip key

    def test_leaving_with_unsaved_work_warns(self, tmp_path):
        from tools.label_releases import write_page
        html = write_page(self._rows(), tmp_path).read_text()
        assert "beforeunload" in html

    def test_a_restore_is_reported_rather_than_silent(self, tmp_path):
        """The labeller must be able to tell whether they are looking at their
        own earlier work or at a fresh start."""
        from tools.label_releases import write_page
        html = write_page(self._rows(), tmp_path).read_text()
        assert "restored" in html and "$('status')" in html
