# processing/track_player.py
import logging
from typing import List, Tuple, Dict, Any, Optional
from pathlib import Path
import cv2
import numpy as np

try:
    from .deepsort_track import track_player_with_deepsort
except Exception:
    track_player_with_deepsort = None

logger = logging.getLogger("processing.track_player")
logging.basicConfig(level=logging.INFO)


def _create_csrt_tracker():
    """
    Create a CSRT tracker in a way that supports both cv2.legacy and cv2 namespaces.
    """
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    elif hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    else:
        # fallback to KCF if CSRT unavailable
        if hasattr(cv2.legacy, "TrackerKCF_create"):
            return cv2.legacy.TrackerKCF_create()
        elif hasattr(cv2, "TrackerKCF_create"):
            return cv2.TrackerKCF_create()
        else:
            raise RuntimeError("No compatible OpenCV tracker constructors found (CSRT/KCF).")


def merge_segments(segments: List[Tuple[float, float]], gap_tolerance: float = 1.0) -> List[Tuple[float, float]]:
    if not segments:
        return []
    segs = sorted(segments, key=lambda x: x[0])
    merged = []
    cur_s, cur_e = segs[0]
    for s, e in segs[1:]:
        if s <= cur_e + gap_tolerance:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    return merged


def track_segment_with_csrt(
    video_path: str,
    seed: Any,
    fps: float,
    max_gap_seconds: float = 3.0,
    hist_sim_threshold: float = 0.35,
    frame_skip: int = 1,
    resize_scale: float = 1.0
) -> Tuple[float, float]:
    """
    Track forward from a seed using CSRT, with optional histogram re-id checks.
    seed: object with attributes time_s, bbox (x1,y1,x2,y2), hist
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Cannot open video for tracking")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    start_frame = max(0, int(seed.time_s * fps) - int(fps * 0.5))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    tracker = _create_csrt_tracker()
    x1, y1, x2, y2 = seed.bbox
    w = x2 - x1
    h = y2 - y1

    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        return (seed.time_s, seed.time_s + 0.5)

    # Optionally resize for speed
    proc_frame = frame
    if resize_scale != 1.0:
        proc_frame = cv2.resize(
            frame,
            (int(frame.shape[1] * resize_scale), int(frame.shape[0] * resize_scale))
        )
        # Scale the seed bbox to match resized frame
        x1, y1, x2, y2 = [int(v * resize_scale) for v in (x1, y1, x2, y2)]
        w = x2 - x1
        h = y2 - y1

    frame_h, frame_w = proc_frame.shape[:2]
    bx = max(0, min(x1, frame_w - 1))
    by = max(0, min(y1, frame_h - 1))
    bw = max(1, min(w, frame_w - bx))
    bh = max(1, min(h, frame_h - by))
    try:
        tracker.init(proc_frame, (bx, by, bw, bh))
    except Exception:
        cap.release()
        return (seed.time_s, seed.time_s + 0.5)

    last_good_frame_idx = start_frame
    end_frame_idx = int(seed.time_s * fps)
    current_frame_idx = start_frame
    lost_frames = 0
    max_lost = int(max_gap_seconds * fps)
    seed_hist = getattr(seed, "hist", None)

    while True:
        # 🔹 Skip frames for speed
        for _ in range(frame_skip - 1):
            cap.grab()

        ok, frame = cap.read()
        if not ok or frame is None:
            break
        current_frame_idx += frame_skip

        proc_frame = frame
        if resize_scale != 1.0:
            proc_frame = cv2.resize(
                frame,
                (int(frame.shape[1] * resize_scale), int(frame.shape[0] * resize_scale))
            )

        success, bbox = tracker.update(proc_frame)
        if success:
            lost_frames = 0
            x, y, w2, h2 = [int(v) for v in bbox]
            last_good_frame_idx = current_frame_idx
            end_frame_idx = current_frame_idx

            # 🔹 Rescale bbox back to original frame space
            if resize_scale != 1.0:
                x = int(x / resize_scale)
                y = int(y / resize_scale)
                w2 = int(w2 / resize_scale)
                h2 = int(h2 / resize_scale)

            # periodic re-id histogram check
            if seed_hist is not None and ((current_frame_idx - start_frame) % max(1, int(fps * 1.5)) == 0):
                px1, py1, px2, py2 = x, y, x + w2, y + h2
                sub = frame[py1:py2, px1:px2]
                if sub is not None and sub.size > 0:
                    try:
                        from .detect_player import compute_color_histogram, hist_similarity
                        cur_hist = compute_color_histogram(sub)
                        sim = hist_similarity(seed_hist, cur_hist)
                    except Exception:
                        sim = 1.0
                    if sim < hist_sim_threshold:
                        logger.debug(f"Tracker hist similarity low ({sim:.3f}) — stopping")
                        break
        else:
            lost_frames += 1
            if lost_frames > max_lost:
                break

    cap.release()
    start_time = max(0.0, (start_frame) / fps)
    end_time = min((end_frame_idx + 1) / fps, (total_frames / fps) if fps > 0 else (end_frame_idx / fps))
    return (start_time, end_time)


def track_player(
    video_path: str,
    detection_payload: Dict[str, Any],
    frame_skip: int = 8,
    resize_scale: float = 1.0,
    prefer_deepsort: bool = False,
    tracking_progress_step: int = 2,
    fps_override: Optional[float] = None,
) -> List[Tuple[float, float]]:
    """
    TEMPORARY SIMPLE MODE (CPU-friendly):
      - Ignore all tracking (DeepSORT / CSRT).
      - Just return the detection-based initial_segments.

    This removes the second heavy YOLO pass and long per-seed tracking.
    """
    if detection_payload is None:
        logger.warning("No detection payload provided")
        return []

    initial_segments = detection_payload.get("initial_segments", []) or []
    logger.info(
        f"[track_player] Tracking disabled; returning {len(initial_segments)} "
        f"detection-based segments."
    )
    return initial_segments