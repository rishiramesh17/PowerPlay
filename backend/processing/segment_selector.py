import math
import os
from typing import Any, Dict, List, Sequence, Tuple

from .utils import clamp_segments

Segment = Tuple[float, float]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _segment_iou(a: Segment, b: Segment) -> float:
    a0, a1 = a
    b0, b1 = b
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    if inter <= 0:
        return 0.0
    union = max(a1, b1) - min(a0, b0)
    if union <= 0:
        return 0.0
    return inter / union


def _segment_overlap_ratio(shorter: Segment, longer: Segment) -> float:
    s0, s1 = shorter
    l0, l1 = longer
    inter = max(0.0, min(s1, l1) - max(s0, l0))
    dur = max(1e-6, s1 - s0)
    return inter / dur


def _seed_time(seed: Any) -> float:
    return _safe_float(getattr(seed, "time_s", -1.0), -1.0)


def _seed_bbox(seed: Any) -> Tuple[float, float, float, float]:
    bbox = getattr(seed, "bbox", None)
    if not bbox or len(bbox) != 4:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        _safe_float(bbox[0], 0.0),
        _safe_float(bbox[1], 0.0),
        _safe_float(bbox[2], 0.0),
        _safe_float(bbox[3], 0.0),
    )


def _segment_seeds(seeds: Sequence[Any], start: float, end: float) -> List[Any]:
    out = [sd for sd in seeds if start <= _seed_time(sd) <= end]
    out.sort(key=lambda s: _seed_time(s))
    return out


def _segment_motion_proxy(seg_seeds: Sequence[Any]) -> float:
    if len(seg_seeds) < 2:
        return 0.0
    speeds: List[float] = []
    for i in range(1, len(seg_seeds)):
        a = seg_seeds[i - 1]
        b = seg_seeds[i]
        ta = _seed_time(a)
        tb = _seed_time(b)
        dt = tb - ta
        if dt <= 0 or dt > 3.5:
            continue
        ax1, ay1, ax2, ay2 = _seed_bbox(a)
        bx1, by1, bx2, by2 = _seed_bbox(b)
        acx = 0.5 * (ax1 + ax2)
        acy = 0.5 * (ay1 + ay2)
        bcx = 0.5 * (bx1 + bx2)
        bcy = 0.5 * (by1 + by2)
        ah = max(18.0, ay2 - ay1)
        dist_norm = math.sqrt((bcx - acx) ** 2 + (bcy - acy) ** 2) / ah
        speeds.append(dist_norm / dt)
    if not speeds:
        return 0.0
    return max(0.0, min(1.0, (sum(speeds) / len(speeds)) / 1.0))


def _segment_scene_stats(seg_seeds: Sequence[Any], duration: float) -> Tuple[float, float]:
    if not seg_seeds:
        return 0.0, 0.0
    scene_ids = [int(getattr(sd, "scene_id", 0)) for sd in seg_seeds]
    switches = 0
    for i in range(1, len(scene_ids)):
        if scene_ids[i] != scene_ids[i - 1]:
            switches += 1
    switch_rate = switches / max(0.5, duration)
    unique_ratio = len(set(scene_ids)) / max(1, len(scene_ids))
    return switch_rate, unique_ratio


def _segment_identity_stats(seg_seeds: Sequence[Any]) -> Tuple[float, float, float, float]:
    if not seg_seeds:
        return 0.0, 0.0, 0.0, 0.0

    id_vals = [_safe_float(getattr(sd, "identity_strength", 0.0)) for sd in seg_seeds]
    replay_flags = [1.0 if bool(getattr(sd, "replay_suspect", False)) else 0.0 for sd in seg_seeds]
    post_cut_flags = [1.0 if bool(getattr(sd, "post_cut_reacquire", False)) else 0.0 for sd in seg_seeds]

    # Team/any-player modes may not carry meaningful identity scores;
    # keep neutral behavior in that case.
    if (max(id_vals) <= 1e-6) and (sum(replay_flags) <= 1e-6) and (sum(post_cut_flags) <= 1e-6):
        return 0.5, 0.0, 0.0, 0.0

    low_id_thresh = max(
        0.0,
        min(1.0, _safe_float(os.getenv("PP_SEG_LOW_IDENTITY_THRESHOLD", "0.38"), 0.38)),
    )
    low_id_rate = sum(1.0 for v in id_vals if v < low_id_thresh) / max(1.0, float(len(id_vals)))

    id_mean = sum(id_vals) / max(1, len(id_vals))
    replay_rate = sum(replay_flags) / max(1, len(replay_flags))
    post_cut_rate = sum(post_cut_flags) / max(1, len(post_cut_flags))
    return id_mean, replay_rate, post_cut_rate, low_id_rate


