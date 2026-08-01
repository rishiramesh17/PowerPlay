import unittest
from pathlib import Path

import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from processing.utils import clamp_segments, limit_total_duration, merge_times_to_segments, parse_timecode


class ProcessingUtilsTests(unittest.TestCase):
    def test_merge_times_to_segments_groups_points_with_padding(self) -> None:
        times = [5.0, 5.4, 8.0, 8.6]

        merged = merge_times_to_segments(times, gap=1.0, pre=0.5, post=0.25)

        self.assertEqual(merged, [(4.5, 5.65), (7.5, 8.85)])

    def test_parse_timecode_supports_hour_minute_second_formats(self) -> None:
        self.assertEqual(parse_timecode("01:02:03"), 3723.0)
        self.assertEqual(parse_timecode("12:34"), 754.0)
        self.assertEqual(parse_timecode("45"), 45.0)
        self.assertEqual(parse_timecode(""), 0.0)

    def test_clamp_segments_respects_media_duration_and_drops_invalid_ranges(self) -> None:
        segments = [(-2.0, 5.0), (8.0, 15.0), (-1.0, -0.2)]

        clamped = clamp_segments(segments, duration=10.0)

        self.assertEqual(clamped, [(0.0, 5.0), (8.0, 10.0)])

    def test_limit_total_duration_keeps_order_and_truncates_final_segment(self) -> None:
        segments = [(0.0, 4.0), (10.0, 15.0), (20.0, 25.0)]

        limited = limit_total_duration(segments, max_total=8.0)

        self.assertEqual(limited, [(0.0, 4.0), (10.0, 14.0)])

    def test_limit_total_duration_returns_empty_for_non_positive_budget(self) -> None:
        self.assertEqual(limit_total_duration([(0.0, 5.0)], max_total=0.0), [])


if __name__ == "__main__":
    unittest.main()
