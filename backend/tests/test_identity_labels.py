import json
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from processing.ml.identity_labels import (
    LABELS_FILENAME,
    NEGATIVE,
    POSITIVE,
    build_label_rows,
    load_labels,
    record_review_labels,
    split_by_job,
    summarize,
)

JOB_ID = "job-1"
REQUEST = {
    "player_data": {"jersey_number": "18", "jersey_color": "blue"},
    "action": "batting",
    "team_mode": False,
    "source": "upload",
    "video_path": "/private/uploads/upload_abc_match.mp4",
}


def review(decision="approved", rejected_ids=(), candidate_ids=("c0", "c1", "c2")):
    return {
        "candidates": [
            {
                "id": cid,
                "time_s": 10.0 * index,
                "bbox": [10, 20, 60, 160],
                "score": 0.5,
                "identity_strength": 0.4,
                "ocr_match": False,
                "scene_id": index,
                "url": f"/outputs/review/{JOB_ID}/{cid}.jpg",
            }
            for index, cid in enumerate(candidate_ids)
        ],
        "seed_count": 42,
        "demo_mode": False,
        "decision": decision,
        "rejected_ids": list(rejected_ids),
        "note": None,
        "decided_at": 1770000000.0,
    }


def write_crops(outputs_dir: Path, candidate_ids=("c0", "c1", "c2")) -> None:
    crop_dir = outputs_dir / "review" / JOB_ID
    crop_dir.mkdir(parents=True, exist_ok=True)
    for cid in candidate_ids:
        (crop_dir / f"{cid}.jpg").write_bytes(b"jpeg")


class LabelAssignmentTests(unittest.TestCase):
    def test_approval_marks_struck_out_crops_as_negatives(self) -> None:
        # The whole point of keeping rejected_ids on an approval: those crops are
        # the lookalikes the current heuristic drifts onto.
        rows = build_label_rows(JOB_ID, review(rejected_ids=["c1"]), REQUEST)

        labels = {row["candidate_id"]: row["label"] for row in rows}
        self.assertEqual(labels, {"c0": POSITIVE, "c1": NEGATIVE, "c2": POSITIVE})

    def test_rejection_condemns_every_crop(self) -> None:
        # "Not my player" is a verdict on the run, not on the crops the user
        # happened to click, so an unmarked crop is still a negative.
        rows = build_label_rows(JOB_ID, review(decision="rejected"), REQUEST)

        self.assertEqual({row["label"] for row in rows}, {NEGATIVE})

    def test_undecided_review_produces_nothing(self) -> None:
        # A parked job has no supervision to offer; recording it would put
        # unlabelled rows into the dataset wearing a label field.
        self.assertEqual(build_label_rows(JOB_ID, review(decision=None), REQUEST), [])

    def test_row_carries_the_player_cues_and_pipeline_scores(self) -> None:
        row = build_label_rows(JOB_ID, review(), REQUEST)[0]

        self.assertEqual(row["player"], {"jersey_number": "18", "jersey_color": "blue"})
        self.assertEqual(row["action"], "batting")
        self.assertEqual(row["score"], 0.5)
        self.assertEqual(row["identity_strength"], 0.4)
        self.assertEqual(row["bbox"], [10, 20, 60, 160])

    def test_only_the_upload_basename_is_kept(self) -> None:
        # The absolute path is the worker's private filesystem layout and has no
        # business in a dataset that may be shared or shipped.
        row = build_label_rows(JOB_ID, review(), REQUEST)[0]

        self.assertEqual(row["source_video"], "upload_abc_match.mp4")

    def test_youtube_source_is_kept_whole(self) -> None:
        request = {**REQUEST, "video_path": None, "youtube_url": "https://youtu.be/xyz"}

        row = build_label_rows(JOB_ID, review(), request)[0]

        self.assertEqual(row["source_video"], "https://youtu.be/xyz")


class RecordReviewLabelsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.outputs = base / "outputs"
        self.root = base / "datasets" / "reid"
        self.addCleanup(self._tmp.cleanup)

    def test_crops_are_copied_out_of_disposable_output_scratch(self) -> None:
        write_crops(self.outputs)

        written = record_review_labels(JOB_ID, review(), REQUEST, self.outputs, self.root)

        self.assertEqual(written, 3)
        rows = load_labels(self.root)
        self.assertEqual(len(rows), 3)
        for row in rows:
            copied = self.root / row["crop_path"]
            self.assertTrue(copied.exists(), row["crop_path"])
            self.assertEqual(copied.read_bytes(), b"jpeg")
        # Surviving deletion of outputs/ is the entire reason for the copy.
        for crop in (self.outputs / "review" / JOB_ID).glob("*.jpg"):
            crop.unlink()
        self.assertEqual(summarize(load_labels(self.root), self.root)["missing_crops"], 0)

    def test_a_candidate_with_no_crop_on_disk_is_dropped(self) -> None:
        # A label without an image cannot train anything, and a row pointing at a
        # missing file would fail at load time instead of here.
        write_crops(self.outputs, candidate_ids=("c0", "c2"))

        written = record_review_labels(JOB_ID, review(), REQUEST, self.outputs, self.root)

        self.assertEqual(written, 2)
        self.assertEqual({r["candidate_id"] for r in load_labels(self.root)}, {"c0", "c2"})

    def test_recording_the_same_job_twice_does_not_duplicate_it(self) -> None:
        write_crops(self.outputs)
        record_review_labels(JOB_ID, review(), REQUEST, self.outputs, self.root)

        again = record_review_labels(JOB_ID, review(), REQUEST, self.outputs, self.root)

        self.assertEqual(again, 0)
        self.assertEqual(len(load_labels(self.root)), 3)

    def test_a_second_job_appends_rather_than_replaces(self) -> None:
        write_crops(self.outputs)
        record_review_labels(JOB_ID, review(), REQUEST, self.outputs, self.root)

        other = "job-2"
        crop_dir = self.outputs / "review" / other
        crop_dir.mkdir(parents=True)
        (crop_dir / "c0.jpg").write_bytes(b"jpeg")
        second = {
            **review(candidate_ids=("c0",)),
            "candidates": [
                {
                    "id": "c0",
                    "time_s": 1.0,
                    "bbox": [0, 0, 5, 5],
                    "score": 0.9,
                    "url": f"/outputs/review/{other}/c0.jpg",
                }
            ],
        }
        record_review_labels(other, second, REQUEST, self.outputs, self.root)

        self.assertEqual(len({r["job_id"] for r in load_labels(self.root)}), 2)

    def test_a_broken_review_never_raises_into_the_request(self) -> None:
        # Losing a training example is cheap; failing the user's review submit,
        # and with it a multi-hour run, is not.
        written = record_review_labels(
            JOB_ID, {"candidates": "not-a-list"}, REQUEST, self.outputs, self.root
        )

        self.assertEqual(written, 0)
        self.assertFalse((self.root / LABELS_FILENAME).exists())

    def test_a_url_escaping_the_outputs_mount_is_refused(self) -> None:
        escaping = review(candidate_ids=("c0",))
        escaping["candidates"][0]["url"] = "/outputs/../../etc/passwd"

        written = record_review_labels(JOB_ID, escaping, REQUEST, self.outputs, self.root)

        self.assertEqual(written, 0)

    def test_corrupt_lines_do_not_make_the_dataset_unreadable(self) -> None:
        write_crops(self.outputs)
        record_review_labels(JOB_ID, review(), REQUEST, self.outputs, self.root)
        with (self.root / LABELS_FILENAME).open("a", encoding="utf-8") as fh:
            fh.write("{not json\n")

        self.assertEqual(len(load_labels(self.root)), 3)


class SplitTests(unittest.TestCase):
    def _rows(self, job_count: int, per_job: int = 6):
        return [
            {"job_id": f"job-{j}", "candidate_id": f"c{i}", "label": POSITIVE}
            for j in range(job_count)
            for i in range(per_job)
        ]

    def test_crops_from_one_job_never_straddle_the_split(self) -> None:
        # Six crops of one player in one match are near-duplicates. Splitting them
        # row-wise reports a validation score about footage it already trained on.
        parts = split_by_job(self._rows(10), val_fraction=0.3, seed=0)

        train_jobs = {r["job_id"] for r in parts["train"]}
        val_jobs = {r["job_id"] for r in parts["val"]}
        self.assertEqual(train_jobs & val_jobs, set())
        self.assertEqual(len(parts["train"]) + len(parts["val"]), 60)

    def test_the_split_is_reproducible_for_a_seed(self) -> None:
        first = split_by_job(self._rows(10), val_fraction=0.3, seed=7)
        second = split_by_job(self._rows(10), val_fraction=0.3, seed=7)

        self.assertEqual(
            [r["job_id"] for r in first["val"]], [r["job_id"] for r in second["val"]]
        )

    def test_training_is_never_left_empty(self) -> None:
        # Rounding on a two-job dataset would otherwise claim both for validation
        # and fail much later, in the training loop, for a confusing reason.
        parts = split_by_job(self._rows(2), val_fraction=0.9, seed=0)

        self.assertTrue(parts["train"])


class SummarizeTests(unittest.TestCase):
    def test_counts_split_positives_negatives_and_jobs(self) -> None:
        rows = [
            {"job_id": "a", "label": POSITIVE, "decision": "approved", "player": {"jersey_number": "1"}},
            {"job_id": "a", "label": NEGATIVE, "decision": "approved", "player": {"jersey_number": "1"}},
            {"job_id": "b", "label": NEGATIVE, "decision": "rejected", "player": {"jersey_number": "2"}},
        ]

        stats = summarize(rows, Path("/nonexistent"))

        self.assertEqual(stats["rows"], 3)
        self.assertEqual(stats["positives"], 1)
        self.assertEqual(stats["negatives"], 2)
        self.assertEqual(stats["jobs"], 2)
        self.assertEqual(stats["rejected_jobs"], 1)
        self.assertEqual(stats["players"], 2)


class SerializationTests(unittest.TestCase):
    def test_every_row_field_survives_json(self) -> None:
        # The rows are written with json.dumps; a value that cannot serialize
        # would take down the append and lose the whole review.
        rows = build_label_rows(JOB_ID, review(rejected_ids=["c1"]), REQUEST)

        for row in rows:
            self.assertEqual(json.loads(json.dumps(row)), row)


if __name__ == "__main__":
    unittest.main()
