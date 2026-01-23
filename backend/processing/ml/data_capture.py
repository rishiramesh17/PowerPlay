import json
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Any

def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)

def extract_clip_ffmpeg(video_path: str, start: float, end: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dur = max(0.01, end - start)

    # re-encode for consistent dataset clips (safer than -c copy for weird youtube streams)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(dur),
        "-vf", "scale=1280:-2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(out_path),
    ]
    _run(cmd)

def extract_frame_ffmpeg(video_path: str, ts: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(ts),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        str(out_path),
    ]
    _run(cmd)

def capture_run(
    video_path: str,
    segments: List[Tuple[float, float]],
    out_root: Path,
    meta: Dict[str, Any],
    thumbs_per_clip: int = 3
) -> Dict[str, Any]:
    """
    Saves:
      - clips/clip_XXXX.mp4
      - thumbs/clip_XXXX_YY.jpg
      - run.json (all metadata + segments)
    """
    out_root.mkdir(parents=True, exist_ok=True)
    clips_dir = out_root / "clips"
    thumbs_dir = out_root / "thumbs"
    clips_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for i, (s, e) in enumerate(segments):
        clip_name = f"clip_{i:04d}.mp4"
        clip_path = clips_dir / clip_name

        extract_clip_ffmpeg(video_path, s, e, clip_path)

        # thumbs at start/mid/end
        ts_list = []
        if thumbs_per_clip >= 1: ts_list.append(s + 0.2)
        if thumbs_per_clip >= 2: ts_list.append((s + e) / 2)
        if thumbs_per_clip >= 3: ts_list.append(max(s + 0.2, e - 0.2))

        thumb_files = []
        for j, ts in enumerate(ts_list):
            tpath = thumbs_dir / f"clip_{i:04d}_{j:02d}.jpg"
            extract_frame_ffmpeg(video_path, ts, tpath)
            thumb_files.append(str(tpath))

        saved.append({
            "clip": str(clip_path),
            "start": float(s),
            "end": float(e),
            "thumbs": thumb_files,
            "label": None,  # you fill this after labeling: "boundary" | "not_boundary" (later "four"/"six")
        })

    payload = {
        "video_path": video_path,
        "segments": saved,
        "meta": meta,
    }

    with (out_root / "run.json").open("w") as f:
        json.dump(payload, f, indent=2)

    return {
        "dataset_dir": str(out_root),
        "num_clips": len(saved),
        "run_json": str(out_root / "run.json"),
    }