def _seed_peak_value(sd: Any) -> float:
    score_raw = _safe_float(getattr(sd, "score", 0.0))
    score_norm = 1.0 - math.exp(-max(0.0, score_raw) / 2.8)
    bank_sim = _safe_float(getattr(sd, "bank_sim", 0.0))
    hist_sim = _safe_float(getattr(sd, "hist_sim", 0.0))
    center = _safe_float(getattr(sd, "center_bias", 0.0))
    temporal = _safe_float(getattr(sd, "temporal_iou", 0.0))
    ocr = 1.0 if bool(getattr(sd, "ocr_match", False)) else 0.0
    value = 0.44 * score_norm + 0.18 * bank_sim + 0.12 * hist_sim + 0.10 * center + 0.08 * temporal + 0.08 * ocr
    return max(0.0, min(1.2, value))


def _detect_action_core(seg: Segment, seg_seeds: Sequence[Any], action: str) -> Tuple[float, float, float, float]:
    start, end = seg
    if not seg_seeds:
        mid = 0.5 * (start + end)
        return start, end, mid, 0.0

    values = [_seed_peak_value(sd) for sd in seg_seeds]
    peak_idx = max(range(len(values)), key=lambda i: values[i])
    peak_seed = seg_seeds[peak_idx]
    peak_t = _seed_time(peak_seed)
    peak_v = values[peak_idx]

    support_window = 3.8 if action == "bowling" else 2.6
    support_thresh = max(0.28, peak_v * 0.55)
    support_times: List[float] = []
    for sd, val in zip(seg_seeds, values):
        t = _seed_time(sd)
        if abs(t - peak_t) <= support_window and val >= support_thresh:
            support_times.append(t)

    if not support_times:
        support_times = [peak_t]

    core_start = max(start, min(support_times))
    core_end = min(end, max(support_times))
    if core_end < core_start:
        core_start, core_end = core_end, core_start
    return core_start, core_end, peak_t, peak_v


def _segment_action_energy(seg_seeds: Sequence[Any], action: str, duration: float) -> float:
    if not seg_seeds:
        return 0.0
    values = [_seed_peak_value(sd) for sd in seg_seeds]
    values.sort(reverse=True)
    top_n = min(4, len(values))
    peak_mean = sum(values[:top_n]) / max(1, top_n)
    motion = _segment_motion_proxy(seg_seeds)
    id_mean, replay_rate, _, _ = _segment_identity_stats(seg_seeds)
    density = min(1.0, len(seg_seeds) / max(2.0, duration / (1.8 if action == "bowling" else 1.5)))

    energy = 0.0
    energy += 0.50 * peak_mean
    energy += 0.22 * motion
    energy += 0.16 * density
    energy += 0.12 * id_mean
    energy -= 0.10 * replay_rate
    return max(0.0, min(1.2, energy))


def _segment_replay_likelihood(seg: Segment, seg_seeds: Sequence[Any], action: str) -> float:
    start, end = seg
    duration = max(0.01, end - start)
    if not seg_seeds:
        return 0.0

    density = min(1.0, len(seg_seeds) / max(2.0, duration / 1.7))
    motion = _segment_motion_proxy(seg_seeds)
    scene_switch_rate, scene_unique_ratio = _segment_scene_stats(seg_seeds, duration)
    id_mean, replay_rate, post_cut_rate, low_id_rate = _segment_identity_stats(seg_seeds)
    temporal_mean = sum(_safe_float(getattr(sd, "temporal_iou", 0.0)) for sd in seg_seeds) / max(1, len(seg_seeds))
    bank_mean = sum(_safe_float(getattr(sd, "bank_sim", 0.0)) for sd in seg_seeds) / max(1, len(seg_seeds))
    ocr_rate = sum(1.0 if bool(getattr(sd, "ocr_match", False)) else 0.0 for sd in seg_seeds) / max(1, len(seg_seeds))

    target_duration = 10.0 if action == "bowling" else 6.5
    long_tail = max(0.0, (duration - target_duration) / max(2.0, target_duration))

    replay = 0.0
    replay += 0.34 * min(1.0, scene_switch_rate / 0.6)
    replay += 0.18 * scene_unique_ratio
    replay += 0.16 * max(0.0, (0.55 - motion) / 0.55)
    replay += 0.14 * max(0.0, (0.42 - temporal_mean) / 0.42)
    replay += 0.10 * max(0.0, (0.45 - density) / 0.45)
    replay += 0.08 * min(1.0, long_tail)
    replay += 0.24 * replay_rate
    replay += 0.12 * post_cut_rate
    replay += 0.10 * low_id_rate
    replay -= 0.08 * bank_mean
    replay -= 0.06 * ocr_rate
    replay -= 0.10 * id_mean

    return max(0.0, min(1.0, replay))


