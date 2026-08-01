# Pipeline Benchmarking

Use this to measure detection/tracking quality and speed with repeatable inputs.

## Script

- Path: `/Users/seyyon/Desktop/projects/powerplay/backend/tools/benchmark_pipeline.py`

## Manifest format (JSONL)

One JSON object per line:

```json
{"video_path":"uploads/match1.mp4","player_data":{"jersey_number":"17","jersey_color":"blue"},"action":"batting","start_time":"00:10:00","end_time":"00:40:00","ground_truth_segments":[[612.2,619.1],[700.0,704.5]],"params":{"frame_skip":12,"detect_every_n_frames":2,"resize_scale":0.6,"prefer_deepsort":false}}
```

Supported fields:

- `video_path` (required)
- `player_data` (optional, default `{}`)
- `action` (`batting`/`bowling`, optional)
- `team_mode` (optional, default `false`)
- `start_sec` / `end_sec` or `start_time` / `end_time` (optional)
- `ground_truth_segments` (optional): list of `[start_sec, end_sec]`
- `params` (optional): `frame_skip`, `detect_every_n_frames`, `resize_scale`, `prefer_deepsort`, `yolo_model`

## Run

From project root:

```bash
python3 backend/tools/benchmark_pipeline.py \
  --manifest backend/reports/sample_manifest.jsonl \
  --output backend/reports/benchmark_results.json \
  --segment-iou-thresh 0.3
```

## Output metrics

- `avg_realtime_factor`: processed video seconds / wall-clock second
- `avg_precision`, `avg_recall`, `avg_f1`: only for cases with `ground_truth_segments`
- `avg_jump_rate_proxy`: continuity break proxy from seed-to-seed bbox/hist jumps
- Per-case metrics include runtime, segment counts, matches, and errors.

## Notes

- If no ground truth is provided, only runtime and jump-rate proxy are computed.
- Use the same manifest over time to compare model/config changes objectively.

