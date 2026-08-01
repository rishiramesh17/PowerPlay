import json
import logging
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    OUTPUT_DIR,
)
from processing.detect_player import detect_player_in_video
from processing.track_player import track_player
from processing.utils import get_video_duration, limit_total_duration
from processing.compile_clips import compile_highlight
from processing.highlight_scorer import score_segments_with_ai, filter_segments_by_score
from processing.segment_selector import select_best_segments
from processing.ml.highlight_dataset import capture_segments_to_dataset

logger = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _adaptive_scan_params(
    duration_sec: float,
    frame_skip: int,
    detect_every_n_frames: int,
    resize_scale: float,
    prefer_deepsort: bool,
):
    if os.getenv("PP_ENABLE_ADAPTIVE_SCAN", "true").lower() not in ("1", "true", "yes"):
        return frame_skip, detect_every_n_frames, resize_scale

    fs = max(1, int(frame_skip))
    det_n = max(1, int(detect_every_n_frames))
    rs = float(resize_scale)

    # Quality mode stays denser, but still gets light adaptation on very long videos.
    if prefer_deepsort:
        if duration_sec >= 3 * 3600:
            fs = max(fs, 10)
            det_n = max(det_n, 2)
            rs = min(rs, 0.65)
        else:
            fs = max(fs, 8)
            det_n = max(det_n, 1)
            rs = min(rs, 0.70)
        return fs, det_n, rs

    if duration_sec >= 3 * 3600:
        fs = max(fs, 18)
        det_n = max(det_n, 3)
        rs = min(rs, 0.52)
    elif duration_sec >= 90 * 60:
        fs = max(fs, 14)
        det_n = max(det_n, 2)
        rs = min(rs, 0.58)
    elif duration_sec >= 45 * 60:
        fs = max(fs, 12)
        det_n = max(det_n, 2)
        rs = min(rs, 0.62)

    return fs, det_n, rs


def _update(store: JobStore, job_id: str, **fields: Any):
    try:
        store.update_job(job_id, **{k: v for k, v in fields.items() if v is not None})
    except Exception as e:
        logger.warning(f"Failed to update job {job_id}: {e}")


def _merge_close_segments(
    segments: List[Tuple[float, float]],
    gap_sec: float = 0.35,
) -> List[Tuple[float, float]]:
    if not segments:
        return []
    ordered = sorted((max(0.0, float(s)), max(0.0, float(e))) for s, e in segments if (float(e) - float(s)) > 0.1)
    if not ordered:
        return []
    merged: List[Tuple[float, float]] = []
    cur_s, cur_e = ordered[0]
    for s, e in ordered[1:]:
        if s <= cur_e + gap_sec:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    return merged


def _selected_segment_seed_stats(segments: List[Tuple[float, float]], seeds: List[Any]) -> Dict[str, float]:
    if not segments or not seeds:
        return {}

    id_vals: List[float] = []
    replay_vals: List[float] = []
    post_cut_vals: List[float] = []

    for s, e in segments:
        for sd in seeds:
            t = float(getattr(sd, "time_s", -1.0) or -1.0)
            if t < s or t > e:
                continue
            id_vals.append(float(getattr(sd, "identity_strength", 0.0) or 0.0))
            replay_vals.append(1.0 if bool(getattr(sd, "replay_suspect", False)) else 0.0)
            post_cut_vals.append(1.0 if bool(getattr(sd, "post_cut_reacquire", False)) else 0.0)

    if not id_vals and not replay_vals and not post_cut_vals:
        return {}

    stats: Dict[str, float] = {}
    if id_vals:
        stats["selected_identity_mean"] = round(sum(id_vals) / max(1, len(id_vals)), 4)
    if replay_vals:
        stats["selected_replay_seed_rate"] = round(sum(replay_vals) / max(1, len(replay_vals)), 4)
    if post_cut_vals:
        stats["selected_post_cut_seed_rate"] = round(sum(post_cut_vals) / max(1, len(post_cut_vals)), 4)
    return stats


