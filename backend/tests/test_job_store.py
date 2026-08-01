import json
import tempfile
import time
import unittest
from pathlib import Path

import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from job_store import JobStatus, JobStore


class JobStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "jobs.db"
        self.store = JobStore(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_job_persists_request_payload_and_defaults(self) -> None:
        payload = {"source": "upload", "video_path": "uploads/input.mp4"}

        job_id = self.store.create_job(payload)
        job = self.store.get_job(job_id)

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], JobStatus.QUEUED)
        self.assertEqual(job["stage"], "queued")
        self.assertEqual(job["message"], "Job queued")
        self.assertEqual(job["download_percent"], 0.0)
        self.assertEqual(job["progress"], 0.0)
        self.assertEqual(job["request"], payload)

    def test_update_job_deserializes_result_payload(self) -> None:
        job_id = self.store.create_job({"source": "youtube", "youtube_url": "https://example.com/watch?v=123"})
        result = {"segments": [[10.0, 14.5]], "highlight_url": "/outputs/highlight.mp4"}

        self.store.update_job(
            job_id,
            status=JobStatus.DONE,
            stage="done",
            progress=100.0,
            output_url=result["highlight_url"],
            result_json=json.dumps(result),
        )

        job = self.store.get_job(job_id)

        self.assertEqual(job["status"], JobStatus.DONE)
        self.assertEqual(job["stage"], "done")
        self.assertEqual(job["progress"], 100.0)
        self.assertEqual(job["output_url"], "/outputs/highlight.mp4")
        self.assertEqual(job["result"], result)

    def test_fetch_next_queued_skips_non_queued_jobs(self) -> None:
        first_job = self.store.create_job({"source": "upload", "video_path": "first.mp4"})
        time.sleep(0.01)
        second_job = self.store.create_job({"source": "upload", "video_path": "second.mp4"})

        self.store.update_job(first_job, status=JobStatus.PROCESSING, stage="detecting")
        next_job = self.store.fetch_next_queued()

        self.assertIsNotNone(next_job)
        self.assertEqual(next_job["id"], second_job)
        self.assertEqual(next_job["request"]["video_path"], "second.mp4")


if __name__ == "__main__":
    unittest.main()
