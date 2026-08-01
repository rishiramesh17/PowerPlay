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


def _normalize_ocr_digits(text: str) -> str:
    """
    OCR often confuses similar glyphs (O/0, I/1, S/5, etc.).
    Normalize to a numeric token for jersey matching.
    """
    if text is None:
        return ""
    s = str(text).upper()
    replacements = {
        "O": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "L": "1",
        "|": "1",
        "S": "5",
        "B": "8",
        "G": "6",
        "Z": "2",
    }
    out = []
    for ch in s:
        if ch.isdigit():
            out.append(ch)
        elif ch in replacements:
            out.append(replacements[ch])
    return "".join(out)


def _ocr_matches_jersey(ocr_text: str, jersey: str) -> bool:
    jersey_digits = "".join(ch for ch in str(jersey) if ch.isdigit())
    if not jersey_digits:
        return False
    token = _normalize_ocr_digits(ocr_text)
    if not token:
        return False
    if jersey_digits in token:
        return True
    # Accept near-miss overlap only for longer jerseys to avoid false positives.
    if len(jersey_digits) >= 3:
        if jersey_digits[:-1] in token or jersey_digits[1:] in token:
            return True
    return False


def compute_color_histogram(image_bgr: np.ndarray, mask: Optional[np.ndarray] = None, bins: int = 16) -> np.ndarray:
    if image_bgr is None or image_bgr.size == 0:
        return np.zeros((bins * bins,), dtype=np.float32)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], mask, [bins, bins], [0, 180, 0, 256])
    hist = cv2.normalize(hist, hist).flatten()
    return hist


# Relative contribution of each body region to a player's appearance descriptor.
#
# Torso dominates because it carries the jersey, which is the strongest identity
# cue. Gloves are weighted lowest: they are small, frequently motion-blurred or
# out of frame, and they are cut FROM the "lower" region, so they already
# double-count that area.
#
# These replace an accidental weighting: the descriptor used to be folded
# together with a running `(combined + next) / 2`, which is not an average. With
# five regions that gave glove_right ~50% of the signature and the torso ~6%.
REGION_DESCRIPTOR_WEIGHTS: Dict[str, float] = {
    "helmet": 0.15,
    "torso": 0.45,
    "lower": 0.20,
    "glove_left": 0.10,
    "glove_right": 0.10,
}


def combine_region_histograms(regions: Dict[str, np.ndarray]) -> Optional[np.ndarray]:
    """
    Fold per-region colour histograms into a single normalised descriptor,
    weighted by REGION_DESCRIPTOR_WEIGHTS.

    Weights are renormalised over the regions actually present, so a partially
    visible player still yields a comparable descriptor. Returns None when no
    region has usable pixels.
    """
    accum: Optional[np.ndarray] = None
    total_weight = 0.0
    for name, region in regions.items():
        if region is None or region.size == 0:
            continue
        weight = REGION_DESCRIPTOR_WEIGHTS.get(name, 0.0)
        if weight <= 0.0:
            continue
        hist = compute_color_histogram(region)
        contribution = hist.astype(np.float32) * weight
        accum = contribution if accum is None else accum + contribution
        total_weight += weight

    if accum is None or total_weight <= 0.0:
        return None

    combined = accum / total_weight
    norm = float(np.linalg.norm(combined))
    if norm > 0.0:
        combined = combined / norm
    return combined.astype(np.float32)


def compute_scene_signature(frame_bgr: np.ndarray) -> np.ndarray:
    if frame_bgr is None or frame_bgr.size == 0:
        return np.zeros((64,), dtype=np.float32)
    small = cv2.resize(frame_bgr, (160, 90))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [8, 8], [0, 180, 0, 256])
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


def appearance_bank_similarity(
    hist: Optional[np.ndarray],
    bank: List[np.ndarray],
    top_k: int = 5,
) -> float:
    if hist is None or hist.size == 0 or not bank:
        return 0.0
    sims: List[float] = []
    for h in bank:
        if h is None or h.size == 0:
            continue
        sims.append(hist_similarity(hist, h))
    if not sims:
        return 0.0
    sims_sorted = sorted(sims, reverse=True)
    k = max(1, min(top_k, len(sims_sorted)))
    return float(np.mean(sims_sorted[:k]))


def scene_aware_bank_similarity(
    hist: Optional[np.ndarray],
    scene_bank: Dict[int, List[np.ndarray]],
    scene_id: int,
    top_k: int = 3,
    neighbor_span: int = 1,
) -> float:
    if hist is None or hist.size == 0 or not scene_bank:
        return 0.0
    local_best = 0.0
    global_best = 0.0
    for sid, bank in scene_bank.items():
        if not bank:
            continue
        sim = appearance_bank_similarity(hist, bank, top_k=top_k)
        global_best = max(global_best, sim)
        if abs(int(sid) - int(scene_id)) <= max(0, int(neighbor_span)):
            local_best = max(local_best, sim)
    return max(local_best, 0.85 * global_best)


def bbox_iou(box_a: Tuple[int, int, int, int], box_b: Tuple[int, int, int, int]) -> float:
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


def bbox_center_dist_norm(
    box_a: Tuple[int, int, int, int],
    box_b: Tuple[int, int, int, int],
    frame_w: int,
    frame_h: int,
) -> float:
    acx = 0.5 * (box_a[0] + box_a[2])
    acy = 0.5 * (box_a[1] + box_a[3])
    bcx = 0.5 * (box_b[0] + box_b[2])
    bcy = 0.5 * (box_b[1] + box_b[3])
    diag = max(1.0, math.sqrt(float(frame_w * frame_w + frame_h * frame_h)))
    return min(1.0, math.sqrt((bcx - acx) ** 2 + (bcy - acy) ** 2) / diag)