def _estimate_pipeline_minutes(
    video_duration_sec: float,
    source: str,
    prefer_deepsort: bool,
    has_time_range: bool,
    team_mode: bool,
) -> float:
    video_min = max(1.0, float(video_duration_sec) / 60.0)
    # Coarse planning model for user expectation setting.
    download_factor = 0.18 if source == "youtube" else 0.04
    analysis_factor = 0.32 if prefer_deepsort else 0.24
    if team_mode:
        analysis_factor += 0.04
    if has_time_range:
        download_factor *= 0.75
        analysis_factor *= 0.85
    overhead_min = 12.0
    return max(8.0, video_min * (download_factor + analysis_factor) + overhead_min)


def _compile_youtube_sections(
    youtube_url: str,
    job_id: str,
    segments: List[Tuple[float, float]],
    source_offset_sec: float = 0.0,
    max_total_duration: float = 130.0,
    keep_downloads: bool = False,
) -> str:
    if not segments:
        raise RuntimeError("No segments available for section-based YouTube compile.")

    if max_total_duration > 0:
        segments = limit_total_duration(sorted(segments, key=lambda x: x[0]), max_total_duration)
    else:
        segments = sorted(segments, key=lambda x: x[0])

    if not segments:
        raise RuntimeError("No segments remain after duration cap for section compile.")

    section_limit = max(1, int(os.getenv("PP_YT_SECTION_MAX_SEGMENTS", "12")))
    merge_gap_sec = max(0.0, float(os.getenv("PP_YT_SECTION_MERGE_GAP_SEC", "0.35")))
    pad_pre_sec = max(0.0, float(os.getenv("PP_YT_SECTION_PRE_PAD_SEC", "0.20")))
    pad_post_sec = max(0.0, float(os.getenv("PP_YT_SECTION_POST_PAD_SEC", "0.35")))
    section_max_height = int(os.getenv("PP_YTDLP_HIGHLIGHT_MAX_HEIGHT", os.getenv("PP_YTDLP_MAX_HEIGHT", "720")))

    source_segments: List[Tuple[float, float]] = []
    for s, e in segments:
        source_s = max(0.0, float(s) + source_offset_sec - pad_pre_sec)
        source_e = max(source_s + 0.1, float(e) + source_offset_sec + pad_post_sec)
        source_segments.append((source_s, source_e))

    merged_source_segments = _merge_close_segments(source_segments, gap_sec=merge_gap_sec)[:section_limit]
    if not merged_source_segments:
        raise RuntimeError("No valid source segments to download for section compile.")

    temp_dir = OUTPUT_DIR / f"yt_sections_{job_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    section_workers = max(1, int(os.getenv("PP_YT_SECTION_DOWNLOAD_WORKERS", "3")))
    section_workers = min(section_workers, len(merged_source_segments))
    logger.info(
        f"[section_compile] Downloading {len(merged_source_segments)} source sections "
        f"with workers={section_workers} (max_height={section_max_height}p)."
    )

    def _download_one(idx: int, s: float, e: float) -> Tuple[int, Optional[Path]]:
        base_path = temp_dir / f"section_{idx:03d}.mp4"
        try:
            clip_path = download_youtube_video(
                youtube_url,
                base_path,
                start_sec=s,
                end_sec=e,
                max_height=section_max_height,
                allow_full_fallback=False,
                prefer_video_only=False,
            ).path
            if clip_path and clip_path.exists():
                return idx, clip_path
            return idx, None
        except Exception as ex:
            logger.warning(f"[section_compile] Failed to download segment {idx} ({s:.2f}-{e:.2f}): {ex}")
            return idx, None

    downloaded: Dict[int, Path] = {}
    if section_workers <= 1:
        for idx, (s, e) in enumerate(merged_source_segments):
            out_idx, clip = _download_one(idx, s, e)
            if clip is not None:
                downloaded[out_idx] = clip
    else:
        with ThreadPoolExecutor(max_workers=section_workers, thread_name_prefix="ytsec") as pool:
            futures = [
                pool.submit(_download_one, idx, seg[0], seg[1])
                for idx, seg in enumerate(merged_source_segments)
            ]
            for fut in as_completed(futures):
                out_idx, clip = fut.result()
                if clip is not None:
                    downloaded[out_idx] = clip

    clip_paths: List[Path] = [downloaded[i] for i in sorted(downloaded.keys())]

    if not clip_paths:
        raise RuntimeError("All section clip downloads failed.")

    concat_list_path = temp_dir / "concat_list.txt"
    with concat_list_path.open("w", encoding="utf-8") as fh:
        for p in clip_paths:
            escaped = str(p.resolve()).replace("'", "'\\''")
            fh.write(f"file '{escaped}'\n")

    out_path = OUTPUT_DIR / f"youtube_{job_id}_highlight.mp4"
    copy_cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c",
        "copy",
        str(out_path),
    ]
    copy_run = subprocess.run(copy_cmd, capture_output=True, text=True)
    if copy_run.returncode != 0:
        # Fallback for mixed stream parameters across section files.
        reencode_cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        enc_run = subprocess.run(reencode_cmd, capture_output=True, text=True)
        if enc_run.returncode != 0:
            err = (enc_run.stderr or copy_run.stderr or "").strip()
            raise RuntimeError(f"Section compile concat failed: {err[:500]}")

    if not keep_downloads:
        try:
            for p in temp_dir.glob("*"):
                p.unlink(missing_ok=True)
            temp_dir.rmdir()
        except Exception:
            pass

    return str(out_path)


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
    prefer_deepsort = bool(payload.get("prefer_deepsort", False)) or (
        os.getenv("PP_ENABLE_DEEPSORT", "false").lower() in ("1", "true", "yes")
    )
    frame_skip = int(payload.get("frame_skip", DEFAULT_FRAME_SKIP))
    detect_every_n_frames = int(payload.get("detect_every_n_frames", DEFAULT_DETECT_EVERY_N_FRAMES))
    resize_scale = float(payload.get("resize_scale", DEFAULT_RESIZE_SCALE))
    yolo_model = payload.get("yolo_model", DEFAULT_YOLO_MODEL)
    start_time = payload.get("start_time")
    end_time = payload.get("end_time")
    save_dataset = bool(payload.get("save_dataset", False))
    start_sec = parse_timecode(start_time) if start_time else None
    end_sec = parse_timecode(end_time) if end_time else None
    dev_test_mode = _as_bool(payload.get("dev_test_mode", False))

    temp_path: Optional[Path] = None
    trimmed_path: Optional[Path] = None

    # allow debugging downloads/temps
    keep_downloads = os.getenv("KEEP_DOWNLOADS_FOR_DEBUG", "false").lower() in ("1", "true", "yes")
    dataset_max_clips_env = os.getenv("HIGHLIGHT_DATASET_MAX_CLIPS", "").strip()
    dataset_max_clips = int(dataset_max_clips_env) if dataset_max_clips_env.isdigit() else 25
    # more aggressive collection in team mode by default
    if team_mode and dataset_max_clips == 25:
        dataset_max_clips = 150

    timings: Dict[str, float] = {}
    pipeline_start = time.perf_counter()
    estimated_total_min = 0.0
    runtime_class = "standard"
    dev_test_overrides: Dict[str, Any] = {}
    dev_disable_rescue = False

    # ==================== DEV TEST MODE ====================
    # Isolated, explicit fast-path for short-cycle product validation.
    if dev_test_mode:
        logger.info(f"🧪 DEV TEST MODE active for job {job_id}")

        dev_window_start = max(0.0, float(os.getenv("PP_DEV_TEST_WINDOW_START_SEC", "0")))
        dev_window_sec = max(60.0, float(os.getenv("PP_DEV_TEST_WINDOW_SEC", "420")))

        if start_sec is None and end_sec is None:
            start_sec = dev_window_start
            end_sec = dev_window_start + dev_window_sec
            dev_test_overrides["forced_window_sec"] = [round(start_sec, 2), round(end_sec, 2)]
        elif start_sec is not None and end_sec is None:
            end_sec = start_sec + dev_window_sec
            dev_test_overrides["auto_end_sec"] = round(end_sec, 2)

        frame_skip_before = frame_skip
        detect_before = detect_every_n_frames
        resize_before = resize_scale

        frame_skip = max(frame_skip, int(os.getenv("PP_DEV_TEST_FRAME_SKIP", "26")))
        detect_every_n_frames = max(detect_every_n_frames, int(os.getenv("PP_DEV_TEST_DETECT_EVERY", "4")))
        resize_scale = min(resize_scale, float(os.getenv("PP_DEV_TEST_RESIZE_SCALE", "0.45")))
        prefer_deepsort = False
        save_dataset = False
        dev_disable_rescue = _as_bool(os.getenv("PP_DEV_TEST_DISABLE_RESCUE", "true"))

        dev_test_overrides.update(
            {
                "frame_skip": [frame_skip_before, frame_skip],
                "detect_every_n_frames": [detect_before, detect_every_n_frames],
                "resize_scale": [round(resize_before, 3), round(resize_scale, 3)],
                "prefer_deepsort_forced": False,
                "save_dataset_forced": False,
                "rescue_pass_enabled": not dev_disable_rescue,
            }
        )
    # =======================================================

    try:
        _update(
            store,
            job_id,
            status=JobStatus.DOWNLOADING if source == "youtube" else JobStatus.PROCESSING,
            stage="preparing",
            message="Preparing job [DEV TEST MODE]" if dev_test_mode else "Preparing job",
            progress=5.0,
        )

        # 1) Acquire video
        t0 = time.perf_counter()
        # True once the acquired file already covers only [start_sec, end_sec],
        # so step 2 knows not to apply the same cut a second time.
        range_already_cut = False
        if source == "upload":
            temp_path = Path(payload["video_path"])
            if not temp_path.exists():
                raise RuntimeError("Uploaded file missing on disk")
        elif source == "youtube":
            youtube_url = payload.get("youtube_url")
            if not youtube_url:
                raise RuntimeError("YouTube URL missing")
            temp_path = DOWNLOADS_DIR / f"youtube_{job_id}.mp4"
            enable_low_res_analysis = os.getenv("PP_ENABLE_ANALYSIS_LOW_RES_DOWNLOAD", "true").lower() in (
                "1",
                "true",
                "yes",
            )
            analysis_max_height: Optional[int] = None
            if enable_low_res_analysis and start_sec is None and end_sec is None:
                try:
                    analysis_max_height = max(144, int(os.getenv("PP_YTDLP_ANALYSIS_MAX_HEIGHT", "480")))
                except Exception:
                    analysis_max_height = 480
            analysis_video_only = os.getenv("PP_ANALYSIS_VIDEO_ONLY_DOWNLOAD", "true").lower() in (
                "1",
                "true",
                "yes",
            )

            # ==================== DEV TEST MODE ====================
            if dev_test_mode:
                dev_max_height = max(144, int(os.getenv("PP_DEV_TEST_MAX_HEIGHT", "360")))
                analysis_video_only = True
                analysis_max_height = (
                    min(analysis_max_height, dev_max_height) if analysis_max_height is not None else dev_max_height
                )
                dev_test_overrides["analysis_max_height"] = analysis_max_height
                dev_test_overrides["analysis_video_only"] = analysis_video_only
            # =======================================================

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

            download = download_youtube_video(
                youtube_url,
                temp_path,
                start_sec=start_sec,
                end_sec=end_sec,
                progress_callback=progress_cb,
                max_height=analysis_max_height,
                prefer_video_only=analysis_video_only,
            )
            temp_path = download.path
            range_already_cut = download.section_applied
            if analysis_max_height:
                logger.info(f"⬇️ Analysis download max height forced to {analysis_max_height}p")
            if analysis_video_only:
                logger.info("⬇️ Analysis download using video-only stream to reduce ingest time")
            _update(store, job_id, download_percent=100.0)
        else:
            raise RuntimeError("Invalid job source")
        timings["acquire_sec"] = round(time.perf_counter() - t0, 2)

        # 2) Trim if requested.
        #
        # yt-dlp may already have cut the range server-side via download_sections,
        # in which case the file on disk starts at start_sec. Trimming it again
        # with the same absolute times would seek start_sec *into the already-cut
        # clip* and return the wrong window entirely. Only trim when the acquired
        # file is still full-length.
        #
        # Either way the analysed file begins at start_sec in source time, which
        # is what source_offset_sec assumes when mapping segments back for
        # section-based compilation.
        t0 = time.perf_counter()
        needs_trim = (start_sec is not None or end_sec is not None) and not range_already_cut
        if needs_trim:
            trimmed_path = trim_with_ffmpeg(temp_path, start_sec, end_sec)
        else:
            if range_already_cut:
                logger.info(
                    f"⏱️ Source already cut to {start_sec}-{end_sec} at download time; skipping redundant trim."
                )
            trimmed_path = temp_path
        timings["trim_sec"] = round(time.perf_counter() - t0, 2)

        video_dur = get_video_duration(str(trimmed_path))
        logger.info(f"🎞️ Video duration to process: {video_dur:.1f}s (start={start_sec}, end={end_sec})")
        frame_skip_eff, detect_every_eff, resize_scale_eff = _adaptive_scan_params(
            duration_sec=video_dur,
            frame_skip=frame_skip,
            detect_every_n_frames=detect_every_n_frames,
            resize_scale=resize_scale,
            prefer_deepsort=prefer_deepsort,
        )
        if (frame_skip_eff, detect_every_eff, resize_scale_eff) != (frame_skip, detect_every_n_frames, resize_scale):
            logger.info(
                "⚙️ Adaptive scan params: "
                f"frame_skip {frame_skip}→{frame_skip_eff}, "
                f"detect_every {detect_every_n_frames}→{detect_every_eff}, "
                f"resize {resize_scale:.2f}→{resize_scale_eff:.2f}"
            )
        frame_skip = frame_skip_eff
        detect_every_n_frames = detect_every_eff
        resize_scale = resize_scale_eff
        estimated_total_min = _estimate_pipeline_minutes(
            video_duration_sec=video_dur,
            source=str(source),
            prefer_deepsort=prefer_deepsort,
            has_time_range=bool(start_sec is not None or end_sec is not None),
            team_mode=team_mode,
        )
        if estimated_total_min <= 45:
            runtime_class = "fast"
        elif estimated_total_min <= 120:
            runtime_class = "standard"
        else:
            runtime_class = "overnight"

        _update(
            store,
            job_id,
            status=JobStatus.PROCESSING,
            stage="detecting",
            message=(
                f"Running detection [DEV TEST MODE] (est. total ~{estimated_total_min:.0f} min)"
                if dev_test_mode
                else f"Running detection (est. total ~{estimated_total_min:.0f} min)"
            ),
            progress=40.0,
        )

        t0 = time.perf_counter()
        jersey_color = str(player_data.get("jersey_color", "")).strip() or None
        helmet_color = str(player_data.get("helmet_color", "")).strip() or None
        pad_color = str(player_data.get("pad_color", "")).strip() or None
        glove_color = str(player_data.get("glove_color", "")).strip() or None
        color_hints = None
        if not team_mode:
            hint_map = {
                "jersey": jersey_color,
                "helmet": helmet_color,
                "pad": pad_color,
                "glove": glove_color,
            }
            compact = {k: v for k, v in hint_map.items() if v}
            color_hints = compact or None

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
        detect_elapsed = time.perf_counter() - t0

        _update(
            store,
            job_id,
            status=JobStatus.PROCESSING,
            stage="tracking",
            message="Refining segments",
            progress=60.0,
        )

        t0 = time.perf_counter()
        tracked_segments = track_player(
            video_path=str(trimmed_path),
            detection_payload=det_payload,
            frame_skip=frame_skip,
            resize_scale=resize_scale,
            prefer_deepsort=prefer_deepsort,
            tracking_progress_step=2,
            fps_override=None,
        )
        track_elapsed = time.perf_counter() - t0

        rescue_enabled = os.getenv("PP_ENABLE_RESCUE_PASS", "true").lower() in ("1", "true", "yes")
        if dev_disable_rescue:
            rescue_enabled = False
        if not tracked_segments and rescue_enabled:
            rescue_frame_skip = max(6, int(max(1, frame_skip) * 0.6))
            rescue_detect_every = max(1, int(max(1, detect_every_n_frames) * 0.5))
            rescue_resize_scale = min(0.72, max(0.60, float(resize_scale)))
            logger.info(
                "🛟 No segments on first pass, retrying with denser scan: "
                f"frame_skip={rescue_frame_skip}, detect_every={rescue_detect_every}, "
                f"resize={rescue_resize_scale:.2f}, windowing=off"
            )

            _update(
                store,
                job_id,
                status=JobStatus.PROCESSING,
                stage="detecting",
                message="Retrying detection with wider scan",
                progress=52.0,
            )
            t_rescue = time.perf_counter()
            det_payload = detect_player_in_video(
                video_path=str(trimmed_path),
                player_data=player_data,
                action=action,
                frame_skip=rescue_frame_skip,
                detect_every_n_frames=rescue_detect_every,
                resize_scale=rescue_resize_scale,
                yolo_model=yolo_model,
                color_hints=color_hints,
                team_mode=team_mode,
                enable_activity_windowing=False,
            )
            detect_elapsed += time.perf_counter() - t_rescue

            _update(
                store,
                job_id,
                status=JobStatus.PROCESSING,
                stage="tracking",
                message="Retrying segment tracking",
                progress=64.0,
            )
            t_rescue = time.perf_counter()
            tracked_segments = track_player(
                video_path=str(trimmed_path),
                detection_payload=det_payload,
                frame_skip=rescue_frame_skip,
                resize_scale=rescue_resize_scale,
                prefer_deepsort=prefer_deepsort,
                tracking_progress_step=2,
                fps_override=None,
            )
            track_elapsed += time.perf_counter() - t_rescue

        timings["detect_sec"] = round(detect_elapsed, 2)
        timings["track_sec"] = round(track_elapsed, 2)

        if not tracked_segments:
            raise RuntimeError("No player segments found. Try adding Jersey/Helmet color hints or a tighter time range.")

        capture_flag = save_dataset or os.getenv("CAPTURE_HIGHLIGHT_DATASET", "false").lower() in ("1", "true", "yes")
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

        t0 = time.perf_counter()
        seeds = det_payload.get("seeds", []) or []
        max_segments_out = int(os.getenv("PP_MAX_SEGMENTS_OUT", "12"))
        max_total_out = float(os.getenv("PP_MAX_TOTAL_HIGHLIGHT_SEC", "130"))

        # ==================== DEV TEST MODE ====================
        if dev_test_mode:
            dev_max_segments = max(2, int(os.getenv("PP_DEV_TEST_MAX_SEGMENTS", "6")))
            dev_max_total = max(20.0, float(os.getenv("PP_DEV_TEST_MAX_TOTAL_HIGHLIGHT_SEC", "75")))
            max_segments_out = min(max_segments_out, dev_max_segments)
            max_total_out = min(max_total_out, dev_max_total)
            dev_test_overrides["max_segments_out"] = max_segments_out
            dev_test_overrides["max_total_highlight_sec"] = round(max_total_out, 1)
        # =======================================================

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

            if filtered_segments:
                filtered_segments = select_best_segments(
                    segments=filtered_segments,
                    seeds=seeds,
                    action=action,
                    duration=video_dur,
                    max_segments=max(6, min(max_segments_out, 12)),
                    max_total_duration=min(max_total_out, 120.0),
                )
            if not filtered_segments:
                filtered_segments = select_best_segments(
                    segments=tracked_segments,
                    seeds=seeds,
                    action=action,
                    duration=video_dur,
                    max_segments=max_segments_out,
                    max_total_duration=max_total_out,
                )
        else:
            filtered_segments = select_best_segments(
                segments=tracked_segments,
                seeds=seeds,
                action=action,
                duration=video_dur,
                max_segments=max_segments_out,
                max_total_duration=max_total_out,
            )

            if not filtered_segments:
                filtered_segments = tracked_segments[:50]
        timings["score_select_sec"] = round(time.perf_counter() - t0, 2)

        _update(
            store,
            job_id,
            status=JobStatus.COMPILING,
            stage="compiling",
            message="Compiling highlight",
            progress=90.0,
        )

        t0 = time.perf_counter()
        compile_mode = "local_file"
        highlight_path: str
        yt_section_compile = os.getenv("PP_ENABLE_YT_SECTION_COMPILE", "true").lower() in ("1", "true", "yes")
        youtube_url_for_compile = str(payload.get("youtube_url", "")).strip()
        if source == "youtube" and yt_section_compile and youtube_url_for_compile:
            try:
                highlight_path = _compile_youtube_sections(
                    youtube_url=youtube_url_for_compile,
                    job_id=job_id,
                    segments=filtered_segments,
                    source_offset_sec=float(start_sec or 0.0),
                    max_total_duration=max_total_out,
                    keep_downloads=keep_downloads,
                )
                compile_mode = "youtube_sections"
            except Exception as e:
                logger.warning(f"[section_compile] Falling back to local compile: {e}")
                highlight_path = compile_highlight(
                    str(trimmed_path),
                    filtered_segments,
                    show_progress=False,
                )
        else:
            highlight_path = compile_highlight(
                str(trimmed_path),
                filtered_segments,
                show_progress=False,
            )
        timings["compile_sec"] = round(time.perf_counter() - t0, 2)
        timings["total_sec"] = round(time.perf_counter() - pipeline_start, 2)

        output_url = f"/outputs/{Path(highlight_path).name}"
        scene_cut_count = int(det_payload.get("scene_cut_count", 0) or 0)
        replay_penalty_hits = int(det_payload.get("replay_penalty_hits", 0) or 0)
        replay_reject_count = int(det_payload.get("replay_reject_count", 0) or 0)
        identity_confirm_hits = int(det_payload.get("identity_confirm_hits", 0) or 0)
        selected_seed_stats = _selected_segment_seed_stats(filtered_segments, seeds)
        result = {
            "highlight_url": output_url,
            "segments": filtered_segments,
            "processing_stats": {
                "total_time": timings["total_sec"],
                "video_duration": round(video_dur, 1),
                "segments_found": len(filtered_segments),
                "compile_mode": compile_mode,
                "estimated_total_minutes": round(estimated_total_min, 1),
                "runtime_class": runtime_class,
                "overnight_recommended": bool(runtime_class == "overnight"),
                "scene_cuts": scene_cut_count,
                "identity_confirm_hits": identity_confirm_hits,
                "replay_penalties": replay_penalty_hits,
                "replay_rejects": replay_reject_count,
                "dev_test_mode": dev_test_mode,
                "dev_test_overrides": dev_test_overrides if dev_test_mode else {},
                **selected_seed_stats,
                **timings,
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
