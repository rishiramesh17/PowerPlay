import json
import logging
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("job_store")


class JobStatus:
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    #: Detection finished and the user has been asked to confirm the identity.
    #: Nothing is running; the job is parked until a human answers.
    AWAITING_REVIEW = "awaiting_review"
    #: The user confirmed. A worker may pick the job back up and finish it.
    REVIEW_APPROVED = "review_approved"
    COMPILING = "compiling"
    DONE = "done"
    FAILED = "failed"


#: Statuses a job sits in while a worker owns it.
#:
#: AWAITING_REVIEW is deliberately absent: it means the job is waiting on a
#: person, not on a worker, so the stale reaper must not treat it as abandoned.
ACTIVE_STATUSES = (
    JobStatus.DOWNLOADING,
    JobStatus.PROCESSING,
    JobStatus.COMPILING,
)

#: Statuses a worker may claim off the queue, in priority order. Approved
#: reviews come first: that work is already half-paid-for and a user is waiting
#: on it, so it should not queue behind a fresh multi-hour detection run.
CLAIMABLE_STATUSES = (
    JobStatus.REVIEW_APPROVED,
    JobStatus.QUEUED,
)

#: Columns `update_job` may write. Anything else is a caller bug, and keeping the
#: list explicit stops arbitrary keys reaching the SQL text.
UPDATABLE_COLUMNS = frozenset(
    {
        "status",
        "stage",
        "message",
        "download_percent",
        "progress",
        "output_url",
        "output_path",
        "request_json",
        "result_json",
        "review_json",
        "resume_json",
        "error",
        "updated_at",
    }
)


