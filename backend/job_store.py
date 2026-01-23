import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


class JobStatus:
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPILING = "compiling"
    DONE = "done"
    FAILED = "failed"


class JobStore:
    def __init__(self, db_path: Path = Path("jobs.db")):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
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
                    error TEXT,
                    created_at REAL,
                    updated_at REAL
                )
                """
            )
            conn.commit()

    def create_job(self, payload: Dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as conn:
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
            conn.commit()
        return job_id

    def update_job(self, job_id: str, **fields: Any):
        if not fields:
            return
        fields["updated_at"] = time.time()

        keys = list(fields.keys())
        values = [fields[k] for k in keys]
        set_clause = ", ".join([f"{k}=?" for k in keys])
        with self._connect() as conn:
            conn.execute(
                f"UPDATE jobs SET {set_clause} WHERE id=?",
                (*values, job_id),
            )
            conn.commit()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
            row = cur.fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def fetch_next_queued(self) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status=?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (JobStatus.QUEUED,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        for key in ("request_json", "result_json"):
            if data.get(key):
                try:
                    data[key[:-5]] = json.loads(data[key])  # strip _json suffix
                except Exception:
                    data[key[:-5]] = data[key]
            data.pop(key, None)
        return data

