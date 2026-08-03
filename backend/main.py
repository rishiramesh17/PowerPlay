# main.py
import json
import subprocess
import os
import uuid
import logging
import inspect
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List, NamedTuple

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from processing.utils import save_upload_file
from processing.practice_mode import analyze_practice_session, analyze_cricket_practice_session
from job_store import JobStore, JobStatus

# optional: yt-dlp
import yt_dlp

class ReviewDecision(BaseModel):
    """The user's answer to 'is this the player you meant?'."""

    approved: bool
    #: Candidate ids the user marked as not-the-player. Kept even on approval:
    #: a mostly-right run with two bad crops is the training signal we want.
    rejected_ids: List[str] = Field(default_factory=list)
    note: Optional[str] = None


# ----------------------------------------------------
# App setup
# ----------------------------------------------------
app = FastAPI()

# Browsers reject allow_origins=["*"] together with allow_credentials=True, and a
# wildcard would expose the API to any page the user has open. Set
# PP_ALLOWED_ORIGINS (comma separated) when the frontend is not on localhost.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "PP_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads"); UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = Path("outputs"); OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR = Path("downloads"); DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Only rendered highlights are served. `uploads/` and `downloads/` hold the user's
# source media; mounting them lets anyone who guesses a filename read it.
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

# Reject oversized uploads before they fill the disk.
MAX_UPLOAD_BYTES = int(os.getenv("PP_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024 * 1024)))

JOB_STORE = JobStore(Path("jobs.db"))

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("main")

# ----------------------------------------------------
# Tunable defaults (middle-ground)
# ----------------------------------------------------
DEFAULT_FRAME_SKIP = 18                # frames advanced each loop iteration in tracking
DEFAULT_DETECT_EVERY_N_FRAMES = 2     # how often to run YOLO in scanning pass
DEFAULT_RESIZE_SCALE = 0.5          # downscale factor before running YOLO (0.5 faster, 1.0 accurate)
DEFAULT_YOLO_MODEL = "yolov8n.pt"
DEFAULT_DETECTION_PROGRESS_STEP = 1   # percent steps for detection logging (1 => log every 1%)
DEFAULT_DOWNLOAD_PROGRESS_STEP = 10   # percent steps for download logging

# ----------------------------------------------------
# Helpers
# ----------------------------------------------------
def parse_timecode(tc: Optional[str]) -> Optional[float]:
    """Convert hh:mm:ss or mm:ss or ss string into seconds (float)."""
    if not tc:
        return None
    try:
        parts = [float(p) for p in tc.strip().split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 1:
            return parts[0]
    except Exception:
        return None
    return None

# progress reporter (10% increments for downloads, configurable for detection step in detect module)
class CoarseProgress:
    def __init__(self, logger, step_percent: int = 10):
        self.logger = logger
        self.step = max(1, step_percent)
        self.last = -self.step

    def maybe(self, percent: int, prefix: str = ""):
        # percent integer 0..100
        if percent // self.step > self.last // self.step:
            self.last = percent
            self.logger.info(f"{prefix}{percent}% complete")

def cleanup_related_upload_files(output_path: Path):
    try:
        parent = output_path.parent
        prefix = output_path.stem  # e.g. youtube_<uuid>
        for p in parent.glob(prefix + "*"):
            try:
                if p.is_file():
                    p.unlink(missing_ok=True)
                    logger.info(f"🗑️ Removed upload artifact: {p.name}")
            except Exception:
                pass
    except Exception:
        pass

# ----------------------------------------------------
# YouTube download (yt-dlp) with coarse progress
# ----------------------------------------------------
def _resolve_downloaded_video_path(output_path: Path) -> Optional[Path]:
    """
    Resolve the final downloaded media path for a given output stem.
    yt-dlp may emit different container extensions depending on source/merge.
    """
    if output_path.exists() and output_path.is_file():
        return output_path

    candidates = []
    for p in output_path.parent.glob(output_path.stem + ".*"):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix in {".part", ".ytdl", ".tmp", ".temp", ".frag", ".json", ".txt"}:
            continue
        candidates.append(p)

    if not candidates:
        return None

    def rank(path: Path):
        try:
            size = path.stat().st_size
        except Exception:
            size = 0
        return (1 if path.suffix.lower() == ".mp4" else 0, size)

    candidates.sort(key=rank, reverse=True)
    return candidates[0]


class YouTubeDownload(NamedTuple):
    """
    Result of a YouTube download.

    `section_applied` is True when yt-dlp cut the requested [start, end] range
    server-side, meaning the file on disk already begins at `start_sec`.
    Callers MUST NOT trim again in that case — a second absolute-time trim
    would cut the wrong window. It is False when the range was requested but
    the download fell back to fetching the full video, which still needs a
    local trim.
    """

    path: Path
    section_applied: bool


def download_youtube_video(
    url: str,
    output_path: Path,
    start_sec: Optional[float] = None,
    end_sec: Optional[float] = None,
    timeout: int = 7200,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    max_height: Optional[int] = None,
    allow_full_fallback: bool = True,
    prefer_video_only: bool = False,
) -> YouTubeDownload:
    """
    Download YouTube video.
    If start_sec/end_sec provided, tries yt-dlp download_sections first.
    Uses multiple format fallbacks to avoid "Requested format is not available".
    """
    logger.info(f"🔄 STARTING YOUTUBE DOWNLOAD: {url}")
    logger.info(f"📁 Download destination: {output_path}")
    progress = CoarseProgress(logger, step_percent=DEFAULT_DOWNLOAD_PROGRESS_STEP)

    def _format_section(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    max_h = int(max_height if (max_height and max_height > 0) else os.getenv("PP_YTDLP_MAX_HEIGHT", "720"))
    concurrent_frags = int(os.getenv("PP_YTDLP_CONCURRENT_FRAGS", "8"))

    # Try multiple format selectors because some videos do NOT offer every combo.
    # In analysis-only mode we can skip audio to reduce download size/time.
    if prefer_video_only:
        FORMAT_CANDIDATES = [
            f"bv*[height<={max_h}]/bestvideo*[height<={max_h}]",
            "bv*/bestvideo*",
            "b",
        ]
    else:
        FORMAT_CANDIDATES = [
            f"bv*[height<={max_h}]+ba/b[height<={max_h}]/b",
            "bv*+ba/b",
            "b",
        ]

    # progress hook
    def progress_hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
            downloaded = d.get("downloaded_bytes") or 0
            percent = int(downloaded / max(1, total) * 100)
            progress.maybe(percent, prefix="[download] ")
            if progress_callback:
                progress_callback(percent, "downloading")
        elif d.get("status") == "finished":
            logger.info("✅ Download finished, now post-processing...")
            progress.maybe(100, prefix="[download] ")
            if progress_callback:
                progress_callback(100, "download_complete")

    # Base yt-dlp options (do NOT force output .mp4 extension here)
    ydl_opts = {
        "format": FORMAT_CANDIDATES[0],
        "outtmpl": str(output_path.with_suffix(".%(ext)s")),
        "merge_output_format": "mp4",
        "progress_hooks": [progress_hook],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "continuedl": True,
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 600,

        # speed helpers
        "concurrent_fragment_downloads": concurrent_frags,
        "http_chunk_size": 10 * 1024 * 1024,  # 10MB
    }
    if prefer_video_only:
        ydl_opts.pop("merge_output_format", None)

    cookiefile = os.getenv("PP_YTDLP_COOKIES_FILE", "").strip()
    if cookiefile:
        cookie_path = Path(cookiefile)
        if cookie_path.exists():
            ydl_opts["cookiefile"] = str(cookie_path)
        else:
            logger.warning(f"⚠️ PP_YTDLP_COOKIES_FILE not found: {cookie_path}")

    user_agent = os.getenv("PP_YTDLP_USER_AGENT", "").strip()
    referer = os.getenv("PP_YTDLP_REFERER", "").strip()
    if user_agent or referer:
        headers = {}
        if user_agent:
            headers["User-Agent"] = user_agent
        if referer:
            headers["Referer"] = referer
        ydl_opts["http_headers"] = headers

    # Define _attempt ONCE, at function scope (always available)
    def _attempt(opts: dict, label: str):
        last_err = None
        for fmt in FORMAT_CANDIDATES:
            try:
                opts2 = dict(opts)
                opts2["format"] = fmt
                logger.info(
                    f"▶️ yt-dlp attempt: {label} | format='{fmt}' "
                    f"| video_only={prefer_video_only}"
                )
                with yt_dlp.YoutubeDL(opts2) as ydl:
                    ydl.download([url])
                return
            except Exception as e:
                last_err = e
                logger.warning(f"⚠️ attempt failed for format='{fmt}': {e}")
        raise last_err

    # If start/end provided, attempt section download
    section_requested = start_sec is not None or end_sec is not None
    section_applied = False
    if section_requested:
        try:
            start_str = _format_section(start_sec or 0.0)
            # An open-ended range must be "inf", not 00:00:00 — the latter is an
            # empty span that makes yt-dlp fail into the full-download fallback.
            end_str = _format_section(end_sec) if end_sec is not None else "inf"
            ydl_opts["download_sections"] = [f"*{start_str}-{end_str}"]
            logger.info(f"🔖 Requesting yt-dlp to download section {start_str} → {end_str} (if supported)")
        except Exception:
            pass

    # ---- Attempt 1: download_sections (if set) ----
    try:
        _attempt(ydl_opts, "download_sections")
        section_applied = section_requested
    except Exception as e:
        logger.warning(f"⚠️ yt-dlp section download failed: {e}")

        # clean partial files
        try:
            for p in output_path.parent.glob(output_path.stem + ".*"):
                if p.exists() and p.stat().st_size < 1024 * 1024:
                    p.unlink(missing_ok=True)
        except Exception:
            pass

        # ---- Attempt 2: external downloader ffmpeg (still section if yt-dlp supports it) ----
        try:
            opts2 = dict(ydl_opts)
            opts2["external_downloader"] = "ffmpeg"
            opts2["external_downloader_args"] = ["-nostdin"]
            _attempt(opts2, "external_downloader=ffmpeg segment")
            section_applied = section_requested
        except Exception as e2:
            logger.warning(f"⚠️ ffmpeg segment downloader failed: {e2}")

            # ---- Attempt 3: FULL download fallback ----
            if allow_full_fallback:
                fallback_opts = dict(ydl_opts)
                fallback_opts.pop("download_sections", None)
                try:
                    _attempt(fallback_opts, "FULL download fallback (slow)")
                    # Full video on disk: the caller still owes us a local trim.
                    section_applied = False
                except Exception as e3:
                    logger.error(f"❌ YouTube download failed: {e3}")
                    raise RuntimeError(f"YouTube download failed: {e3}")
            else:
                raise RuntimeError(
                    f"YouTube section download failed without full fallback: {e2}"
                )

    final_path = _resolve_downloaded_video_path(output_path)
    if final_path is None:
        raise RuntimeError("Downloaded file is missing or corrupted")

    logger.info(
        f"✅ YouTube download completed successfully: {final_path.name} "
        f"(section_applied={section_applied})"
    )
    return YouTubeDownload(final_path, section_applied)

def trim_with_ffmpeg(input_path: Path, start_sec: Optional[float], end_sec: Optional[float]) -> Path:
    """
    Trim video using ffmpeg and return trimmed path. If no trimming requested, returns original path.

    start_sec/end_sec are absolute offsets into `input_path`. Either may be
    omitted: start-only trims to the end of the video, end-only trims from 0.
    """
    if (start_sec is None and end_sec is None):
        return input_path
    if end_sec is not None and end_sec <= (start_sec or 0.0):
        raise RuntimeError(
            f"Invalid trim range: end ({end_sec}) must be after start ({start_sec or 0.0})"
        )
    out = input_path.parent / f"{input_path.stem}_trimmed.mp4"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if start_sec is not None:
        # -ss must come BEFORE -i to get input seeking: ffmpeg jumps straight to
        # the nearest keyframe instead of decoding every frame from 0. On a
        # multi-hour source that is the difference between seconds and minutes.
        cmd += ["-ss", str(start_sec)]
    cmd += ["-i", str(input_path)]
    if end_sec is not None:
        # -t is measured from the seek point, so it is a span, not an endpoint.
        # Previously this was skipped whenever start_sec was None, which meant
        # an end time on its own silently produced an untrimmed video.
        duration = end_sec - (start_sec or 0.0)
        cmd += ["-t", str(duration)]
    # Stream copy starts at a keyframe, which can leave negative leading
    # timestamps; normalising them avoids a frozen first frame in the output.
    cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero", str(out)]
    logger.info(f"⏱️ Trimming video to range {start_sec} - {end_sec} seconds (ffmpeg copy mode)")
    subprocess.run(cmd, check=True)
    return out

# ----------------------------------------------------
# Job enqueue helpers
# ----------------------------------------------------
async def enqueue_processing_job(
    video: UploadFile = File(None),
    youtube_url: str = Form(None),
    playerData: str = Form(...),
    action: str = Form("batting"),
    scope: str = Form("player"), 
    start_time: str = Form(None),
    end_time: str = Form(None),
    frame_skip: int = Form(DEFAULT_FRAME_SKIP),
    detect_every_n_frames: int = Form(DEFAULT_DETECT_EVERY_N_FRAMES),
    resize_scale: float = Form(DEFAULT_RESIZE_SCALE),
    yolo_model: str = Form(DEFAULT_YOLO_MODEL),
    save_dataset: bool = Form(False),
    prefer_deepsort: bool = Form(False),
    dev_test_mode: bool = Form(False),
    require_review: bool = Form(False),
):
    try:
        player_data = json.loads(playerData)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid playerData JSON")

    scope_norm = (scope or "player").strip().lower()
    team_mode = scope_norm in ("team", "any", "all", "team_mode")
    jersey_raw = str(player_data.get("jersey_number", "")).strip()
    jersey_color = str(player_data.get("jersey_color", "")).strip() or None
    jersey = jersey_raw if jersey_raw and jersey_raw.lower() not in ("na", "none", "n/a", "null") else None

    logger.info(f"🧭 Scope: {scope_norm} (team_mode={team_mode})")
    logger.info(f"👕 Jersey: {jersey_raw}")
    logger.info(f"🎨 Jersey Color: {jersey_color}")

    if not team_mode and (not jersey and not jersey_color):
        raise HTTPException(
            status_code=400,
            detail='Provide either a jersey number or jersey color (jersey number may be "na"), '
                   'or set scope="team" to generate team highlights.',
        )

    payload: Dict[str, Any] = {
        "player_data": player_data,
        "action": action,
        "scope": scope_norm,
        "team_mode": team_mode,
        "start_time": start_time,
        "end_time": end_time,
        "frame_skip": frame_skip,
        "detect_every_n_frames": detect_every_n_frames,
        "resize_scale": resize_scale,
        "yolo_model": yolo_model,
        "save_dataset": bool(save_dataset),
        "prefer_deepsort": bool(prefer_deepsort),
        # Pause after detection and ask the user to confirm the identity before
        # spending compile time on the wrong person.
        "require_review": bool(require_review),
        # ==================== DEV TEST MODE ====================
        # Fast validation mode for short turnaround testing.
        "dev_test_mode": bool(dev_test_mode),
        # =======================================================
    }

    if bool(dev_test_mode):
        logger.info("🧪 DEV TEST MODE enabled for this job")

    if video:
        # Path(...).name strips any directory component, so a filename like
        # "../../etc/passwd" cannot write outside uploads/.
        safe_name = Path(video.filename or "video.mp4").name
        temp_path = UPLOAD_DIR / f"upload_{uuid.uuid4()}_{safe_name}"
        try:
            await run_in_threadpool(save_upload_file, video, temp_path, MAX_UPLOAD_BYTES)
        except ValueError as e:
            raise HTTPException(status_code=413, detail=str(e))
        payload["source"] = "upload"
        payload["video_path"] = str(temp_path)
        logger.info(f"✅ Uploaded video saved for job: {temp_path.name}")
    elif youtube_url:
        payload["source"] = "youtube"
        payload["youtube_url"] = youtube_url
    else:
        raise HTTPException(status_code=400, detail="No video source provided")

    job_id = JOB_STORE.create_job(payload)
    return {"job_id": job_id, "status": JobStatus.QUEUED, "stage": "queued"}

# ----------------------------------------------------
# Routes
# ----------------------------------------------------
@app.get("/")
async def root():
    return {"message": "PowerPlay Backend API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "message": "Backend is running"}

@app.post("/jobs")
async def create_job_endpoint(
    video: UploadFile = File(None),
    youtube_url: str = Form(None),
    playerData: str = Form(...),
    action: str = Form("batting"),
    scope: str = Form("player"), 
    start_time: str = Form(None),
    end_time: str = Form(None),
    frame_skip: int = Form(DEFAULT_FRAME_SKIP),
    detect_every_n_frames: int = Form(DEFAULT_DETECT_EVERY_N_FRAMES),
    resize_scale: float = Form(DEFAULT_RESIZE_SCALE),
    yolo_model: str = Form(DEFAULT_YOLO_MODEL),
    save_dataset: bool = Form(False),
    prefer_deepsort: bool = Form(False),
    dev_test_mode: bool = Form(False),
    require_review: bool = Form(False),
):
    return await enqueue_processing_job(
        video=video,
        youtube_url=youtube_url,
        playerData=playerData,
        action=action,
        scope=scope,
        start_time=start_time,
        end_time=end_time,
        frame_skip=frame_skip,
        detect_every_n_frames=detect_every_n_frames,
        resize_scale=resize_scale,
        yolo_model=yolo_model,
        save_dataset=save_dataset,
        prefer_deepsort=prefer_deepsort,
        dev_test_mode=dev_test_mode,
        require_review=require_review,
    )


@app.post("/process-video")
async def process_video(
    video: UploadFile = File(None),
    youtube_url: str = Form(None),
    playerData: str = Form(...),
    action: str = Form("batting"),
    scope: str = Form("player"), 
    start_time: str = Form(None),
    end_time: str = Form(None),
    frame_skip: int = Form(DEFAULT_FRAME_SKIP),
    detect_every_n_frames: int = Form(DEFAULT_DETECT_EVERY_N_FRAMES),
    resize_scale: float = Form(DEFAULT_RESIZE_SCALE),
    yolo_model: str = Form(DEFAULT_YOLO_MODEL),
    save_dataset: bool = Form(False),
    prefer_deepsort: bool = Form(False),
    dev_test_mode: bool = Form(False),
    require_review: bool = Form(False),
):
    """
    Backwards-compatible entrypoint that now enqueues a background job.
    """
    resp = await enqueue_processing_job(
        video=video,
        youtube_url=youtube_url,
        playerData=playerData,
        action=action,
        scope=scope,
        start_time=start_time,
        end_time=end_time,
        frame_skip=frame_skip,
        detect_every_n_frames=detect_every_n_frames,
        resize_scale=resize_scale,
        yolo_model=yolo_model,
        save_dataset=save_dataset,
        prefer_deepsort=prefer_deepsort,
        dev_test_mode=dev_test_mode,
        require_review=require_review,
    )
    resp["message"] = f"Job queued. Poll /jobs/{resp['job_id']} for status."
    return resp


@app.get("/jobs/{job_id}")
async def job_status(job_id: str):
    job = JOB_STORE.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["job_id"] = job_id
    return job

@app.get("/jobs/{job_id}/review")
async def get_job_review(job_id: str):
    """The candidate crops the user is being asked to confirm."""
    job = JOB_STORE.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    review = job.get("review")
    if not isinstance(review, dict):
        raise HTTPException(status_code=404, detail="This job has no identity review")

    return {
        "job_id": job_id,
        "status": job.get("status"),
        # Only actionable while the job is parked; afterwards this is a record of
        # what was decided, which the UI shows read-only.
        "awaiting_decision": job.get("status") == JobStatus.AWAITING_REVIEW,
        **review,
    }


@app.post("/jobs/{job_id}/review")
async def submit_job_review(job_id: str, decision: ReviewDecision):
    """
    Record the user's verdict: resume the job, or stop it as a wrong match.

    Returns 409 rather than 404 when the job exists but is not awaiting a
    decision, so a double-submit from two tabs is distinguishable from a bad id.
    """
    job = JOB_STORE.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    accepted = JOB_STORE.record_review_decision(
        job_id,
        approved=bool(decision.approved),
        rejected_ids=decision.rejected_ids,
        note=decision.note,
    )
    if not accepted:
        raise HTTPException(
            status_code=409,
            detail=f"Job is not awaiting review (status: {job.get('status')})",
        )

    updated = JOB_STORE.get_job(job_id)
    return {
        "job_id": job_id,
        "status": updated.get("status"),
        "stage": updated.get("stage"),
        "message": updated.get("message"),
    }


@app.get("/jobs")
async def list_jobs(limit: int = 50):
    """
    Recent jobs, newest first, so a run survives the tab being closed.

    Without this a job id exists only in the browser's memory, and a multi-hour
    analysis becomes unreachable the moment the page is refreshed.
    """
    limit = max(1, min(int(limit), 200))
    jobs = JOB_STORE.list_jobs(limit=limit)
    for job in jobs:
        job["job_id"] = job.get("id")
    return {"jobs": jobs}

@app.post("/practice-mode")
async def practice_mode(
    video: UploadFile = File(None),
    youtube_url: str = Form(None),

    # keep these to match your frontend PracticeModePage formData keys:
    practice_type: str = Form("batting"),
    video_length: str = Form(""),
    desired_clip_length: str = Form(""),
    movement_threshold: float = Form(0.02),
    min_movement_duration: float = Form(0.5),
    padding_before: float = Form(1.0),
    padding_after: float = Form(4.0),
    output_mode: str = Form("clips"),
):
    temp_path = None
    try:
        if video:
            # Never build a path from the client's filename directly: "../" in it
            # would write outside uploads/, and a repeated name would clobber
            # another user's in-flight file.
            temp_path = UPLOAD_DIR / f"practice_{uuid.uuid4()}{Path(video.filename or '').suffix}"
            await run_in_threadpool(save_upload_file, video, temp_path, MAX_UPLOAD_BYTES)
        elif youtube_url:
            temp_path = UPLOAD_DIR / f"practice_{uuid.uuid4()}.mp4"
            result = await run_in_threadpool(download_youtube_video, youtube_url, temp_path)
            temp_path = result.path
        else:
            return {"status": "error", "message": "No video source provided"}

        # Build all possible args from the frontend
        all_args = {
            "video_path": str(temp_path),
            "output_dir": str(OUTPUT_DIR),
            "practice_type": practice_type,
            "video_length": video_length,
            "desired_clip_length": desired_clip_length,
            "movement_threshold": movement_threshold,
            "min_movement_duration": min_movement_duration,
            "padding_before": padding_before,
            "padding_after": padding_after,
            "output_mode": output_mode,
        }

        # Only pass the args that this function actually accepts
        sig = inspect.signature(analyze_cricket_practice_session)
        filtered_args = {k: v for k, v in all_args.items() if k in sig.parameters}

        # This is minutes of OpenCV work. Running it inline on the event loop
        # freezes every other request, including job-status polling.
        data = await run_in_threadpool(analyze_cricket_practice_session, **filtered_args)
        return data

    except Exception as e:
        logger.error(f"❌ Practice mode failed: {e}")
        return {"status": "error", "message": f"Practice mode failed: {str(e)}"}
    finally:
        try:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
        except Exception:
            pass

if __name__ == "__main__":
    import uvicorn

    # reload= is ignored when an app object is passed rather than an import
    # string, so name the module explicitly and let PP_RELOAD opt in.
    uvicorn.run(
        "main:app",
        host=os.getenv("PP_HOST", "127.0.0.1"),
        port=int(os.getenv("PP_PORT", "8000")),
        reload=os.getenv("PP_RELOAD", "false").lower() in ("1", "true", "yes"),
    )
