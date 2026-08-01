import unittest
from collections import namedtuple
from pathlib import Path

import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from processing.segment_selector import (
    _segment_identity_stats,
    _segment_iou,
    _segment_overlap_ratio,
    select_best_segments,
)

Seed = namedtuple(
    "Seed",
    [
        "time_s",
        "bbox",
        "scene_id",
        "identity_strength",
        "replay_suspect",
        "post_cut_reacquire",
        "score",
        "bank_sim",
        "hist_sim",
        "center_bias",
        "temporal_iou",
        "ocr_match",
    ],
)


class SegmentSelectorTests(unittest.TestCase):
    def test_segment_iou_uses_intersection_over_union_of_time_ranges(self) -> None:
        self.assertAlmostEqual(_segment_iou((0.0, 4.0), (2.0, 6.0)), 2.0 / 6.0)
        self.assertEqual(_segment_iou((0.0, 1.0), (2.0, 3.0)), 0.0)

    def test_segment_overlap_ratio_measures_coverage_of_shorter_segment(self) -> None:
        self.assertAlmostEqual(_segment_overlap_ratio((2.0, 4.0), (1.0, 5.0)), 1.0)
        self.assertAlmostEqual(_segment_overlap_ratio((0.0, 2.0), (1.0, 5.0)), 0.5)

    def test_identity_stats_return_neutral_defaults_when_identity_signals_are_missing(self) -> None:
        seeds = [
            Seed(1.0, (0.0, 0.0, 10.0, 20.0), 1, 0.0, False, False, 0.2, 0.0, 0.0, 0.0, 0.0, False),
            Seed(2.0, (1.0, 1.0, 11.0, 21.0), 1, 0.0, False, False, 0.3, 0.0, 0.0, 0.0, 0.0, False),
        ]

        self.assertEqual(_segment_identity_stats(seeds), (0.5, 0.0, 0.0, 0.0))

    def test_select_best_segments_returns_chronological_segments_with_duration_cap(self) -> None:
        segments = [(0.0, 6.0), (8.0, 16.0), (20.0, 28.0)]
        seeds = [
            Seed(1.0, (0.0, 0.0, 20.0, 80.0), 1, 0.9, False, False, 5.0, 0.9, 0.8, 0.8, 0.8, True),
            Seed(2.5, (2.0, 2.0, 22.0, 82.0), 1, 0.92, False, False, 5.5, 0.9, 0.8, 0.8, 0.8, True),
            Seed(9.0, (5.0, 0.0, 25.0, 80.0), 2, 0.85, False, False, 4.8, 0.88, 0.78, 0.75, 0.82, True),
            Seed(11.0, (8.0, 3.0, 28.0, 83.0), 2, 0.87, False, False, 4.9, 0.87, 0.77, 0.76, 0.8, True),
            Seed(21.0, (10.0, 4.0, 30.0, 84.0), 3, 0.83, False, False, 4.6, 0.85, 0.76, 0.74, 0.79, True),
            Seed(23.0, (13.0, 5.0, 33.0, 85.0), 3, 0.84, False, False, 4.7, 0.86, 0.75, 0.73, 0.78, True),
        ]

        selected = select_best_segments(
            segments=segments,
            seeds=seeds,
            action="batting",
            duration=30.0,
            max_segments=3,
            max_total_duration=10.0,
        )

        self.assertTrue(selected)
        self.assertEqual(selected, sorted(selected, key=lambda seg: seg[0]))
        self.assertLessEqual(sum(end - start for start, end in selected), 10.0)


if __name__ == "__main__":
    unittest.main()