class JobStore:
    def __init__(self, db_path: Path = Path("jobs.db")):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        # The API polls this database every couple of seconds while the worker
        # writes to it, so WAL (concurrent readers) and a busy timeout (wait
        # rather than raise "database is locked") are both load-bearing.
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY,
                        status TEXT,
                        stage TEXT,
                        message TEXT,
                        download_percent REAL,
                        progress REAL,
                        output_url TEXT,
                        output_path TEXT,
                        request_json TEXT,
                        result_json TEXT,
                        review_json TEXT,
                        resume_json TEXT,
                        error TEXT,
                        created_at REAL,
                        updated_at REAL
                    )
                    """
                )
                # Supports both the queue scan and newest-first job listing.
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_status_created "
                    "ON jobs (status, created_at)"
                )
                self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """
        Add columns introduced after a database was first created.

        CREATE TABLE IF NOT EXISTS silently does nothing when the table exists,
        so a developer with an existing jobs.db would otherwise get "no such
        column" at runtime rather than at startup.
        """
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        for column, ddl in (("review_json", "TEXT"), ("resume_json", "TEXT")):
            if column not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {ddl}")
                logger.info(f"Migrated jobs table: added column {column}")

    def create_job(self, payload: Dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        now = time.time()
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        id, status, stage, message, download_percent, progress,
                        request_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        JobStatus.QUEUED,
                        "queued",
                        "Job queued",
                        0.0,
                        0.0,
                        json.dumps(payload),
                        now,
                        now,
                    ),
                )
        return job_id

    def update_job(self, job_id: str, **fields: Any):
        if not fields:
            return

        unknown = set(fields) - UPDATABLE_COLUMNS
        if unknown:
            raise ValueError(
                f"update_job received unknown column(s): {', '.join(sorted(unknown))}"
            )

        # Callers may set updated_at explicitly (tests, replays); default to now.
        fields.setdefault("updated_at", time.time())
        keys = list(fields.keys())
        values = [fields[k] for k in keys]
        set_clause = ", ".join(f"{k}=?" for k in keys)
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    f"UPDATE jobs SET {set_clause} WHERE id=?",
                    (*values, job_id),
                )

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            cur = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
            row = cur.fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def list_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Most recent jobs first, so a returning user can find a run they lost."""
        with closing(self._connect()) as conn:
            cur = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            )
            rows = cur.fetchall()
        return [self._row_to_dict(row) for row in rows]

    def fetch_next_queued(self) -> Optional[Dict[str, Any]]:
        """
        Atomically claim the oldest claimable job, marking it processing.

        The claim has to be one transaction: a plain SELECT lets two workers read
        the same row and process the same video twice.

        Statuses are tried in CLAIMABLE_STATUSES order, so a job whose review the
        user just approved resumes ahead of a brand-new run. The returned row
        carries `claimed_from`, which tells the worker whether this is a fresh
        job or one resuming after review.
        """
        now = time.time()
        with closing(self._connect()) as conn:
            try:
                # BEGIN IMMEDIATE takes the write lock up front, so a second
                # worker blocks here instead of reading the same row.
                conn.execute("BEGIN IMMEDIATE")

                row = None
                claimed_from = None
                for status in CLAIMABLE_STATUSES:
                    cur = conn.execute(
                        "SELECT id FROM jobs WHERE status=? ORDER BY created_at ASC LIMIT 1",
                        (status,),
                    )
                    row = cur.fetchone()
                    if row:
                        claimed_from = status
                        break

                if not row:
                    conn.execute("ROLLBACK")
                    return None

                job_id = row["id"]
                resuming = claimed_from == JobStatus.REVIEW_APPROVED
                cur = conn.execute(
                    """
                    UPDATE jobs
                       SET status=?, stage=?, message=?, updated_at=?
                     WHERE id=? AND status=?
                    """,
                    (
                        JobStatus.PROCESSING,
                        "resuming" if resuming else "preparing",
                        "Building your highlight" if resuming else "Starting worker",
                        now,
                        job_id,
                        claimed_from,
                    ),
                )
                if cur.rowcount == 0:
                    # Another worker claimed it between the select and update.
                    conn.execute("ROLLBACK")
                    return None

                cur = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
                claimed = cur.fetchone()
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        if not claimed:
            return None
        job = self._row_to_dict(claimed)
        job["claimed_from"] = claimed_from
        return job

    def save_review(self, job_id: str, review: Dict[str, Any]) -> None:
        """Park a job on the identity-confirmation step with its candidate crops."""
        self.update_job(
            job_id,
            status=JobStatus.AWAITING_REVIEW,
            stage="awaiting_review",
            message="Confirm we found the right player",
            review_json=json.dumps(review),
        )

    def save_resume_state(self, job_id: str, state: Dict[str, Any]) -> None:
        """Persist what a later worker needs to finish this job after review."""
        self.update_job(job_id, resume_json=json.dumps(state))

    def get_resume_state(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Read resume state. Deliberately not part of the job dict — see _row_to_dict.
        """
        with closing(self._connect()) as conn:
            cur = conn.execute("SELECT resume_json FROM jobs WHERE id=?", (job_id,))
            row = cur.fetchone()
        if not row or not row["resume_json"]:
            return None
        try:
            return json.loads(row["resume_json"])
        except Exception:
            logger.warning(f"Job {job_id} has unreadable resume state")
            return None

    def get_review(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self.get_job(job_id)
        if not job:
            return None
        review = job.get("review")
        return review if isinstance(review, dict) else None

    def record_review_decision(
        self,
        job_id: str,
        approved: bool,
        rejected_ids: Optional[List[str]] = None,
        note: Optional[str] = None,
    ) -> bool:
        """
        Record the user's verdict and release the job, or fail it outright.

        Returns False when the job is not actually awaiting review, so a double
        submit or a stale browser tab cannot resurrect a finished job. The status
        check and the write share one transaction for the same reason the claim
        does: two tabs can submit at once.
        """
        now = time.time()
        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute(
                    "SELECT review_json FROM jobs WHERE id=? AND status=?",
                    (job_id, JobStatus.AWAITING_REVIEW),
                )
                row = cur.fetchone()
                if not row:
                    conn.execute("ROLLBACK")
                    return False

                try:
                    review = json.loads(row["review_json"]) if row["review_json"] else {}
                except Exception:
                    review = {}
                review["decision"] = "approved" if approved else "rejected"
                review["rejected_ids"] = list(rejected_ids or [])
                review["note"] = note
                review["decided_at"] = now

                if approved:
                    status, stage, message, error = (
                        JobStatus.REVIEW_APPROVED,
                        "review_approved",
                        "Identity confirmed — building your highlight",
                        None,
                    )
                else:
                    # A rejection is a real answer, not a crash: the pipeline did
                    # its job and found the wrong person. Say that plainly.
                    status, stage, message, error = (
                        JobStatus.FAILED,
                        "failed",
                        "You told us this was not the right player",
                        "Identity rejected at review. Try clearer colour hints, a "
                        "jersey number, or a tighter time range.",
                    )

                conn.execute(
                    """
                    UPDATE jobs
                       SET status=?, stage=?, message=?, error=?, review_json=?, updated_at=?
                     WHERE id=?
                    """,
                    (status, stage, message, error, json.dumps(review), now, job_id),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return True

    def reap_stale_jobs(self, stale_after_sec: float = 6 * 60 * 60) -> int:
        """
        Fail jobs left mid-flight by a worker that died.

        Without this they sit in `processing` forever and the UI polls them until
        it times out hours later. Returns the number of jobs reaped.
        """
        cutoff = time.time() - stale_after_sec
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        with closing(self._connect()) as conn:
            with conn:
                cur = conn.execute(
                    f"""
                    UPDATE jobs
                       SET status=?, stage=?, message=?, error=?, updated_at=?
                     WHERE status IN ({placeholders}) AND updated_at < ?
                    """,
                    (
                        JobStatus.FAILED,
                        "failed",
                        "Worker stopped before this job finished",
                        "Job was interrupted; the worker did not report progress in time",
                        time.time(),
                        *ACTIVE_STATUSES,
                        cutoff,
                    ),
                )
                reaped = cur.rowcount or 0
        if reaped:
            logger.warning(f"Reaped {reaped} stale job(s) left behind by a stopped worker")
        return reaped

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        for key in ("request_json", "result_json", "review_json"):
            if data.get(key):
                try:
                    data[key[:-5]] = json.loads(data[key])  # strip _json suffix
                except Exception:
                    data[key[:-5]] = data[key]
            data.pop(key, None)
        # Dropped, never expanded: resume state holds absolute paths on the
        # worker's disk, and `GET /jobs/{id}` returns this dict straight to the
        # browser. Workers read it through get_resume_state() instead.
        data.pop("resume_json", None)
        return data

