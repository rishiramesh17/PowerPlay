# processing/track_player.py
import os
import logging
from typing import List, Tuple, Dict, Any, Optional

try:
    from .deepsort_track import track_player_with_deepsort
except Exception:
    track_player_with_deepsort = None

logger = logging.getLogger("processing.track_player")


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
    Refine detection segments with DeepSORT, when asked and when affordable.

    With `prefer_deepsort=False` (the default) this is a pass-through: the
    detector's segments are already the answer, and callers should not describe
    this step as if it changed them.
    """
    if detection_payload is None:
        logger.warning("No detection payload provided")
        return []

    initial_segments = detection_payload.get("initial_segments", []) or []
    if not prefer_deepsort:
        logger.info(
            f"[track_player] DeepSORT disabled; returning {len(initial_segments)} "
            f"detection-based segments unchanged."
        )
        return initial_segments

    if track_player_with_deepsort is None:
        logger.warning("[track_player] DeepSORT module unavailable; falling back to detection segments.")
        return initial_segments

    duration = float(detection_payload.get("duration") or 0.0)
    max_duration_for_deepsort = float(os.getenv("PP_DEEPSORT_MAX_DURATION_SEC", "5400"))
    if duration > max_duration_for_deepsort:
        logger.warning(
            "[track_player] DeepSORT skipped for long video "
            f"({duration:.1f}s > {max_duration_for_deepsort:.1f}s)."
        )
        return initial_segments

    try:
        logger.info("[track_player] Running DeepSORT refinement pass.")
        ds_segments = track_player_with_deepsort(
            video_path=video_path,
            detection_payload=detection_payload,
            action=detection_payload.get("action", "batting"),
            detection_frame_skip=max(6, int(frame_skip)),
            resize_scale=max(0.5, min(1.0, float(resize_scale))),
        )
        if ds_segments:
            logger.info(
                f"[track_player] DeepSORT refinement produced {len(ds_segments)} segments "
                f"(initial={len(initial_segments)})."
            )
            return ds_segments
    except Exception as e:
        logger.warning(f"[track_player] DeepSORT refinement failed; using initial segments. Error: {e}")

    return initial_segments
