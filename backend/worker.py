import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from job_store import JobStore, JobStatus
from main import (
    cleanup_related_upload_files,
    download_youtube_video,
    parse_timecode,
    trim_with_ffmpeg,
    DEFAULT_FRAME_SKIP,
    DEFAULT_DETECT_EVERY_N_FRAMES,
    DEFAULT_RESIZE_SCALE,
    DEFAULT_YOLO_MODEL,
    DOWNLOADS_DIR,
)
from processing.detect_player import detect_player_in_video
from processing.track_player import track_player
from processing.utils import get_video_duration
from processing.compile_clips import compile_highlight
from processing.highlight_scorer import score_segments_with_ai, filter_segments_by_score
from processing.ml.highlight_dataset import capture_segments_to_dataset

logger = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def _update(store: JobStore, job_id: str, **fields: Any):
    try:
        store.update_job(job_id, **{k: v for k, v in fields.items() if v is not None})
    except Exception as e:
        logger.warning(f"Failed to update job {job_id}: {e}")


def process_job(job: Dict[str, Any], store: JobStore):
    job_id = job["id"]
    payload: Dict[str, Any] = job.get("request") or {}
    if not payload:
        _update(store, job_id, status=JobStatus.FAILED, stage="failed", message="Missing job payload")
        return

    source = payload.get("source")
    player_data = payload.get("player_data", {})
    action = payload.get("action", "batting")
    team_mode = bool(payload.get("team_mode"))
    frame_skip = int(payload.get("frame_skip", DEFAULT_FRAME_SKIP))
    detect_every_n_frames = int(payload.get("detect_every_n_frames", DEFAULT_DETECT_EVERY_N_FRAMES))
    resize_scale = float(payload.get("resize_scale", DEFAULT_RESIZE_SCALE))
    yolo_model = payload.get("yolo_model", DEFAULT_YOLO_MODEL)
    start_time = payload.get("start_time")
    end_time = payload.get("end_time")
    save_dataset = bool(payload.get("save_dataset", False))

    temp_path: Optional[Path] = None
    trimmed_path: Optional[Path] = None

    # allow debugging downloads/temps
    keep_downloads = os.getenv("KEEP_DOWNLOADS_FOR_DEBUG", "false").lower() in ("1", "true", "yes")
    dataset_max_clips_env = os.getenv("HIGHLIGHT_DATASET_MAX_CLIPS", "").strip()
    dataset_max_clips = int(dataset_max_clips_env) if dataset_max_clips_env.isdigit() else 25
    # more aggressive collection in team mode by default
    if team_mode and dataset_max_clips == 25:
        dataset_max_clips = 150

    try:
        _update(
            store,
            job_id,
            status=JobStatus.DOWNLOADING if source == "youtube" else JobStatus.PROCESSING,
            stage="preparing",
            message="Preparing job",
            progress=5.0,
        )

        # 1) Acquire video
        if source == "upload":
            temp_path = Path(payload["video_path"])
            if not temp_path.exists():
                raise RuntimeError("Uploaded file missing on disk")
        elif source == "youtube":
            youtube_url = payload.get("youtube_url")
            if not youtube_url:
                raise RuntimeError("YouTube URL missing")
            temp_path = DOWNLOADS_DIR / f"youtube_{job_id}.mp4"
            start_sec = parse_timecode(start_time) if start_time else None
            end_sec = parse_timecode(end_time) if end_time else None

            def progress_cb(percent: int, msg: str = "downloading"):
                _update(
                    store,
                    job_id,
                    status=JobStatus.DOWNLOADING,
                    stage="downloading",
                    download_percent=float(percent),
                    message=msg,
                    progress=min(25.0, float(percent) * 0.25),
                )

            download_youtube_video(
                youtube_url,
                temp_path,
                start_sec=start_sec,
                end_sec=end_sec,
                progress_callback=progress_cb,
            )
            _update(store, job_id, download_percent=100.0)
        else:
            raise RuntimeError("Invalid job source")

        # 2) Trim if requested
        start_sec = parse_timecode(start_time) if start_time else None
        end_sec = parse_timecode(end_time) if end_time else None
        trimmed_path = trim_with_ffmpeg(temp_path, start_sec, end_sec) if (start_sec or end_sec) else temp_path

        video_dur = get_video_duration(str(trimmed_path))
        logger.info(f"🎞️ Video duration to process: {video_dur:.1f}s (start={start_sec}, end={end_sec})")

        _update(
            store,
            job_id,
            status=JobStatus.PROCESSING,
            stage="detecting",
            message="Running detection",
            progress=40.0,
        )

        jersey_color = str(player_data.get("jersey_color", "")).strip() or None
        color_hints = {"jersey": jersey_color} if (jersey_color and not team_mode) else None

        det_payload = detect_player_in_video(
            video_path=str(trimmed_path),
            player_data=player_data,
            action=action,
            frame_skip=frame_skip,
            detect_every_n_frames=detect_every_n_frames,
            resize_scale=resize_scale,
            yolo_model=yolo_model,
            color_hints=color_hints,
            team_mode=team_mode,
        )

        _update(
            store,
            job_id,
            status=JobStatus.PROCESSING,
            stage="tracking",
            message="Refining segments",
            progress=60.0,
        )

        tracked_segments = track_player(
            video_path=str(trimmed_path),
            detection_payload=det_payload,
            frame_skip=frame_skip,
            resize_scale=resize_scale,
            prefer_deepsort=False,
            tracking_progress_step=2,
            fps_override=None,
        )

        if not tracked_segments:
            raise RuntimeError("No player segments found. Try setting Jersey Color or a tighter time range.")

        capture_flag = save_dataset or os.getenv("CAPTURE_HIGHLIGHT_DATASET", "true").lower() in ("1", "true", "yes")
        if capture_flag:
            info = capture_segments_to_dataset(
                video_path=str(trimmed_path),
                segments=tracked_segments,
                meta={
                    "mode": "game" if source == "youtube" else "upload",
                    "action": action,
                    "player": player_data,
                },
                max_clips=dataset_max_clips,
            )
            logger.info(f"📦 Dataset capture: saved={info['saved']} clips into {info['clips_dir']}")

        use_openai = os.getenv("USE_OPENAI", "false").lower() in ("1", "true", "yes")
        _update(
            store,
            job_id,
            status=JobStatus.PROCESSING,
            stage="scoring" if use_openai else "filtering",
            message="Scoring segments" if use_openai else "Selecting segments",
            progress=75.0,
        )

        if use_openai:
            scored_segments = score_segments_with_ai(
                video_path=str(trimmed_path),
                segments=tracked_segments,
                max_segments_for_ai=40,
            )

            filtered_segments = filter_segments_by_score(
                scored_segments,
                min_score=0.55,
                max_segments=10,
                max_total_duration=120.0,
            )

            if not filtered_segments:
                filtered_segments = tracked_segments[:5]
        else:
            filtered_segments = tracked_segments[:50]  # allow more segments when compiling long games

        _update(
            store,
            job_id,
            status=JobStatus.COMPILING,
            stage="compiling",
            message="Compiling highlight",
            progress=90.0,
        )

        highlight_path = compile_highlight(
            str(trimmed_path),
            filtered_segments,
            show_progress=False,
        )

        output_url = f"/outputs/{Path(highlight_path).name}"
        result = {
            "highlight_url": output_url,
            "segments": filtered_segments,
            "processing_stats": {
                "video_duration": round(video_dur, 1),
                "segments_found": len(filtered_segments),
            },
        }

        _update(
            store,
            job_id,
            status=JobStatus.DONE,
            stage="done",
            message="Highlight ready",
            progress=100.0,
            output_url=output_url,
            output_path=str(highlight_path),
            result_json=json.dumps(result),
        )
        logger.info(f"✅ Job {job_id} completed: {output_url}")

    except Exception as e:
        logger.error(f"❌ Job {job_id} failed: {e}")
        _update(
            store,
            job_id,
            status=JobStatus.FAILED,
            stage="failed",
            message=str(e),
            error=str(e),
        )
    finally:
        try:
            if trimmed_path and trimmed_path.exists() and temp_path and trimmed_path != temp_path and not keep_downloads:
                trimmed_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            if temp_path and not keep_downloads:
                cleanup_related_upload_files(temp_path)
        except Exception:
            pass


def run_worker(poll_interval: float = 2.0):
    store = JobStore(Path("jobs.db"))
    logger.info("👷 Worker started. Waiting for jobs...")
    while True:
        job = store.fetch_next_queued()
        if not job:
            time.sleep(poll_interval)
            continue

        job_id = job["id"]
        logger.info(f"🚀 Processing job {job_id}")
        _update(store, job_id, status=JobStatus.PROCESSING, stage="preparing", message="Starting worker")

        process_job(job, store)


if __name__ == "__main__":
    run_worker()
