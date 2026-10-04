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
        return [{"outcome": o, "tick_t": tick, "release_t": rel}
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

    def test_separated_buckets_are_reported_as_outcome_dependence(self):
        """Dots at 3s and sixes at 11s: knowing the outcome removes the spread."""
        r = analyse(self._labels([
            ("dot", 100.0, 97.0), ("dot", 200.0, 197.2),
            ("six", 300.0, 289.0), ("six", 400.0, 389.2),
        ]))
        dep = r["outcome_dependence"]
        assert dep["sd_per_outcome"] < dep["sd_one_constant"]
        assert dep["improvement"] > 0.9

    def test_overlapping_buckets_show_no_improvement(self):
        """Guards against reading noise as structure and fitting per-outcome."""
        r = analyse(self._labels([
            ("dot", 100.0, 93.0), ("dot", 200.0, 195.0),
            ("six", 300.0, 293.0), ("six", 400.0, 395.0),
        ]))
        assert r["outcome_dependence"]["improvement"] < 0.25

    def test_dependence_is_not_reported_from_single_samples(self):
        """
        One dot and one six always "separate" perfectly. Claiming structure from
        that would be fitting a rule to two points.
        """
        r = analyse(self._labels([("dot", 100.0, 97.0), ("six", 300.0, 289.0)]))
        assert "outcome_dependence" not in r


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
                 "runs_delta": 1, "tick_t": 90.0, "release_t": None}]

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

    def test_the_page_knows_the_lead_used_to_cut_the_clips(self, tmp_path):
        """
        Release time is reconstructed as clip_start + playhead, and clip_start
        is tick_t - LEAD_SEC. If the page disagreed with the cutter about LEAD,
        every label would be offset by the difference -- a constant error, which
        is the hardest kind to notice in a measurement of a constant.
        """
        from tools.label_releases import write_page, LEAD_SEC
        html = write_page(self._rows(), tmp_path).read_text()
        assert f"const LEAD = {LEAD_SEC!r}" in html

    def test_it_is_self_contained(self, tmp_path):
        """No network: the machine labelling may be offline, and a missing
        stylesheet would silently degrade the frame-stepping controls."""
        from tools.label_releases import write_page
        html = write_page(self._rows(), tmp_path).read_text()
        assert "http://" not in html and "https://" not in html
