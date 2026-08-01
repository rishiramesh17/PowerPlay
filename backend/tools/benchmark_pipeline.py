#!/usr/bin/env python3
"""
Offline benchmark for PowerPlay player-highlight detection/tracking.

Manifest format (JSONL, one case per line):
{
  "video_path": "uploads/match.mp4",
  "player_data": {"jersey_number": "17", "jersey_color": "blue"},
  "action": "batting",
  "team_mode": false,
  "start_time": "00:10:00",
  "end_time": "00:40:00",
  "ground_truth_segments": [[612.2, 619.1], [700.0, 704.5]],
  "params": {
    "frame_skip": 12,
    "detect_every_n_frames": 2,
    "resize_scale": 0.6,
    "prefer_deepsort": false
  }
}
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Make backend package imports work regardless of cwd.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from processing.detect_player import detect_player_in_video, bbox_iou, hist_similarity  # noqa: E402
from processing.track_player import track_player  # noqa: E402
from processing.utils import get_video_duration  # noqa: E402


Segment = Tuple[float, float]


@dataclass
class CaseMetrics:
    index: int
    video_path: str
    elapsed_sec: float
    video_span_sec: float
    realtime_factor: float
    segments_pred: int
    segments_gt: int
    precision: Optional[float]
    recall: Optional[float]
    f1: Optional[float]
    matched_pred: Optional[int]
    matched_gt: Optional[int]
    jump_rate: Optional[float]
    jumps: Optional[int]
    seed_pairs: Optional[int]
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "video_path": self.video_path,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "video_span_sec": round(self.video_span_sec, 3),
            "realtime_factor": round(self.realtime_factor, 3),
            "segments_pred": self.segments_pred,
            "segments_gt": self.segments_gt,
            "precision": None if self.precision is None else round(self.precision, 4),
            "recall": None if self.recall is None else round(self.recall, 4),
            "f1": None if self.f1 is None else round(self.f1, 4),
            "matched_pred": self.matched_pred,
            "matched_gt": self.matched_gt,
            "jump_rate": None if self.jump_rate is None else round(self.jump_rate, 4),
            "jumps": self.jumps,
            "seed_pairs": self.seed_pairs,
            "error": self.error,
        }


def parse_timecode(tc: Optional[str]) -> Optional[float]:
    if tc is None:
        return None
    s = str(tc).strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        vals = [float(p) for p in parts]
    except Exception:
        return None
    if len(vals) == 3:
        return vals[0] * 3600 + vals[1] * 60 + vals[2]
    if len(vals) == 2:
        return vals[0] * 60 + vals[1]
    if len(vals) == 1:
        return vals[0]
    return None


def temporal_iou(a: Segment, b: Segment) -> float:
    a0, a1 = a
    b0, b1 = b
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    if inter <= 0:
        return 0.0
    union = max(a1, b1) - min(a0, b0)
    if union <= 0:
        return 0.0
    return inter / union


def sanitize_segments(raw: Sequence[Sequence[float]]) -> List[Segment]:
    out: List[Segment] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        try:
            s = float(item[0])
            e = float(item[1])
        except Exception:
            continue
        if e > s:
            out.append((s, e))
    out.sort(key=lambda x: x[0])
    return out


def match_segments(
    pred: List[Segment],
    gt: List[Segment],
    iou_thresh: float,
) -> Tuple[int, int]:
    if not pred or not gt:
        return 0, 0

    pairs: List[Tuple[float, int, int]] = []
    for i, p in enumerate(pred):
        for j, g in enumerate(gt):
            iou = temporal_iou(p, g)
            if iou >= iou_thresh:
                pairs.append((iou, i, j))

    pairs.sort(reverse=True, key=lambda x: x[0])
    used_pred = set()
    used_gt = set()
    for _, i, j in pairs:
        if i in used_pred or j in used_gt:
            continue
        used_pred.add(i)
        used_gt.add(j)

    return len(used_pred), len(used_gt)


def f1(precision: float, recall: float) -> float:
    denom = precision + recall
    if denom <= 0:
        return 0.0
    return 2.0 * precision * recall / denom


def track_jump_rate_proxy(
    seeds: Sequence[Any],
    max_dt_sec: float = 8.0,
    iou_cutoff: float = 0.02,
    hist_cutoff: float = 0.35,
) -> Tuple[float, int, int]:
    if len(seeds) < 2:
        return 0.0, 0, 0
    jumps = 0
    pairs = 0
    seeds_sorted = sorted(seeds, key=lambda s: getattr(s, "time_s", 0.0))
    for i in range(1, len(seeds_sorted)):
        a = seeds_sorted[i - 1]
        b = seeds_sorted[i]
        ta = float(getattr(a, "time_s", 0.0))
        tb = float(getattr(b, "time_s", 0.0))
        dt = tb - ta
        if dt <= 0 or dt > max_dt_sec:
            continue
        ba = getattr(a, "bbox", None)
        bb = getattr(b, "bbox", None)
        ha = getattr(a, "hist", None)
        hb = getattr(b, "hist", None)
        if ba is None or bb is None or ha is None or hb is None:
            continue
        pairs += 1
        iou = bbox_iou(ba, bb)
        sim = hist_similarity(ha, hb)
        if iou < iou_cutoff and sim < hist_cutoff:
            jumps += 1
    if pairs <= 0:
        return 0.0, 0, 0
    return jumps / pairs, jumps, pairs


def read_manifest(path: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            row = line.strip()
            if not row or row.startswith("#"):
                continue
            try:
                obj = json.loads(row)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON on line {idx}: {e}") from e
            if not isinstance(obj, dict):
                raise ValueError(f"Manifest line {idx} must be an object.")
            cases.append(obj)
    if not cases:
        raise ValueError("Manifest is empty.")
    return cases


def resolve_video_span(case: Dict[str, Any], video_path: str) -> Tuple[Optional[float], Optional[float], float]:
    start_sec = case.get("start_sec")
    end_sec = case.get("end_sec")
    if start_sec is None:
        start_sec = parse_timecode(case.get("start_time"))
    if end_sec is None:
        end_sec = parse_timecode(case.get("end_time"))

    duration = float(get_video_duration(video_path) or 0.0)
    s = float(start_sec) if start_sec is not None else 0.0
    e = float(end_sec) if end_sec is not None else duration
    if duration > 0:
        s = max(0.0, min(s, duration))
        e = max(0.0, min(e, duration))
    if e <= s:
        e = duration if duration > 0 else s
    span = max(0.0, e - s) if duration > 0 else max(0.0, e - s)
    return start_sec, end_sec, span


def run_case(index: int, case: Dict[str, Any], iou_thresh: float) -> CaseMetrics:
    video_path = str(case.get("video_path", "")).strip()
    if not video_path:
        return CaseMetrics(
            index=index,
            video_path="",
            elapsed_sec=0.0,
            video_span_sec=0.0,
            realtime_factor=0.0,
            segments_pred=0,
            segments_gt=0,
            precision=None,
            recall=None,
            f1=None,
            matched_pred=None,
            matched_gt=None,
            jump_rate=None,
            jumps=None,
            seed_pairs=None,
            error="Missing video_path",
        )

    player_data = case.get("player_data") or {}
    if not isinstance(player_data, dict):
        player_data = {}

    action = str(case.get("action", "batting"))
    team_mode = bool(case.get("team_mode", False))
    params = case.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    frame_skip = int(params.get("frame_skip", 12))
    detect_every = int(params.get("detect_every_n_frames", 2))
    resize_scale = float(params.get("resize_scale", 0.6))
    prefer_deepsort = bool(params.get("prefer_deepsort", False))
    yolo_model = str(params.get("yolo_model", "yolov8n.pt"))

    jersey_color = str(player_data.get("jersey_color", "")).strip() or None
    helmet_color = str(player_data.get("helmet_color", "")).strip() or None
    pad_color = str(player_data.get("pad_color", "")).strip() or None
    glove_color = str(player_data.get("glove_color", "")).strip() or None
    color_hints = None
    if not team_mode:
        compact = {
            "jersey": jersey_color,
            "helmet": helmet_color,
            "pad": pad_color,
            "glove": glove_color,
        }
        color_hints = {k: v for k, v in compact.items() if v} or None

    start_sec, end_sec, video_span = resolve_video_span(case, video_path)

    t0 = time.perf_counter()
    try:
        det_payload = detect_player_in_video(
            video_path=video_path,
            player_data=player_data,
            frame_skip=frame_skip,
            action=action,
            start_sec=start_sec,
            end_sec=end_sec,
            color_hints=color_hints,
            detect_every_n_frames=detect_every,
            yolo_model=yolo_model,
            team_mode=team_mode,
            resize_scale=resize_scale,
        )
        pred_segments = track_player(
            video_path=video_path,
            detection_payload=det_payload,
            frame_skip=frame_skip,
            resize_scale=resize_scale,
            prefer_deepsort=prefer_deepsort,
        )
        elapsed = time.perf_counter() - t0

        gt_segments = sanitize_segments(case.get("ground_truth_segments", []) or [])
        pred_segments = sanitize_segments(pred_segments)

        precision = recall = f1_score = None
        matched_pred = matched_gt = None
        if gt_segments:
            matched_pred, matched_gt = match_segments(pred_segments, gt_segments, iou_thresh=iou_thresh)
            precision = matched_pred / len(pred_segments) if pred_segments else 0.0
            recall = matched_gt / len(gt_segments) if gt_segments else 0.0
            f1_score = f1(precision, recall)

        jump_rate, jumps, seed_pairs = track_jump_rate_proxy(det_payload.get("seeds", []) or [])
        rtf = (video_span / elapsed) if elapsed > 0 else 0.0
        return CaseMetrics(
            index=index,
            video_path=video_path,
            elapsed_sec=elapsed,
            video_span_sec=video_span,
            realtime_factor=rtf,
            segments_pred=len(pred_segments),
            segments_gt=len(gt_segments),
            precision=precision,
            recall=recall,
            f1=f1_score,
            matched_pred=matched_pred,
            matched_gt=matched_gt,
            jump_rate=jump_rate,
            jumps=jumps,
            seed_pairs=seed_pairs,
        )
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return CaseMetrics(
            index=index,
            video_path=video_path,
            elapsed_sec=elapsed,
            video_span_sec=video_span,
            realtime_factor=0.0,
            segments_pred=0,
            segments_gt=0,
            precision=None,
            recall=None,
            f1=None,
            matched_pred=None,
            matched_gt=None,
            jump_rate=None,
            jumps=None,
            seed_pairs=None,
            error=str(e),
        )


def mean_or_none(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return float(statistics.mean(values))


def build_summary(cases: List[CaseMetrics]) -> Dict[str, Any]:
    ok = [c for c in cases if not c.error]
    with_gt = [c for c in ok if c.segments_gt > 0 and c.precision is not None and c.recall is not None]

    summary = {
        "cases_total": len(cases),
        "cases_success": len(ok),
        "cases_failed": len(cases) - len(ok),
        "avg_elapsed_sec": mean_or_none([c.elapsed_sec for c in ok]),
        "avg_realtime_factor": mean_or_none([c.realtime_factor for c in ok]),
        "avg_jump_rate_proxy": mean_or_none([c.jump_rate for c in ok if c.jump_rate is not None]),
        "gt_cases": len(with_gt),
        "avg_precision": mean_or_none([c.precision for c in with_gt if c.precision is not None]),
        "avg_recall": mean_or_none([c.recall for c in with_gt if c.recall is not None]),
        "avg_f1": mean_or_none([c.f1 for c in with_gt if c.f1 is not None]),
    }
    for k, v in list(summary.items()):
        if isinstance(v, float):
            summary[k] = round(v, 4)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark PowerPlay detection/tracking pipeline.")
    parser.add_argument("--manifest", type=Path, required=True, help="JSONL benchmark manifest path.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/reports/benchmark_results.json"),
        help="Output JSON report file.",
    )
    parser.add_argument(
        "--segment-iou-thresh",
        type=float,
        default=0.3,
        help="Temporal IoU threshold for predicted/ground-truth segment matching.",
    )
    args = parser.parse_args()

    cases_raw = read_manifest(args.manifest)
    cases_metrics: List[CaseMetrics] = []

    for idx, case in enumerate(cases_raw, start=1):
        metrics = run_case(idx, case, iou_thresh=float(args.segment_iou_thresh))
        cases_metrics.append(metrics)
        status = "OK" if not metrics.error else "ERR"
        print(
            f"[{status}] case={idx} video={metrics.video_path} "
            f"elapsed={metrics.elapsed_sec:.2f}s rtf={metrics.realtime_factor:.2f} "
            f"pred={metrics.segments_pred} gt={metrics.segments_gt}"
            + (f" err={metrics.error}" if metrics.error else "")
        )

    summary = build_summary(cases_metrics)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": str(args.manifest),
        "segment_iou_threshold": float(args.segment_iou_thresh),
        "summary": summary,
        "cases": [c.as_dict() for c in cases_metrics],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\nSummary:")
    print(json.dumps(summary, indent=2))
    print(f"\nSaved report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

