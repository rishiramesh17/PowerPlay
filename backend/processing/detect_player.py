# processing/detect_player.py
import os
import math
import uuid
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any

import cv2
import numpy as np
import colorsys

# best-effort imports (will raise if missing at runtime)
from ultralytics import YOLO
import easyocr
import torch
from .utils import merge_times_to_segments

logger = logging.getLogger("processing.detect_player")
logging.basicConfig(level=logging.INFO)

# -------------------- Defaults -------------------- #
DEFAULT_YOLO_MODEL = "yolov8n.pt"
DEFAULT_DETECT_EVERY_N_FRAMES = 15   # higher => faster, less sensitive
DEFAULT_COLOR_MATCH_THRESHOLD = 0.35
DEFAULT_HIST_SIM_THRESHOLD = 0.40
DEFAULT_PROGRESS_STEP = 1  # percent step for progress logging


# -------------------- Utilities -------------------- #
COLOR_NAME_MAP = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "blue": (0, 0, 255),
    "green": (0, 255, 0),
    "yellow": (255, 255, 0),
    "orange": (255, 165, 0),
    "pink": (255, 192, 203),
    "purple": (128, 0, 128),
    "grey": (128, 128, 128),
    "gray": (128, 128, 128),
    "navy": (0, 0, 128),
    "maroon": (128, 0, 0),
    "brown": (165, 42, 42),
}


def parse_color_input(s: Optional[str]) -> Optional[tuple]:
    if not s:
        return None
    s = s.strip().lower()
    if s in COLOR_NAME_MAP:
        r, g, b = COLOR_NAME_MAP[s]
        # convert to BGR (OpenCV)
        return (b, g, r)
    if s.startswith("#") and len(s) in (7, 4):
        try:
            if len(s) == 7:
                r = int(s[1:3], 16)
                g = int(s[3:5], 16)
                b = int(s[5:7], 16)
            else:
                r = int(s[1] * 2, 16)
                g = int(s[2] * 2, 16)
                b = int(s[3] * 2, 16)
            return (b, g, r)
        except Exception:
            return None
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) == 3:
            try:
                r, g, b = map(int, parts)
                return (b, g, r)
            except Exception:
                return None
    return None


def bgr_to_hsv_tuple(bgr: tuple) -> tuple:
    b, g, r = bgr
    return colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)


def color_distance_hsv(c1_bgr: tuple, c2_bgr: tuple) -> float:
    h1, s1, v1 = bgr_to_hsv_tuple(c1_bgr)
    h2, s2, v2 = bgr_to_hsv_tuple(c2_bgr)
    dh = min(abs(h1 - h2), 1 - abs(h1 - h2)) * 2.0
    ds = abs(s1 - s2)
    dv = abs(v1 - v2)
    return math.sqrt(dh * dh + ds * ds + dv * dv)


def compute_color_histogram(image_bgr: np.ndarray, mask: Optional[np.ndarray] = None, bins: int = 16) -> np.ndarray:
    if image_bgr is None or image_bgr.size == 0:
        return np.zeros((bins * bins,), dtype=np.float32)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], mask, [bins, bins], [0, 180, 0, 256])
    hist = cv2.normalize(hist, hist).flatten()
    return hist


def hist_similarity(h1: np.ndarray, h2: np.ndarray) -> float:
    if h1 is None or h2 is None or h1.size == 0 or h2.size == 0:
        return 0.0
    try:
        d = cv2.compareHist(h1.astype("float32"), h2.astype("float32"), cv2.HISTCMP_BHATTACHARYYA)
        return max(0.0, 1.0 - d)
    except Exception:
        return 0.0


# -------------------- Merge helpers -------------------- #
def merge_detections_to_segments(
    detected_times: List[float],
    action: str = "batting"
) -> List[Tuple[float, float]]:
    """
    Wrapper around utils.merge_times_to_segments to keep behavior consistent.

    action:
      - "batting": shorter post padding
      - "bowling": longer post padding
    """
    if not detected_times:
        return []

    gap = 2.5
    pre = 2.0
    post = 12.0 if action == "bowling" else 4.0

    detected_times = sorted(detected_times)
    return merge_times_to_segments(detected_times, gap=gap, pre=pre, post=post)


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


