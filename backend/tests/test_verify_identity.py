import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from processing.verify_identity import select_review_candidates


class FakeSeed:
    """Stands in for detect_player.Seed without importing the torch stack."""

    def __init__(self, time_s, score=0.5, scene_id=0, bbox=(10, 10, 60, 160)):
        self.time_s = time_s
        self.score = score
        self.scene_id = scene_id
        self.bbox = bbox
        self.identity_strength = score * 0.9
        self.ocr_match = False


class SelectReviewCandidatesTests(unittest.TestCase):
    def test_candidates_are_spread_across_the_whole_video(self) -> None:
        # Picking the top-scoring seeds would cluster on one confident moment and
        # hide exactly the drift the user is being asked to catch.
        seeds = [FakeSeed(float(t), score=0.9 if t < 10 else 0.2) for t in range(100)]

        picked = select_review_candidates(seeds, duration=100.0, max_candidates=5)

        times = [p.time_s for p in picked]
        self.assertEqual(len(picked), 5)
        self.assertLess(max(times), 100.0)
        # Every 20s bucket contributes one, so the last pick is late in the video
        # despite every high score sitting in the first 10 seconds.
        self.assertGreater(times[-1], 50.0)
        self.assertEqual(times, sorted(times))

    def test_scenes_already_shown_are_deprioritised(self) -> None:
        # Scene 0 has the best score in every bucket, but showing six crops from
        # one camera angle would hide a wrong match in the other angles.
        seeds = []
        for t in range(60):
            seeds.append(FakeSeed(float(t), score=0.95, scene_id=0))
            seeds.append(FakeSeed(float(t) + 0.5, score=0.10, scene_id=(t % 4) + 1))

        picked = select_review_candidates(seeds, duration=60.0, max_candidates=5)

        self.assertGreater(len({p.scene_id for p in picked}), 1)

    def test_returns_everything_available_when_seeds_are_scarce(self) -> None:
        seeds = [FakeSeed(1.0), FakeSeed(2.0)]

        picked = select_review_candidates(seeds, duration=100.0, max_candidates=6)

        self.assertEqual([p.time_s for p in picked], [1.0, 2.0])

    def test_seeds_without_a_bbox_are_ignored(self) -> None:
        # A crop cannot be made without a box, so such a seed would become a
        # broken image in the review grid.
        usable = FakeSeed(1.0)
        unusable = FakeSeed(2.0)
        unusable.bbox = None

        picked = select_review_candidates([usable, unusable], duration=10.0, max_candidates=6)

        self.assertEqual(picked, [usable])

    def test_degenerate_inputs_return_nothing(self) -> None:
        self.assertEqual(select_review_candidates([], duration=10.0), [])
        self.assertEqual(select_review_candidates([FakeSeed(1.0)], 10.0, max_candidates=0), [])

    def test_unknown_duration_still_produces_candidates(self) -> None:
        # duration can arrive as 0.0 when ffprobe fails; bucketing must not
        # divide by zero.
        seeds = [FakeSeed(float(t)) for t in range(10)]

        picked = select_review_candidates(seeds, duration=0.0, max_candidates=3)

        self.assertEqual(len(picked), 3)


class SeedSerializationTests(unittest.TestCase):
    """Resuming a reviewed job depends on seeds surviving a JSON round trip."""

    def setUp(self) -> None:
        try:
            from processing.detect_player import seed_from_record, seed_to_record, Seed
        except Exception as exc:  # torch/ultralytics/easyocr not installed
            self.skipTest(f"detect_player unavailable: {exc}")
        self.seed_to_record = seed_to_record
        self.seed_from_record = seed_from_record
        self.Seed = Seed

    def test_round_trip_preserves_every_field_selection_reads(self) -> None:
        import json

        original = self.Seed(
            time_s=12.5,
            bbox=(100, 40, 180, 300),
            hist=None,
            label="7",
            score=0.71,
            ocr_match=True,
            bank_sim=0.44,
            hist_sim=0.52,
            center_bias=0.13,
            temporal_iou=0.61,
            scene_id=3,
            identity_strength=0.62,
            replay_suspect=True,
            post_cut_reacquire=True,
        )

        # Must survive the actual persistence format, not just the dict.
        restored = self.seed_from_record(json.loads(json.dumps(self.seed_to_record(original))))

        for field in (
            "time_s", "score", "ocr_match", "bank_sim", "hist_sim", "center_bias",
            "temporal_iou", "scene_id", "identity_strength", "replay_suspect",
            "post_cut_reacquire", "label",
        ):
            self.assertEqual(getattr(restored, field), getattr(original, field), field)
        self.assertEqual(restored.bbox, original.bbox)

    def test_missing_fields_fall_back_to_defaults(self) -> None:
        restored = self.seed_from_record({"time_s": 4.0})

        self.assertEqual(restored.time_s, 4.0)
        self.assertEqual(restored.bbox, (0, 0, 0, 0))
        self.assertEqual(restored.score, 0.0)
        self.assertFalse(restored.replay_suspect)


if __name__ == "__main__":
    unittest.main()