def _score_segment(seg: Segment, seg_seeds: Sequence[Any], action: str) -> float:
    start, end = seg
    duration = max(0.01, end - start)
    if not seg_seeds:
        return max(0.01, 0.12 - 0.03 * max(0.0, duration - 10.0))

    seed_scores = [_safe_float(getattr(sd, "score", 0.0)) for sd in seg_seeds]
    ocr_hits = [1.0 if bool(getattr(sd, "ocr_match", False)) else 0.0 for sd in seg_seeds]
    bank_sims = [_safe_float(getattr(sd, "bank_sim", 0.0)) for sd in seg_seeds]
    hist_sims = [_safe_float(getattr(sd, "hist_sim", 0.0)) for sd in seg_seeds]
    center_biases = [_safe_float(getattr(sd, "center_bias", 0.0)) for sd in seg_seeds]
    temporal_ious = [_safe_float(getattr(sd, "temporal_iou", 0.0)) for sd in seg_seeds]
    id_strengths = [_safe_float(getattr(sd, "identity_strength", 0.0)) for sd in seg_seeds]
    replay_flags = [1.0 if bool(getattr(sd, "replay_suspect", False)) else 0.0 for sd in seg_seeds]

    mean_score_raw = sum(seed_scores) / max(1, len(seed_scores))
    score_norm = 1.0 - math.exp(-max(0.0, mean_score_raw) / 2.5)

    density = min(1.0, len(seg_seeds) / max(2.0, duration / 1.6))
    ocr_rate = sum(ocr_hits) / max(1, len(ocr_hits))
    bank_mean = sum(bank_sims) / max(1, len(bank_sims))
    hist_mean = sum(hist_sims) / max(1, len(hist_sims))
    center_mean = sum(center_biases) / max(1, len(center_biases))
    temporal_mean = sum(temporal_ious) / max(1, len(temporal_ious))
    id_mean = sum(id_strengths) / max(1, len(id_strengths))
    replay_rate = sum(replay_flags) / max(1, len(replay_flags))
    motion = _segment_motion_proxy(seg_seeds)

    target_duration = 12.0 if action == "bowling" else 7.0
    duration_penalty = min(1.0, abs(duration - target_duration) / max(2.0, target_duration))

    quality = 0.0
    quality += 0.30 * score_norm
    quality += 0.17 * density
    quality += 0.15 * bank_mean
    quality += 0.11 * hist_mean
    quality += 0.09 * ocr_rate
    quality += 0.06 * center_mean
    quality += 0.06 * temporal_mean
    quality += 0.08 * id_mean
    quality += 0.06 * motion
    quality -= 0.08 * replay_rate
    quality -= 0.12 * duration_penalty

    return max(0.0, quality)


def _refine_segment_boundaries(
    seg: Segment,
    seg_seeds: Sequence[Any],
    action: str,
    duration: float,
) -> Tuple[Segment, float, float]:
    start, end = seg
    if not seg_seeds:
        mid = 0.5 * (start + end)
        return (max(0.0, start), min(duration, end)), mid, 0.0

    core_start, core_end, core_time, core_strength = _detect_action_core(seg, seg_seeds, action)
    motion = _segment_motion_proxy(seg_seeds)

    pre = 2.4 if action == "bowling" else 1.1
    post = 5.8 if action == "bowling" else 3.0
    post += 1.2 * max(0.0, motion - 0.55)

    refined = (
        max(start, core_start - pre),
        min(end, core_end + post),
    )
    if refined[1] - refined[0] < 1.4:
        refined = (
            max(0.0, core_time - 0.9),
            min(duration, core_time + 0.9),
        )

    return (max(0.0, refined[0]), min(duration, refined[1])), core_time, core_strength