# -------------------- Seed & regions -------------------- #
class Seed:
    def __init__(self, time_s: float, bbox: Tuple[int, int, int, int], hist: np.ndarray, label: Optional[str]):
        self.time_s = time_s
        self.bbox = bbox
        self.hist = hist
        self.label = label


def extract_regions_from_bbox(frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> Dict[str, np.ndarray]:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    x1 = max(0, x1); y1 = max(0, y1); x2 = min(w - 1, x2); y2 = min(h - 1, y2)
    person = frame[y1:y2, x1:x2].copy()
    ph, pw = person.shape[:2]
    regions: Dict[str, np.ndarray] = {}
    if ph <= 0 or pw <= 0:
        return regions
    top_h = max(1, int(ph * 0.15))
    regions["helmet"] = person[0:top_h, :]
    t1 = int(ph * 0.15)
    t2 = int(ph * 0.6)
    regions["torso"] = person[t1:t2, :]
    lower_start = int(ph * 0.6)
    regions["lower"] = person[lower_start:ph, :]
    lw = regions["lower"].shape[1]
    if lw > 0:
        regions["glove_left"] = regions["lower"][:, 0: max(1, lw // 3)]
        regions["glove_right"] = regions["lower"][:, max(0, 2 * lw // 3): lw]
    return regions


def build_segments_from_seeds(
    seeds: List[Seed],
    action: str = "batting",
    time_gap: float = 2.5,
    motion_threshold: float = 100.0,
    jitter_px: float = 3.0,
) -> List[Tuple[float, float]]:
    """
    Convert seeds into highlight segments by keeping only moments where the
    player's bbox center is moving fast enough (action burst), not idle time.
    """

    if len(seeds) < 3:
        return []

    seeds_sorted = sorted(seeds, key=lambda s: s.time_s)

    active_times: List[float] = []

    for i in range(1, len(seeds_sorted)):
        a = seeds_sorted[i - 1]
        b = seeds_sorted[i]
        dt = max(1e-3, b.time_s - a.time_s)

        ax1, ay1, ax2, ay2 = a.bbox
        bx1, by1, bx2, by2 = b.bbox

        acx = 0.5 * (ax1 + ax2)
        acy = 0.5 * (ay1 + ay2)
        bcx = 0.5 * (bx1 + bx2)
        bcy = 0.5 * (by1 + by2)

        dist = ((bcx - acx) ** 2 + (bcy - acy) ** 2) ** 0.5

        # ignore detector jitter
        if dist < jitter_px:
            continue

        speed = dist / dt
        if speed >= motion_threshold:
            active_times.append(b.time_s)

    if not active_times:
        return []

    pre = 1.5
    post = 10.0 if action == "bowling" else 4.0

    return merge_times_to_segments(sorted(active_times), gap=time_gap, pre=pre, post=post)


# -------------------- Device selection -------------------- #
def choose_device():
    try:
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"

# -------------------- Main detect function -------------------- #
def detect_player_in_video(
    video_path: str,
    player_data: Dict[str, Any],
    frame_skip: int = 10,  # slightly higher default for speed
    action: str = "batting",
    start_sec: Optional[float] = None,
    end_sec: Optional[float] = None,
    color_hints: Optional[Dict[str, str]] = None,
    detect_every_n_frames: int = DEFAULT_DETECT_EVERY_N_FRAMES,
    ocr_gpu: bool = False,
    yolo_model: str = DEFAULT_YOLO_MODEL,
    color_match_threshold: float = DEFAULT_COLOR_MATCH_THRESHOLD,
    hist_similarity_threshold: float = DEFAULT_HIST_SIM_THRESHOLD,
    return_seeds: bool = True,
    detection_progress_step: int = DEFAULT_PROGRESS_STEP,
    team_mode: bool = False,
    resize_scale: float = 0.6,   # downscale for speed
) -> Any:
    """
    Scan video and detect candidate frames for a player.

    Key changes vs previous version:
      - No cv2.VideoCapture.set(...) inside the loop (sequential read only).
      - Only run YOLO on a subset of frames (frame_skip).
      - Optional downscale via resize_scale to speed up YOLO.
      - Throttled OCR calls.
      - 'Reference' histogram for more tolerant matching after initial lock-on.

    Returns:
      - If return_seeds=True: dict with keys
          seeds: list[Seed]
          detected_times: list[float]
          initial_segments: list[(s,e)]
          fps, total_frames, duration, action
      - else: merged segments list.
    """
    device = choose_device()
    logger.info(f"Device selected for inference: {device}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total_frames / fps if fps > 0 else 0.0

    # Clamp start/end in frame indices
    start_frame = int((start_sec or 0.0) * fps)
    end_frame = int((end_sec * fps) if end_sec is not None else total_frames)

    start_frame = max(0, min(start_frame, total_frames))
    end_frame = max(0, min(end_frame, total_frames))

    if start_frame >= end_frame:
        logger.warning("start_sec/end_sec range invalid; using full video")
        start_frame = 0
        end_frame = total_frames

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frame_idx = start_frame

    logger.info(
        f"⚙️ Detection config: frame_skip={frame_skip}, "
        f"detect_every_n_frames={detect_every_n_frames}, resize_scale={resize_scale}"
    )

    jersey = str(player_data.get("jersey_number", "")).strip() or None
    if team_mode:
        jersey = None
    helmet_hint = parse_color_input(color_hints.get("helmet")) if color_hints else None
    glove_hint = parse_color_input(color_hints.get("glove")) if color_hints else None
    pad_hint = parse_color_input(color_hints.get("pad")) if color_hints else None
    jersey_hint = parse_color_input(color_hints.get("jersey")) if color_hints else None

    # Optional jersey color hint (torso/kit)
    jersey_color_hint = None
    if color_hints and color_hints.get("jersey"):
        jersey_color_hint = parse_color_input(color_hints.get("jersey"))

    # Load YOLO model
    try:
        model = YOLO(yolo_model)
        try:
            if device != "cpu" and hasattr(model, "to"):
                model.to(device)
        except Exception:
            pass
    except Exception as e:
        raise RuntimeError(f"Failed to load YOLO model '{yolo_model}': {e}")

    # OCR if jersey provided
    reader = None
    if jersey:
        try:
            reader = easyocr.Reader(["en"], gpu=(device != "cpu") and ocr_gpu)
        except Exception:
            try:
                reader = easyocr.Reader(["en"], gpu=False)
            except Exception:
                reader = None

    detected_times: List[float] = []
    seeds: List[Seed] = []

    # Reference hist to relax matching once we "lock on"
    reference_hist: Optional[np.ndarray] = None

    last_logged_percent = -1
    OCR_FRAME_INTERVAL = 5  # only OCR every N sampled frames

    logger.info(
        f"Detect: video={video_path}, fps={fps:.2f}, frames={total_frames}, "
        f"scanning {start_frame}-{end_frame}, jersey={jersey}, hints={bool(color_hints)}"
    )

    while cap.isOpened() and frame_idx < end_frame:
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        offset = frame_idx - start_frame
        candidates = []

        # Only process every frame_skip-th frame for detection
        if offset % frame_skip != 0:
            frame_idx += 1
            continue

        # Prepare frame for YOLO
        original_frame = frame
        if resize_scale != 1.0:
            proc_frame = cv2.resize(
                original_frame,
                (int(original_frame.shape[1] * resize_scale),
                 int(original_frame.shape[0] * resize_scale))
            )
        else:
            proc_frame = original_frame

        # Run YOLO periodically based on detect_every_n_frames (in units of sampled frames)
        if (offset // frame_skip) % max(1, detect_every_n_frames) == 0:
            try:
                # Class 0 = person on COCO models
                results = model(proc_frame, classes=[0])
            except Exception as e:
                logger.warning(f"YOLO inference failed at frame {frame_idx}: {e}")
                results = []
        else:
            results = []

        for r in results:
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue

            try:
                xyxy_arr = boxes.xyxy.cpu().numpy() if hasattr(boxes, "xyxy") else np.array([])
            except Exception:
                xyxy_arr = np.array([])

            # Rescale boxes back to original frame coords
            if resize_scale != 1.0 and len(xyxy_arr) > 0:
                xyxy_arr = xyxy_arr / resize_scale

            # ✅ Always define candidates here (fixes your UnboundLocalError)

            H, W = original_frame.shape[:2]

            candidates = []

            for box in xyxy_arr:
                if len(box) < 4:
                    continue

                x1, y1, x2, y2 = map(float, box[:4])
                x1_i, y1_i, x2_i, y2_i = int(x1), int(y1), int(x2), int(y2)

                # bbox sanity
                bw = x2_i - x1_i
                bh = y2_i - y1_i
                if bw < 20 or bh < 40:
                    continue

                crop = original_frame[y1_i:y2_i, x1_i:x2_i].copy()
                if crop is None or crop.size == 0:
                    continue

                regions = extract_regions_from_bbox(original_frame, (x1_i, y1_i, x2_i, y2_i))

                # Build combined hist
                hist_combined = None
                for _, region in regions.items():
                    if region is None or region.size == 0:
                        continue
                    hst = compute_color_histogram(region)
                    if hist_combined is None:
                        hist_combined = hst.copy()
                    else:
                        hist_combined = (hist_combined + hst) / 2.0

                # ---------------- TEAM MODE ----------------
                if team_mode:
                    frame_h0, frame_w0 = original_frame.shape[:2]
                    area = float((x2_i - x1_i) * (y2_i - y1_i))
                    area_norm = area / max(1.0, float(frame_w0 * frame_h0))

                    cx = 0.5 * (x1_i + x2_i) / max(1.0, frame_w0)
                    cy = 0.5 * (y1_i + y2_i) / max(1.0, frame_h0)

                    # Bias toward striker-ish region (roughly lower-middle of frame)
                    center_bias = 1.0 - abs(cx - 0.5)          # 1 best at center
                    lower_bias = 1.0 if cy >= 0.45 else 0.25    # prefer lower half

                    score = 0.0
                    score += 0.7 * center_bias
                    score += 0.6 * lower_bias
                    score += 0.4 * min(1.0, area_norm * 8.0)    # prefer bigger box but cap it

                    candidates.append((score, x1_i, y1_i, x2_i, y2_i, hist_combined))
                    continue

                # --- Signals ---
                # 1) OCR (bonus)
                ocr_match = False
                ocr_label = None
                should_run_ocr = (
                    jersey
                    and reader is not None
                    and crop is not None
                    and ((offset // frame_skip) % OCR_FRAME_INTERVAL == 0)
                )
                if should_run_ocr:
                    try:
                        ocr_texts = reader.readtext(crop, detail=0)
                        for t in ocr_texts:
                            if str(jersey) in str(t).replace(" ", ""):
                                ocr_match = True
                                ocr_label = str(t)
                                break
                    except Exception:
                        pass

                # 2) Color hints (helmet/glove/pad)
                color_score = 0.0
                color_confident = False
                if (helmet_hint or glove_hint or pad_hint):
                    scores = []
                    if helmet_hint and "helmet" in regions and regions["helmet"].size > 0:
                        mean = tuple(map(int, regions["helmet"].mean(axis=(0, 1)).tolist()))
                        scores.append(1.0 - color_distance_hsv(mean, helmet_hint))
                    if glove_hint and "glove_left" in regions and regions["glove_left"].size > 0:
                        mean = tuple(map(int, regions["glove_left"].mean(axis=(0, 1)).tolist()))
                        scores.append(1.0 - color_distance_hsv(mean, glove_hint))
                    if pad_hint and "torso" in regions and regions["torso"].size > 0:
                        mean = tuple(map(int, regions["torso"].mean(axis=(0, 1)).tolist()))
                        scores.append(1.0 - color_distance_hsv(mean, pad_hint))

                    if scores:
                        color_score = float(np.mean(scores))
                        color_confident = color_score >= (1.0 - color_match_threshold)

                # 3) Jersey color (torso)
                jersey_color_sim = 0.0
                if jersey_color_hint and "torso" in regions and regions["torso"].size > 0:
                    mean = tuple(map(int, regions["torso"].mean(axis=(0, 1)).tolist()))
                    jersey_color_sim = 1.0 - color_distance_hsv(mean, jersey_color_hint)

                # 4) Center bias + area
                cx = 0.5 * (x1_i + x2_i)
                cy = 0.5 * (y1_i + y2_i)
                dx = (cx - W / 2) / max(1.0, W)
                dy = (cy - H / 2) / max(1.0, H)
                center_bias = 1.0 - min(1.0, (dx * dx + dy * dy) ** 0.5)  # 1 best, 0 worst

                area = float(bw * bh)
                area_norm = area / float(W * H)

                # Reference hist lock-on
                if (ocr_match or color_confident or jersey_color_sim >= 0.6) and hist_combined is not None:
                    if reference_hist is None:
                        reference_hist = hist_combined.copy()

                # Hist similarity if we already locked on
                hist_sim = 0.0
                if reference_hist is not None and hist_combined is not None:
                    hist_sim = hist_similarity(reference_hist, hist_combined)

                # Build a single numeric score for THIS bbox candidate
                area = float((x2_i - x1_i) * (y2_i - y1_i))

                score = 0.0
                score += 2.0 if ocr_match else 0.0
                score += 1.0 if color_confident else 0.0
                score += 0.8 * float(jersey_color_sim)
                score += 0.6 * float(hist_sim)
                score += 0.3 * float(center_bias)
                score += 0.2 * float(area_norm)

                candidates.append((score, area, x1_i, y1_i, x2_i, y2_i, hist_combined, ocr_label, ocr_match))

            # ... END of per-person bbox loop ...

            # ---------------- SELECT BEST PER FRAME ----------------
            if candidates:
                candidates.sort(key=lambda t: t[0], reverse=True)
                best = candidates[0]

                # team_mode tuple: (score, x1_i, y1_i, x2_i, y2_i, hist_combined)
                if team_mode:
                    _, x1_i, y1_i, x2_i, y2_i, hist_combined = best
                    ocr_label = None
                    accept = True
                else:
                    score, area, x1_i, y1_i, x2_i, y2_i, hist_combined, ocr_label, ocr_match = best

                    # ✅ Acceptance rule:
                    min_accept = 0.45 if jersey_color_hint else 0.25
                    accept = (score >= min_accept)

                    # If no identity hints at all, accept biggest person (demo mode)
                    if (not jersey) and (not helmet_hint and not glove_hint and not pad_hint) and (not jersey_color_hint):
                        accept = True

                if not accept:
                    continue

                t_sec = frame_idx / fps if fps > 0 else 0.0
                detected_times.append(t_sec)

                if hist_combined is None:
                    hist_combined = np.zeros((256,), dtype=np.float32)

                # Lock reference histogram once we accept a candidate
                if reference_hist is None:
                    reference_hist = hist_combined.copy()

                seeds.append(Seed(t_sec, (x1_i, y1_i, x2_i, y2_i), hist_combined, ocr_label))
                
        # progress logging (percent steps)
        if end_frame > start_frame:
            percent_done = int(100 * (frame_idx - start_frame) / max(1, (end_frame - start_frame)))
            if percent_done >= last_logged_percent + max(1, detection_progress_step):
                logger.info(f"Detect progress: {percent_done}% frame {frame_idx} seeds={len(seeds)}")
                last_logged_percent = percent_done

        frame_idx += 1  # move to next frame (no cap.set inside loop)

    cap.release()
    logger.info(f"Detection finished. seeds={len(seeds)}, detections={len(detected_times)}")

    # Build motion-filtered segments from seeds:
    initial_segments = build_segments_from_seeds(
        seeds,
        action=action,
        motion_threshold=20.0,  # ✅ lower so it stops deleting all clusters
    )

    if not initial_segments and detected_times:
        initial_segments = merge_detections_to_segments(detected_times, action=action)

    payload = {
        "seeds": seeds,
        "detected_times": detected_times,
        "initial_segments": initial_segments,
        "fps": fps,
        "total_frames": total_frames,
        "duration": duration,
        "action": action,
    }

    return payload if return_seeds else initial_segments 