def merge_frame_windows(
    windows: List[Tuple[int, int]],
    gap_frames: int = 0,
) -> List[Tuple[int, int]]:
    if not windows:
        return []
    windows_sorted = sorted(windows, key=lambda x: x[0])
    merged: List[Tuple[int, int]] = []
    cur_s, cur_e = windows_sorted[0]
    for s, e in windows_sorted[1:]:
        if s <= cur_e + gap_frames:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    return merged


def propose_activity_windows(
    video_path: str,
    start_frame: int,
    end_frame: int,
    fps: float,
) -> List[Tuple[int, int]]:
    """
    Cheap pre-pass for long videos:
      - sample sparsely
      - detect movement in a central-lower ROI
      - return merged frame windows likely to contain action
    """
    total_frames = max(0, end_frame - start_frame)
    if fps <= 0 or total_frames <= 0:
        return [(start_frame, end_frame)]

    total_sec = total_frames / fps
    min_video_sec = float(os.getenv("PP_WINDOWING_MIN_VIDEO_SEC", "900"))
    if total_sec < min_video_sec:
        return [(start_frame, end_frame)]

    stride_sec = max(0.5, float(os.getenv("PP_WINDOW_STRIDE_SEC", "1.5")))
    stride_frames = max(1, int(fps * stride_sec))
    motion_threshold = float(os.getenv("PP_WINDOW_MOTION_THRESHOLD", "0.012"))
    diff_threshold = int(os.getenv("PP_WINDOW_DIFF_THRESHOLD", "18"))
    pre_sec = max(0.0, float(os.getenv("PP_WINDOW_PRE_SEC", "10")))
    post_sec = max(0.0, float(os.getenv("PP_WINDOW_POST_SEC", "16")))
    gap_sec = max(0.1, float(os.getenv("PP_WINDOW_GAP_SEC", "8")))
    min_window_sec = max(1.0, float(os.getenv("PP_WINDOW_MIN_SEC", "2")))
    merge_gap_sec = max(0.0, float(os.getenv("PP_WINDOW_MERGE_GAP_SEC", "2")))
    max_coverage = min(1.0, max(0.1, float(os.getenv("PP_WINDOW_MAX_COVERAGE", "0.92"))))

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning("[windowing] Could not open video for window proposal; using full scan.")
        return [(start_frame, end_frame)]

    active_times: List[float] = []
    prev_roi = None
    frame_idx = start_frame
    sampled = 0

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    while cap.isOpened() and frame_idx < end_frame:
        if sampled > 0 and stride_frames > 1:
            to_skip = min(stride_frames - 1, max(0, end_frame - frame_idx - 1))
            skipped = 0
            for _ in range(to_skip):
                if not cap.grab():
                    break
                skipped += 1
                frame_idx += 1
            if skipped < to_skip:
                break

        ret, frame = cap.read()
        if not ret or frame is None:
            break

        current_idx = frame_idx
        frame_idx += 1
        sampled += 1

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (0, 0), fx=0.25, fy=0.25)
        gray = cv2.GaussianBlur(gray, (9, 9), 0)

        h, w = gray.shape[:2]
        y1, y2 = int(h * 0.30), int(h * 0.95)
        x1, x2 = int(w * 0.15), int(w * 0.85)
        roi = gray[y1:y2, x1:x2]
        if roi is None or roi.size == 0:
            continue

        if prev_roi is not None and prev_roi.shape == roi.shape:
            diff = cv2.absdiff(prev_roi, roi)
            motion = float(np.mean(diff > diff_threshold))
            if motion >= motion_threshold:
                active_times.append(current_idx / fps)

        prev_roi = roi

    cap.release()

    if not active_times:
        logger.info("[windowing] No activity peaks found; using full scan.")
        return [(start_frame, end_frame)]

    windows_sec = merge_times_to_segments(
        sorted(active_times),
        gap=gap_sec,
        pre=pre_sec,
        post=post_sec,
    )

    windows_frames: List[Tuple[int, int]] = []
    min_window_frames = max(1, int(min_window_sec * fps))
    for s, e in windows_sec:
        ws = max(start_frame, int(s * fps))
        we = min(end_frame, int(e * fps))
        if we - ws >= min_window_frames:
            windows_frames.append((ws, we))

    if not windows_frames:
        logger.info("[windowing] Proposal produced empty windows after clamping; using full scan.")
        return [(start_frame, end_frame)]

    windows_frames = merge_frame_windows(windows_frames, gap_frames=max(0, int(merge_gap_sec * fps)))
    proposed_frames = sum((e - s) for s, e in windows_frames)
    coverage = proposed_frames / max(1, total_frames)

    if coverage >= max_coverage:
        logger.info(f"[windowing] Coverage {coverage*100:.1f}% too high; using full scan.")
        return [(start_frame, end_frame)]

    logger.info(
        f"[windowing] Proposed {len(windows_frames)} windows; "
        f"coverage {coverage*100:.1f}% of requested span."
    )
    return windows_frames


def _box_overlap_ratio(
    box_a: Tuple[int, int, int, int],
    box_b: Tuple[int, int, int, int],
) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter = inter_w * inter_h
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    return inter / float(area_a)