def select_best_segments(
    segments: Sequence[Segment],
    seeds: Sequence[Any],
    action: str,
    duration: float,
    max_segments: int = 12,
    max_total_duration: float = 130.0,
    overlap_reject_ratio: float = 0.7,
) -> List[Segment]:
    if not segments:
        return []

    clamped = clamp_segments(list(segments), duration)
    if not clamped:
        return []

    replay_thresh = max(0.0, min(1.0, _safe_float(os.getenv("PP_REPLAY_SUPPRESS_THRESHOLD", "0.63"), 0.63)))
    replay_override_score = max(0.0, min(1.5, _safe_float(os.getenv("PP_REPLAY_OVERRIDE_SCORE", "0.72"), 0.72)))
    replay_cluster_sec = max(8.0, _safe_float(os.getenv("PP_REPLAY_CLUSTER_SEC", "32"), 32))
    dedupe_iou = max(0.2, min(0.95, _safe_float(os.getenv("PP_SEGMENT_DEDUPE_IOU", "0.6"), 0.6)))
    replay_penalty_weight = max(0.0, min(1.0, _safe_float(os.getenv("PP_REPLAY_SCORE_WEIGHT", "0.38"), 0.38)))
    energy_bonus_weight = max(0.0, min(0.6, _safe_float(os.getenv("PP_SEG_ENERGY_BONUS_WEIGHT", "0.16"), 0.16)))
    min_action_energy = max(0.0, min(1.0, _safe_float(os.getenv("PP_SEG_MIN_ACTION_ENERGY", "0.20"), 0.20)))
    low_energy_reject = max(0.0, min(1.0, _safe_float(os.getenv("PP_SEG_LOW_ENERGY_REJECT", "0.12"), 0.12)))

    candidates: List[Dict[str, Any]] = []
    for seg in clamped:
        seg_seeds = _segment_seeds(seeds, seg[0], seg[1])
        refined, core_time, core_strength = _refine_segment_boundaries(seg, seg_seeds, action=action, duration=duration)
        if refined[1] - refined[0] <= 0.1:
            continue
        seg_duration = max(0.01, refined[1] - refined[0])
        action_energy = _segment_action_energy(seg_seeds, action=action, duration=seg_duration)
        base_score = _score_segment(refined, seg_seeds, action=action)
        replay_like = _segment_replay_likelihood(refined, seg_seeds, action=action)
        adjusted_score = max(0.0, base_score - replay_penalty_weight * replay_like + energy_bonus_weight * action_energy)
        candidates.append(
            {
                "segment": refined,
                "score": base_score,
                "adjusted_score": adjusted_score,
                "replay": replay_like,
                "core_time": core_time,
                "core_strength": core_strength,
                "action_energy": action_energy,
            }
        )

    if not candidates:
        return []

    candidates.sort(
        key=lambda x: (
            x["adjusted_score"],
            x["score"],
            x["action_energy"],
            x["core_strength"],
            x["segment"][1] - x["segment"][0],
        ),
        reverse=True,
    )

    selected_meta: List[Dict[str, Any]] = []
    total = 0.0

    for cand in candidates:
        seg = cand["segment"]
        seg_len = seg[1] - seg[0]
        if seg_len <= 0:
            continue
        if len(selected_meta) >= max_segments:
            break

        if cand["action_energy"] < low_energy_reject and cand["score"] < (replay_override_score - 0.06):
            continue
        if cand["action_energy"] < min_action_energy and cand["adjusted_score"] < replay_override_score:
            continue

        if cand["replay"] >= replay_thresh and cand["score"] < replay_override_score:
            continue

        dup = False
        for ex in selected_meta:
            existing = ex["segment"]
            short = seg if (seg[1] - seg[0]) <= (existing[1] - existing[0]) else existing
            long = existing if short is seg else seg
            if _segment_overlap_ratio(short, long) >= overlap_reject_ratio:
                dup = True
                break
            if _segment_iou(seg, existing) >= dedupe_iou:
                dup = True
                break

            # Replay-like cluster suppression near the same broadcast moment.
            if abs(_safe_float(cand["core_time"]) - _safe_float(ex["core_time"])) <= replay_cluster_sec:
                if cand["replay"] >= ex["replay"] and cand["adjusted_score"] <= ex["adjusted_score"] + 0.06:
                    dup = True
                    break
                if cand["replay"] >= replay_thresh and cand["score"] <= ex["score"] + 0.02:
                    dup = True
                    break

        if dup:
            continue

        if total + seg_len > max_total_duration:
            remaining = max_total_duration - total
            if remaining <= 1.2:
                continue
            seg = (seg[0], min(seg[1], seg[0] + remaining))
            seg_len = seg[1] - seg[0]
            if seg_len <= 1.0:
                continue
            cand = dict(cand)
            cand["segment"] = seg

        selected_meta.append(cand)
        total += seg_len

    selected = [c["segment"] for c in selected_meta]
    selected.sort(key=lambda x: x[0])
    return selected
