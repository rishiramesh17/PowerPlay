# backend/processing/deepsort_track.py
import logging
from typing import Dict, Any, List, Tuple, Optional
from collections import defaultdict

import cv2
import numpy as np
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort

from .utils import merge_times_to_segments, clamp_segments, get_video_duration
from .detect_player import (
    DEFAULT_YOLO_MODEL,
    choose_device,
)

logger = logging.getLogger("processing.deepsort_track")
logging.basicConfig(level=logging.INFO)


def _iou(
    box_a: Tuple[int, int, int, int],
    box_b: Tuple[int, int, int, int]
) -> float:
    """
    IoU between two boxes in (x1, y1, x2, y2) format.
    """
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)

    denom = area_a + area_b - inter_area + 1e-6
    if denom <= 0:
        return 0.0
    return inter_area / denom


def track_player_with_deepsort(
    video_path: str,
    detection_payload: Dict[str, Any],
    action: str = "batting",
    yolo_model: str = DEFAULT_YOLO_MODEL,
    detection_frame_skip: int = 10,
    resize_scale: float = 0.6,
    iou_match_thresh: float = 0.4,
    time_match_window: float = 0.7,
) -> List[Tuple[float, float]]:
    """
    Use YOLO + DeepSORT to track all players, then choose the track_id
    that best matches our seeds and turn it into highlight segments.

    Returns: merged segments [(start_sec, end_sec), ...]
    """
    if detection_payload is None:
        logger.warning("[DeepSORT] No detection_payload provided")
        return []

    seeds = detection_payload.get("seeds", []) or []
    fps = detection_payload.get("fps") or 30.0
    total_frames = detection_payload.get("total_frames") or 0

    if not seeds:
        logger.warning("[DeepSORT] No seeds in detection_payload; cannot identify target player for DeepSORT.")
        return []

    # Step 1: open video & prepare YOLO + DeepSORT
    device = choose_device()
    logger.info(f"[DeepSORT] Using device: {device}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"[DeepSORT] Cannot open video: {video_path}")

    # Re-read FPS / total_frames from video as a safety fallback
    video_fps = cap.get(cv2.CAP_PROP_FPS) or fps or 30.0
    video_total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or total_frames or 0)
    duration = video_total_frames / video_fps if video_fps > 0 else 0.0

    logger.info(
        f"[DeepSORT] video_fps={video_fps:.2f}, frames={video_total_frames}, duration={duration:.1f}s"
    )

    # YOLO for detection
    try:
        yolo = YOLO(yolo_model)
        try:
            if device != "cpu" and hasattr(yolo, "to"):
                yolo.to(device)
        except Exception:
            pass
    except Exception as e:
        raise RuntimeError(f"[DeepSORT] Failed to load YOLO model '{yolo_model}': {e}")

    # DeepSORT tracker
    tracker = DeepSort(
        max_age=30,
        n_init=3,
        max_iou_distance=0.7,
        max_cosine_distance=0.3,
        nms_max_overlap=1.0,
        embedder="mobilenet",
        half=True,
        bgr=True,
    )

    # track_history: track_id -> list[(time_s, (x1,y1,x2,y2))]
    track_history: Dict[int, List[Tuple[float, Tuple[int, int, int, int]]]] = defaultdict(list)

    # Step 2: walk the video, run YOLO + DeepSORT on sampled frames
    frame_idx = 0
    last_logged_percent = -1

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        if frame_idx >= video_total_frames:
            break

        # Sparse sampling for speed
        if frame_idx % detection_frame_skip != 0:
            frame_idx += 1
            continue

        # Prepare frame
        original_frame = frame
        if resize_scale != 1.0:
            proc_frame = cv2.resize(
                original_frame,
                (int(original_frame.shape[1] * resize_scale),
                 int(original_frame.shape[0] * resize_scale))
            )
        else:
            proc_frame = original_frame

        # YOLO: detect persons only
        try:
            results = yolo(proc_frame, classes=[0])  # 0 = person in COCO
        except Exception as e:
            logger.warning(f"[DeepSORT] YOLO inference failed at frame {frame_idx}: {e}")
            results = []

        detections = []
        for r in results:
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue
            try:
                xyxy_arr = boxes.xyxy.cpu().numpy() if hasattr(boxes, "xyxy") else np.array([])
                conf_arr = boxes.conf.cpu().numpy() if hasattr(boxes, "conf") else None
            except Exception:
                xyxy_arr = np.array([])
                conf_arr = None

            if xyxy_arr is None or len(xyxy_arr) == 0:
                continue

            if resize_scale != 1.0:
                xyxy_arr = xyxy_arr / resize_scale

            for i_box, box in enumerate(xyxy_arr):
                if len(box) < 4:
                    continue
                x1, y1, x2, y2 = map(float, box[:4])
                x1_i, y1_i, x2_i, y2_i = int(x1), int(y1), int(x2), int(y2)
                if x2_i - x1_i < 20 or y2_i - y1_i < 40:
                    continue

                conf = float(conf_arr[i_box]) if conf_arr is not None else 0.5
                # deep_sort_realtime expects: ((x1,y1,x2,y2), confidence, class_name)
                detections.append(((x1_i, y1_i, x2_i, y2_i), conf, "person"))

        # Update DeepSORT with detections
        if detections:
            tracks = tracker.update_tracks(detections, frame=original_frame)
            for t in tracks:
                # Filter to confirmed, recently updated tracks
                if not t.is_confirmed() or t.time_since_update > 0:
                    continue

                track_id = t.track_id
                try:
                    bx1, by1, bx2, by2 = map(int, t.to_ltrb())
                except Exception:
                    # Fallback: if only ltwh available
                    lx, ty, w, h = t.to_ltwh()
                    bx1, by1 = int(lx), int(ty)
                    bx2, by2 = int(lx + w), int(ty + h)

                time_s = frame_idx / video_fps if video_fps > 0 else 0.0
                track_history[track_id].append((time_s, (bx1, by1, bx2, by2)))

        # progress logging
        if video_total_frames > 0:
            percent_done = int(100 * frame_idx / video_total_frames)
            if percent_done >= last_logged_percent + 5:
                logger.info(f"[DeepSORT] Progress: {percent_done}% frames processed")
                last_logged_percent = percent_done

        frame_idx += 1

    cap.release()
    logger.info(f"[DeepSORT] Tracking pass finished. Tracks found: {len(track_history)}")

    if not track_history:
        logger.warning("[DeepSORT] No tracks found; falling back to initial segments.")
        return detection_payload.get("initial_segments", []) or []

    # Step 3: choose the track_id that best matches our seeds
    track_votes: Dict[int, int] = defaultdict(int)

    for seed in seeds:
        seed_time = getattr(seed, "time_s", None)
        seed_bbox = getattr(seed, "bbox", None)
        if seed_time is None or seed_bbox is None:
            continue

        for tr_id, entries in track_history.items():
            for time_s, bbox in entries:
                if abs(time_s - seed_time) > time_match_window:
                    continue
                if _iou(seed_bbox, bbox) >= iou_match_thresh:
                    track_votes[tr_id] += 1
                    break  # only count once per track for this seed

    if not track_votes:
        logger.warning("[DeepSORT] Could not associate any track with seeds; falling back to initial segments.")
        return detection_payload.get("initial_segments", []) or []

    best_track_id = max(track_votes.items(), key=lambda x: x[1])[0]
    logger.info(f"[DeepSORT] Selected track_id={best_track_id} with {track_votes[best_track_id]} seed matches.")

    # Step 4: build time series for best track and convert to segments
    best_times = [time_s for (time_s, _) in track_history[best_track_id]]
    if not best_times:
        logger.warning("[DeepSORT] Selected track has no timestamps; falling back to initial segments.")
        return detection_payload.get("initial_segments", []) or []

    best_times_sorted = sorted(best_times)

    gap = 2.5
    pre = 2.0
    post = 12.0 if action == "bowling" else 4.0
    segments = merge_times_to_segments(best_times_sorted, gap=gap, pre=pre, post=post)

    # Clamp to video duration
    segments = clamp_segments(segments, duration)

    logger.info(f"[DeepSORT] Produced {len(segments)} segments from track_id={best_track_id}")
    return segments