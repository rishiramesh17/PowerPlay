# processing/verify_identity.py
"""
Build the "is this the right player?" confirmation step.

Detection produces seeds: timestamped bounding boxes it believes are the target.
Whether it found the *right* person is a question only the user can answer, and
answering it before we spend minutes compiling a reel is far cheaper than
answering it afterwards. This module turns seeds into a handful of cropped
thumbnails a human can judge in a few seconds.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import cv2

logger = logging.getLogger("processing.verify_identity")

#: Crops live under the output directory so the existing /outputs static mount
#: serves them without a second mount or an auth-bypassing file endpoint.
REVIEW_SUBDIR = "review"

#: Longest side of a saved crop. Big enough to recognise a face or kit, small
#: enough that six of them load instantly on a phone.
CROP_MAX_EDGE = 320

#: Fraction of the bbox added as context on each side. A tightly cropped torso
#: is genuinely hard to identify; a little background makes it obvious.
CROP_PAD_RATIO = 0.18


def select_review_candidates(
    seeds: Sequence[Any],
    duration: float,
    max_candidates: int = 6,
) -> List[Any]:
    """
    Pick a spread of seeds that represents the whole run, not just its best moment.

    Sampling the top-scoring seeds would show the user six frames of the same
    confident moment and hide exactly the drift we want them to catch. Instead we
    slice the video into equal time buckets and take the strongest seed from each,
    preferring seeds from scenes not already represented so a camera angle that
    latched onto the wrong person cannot hide behind a well-covered one.
    """
    usable = [s for s in seeds if getattr(s, "bbox", None)]
    if not usable or max_candidates <= 0:
        return []

    ordered = sorted(usable, key=lambda s: float(getattr(s, "time_s", 0.0) or 0.0))
    span = float(duration or 0.0)
    if span <= 0:
        span = float(getattr(ordered[-1], "time_s", 0.0) or 0.0) + 1.0

    bucket_count = min(max_candidates, len(ordered))
    bucket_width = span / bucket_count if bucket_count else span

    buckets: Dict[int, List[Any]] = {}
    for seed in ordered:
        t = float(getattr(seed, "time_s", 0.0) or 0.0)
        idx = min(bucket_count - 1, int(t / bucket_width)) if bucket_width > 0 else 0
        buckets.setdefault(idx, []).append(seed)

    chosen: List[Any] = []
    seen_scenes: set = set()
    for idx in range(bucket_count):
        members = buckets.get(idx)
        if not members:
            continue
        # Strongest seed from a scene we have not shown yet, else strongest overall.
        fresh = [m for m in members if int(getattr(m, "scene_id", 0) or 0) not in seen_scenes]
        pool = fresh or members
        best = max(pool, key=lambda s: float(getattr(s, "score", 0.0) or 0.0))
        chosen.append(best)
        seen_scenes.add(int(getattr(best, "scene_id", 0) or 0))

    # Empty buckets (a gap where the player was off screen) leave us short; refill
    # from the strongest unused seeds so the user still gets a full set to judge.
    if len(chosen) < min(max_candidates, len(ordered)):
        picked = {id(s) for s in chosen}
        spare = sorted(
            (s for s in ordered if id(s) not in picked),
            key=lambda s: float(getattr(s, "score", 0.0) or 0.0),
            reverse=True,
        )
        for seed in spare:
            if len(chosen) >= max_candidates:
                break
            chosen.append(seed)

    chosen.sort(key=lambda s: float(getattr(s, "time_s", 0.0) or 0.0))
    return chosen[:max_candidates]


def _crop_with_padding(frame, bbox) -> Optional[Any]:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in bbox)
    pad_x = int((x2 - x1) * CROP_PAD_RATIO)
    pad_y = int((y2 - y1) * CROP_PAD_RATIO)
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(w, x2 + pad_x)
    y2 = min(h, y2 + pad_y)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None

    crop = frame[y1:y2, x1:x2]
    ch, cw = crop.shape[:2]
    longest = max(ch, cw)
    if longest > CROP_MAX_EDGE:
        scale = CROP_MAX_EDGE / float(longest)
        crop = cv2.resize(crop, (max(1, int(cw * scale)), max(1, int(ch * scale))))
    return crop


def extract_candidate_crops(
    video_path: str,
    candidates: Sequence[Any],
    output_dir: Path,
    job_id: str,
) -> List[Dict[str, Any]]:
    """
    Write one JPEG per candidate and return their metadata.

    Candidates whose frame cannot be read are dropped rather than returned with a
    dead URL: a broken image in the review grid reads as "the system is broken",
    which is a worse answer than showing five crops instead of six.
    """
    if not candidates:
        return []

    crop_dir = Path(output_dir) / REVIEW_SUBDIR / job_id
    crop_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning(f"[verify_identity] Could not open {video_path} for review crops")
        return []

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    results: List[Dict[str, Any]] = []
    try:
        for idx, seed in enumerate(candidates):
            time_s = float(getattr(seed, "time_s", 0.0) or 0.0)
            cap.set(cv2.CAP_PROP_POS_MSEC, time_s * 1000.0)
            ok, frame = cap.read()
            if not ok and fps > 0:
                # Some containers ignore millisecond seeks; fall back to frames.
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(time_s * fps))
                ok, frame = cap.read()
            if not ok or frame is None:
                logger.warning(f"[verify_identity] No frame at {time_s:.2f}s; skipping candidate")
                continue

            crop = _crop_with_padding(frame, getattr(seed, "bbox"))
            if crop is None:
                continue

            candidate_id = f"c{idx}"
            file_path = crop_dir / f"{candidate_id}.jpg"
            if not cv2.imwrite(str(file_path), crop, [int(cv2.IMWRITE_JPEG_QUALITY), 85]):
                logger.warning(f"[verify_identity] Failed to write {file_path}")
                continue

            results.append(
                {
                    "id": candidate_id,
                    "time_s": round(time_s, 2),
                    "bbox": [int(v) for v in getattr(seed, "bbox")],
                    "score": round(float(getattr(seed, "score", 0.0) or 0.0), 4),
                    "identity_strength": round(
                        float(getattr(seed, "identity_strength", 0.0) or 0.0), 4
                    ),
                    "scene_id": int(getattr(seed, "scene_id", 0) or 0),
                    "ocr_match": bool(getattr(seed, "ocr_match", False)),
                    "url": f"/outputs/{REVIEW_SUBDIR}/{job_id}/{candidate_id}.jpg",
                }
            )
    finally:
        cap.release()

    return results


def build_identity_review(
    video_path: str,
    seeds: Sequence[Any],
    duration: float,
    job_id: str,
    output_dir: Path,
    max_candidates: int = 6,
    demo_mode: bool = False,
) -> Dict[str, Any]:
    """Produce the payload the review UI renders. Empty `candidates` means skip review."""
    chosen = select_review_candidates(seeds, duration=duration, max_candidates=max_candidates)
    candidates = extract_candidate_crops(
        video_path=video_path,
        candidates=chosen,
        output_dir=output_dir,
        job_id=job_id,
    )
    return {
        "candidates": candidates,
        "seed_count": len(seeds),
        "demo_mode": bool(demo_mode),
        "prompt": (
            "We tracked whoever was most prominent on screen — no jersey number "
            "or colour was given. Is this the player you meant?"
            if demo_mode
            else "Is this the player you meant?"
        ),
        "decision": None,
    }