def estimate_pitch_roi(
    video_path: str,
    start_frame: int,
    end_frame: int,
    fps: float,
) -> Tuple[Optional[Tuple[float, float, float, float]], float]:
    """
    Estimate pitch-centric ROI in normalized coords (x1,y1,x2,y2).
    Returns (roi, confidence in [0,1]).
    """
    total_frames = max(0, end_frame - start_frame)
    if total_frames <= 0 or fps <= 0:
        return None, 0.0

    sample_target = max(18, int(os.getenv("PP_PITCH_ROI_MAX_SAMPLES", "72")))
    stride = max(1, total_frames // sample_target)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None, 0.0

    candidates: List[Tuple[float, float, float, float, float, float]] = []
    frame_idx = start_frame
    sampled = 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    while cap.isOpened() and frame_idx < end_frame and sampled < sample_target:
        if sampled > 0 and stride > 1:
            to_skip = min(stride - 1, max(0, end_frame - frame_idx - 1))
            for _ in range(to_skip):
                if not cap.grab():
                    break
                frame_idx += 1

        ret, frame = cap.read()
        if not ret or frame is None:
            break

        sampled += 1
        frame_idx += 1
        h0, w0 = frame.shape[:2]
        if h0 <= 0 or w0 <= 0:
            continue

        small_w = 512
        scale = small_w / max(1.0, float(w0))
        small_h = max(1, int(h0 * scale))
        small = cv2.resize(frame, (small_w, small_h))
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

        # Typical pitch strip sits in tan/brown range.
        tan_mask = cv2.inRange(hsv, (5, 20, 35), (35, 220, 255))
        # Remove strong green outfield.
        green_mask = cv2.inRange(hsv, (35, 35, 35), (95, 255, 255))
        mask = cv2.bitwise_and(tan_mask, cv2.bitwise_not(green_mask))

        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        best_score = -1.0
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if w <= 0 or h <= 0:
                continue
            area = float(w * h)
            area_n = area / max(1.0, float(small_w * small_h))
            if area_n < 0.01 or area_n > 0.45:
                continue

            cx_n = (x + 0.5 * w) / max(1.0, small_w)
            cy_n = (y + 0.5 * h) / max(1.0, small_h)
            center_term = max(0.0, 1.0 - abs(cx_n - 0.5) * 2.2)
            lower_term = 1.0 if cy_n >= 0.35 else 0.4
            shape_term = min(1.0, max(0.0, h / max(1.0, w)) / 2.5)
            score = 0.55 * center_term + 0.20 * lower_term + 0.15 * shape_term + 0.10 * min(1.0, area_n * 8.0)
            if score > best_score:
                best_score = score
                best = (x, y, w, h)

        if best is None:
            continue

        x, y, w, h = best
        x1_n = x / max(1.0, small_w)
        y1_n = y / max(1.0, small_h)
        x2_n = (x + w) / max(1.0, small_w)
        y2_n = (y + h) / max(1.0, small_h)
        cx_n = 0.5 * (x1_n + x2_n)
        cy_n = 0.5 * (y1_n + y2_n)
        candidates.append((x1_n, y1_n, x2_n, y2_n, cx_n, cy_n))

    cap.release()

    if len(candidates) < 3:
        return None, 0.0

    arr = np.array(candidates, dtype=np.float32)
    x1 = float(np.median(arr[:, 0]))
    y1 = float(np.median(arr[:, 1]))
    x2 = float(np.median(arr[:, 2]))
    y2 = float(np.median(arr[:, 3]))
    cx = arr[:, 4]
    cy = arr[:, 5]
    spread = float(np.mean(np.abs(cx - np.median(cx))) + np.mean(np.abs(cy - np.median(cy))))

    # Expand ROI to cover striker/bowler context around the strip.
    pad_x = 0.12
    pad_y_top = 0.08
    pad_y_bottom = 0.10
    roi = (
        max(0.0, x1 - pad_x),
        max(0.0, y1 - pad_y_top),
        min(1.0, x2 + pad_x),
        min(1.0, y2 + pad_y_bottom),
    )
    if roi[2] - roi[0] < 0.08 or roi[3] - roi[1] < 0.08:
        return None, 0.0

    conf = min(1.0, len(candidates) / 16.0) * max(0.0, min(1.0, 1.0 - spread * 2.8))
    return roi, float(conf)


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
    def __init__(
        self,
        time_s: float,
        bbox: Tuple[int, int, int, int],
        hist: np.ndarray,
        label: Optional[str],
        score: float = 0.0,
        ocr_match: bool = False,
        bank_sim: float = 0.0,
        hist_sim: float = 0.0,
        center_bias: float = 0.0,
        temporal_iou: float = 0.0,
        scene_id: int = 0,
        identity_strength: float = 0.0,
        replay_suspect: bool = False,
        post_cut_reacquire: bool = False,
    ):
        self.time_s = time_s
        self.bbox = bbox
        self.hist = hist
        self.label = label
        self.score = float(score)
        self.ocr_match = bool(ocr_match)
        self.bank_sim = float(bank_sim)
        self.hist_sim = float(hist_sim)
        self.center_bias = float(center_bias)
        self.temporal_iou = float(temporal_iou)
        self.scene_id = int(scene_id)
        self.identity_strength = float(identity_strength)
        self.replay_suspect = bool(replay_suspect)
        self.post_cut_reacquire = bool(post_cut_reacquire)


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
    enable_activity_windowing: Optional[bool] = None,
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
    appearance_bank: List[np.ndarray] = []
    scene_appearance_bank: Dict[int, List[np.ndarray]] = {}

    last_logged_percent = -1
    base_scan_stride = max(1, int(frame_skip)) * max(1, int(detect_every_n_frames))
    fps_stride_multiplier = 1.0
    if (
        os.getenv("PP_ENABLE_FPS_STRIDE_NORMALIZE", "true").lower() in ("1", "true", "yes")
        and fps > 36.0
    ):
        fps_stride_multiplier = min(3.0, fps / 30.0)
    effective_scan_stride = max(1, int(round(base_scan_stride * fps_stride_multiplier)))

    OCR_FRAME_INTERVAL = max(1, int(os.getenv("PP_OCR_FRAME_INTERVAL", "8")))
    OCR_REFRESH_INTERVAL_LOCKED = max(
        OCR_FRAME_INTERVAL,
        int(os.getenv("PP_OCR_REFRESH_LOCKED", "30")),
    )
    MAX_OCR_CANDIDATES_PER_FRAME = max(1, int(os.getenv("PP_OCR_TOPK_PER_FRAME", "2")))
    MAX_OCR_CALLS_TOTAL = max(20, int(os.getenv("PP_OCR_MAX_CALLS", "500")))
    APPEARANCE_BANK_SIZE = max(5, int(os.getenv("PP_APPEARANCE_BANK_SIZE", "36")))
    APPEARANCE_BANK_TOPK = max(1, int(os.getenv("PP_APPEARANCE_BANK_TOPK", "5")))
    IDENTITY_LOCK_MIN_HITS = max(1, int(os.getenv("PP_IDENTITY_LOCK_MIN_HITS", "2")))
    SCENE_BANK_SIZE = max(3, int(os.getenv("PP_SCENE_BANK_SIZE", "12")))
    SCENE_BANK_TOPK = max(1, int(os.getenv("PP_SCENE_BANK_TOPK", "3")))
    SCENE_BANK_NEIGHBOR_SPAN = max(0, int(os.getenv("PP_SCENE_BANK_NEIGHBOR_SPAN", "1")))
    SCENE_BANK_MAX_SCENES = max(4, int(os.getenv("PP_SCENE_BANK_MAX_SCENES", "28")))
    SCENE_BANK_WEIGHT = max(0.0, float(os.getenv("PP_SCENE_BANK_WEIGHT", "0.65")))
    LOCK_MISMATCH_FLOOR = max(0.0, min(1.0, float(os.getenv("PP_LOCK_MISMATCH_FLOOR", "0.42"))))
    LOCK_MISMATCH_PENALTY = max(0.0, float(os.getenv("PP_LOCK_MISMATCH_PENALTY", "0.55")))
    SCENE_REACQUIRE_SEC = max(0.0, float(os.getenv("PP_SCENE_REACQUIRE_SEC", "2.8")))
    SCENE_REACQUIRE_MIN_IDENTITY = max(
        0.0,
        min(1.0, float(os.getenv("PP_SCENE_REACQUIRE_MIN_IDENTITY", "0.32"))),
    )
    REPLAY_SCENE_WINDOW_SEC = max(4.0, float(os.getenv("PP_REPLAY_SCENE_WINDOW_SEC", "12")))
    REPLAY_CUT_THRESHOLD = max(2, int(os.getenv("PP_REPLAY_CUT_THRESHOLD", "3")))
    REPLAY_SUPPRESS_SEC = max(1.0, float(os.getenv("PP_REPLAY_SUPPRESS_SEC", "10")))
    REPLAY_MIN_IDENTITY = max(0.0, min(1.0, float(os.getenv("PP_REPLAY_MIN_IDENTITY", "0.44"))))
    REPLAY_SCORE_PENALTY = max(0.0, float(os.getenv("PP_REPLAY_SCORE_PENALTY", "0.65")))
    REFERENCE_HIST_EMA_ALPHA = min(
        0.8,
        max(0.05, float(os.getenv("PP_REFERENCE_HIST_EMA_ALPHA", "0.15"))),
    )
    ocr_calls_total = 0

    processed_steps = 0
    prev_seed_bbox: Optional[Tuple[int, int, int, int]] = None
    prev_seed_hist: Optional[np.ndarray] = None
    prev_scene_sig: Optional[np.ndarray] = None
    current_scene_id = 0
    last_scene_cut_frame_idx = -10**9
    replay_suspect_until_frame = -10**9
    scene_cut_history: List[int] = []
    last_accepted_frame_idx = start_frame
    scene_cut_count = 0
    replay_penalty_hits = 0
    replay_reject_count = 0
    identity_confirm_hits = 0
    scene_cut_min_similarity = max(
        0.0,
        min(1.0, float(os.getenv("PP_SCENE_CUT_MIN_SIMILARITY", "0.45"))),
    )
    full_scan_frames = max(1, end_frame - start_frame)

    scan_windows: List[Tuple[int, int]] = [(start_frame, end_frame)]
    if enable_activity_windowing is None:
        use_windowing = os.getenv("PP_ENABLE_ACTIVITY_WINDOWING", "true").lower() in ("1", "true", "yes")
    else:
        use_windowing = bool(enable_activity_windowing)
    if use_windowing:
        try:
            scan_windows = propose_activity_windows(video_path, start_frame, end_frame, fps)
        except Exception as e:
            logger.warning(f"[windowing] Proposal failed, falling back to full scan: {e}")
            scan_windows = [(start_frame, end_frame)]

    window_coverage = sum((e - s) for s, e in scan_windows) / float(full_scan_frames)
    window_ptr = 0

    pitch_roi_norm: Optional[Tuple[float, float, float, float]] = None
    pitch_roi_conf = 0.0
    use_pitch_roi = os.getenv("PP_ENABLE_PITCH_ROI", "true").lower() in ("1", "true", "yes")
    pitch_roi_min_video_sec = max(30.0, float(os.getenv("PP_PITCH_ROI_MIN_VIDEO_SEC", "120")))
    pitch_roi_score_weight = max(0.0, float(os.getenv("PP_PITCH_ROI_SCORE_WEIGHT", "0.75")))
    pitch_roi_gate_conf = max(0.0, min(1.0, float(os.getenv("PP_PITCH_ROI_GATE_CONF", "0.55"))))
    pitch_roi_gate_max_dist = max(0.05, min(1.5, float(os.getenv("PP_PITCH_ROI_GATE_MAX_DIST", "0.42"))))
    pitch_roi_gate_min_bias = max(0.0, min(1.0, float(os.getenv("PP_PITCH_ROI_GATE_MIN_BIAS", "0.08"))))

    if use_pitch_roi and duration >= pitch_roi_min_video_sec:
        try:
            pitch_roi_norm, pitch_roi_conf = estimate_pitch_roi(video_path, start_frame, end_frame, fps)
        except Exception as e:
            logger.warning(f"[pitch_roi] estimation failed: {e}")
            pitch_roi_norm, pitch_roi_conf = None, 0.0

    logger.info(
        f"Detect: video={video_path}, fps={fps:.2f}, frames={total_frames}, "
        f"scanning {start_frame}-{end_frame}, stride={effective_scan_stride} "
        f"(base={base_scan_stride}, fps_mul={fps_stride_multiplier:.2f}), "
        f"windows={len(scan_windows)}, coverage={window_coverage*100:.1f}%, "
        f"pitch_roi={'yes' if pitch_roi_norm else 'no'}({pitch_roi_conf:.2f}), "
        f"jersey={jersey}, hints={bool(color_hints)}"
    )
    scene_reacquire_frames = max(1, int(SCENE_REACQUIRE_SEC * fps))
    replay_scene_window_frames = max(1, int(REPLAY_SCENE_WINDOW_SEC * fps))
    replay_suppress_frames = max(1, int(REPLAY_SUPPRESS_SEC * fps))

    while cap.isOpened() and frame_idx < end_frame:
        while window_ptr < len(scan_windows) and frame_idx >= scan_windows[window_ptr][1]:
            window_ptr += 1
        if window_ptr >= len(scan_windows):
            break

        window_start, window_end = scan_windows[window_ptr]
        if frame_idx < window_start:
            jump_frames = window_start - frame_idx
            # Large jumps are cheaper with a direct seek.
            if jump_frames > max(10, effective_scan_stride * 2):
                cap.set(cv2.CAP_PROP_POS_FRAMES, window_start)
                frame_idx = window_start
            else:
                for _ in range(jump_frames):
                    if not cap.grab():
                        frame_idx = end_frame
                        break
                    frame_idx += 1
            continue

        if processed_steps > 0 and effective_scan_stride > 1:
            to_skip = min(
                effective_scan_stride - 1,
                max(0, window_end - frame_idx - 1),
                max(0, end_frame - frame_idx - 1),
            )
            skipped = 0
            for _ in range(to_skip):
                if not cap.grab():
                    break
                skipped += 1
                frame_idx += 1
            if skipped < to_skip:
                break

        ret, frame = cap.read()
        if not ret or frame is None:
            break

        current_frame_idx = frame_idx
        frame_idx += 1
        processed_steps += 1
        if current_frame_idx >= window_end:
            continue
        candidates = []

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

        # Camera-cut awareness: reset continuity on hard scene changes.
        try:
            current_scene_sig = compute_scene_signature(original_frame)
            if prev_scene_sig is not None:
                scene_sim = hist_similarity(prev_scene_sig, current_scene_sig)
                if scene_sim < scene_cut_min_similarity:
                    prev_seed_bbox = None
                    prev_seed_hist = None
                    scene_cut_count += 1
                    current_scene_id += 1
                    if identity_confirm_hits > 0:
                        identity_confirm_hits = max(0, identity_confirm_hits - 1)
                    last_scene_cut_frame_idx = current_frame_idx
                    scene_cut_history.append(current_frame_idx)
                    min_keep = current_frame_idx - replay_scene_window_frames
                    while scene_cut_history and scene_cut_history[0] < min_keep:
                        scene_cut_history.pop(0)
                    if len(scene_cut_history) >= REPLAY_CUT_THRESHOLD:
                        replay_suspect_until_frame = max(
                            replay_suspect_until_frame,
                            current_frame_idx + replay_suppress_frames,
                        )
            prev_scene_sig = current_scene_sig
        except Exception:
            pass

        try:
            # Class 0 = person on COCO models
            results = model(proc_frame, classes=[0], verbose=False)
        except Exception as e:
            logger.warning(f"YOLO inference failed at frame {current_frame_idx}: {e}")
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

            H, W = original_frame.shape[:2]
            pitch_roi_px = None
            pitch_cx = 0.5
            pitch_cy = 0.5
            if pitch_roi_norm is not None:
                prx1 = int(max(0.0, min(1.0, pitch_roi_norm[0])) * W)
                pry1 = int(max(0.0, min(1.0, pitch_roi_norm[1])) * H)
                prx2 = int(max(0.0, min(1.0, pitch_roi_norm[2])) * W)
                pry2 = int(max(0.0, min(1.0, pitch_roi_norm[3])) * H)
                if prx2 > prx1 and pry2 > pry1:
                    pitch_roi_px = (prx1, pry1, prx2, pry2)
                    pitch_cx = 0.5 * (prx1 + prx2)
                    pitch_cy = 0.5 * (pry1 + pry2)

            candidates = []
            ocr_candidate_indices = set()
            identity_locked = (
                ((reference_hist is not None) and (identity_confirm_hits >= IDENTITY_LOCK_MIN_HITS))
                or (len(appearance_bank) >= 3)
            )
            should_attempt_ocr_this_frame = (
                (not team_mode)
                and jersey
                and reader is not None
                and ocr_calls_total < MAX_OCR_CALLS_TOTAL
                and (
                    ((not identity_locked) and (processed_steps % OCR_FRAME_INTERVAL == 0))
                    or (
                        identity_locked
                        and (processed_steps % OCR_REFRESH_INTERVAL_LOCKED == 0)
                    )
                )
            )
            if should_attempt_ocr_this_frame and len(xyxy_arr) > 0:
                area_rank = []
                for i_box, box in enumerate(xyxy_arr):
                    if len(box) < 4:
                        continue
                    x1, y1, x2, y2 = map(float, box[:4])
                    bw = int(x2) - int(x1)
                    bh = int(y2) - int(y1)
                    if bw < 20 or bh < 40:
                        continue
                    area_rank.append((float(bw * bh), i_box))
                area_rank.sort(reverse=True, key=lambda x: x[0])
                ocr_candidate_indices = {idx for _, idx in area_rank[:MAX_OCR_CANDIDATES_PER_FRAME]}

            for i_box, box in enumerate(xyxy_arr):
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
                hist_combined = combine_region_histograms(regions)

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
                    pitch_bias = 0.0
                    if pitch_roi_px is not None:
                        roi_overlap = _box_overlap_ratio((x1_i, y1_i, x2_i, y2_i), pitch_roi_px)
                        diag = max(1.0, math.sqrt(float(W * W + H * H)))
                        cand_cx = 0.5 * (x1_i + x2_i)
                        cand_cy = 0.5 * (y1_i + y2_i)
                        dist = math.sqrt((cand_cx - pitch_cx) ** 2 + (cand_cy - pitch_cy) ** 2) / diag
                        pitch_prox = max(0.0, 1.0 - dist / 0.45)
                        pitch_bias = 0.6 * roi_overlap + 0.4 * pitch_prox

                    score = 0.0
                    score += 0.7 * center_bias
                    score += 0.6 * lower_bias
                    score += 0.4 * min(1.0, area_norm * 8.0)    # prefer bigger box but cap it
                    score += 0.8 * pitch_bias * pitch_roi_conf

                    candidates.append((score, area_norm, x1_i, y1_i, x2_i, y2_i, hist_combined))
                    continue

                # --- Signals ---
                # 1) OCR (bonus)
                ocr_match = False
                ocr_label = None
                should_run_ocr = (
                    should_attempt_ocr_this_frame
                    and i_box in ocr_candidate_indices
                    and ocr_calls_total < MAX_OCR_CALLS_TOTAL
                )
                if should_run_ocr:
                    try:
                        ocr_calls_total += 1
                        ocr_texts = reader.readtext(crop, detail=0)
                        for t in ocr_texts:
                            if _ocr_matches_jersey(str(t), str(jersey)):
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
                    if glove_hint:
                        glove_regions = []
                        if "glove_left" in regions and regions["glove_left"].size > 0:
                            glove_regions.append(regions["glove_left"])
                        if "glove_right" in regions and regions["glove_right"].size > 0:
                            glove_regions.append(regions["glove_right"])
                        for g in glove_regions:
                            mean = tuple(map(int, g.mean(axis=(0, 1)).tolist()))
                            scores.append(1.0 - color_distance_hsv(mean, glove_hint))
                    if pad_hint and "lower" in regions and regions["lower"].size > 0:
                        mean = tuple(map(int, regions["lower"].mean(axis=(0, 1)).tolist()))
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
                pitch_bias = 0.0
                pitch_dist = 1.0
                if pitch_roi_px is not None:
                    roi_overlap = _box_overlap_ratio((x1_i, y1_i, x2_i, y2_i), pitch_roi_px)
                    diag = max(1.0, math.sqrt(float(W * W + H * H)))
                    cand_cx = 0.5 * (x1_i + x2_i)
                    cand_cy = 0.5 * (y1_i + y2_i)
                    pitch_dist = math.sqrt((cand_cx - pitch_cx) ** 2 + (cand_cy - pitch_cy) ** 2) / diag
                    pitch_prox = max(0.0, 1.0 - pitch_dist / 0.45)
                    pitch_bias = 0.58 * roi_overlap + 0.42 * pitch_prox

                # When ROI is reliable and identity is not locked yet, ignore far-off candidates.
                if (
                    (pitch_roi_px is not None)
                    and (pitch_roi_conf >= pitch_roi_gate_conf)
                    and (not identity_locked)
                    and (pitch_dist > pitch_roi_gate_max_dist)
                    and (pitch_bias < pitch_roi_gate_min_bias)
                ):
                    continue

                # Reference hist lock-on
                if (ocr_match or color_confident or jersey_color_sim >= 0.6) and hist_combined is not None:
                    if reference_hist is None:
                        reference_hist = hist_combined.copy()

                # Hist similarity if we already locked on
                hist_sim = 0.0
                if reference_hist is not None and hist_combined is not None:
                    hist_sim = hist_similarity(reference_hist, hist_combined)

                # Appearance bank similarity (more robust across camera changes)
                bank_sim = appearance_bank_similarity(
                    hist_combined,
                    appearance_bank,
                    top_k=APPEARANCE_BANK_TOPK,
                )
                scene_bank_sim = scene_aware_bank_similarity(
                    hist_combined,
                    scene_appearance_bank,
                    current_scene_id,
                    top_k=SCENE_BANK_TOPK,
                    neighbor_span=SCENE_BANK_NEIGHBOR_SPAN,
                )
                identity_strength = max(float(hist_sim), float(bank_sim), float(scene_bank_sim))
                post_cut_reacquire = (
                    (current_frame_idx - last_scene_cut_frame_idx) >= 0
                    and (current_frame_idx - last_scene_cut_frame_idx) <= scene_reacquire_frames
                )
                replay_suspect_active = current_frame_idx <= replay_suspect_until_frame

                # 5) Temporal continuity to reduce identity switches
                curr_bbox = (x1_i, y1_i, x2_i, y2_i)
                temporal_iou = bbox_iou(prev_seed_bbox, curr_bbox) if prev_seed_bbox else 0.0
                prev_hist_sim = hist_similarity(prev_seed_hist, hist_combined) if (
                    prev_seed_hist is not None and hist_combined is not None
                ) else 0.0
                shift_norm = bbox_center_dist_norm(prev_seed_bbox, curr_bbox, W, H) if prev_seed_bbox else 0.0
                continuity_term = (
                    0.9 * float(temporal_iou)
                    + 0.6 * float(prev_hist_sim)
                    + 0.2 * float(max(0.0, 1.0 - shift_norm))
                )

                # Build a single numeric score for THIS bbox candidate
                area = float((x2_i - x1_i) * (y2_i - y1_i))

                score = 0.0
                score += 2.0 if ocr_match else 0.0
                score += 1.0 if color_confident else 0.0
                score += 0.8 * float(jersey_color_sim)
                score += 0.6 * float(hist_sim)
                score += 0.85 * float(bank_sim)
                score += SCENE_BANK_WEIGHT * float(scene_bank_sim)
                score += 0.3 * float(center_bias)
                score += 0.2 * float(area_norm)
                score += pitch_roi_score_weight * float(pitch_bias) * float(pitch_roi_conf)
                score += continuity_term
                if identity_locked:
                    lock_mismatch = max(0.0, LOCK_MISMATCH_FLOOR - identity_strength)
                    score -= LOCK_MISMATCH_PENALTY * lock_mismatch
                    if post_cut_reacquire and (identity_strength < SCENE_REACQUIRE_MIN_IDENTITY):
                        score -= 0.38 * (SCENE_REACQUIRE_MIN_IDENTITY - identity_strength)
                    if replay_suspect_active and (identity_strength < REPLAY_MIN_IDENTITY):
                        score -= REPLAY_SCORE_PENALTY * (REPLAY_MIN_IDENTITY - identity_strength)
                        replay_penalty_hits += 1

                candidates.append(
                    (
                        score,
                        area,
                        x1_i,
                        y1_i,
                        x2_i,
                        y2_i,
                        hist_combined,
                        ocr_label,
                        ocr_match,
                        temporal_iou,
                        prev_hist_sim,
                        shift_norm,
                        bank_sim,
                        color_confident,
                        jersey_color_sim,
                        hist_sim,
                        center_bias,
                        scene_bank_sim,
                        identity_strength,
                        post_cut_reacquire,
                        replay_suspect_active,
                    )
                )

            # ... END of per-person bbox loop ...

            # ---------------- SELECT BEST PER FRAME ----------------
            if candidates:
                candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
                best = candidates[0]

                # team_mode tuple: (score, area_norm, x1_i, y1_i, x2_i, y2_i, hist_combined)
                if team_mode:
                    score, _, x1_i, y1_i, x2_i, y2_i, hist_combined = best
                    ocr_label = None
                    accept = True
                    ocr_match = False
                    temporal_iou = 0.0
                    prev_hist_sim = 0.0
                    shift_norm = 0.0
                    bank_sim = 0.0
                    color_confident = False
                    jersey_color_sim = 0.0
                    hist_sim = 0.0
                    center_bias = 0.0
                    scene_bank_sim = 0.0
                    identity_strength = 0.0
                    post_cut_reacquire = False
                    replay_suspect_active = False
                else:
                    (
                        score,
                        area,
                        x1_i,
                        y1_i,
                        x2_i,
                        y2_i,
                        hist_combined,
                        ocr_label,
                        ocr_match,
                        temporal_iou,
                        prev_hist_sim,
                        shift_norm,
                        bank_sim,
                        color_confident,
                        jersey_color_sim,
                        hist_sim,
                        center_bias,
                        scene_bank_sim,
                        identity_strength,
                        post_cut_reacquire,
                        replay_suspect_active,
                    ) = best

                    # ✅ Acceptance rule:
                    min_accept = 0.45 if jersey_color_hint else 0.25
                    if reference_hist is not None or appearance_bank:
                        min_accept += 0.05
                    accept = (score >= min_accept)

                    # After lock-on, strongly prefer temporal continuity unless score is very strong.
                    if prev_seed_bbox is not None:
                        continuity_good = (
                            temporal_iou >= 0.05
                            or prev_hist_sim >= max(hist_similarity_threshold, 0.45)
                            or shift_norm <= 0.12
                            or bank_sim >= max(0.5, hist_similarity_threshold)
                            or scene_bank_sim >= max(0.48, hist_similarity_threshold)
                        )
                        if (not continuity_good) and (score < min_accept + 0.35):
                            accept = False

                    if identity_locked and (identity_strength < 0.24) and (not ocr_match) and (not color_confident):
                        accept = False
                    if (
                        identity_locked
                        and post_cut_reacquire
                        and (identity_strength < SCENE_REACQUIRE_MIN_IDENTITY)
                        and (not ocr_match)
                        and (not color_confident)
                    ):
                        accept = False
                    if (
                        identity_locked
                        and replay_suspect_active
                        and (identity_strength < REPLAY_MIN_IDENTITY)
                        and (not ocr_match)
                        and (not color_confident)
                    ):
                        accept = False
                        replay_reject_count += 1

                    # If no identity hints at all, accept biggest person (demo mode)
                    if (not jersey) and (not helmet_hint and not glove_hint and not pad_hint) and (not jersey_color_hint):
                        accept = True

                if not accept:
                    continue

                t_sec = current_frame_idx / fps if fps > 0 else 0.0
                detected_times.append(t_sec)

                if hist_combined is None:
                    hist_combined = np.zeros((256,), dtype=np.float32)

                # Lock and adapt reference histogram once we accept a candidate.
                if reference_hist is None:
                    reference_hist = hist_combined.copy()
                else:
                    reference_hist = (1.0 - REFERENCE_HIST_EMA_ALPHA) * reference_hist + (
                        REFERENCE_HIST_EMA_ALPHA * hist_combined
                    )
                    reference_hist = cv2.normalize(reference_hist, None).flatten()

                # Keep an appearance bank to stabilize identity across shot/camera changes.
                if (not team_mode):
                    bank_confident = (
                        ocr_match
                        or color_confident
                        or jersey_color_sim >= 0.62
                        or bank_sim >= 0.62
                        or (temporal_iou >= 0.08 and prev_hist_sim >= 0.5)
                    )
                    if bank_confident:
                        appearance_bank.append(hist_combined.copy())
                        if len(appearance_bank) > APPEARANCE_BANK_SIZE:
                            appearance_bank = appearance_bank[-APPEARANCE_BANK_SIZE:]

                        scene_bank = scene_appearance_bank.get(current_scene_id, [])
                        scene_bank.append(hist_combined.copy())
                        if len(scene_bank) > SCENE_BANK_SIZE:
                            scene_bank = scene_bank[-SCENE_BANK_SIZE:]
                        scene_appearance_bank[current_scene_id] = scene_bank

                        if len(scene_appearance_bank) > SCENE_BANK_MAX_SCENES:
                            for sid in sorted(scene_appearance_bank.keys())[:-SCENE_BANK_MAX_SCENES]:
                                scene_appearance_bank.pop(sid, None)

                if not team_mode:
                    lock_signal = (
                        ocr_match
                        or color_confident
                        or jersey_color_sim >= 0.62
                        or bank_sim >= 0.62
                        or scene_bank_sim >= 0.58
                        or identity_strength >= 0.62
                    )
                    if lock_signal:
                        identity_confirm_hits = min(IDENTITY_LOCK_MIN_HITS + 8, identity_confirm_hits + 1)
                    elif identity_confirm_hits > 0:
                        identity_confirm_hits = max(0, identity_confirm_hits - 1)

                seeds.append(
                    Seed(
                        t_sec,
                        (x1_i, y1_i, x2_i, y2_i),
                        hist_combined,
                        ocr_label,
                        score=score,
                        ocr_match=ocr_match,
                        bank_sim=bank_sim,
                        hist_sim=hist_sim,
                        center_bias=center_bias,
                        temporal_iou=temporal_iou,
                        scene_id=current_scene_id,
                        identity_strength=identity_strength,
                        replay_suspect=replay_suspect_active,
                        post_cut_reacquire=post_cut_reacquire,
                    )
                )
                prev_seed_bbox = (x1_i, y1_i, x2_i, y2_i)
                prev_seed_hist = hist_combined.copy()
                last_accepted_frame_idx = current_frame_idx

        # If we have no accepted detection for a while, relax continuity lock.
        if current_frame_idx - last_accepted_frame_idx > (effective_scan_stride * 8):
            prev_seed_bbox = None
            prev_seed_hist = None
            if identity_confirm_hits > 0:
                identity_confirm_hits = max(0, identity_confirm_hits - 1)

        # progress logging (percent steps)
        if end_frame > start_frame:
            percent_done = int(100 * (current_frame_idx - start_frame) / max(1, (end_frame - start_frame)))
            if percent_done >= last_logged_percent + max(1, detection_progress_step):
                logger.info(f"Detect progress: {percent_done}% frame {current_frame_idx} seeds={len(seeds)}")
                last_logged_percent = percent_done

    cap.release()
    logger.info(
        f"Detection finished. seeds={len(seeds)}, detections={len(detected_times)}, "
        f"ocr_calls={ocr_calls_total}, stride={effective_scan_stride}, scene_cuts={scene_cut_count}, "
        f"appearance_bank={len(appearance_bank)}, scene_banks={len(scene_appearance_bank)}, "
        f"identity_hits={identity_confirm_hits}, "
        f"pitch_roi_conf={pitch_roi_conf:.2f}, replay_penalties={replay_penalty_hits}, "
        f"replay_rejects={replay_reject_count}"
    )

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
        "pitch_roi": pitch_roi_norm,
        "pitch_roi_confidence": pitch_roi_conf,
        "scene_cut_count": scene_cut_count,
        "replay_penalty_hits": replay_penalty_hits,
        "replay_reject_count": replay_reject_count,
        "identity_confirm_hits": identity_confirm_hits,
    }

    return payload if return_seeds else initial_segments 
