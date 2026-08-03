import json
import sqlite3
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

    def test_fetch_next_queued_claims_the_job(self) -> None:
        """A claimed job must not be handed out a second time."""
        job_id = self.store.create_job({"source": "upload", "video_path": "only.mp4"})

        first = self.store.fetch_next_queued()
        second = self.store.fetch_next_queued()

        self.assertIsNotNone(first)
        self.assertEqual(first["id"], job_id)
        self.assertEqual(first["status"], JobStatus.PROCESSING)
        self.assertIsNone(second, "the same job was claimed twice")

    def test_fetch_next_queued_returns_none_when_empty(self) -> None:
        self.assertIsNone(self.store.fetch_next_queued())

    def test_update_job_rejects_unknown_columns(self) -> None:
        job_id = self.store.create_job({"source": "upload"})

        with self.assertRaises(ValueError):
            self.store.update_job(job_id, definitely_not_a_column="x")

    def test_reap_stale_jobs_fails_abandoned_runs(self) -> None:
        stale = self.store.create_job({"source": "upload", "video_path": "stale.mp4"})
        fresh = self.store.create_job({"source": "upload", "video_path": "fresh.mp4"})

        self.store.fetch_next_queued()  # claims `stale`
        # Backdate it past the threshold to stand in for a worker that died.
        self.store.update_job(stale, updated_at=time.time() - 10_000)

        reaped = self.store.reap_stale_jobs(stale_after_sec=3600)

        self.assertEqual(reaped, 1)
        self.assertEqual(self.store.get_job(stale)["status"], JobStatus.FAILED)
        self.assertEqual(self.store.get_job(fresh)["status"], JobStatus.QUEUED)

    def test_reap_stale_jobs_leaves_finished_jobs_alone(self) -> None:
        job_id = self.store.create_job({"source": "upload"})
        self.store.update_job(
            job_id, status=JobStatus.DONE, updated_at=time.time() - 10_000
        )

        self.assertEqual(self.store.reap_stale_jobs(stale_after_sec=3600), 0)
        self.assertEqual(self.store.get_job(job_id)["status"], JobStatus.DONE)

    def test_list_jobs_returns_newest_first(self) -> None:
        first = self.store.create_job({"source": "upload", "video_path": "first.mp4"})
        time.sleep(0.01)
        second = self.store.create_job({"source": "upload", "video_path": "second.mp4"})

        jobs = self.store.list_jobs()

        self.assertEqual([j["id"] for j in jobs], [second, first])

    def test_list_jobs_respects_limit(self) -> None:
        for _ in range(5):
            self.store.create_job({"source": "upload"})
            time.sleep(0.005)

        self.assertEqual(len(self.store.list_jobs(limit=3)), 3)


class IdentityReviewTests(unittest.TestCase):
    """The pause-for-confirmation state machine."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "jobs.db"
        self.store = JobStore(self.db_path)
        self.review = {"candidates": [{"id": "c0", "url": "/outputs/review/x/c0.jpg"}]}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _park(self) -> str:
        job_id = self.store.create_job({"source": "upload", "require_review": True})
        self.store.fetch_next_queued()
        self.store.save_review(job_id, self.review)
        return job_id

    def test_parked_job_is_not_claimable_by_a_worker(self) -> None:
        # The whole design rests on this: a job waiting on a human must not be
        # picked up, or a second worker would redo the run.
        self._park()

        self.assertIsNone(self.store.fetch_next_queued())

    def test_approving_makes_the_job_claimable_again(self) -> None:
        job_id = self._park()

        self.assertTrue(self.store.record_review_decision(job_id, approved=True))
        self.assertEqual(self.store.get_job(job_id)["status"], JobStatus.REVIEW_APPROVED)

        claimed = self.store.fetch_next_queued()
        self.assertEqual(claimed["id"], job_id)
        self.assertEqual(claimed["claimed_from"], JobStatus.REVIEW_APPROVED)

    def test_approved_reviews_are_claimed_before_new_jobs(self) -> None:
        approved = self._park()
        self.store.record_review_decision(approved, approved=True)
        time.sleep(0.01)
        self.store.create_job({"source": "upload", "video_path": "newer.mp4"})

        # Even though the queued job is newer, half-finished work goes first.
        self.assertEqual(self.store.fetch_next_queued()["id"], approved)

    def test_rejecting_fails_the_job_with_a_reason(self) -> None:
        job_id = self._park()

        self.assertTrue(self.store.record_review_decision(job_id, approved=False))

        job = self.store.get_job(job_id)
        self.assertEqual(job["status"], JobStatus.FAILED)
        self.assertIn("not the right player", job["message"])
        self.assertTrue(job["error"])
        self.assertIsNone(self.store.fetch_next_queued())

    def test_decision_is_rejected_when_job_is_not_awaiting_review(self) -> None:
        job_id = self._park()
        self.store.record_review_decision(job_id, approved=True)

        # A second tab submitting again must not resurrect the job.
        self.assertFalse(self.store.record_review_decision(job_id, approved=False))
        self.assertEqual(self.store.get_job(job_id)["status"], JobStatus.REVIEW_APPROVED)

    def test_decision_records_rejected_candidates(self) -> None:
        job_id = self._park()

        self.store.record_review_decision(
            job_id, approved=True, rejected_ids=["c2", "c4"], note="two bad crops"
        )

        review = self.store.get_review(job_id)
        self.assertEqual(review["decision"], "approved")
        self.assertEqual(review["rejected_ids"], ["c2", "c4"])
        self.assertEqual(review["note"], "two bad crops")

    def test_reaper_leaves_jobs_awaiting_a_human_alone(self) -> None:
        job_id = self._park()
        self.store.update_job(job_id, updated_at=time.time() - 10_000)

        # A user may take hours to answer; that is not an abandoned job.
        self.assertEqual(self.store.reap_stale_jobs(stale_after_sec=3600), 0)
        self.assertEqual(self.store.get_job(job_id)["status"], JobStatus.AWAITING_REVIEW)

    def test_resume_state_never_reaches_the_public_job_dict(self) -> None:
        # GET /jobs/{id} returns this dict verbatim, and resume state holds
        # absolute paths on the worker's disk.
        job_id = self._park()
        self.store.save_resume_state(job_id, {"trimmed_path": "/srv/tmp/secret.mp4"})

        job = self.store.get_job(job_id)
        self.assertNotIn("resume", job)
        self.assertNotIn("resume_json", job)
        self.assertEqual(
            self.store.get_resume_state(job_id)["trimmed_path"], "/srv/tmp/secret.mp4"
        )

    def test_migration_adds_review_columns_to_an_existing_database(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        conn = sqlite3.connect(legacy_path)
        conn.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, status TEXT, stage TEXT, message TEXT,
                download_percent REAL, progress REAL, output_url TEXT,
                output_path TEXT, request_json TEXT, result_json TEXT,
                error TEXT, created_at REAL, updated_at REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO jobs (id, status, created_at, updated_at) VALUES (?,?,?,?)",
            ("legacy", JobStatus.QUEUED, 1.0, 1.0),
        )
        conn.commit()
        conn.close()

        store = JobStore(legacy_path)  # must ALTER rather than raise

        columns = {row[1] for row in sqlite3.connect(legacy_path).execute("PRAGMA table_info(jobs)")}
        self.assertIn("review_json", columns)
        self.assertIn("resume_json", columns)
        self.assertEqual(store.get_job("legacy")["status"], JobStatus.QUEUED)


if __name__ == "__main__":
    unittest.main()
