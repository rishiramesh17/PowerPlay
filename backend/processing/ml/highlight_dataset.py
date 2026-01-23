import json
import uuid
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

DATA_ROOT = Path("data") / "highlight_dataset"
CLIPS_DIR = DATA_ROOT / "clips"
LABELS_PATH = DATA_ROOT / "labels.jsonl"

def _ensure_dirs():
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LABELS_PATH.exists():
        LABELS_PATH.write_text("", encoding="utf-8")

def _ffmpeg_extract_clip(video_path: str, start: float, end: float, out_path: Path) -> None:
    """
    Extract a clip and re-encode (more reliable than stream-copy for random timestamps).
    Keeps it small for training.
    """
    duration = max(0.0, end - start)
    if duration <= 0:
        raise ValueError("Invalid clip duration")

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", video_path,
        "-t", f"{duration:.3f}",
        "-vf", "scale=-2:360",      # keep it small (height 360)
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "28",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)

def capture_segments_to_dataset(
    video_path: str,
    segments: List[Tuple[float, float]],
    meta: Optional[Dict[str, Any]] = None,
    max_clips: int = 25,
    min_len: float = 2.5,
    max_len: float = 10.0,
) -> Dict[str, Any]:
    """
    Saves up to max_clips clips into data/highlight_dataset/clips
    and appends jsonl rows with label=null.
    """
    _ensure_dirs()
    meta = meta or {}

    saved = 0
    rows = []

    for (s, e) in segments[:max_clips]:
        length = max(0.0, e - s)
        if length < min_len:
            continue

        # cap clip length for training consistency
        if length > max_len:
            e = s + max_len

        clip_id = str(uuid.uuid4())[:8]
        out_path = CLIPS_DIR / f"{clip_id}.mp4"

        try:
            _ffmpeg_extract_clip(video_path, s, e, out_path)
        except Exception:
            continue

        row = {
            "clip_path": str(out_path).replace("\\", "/"),
            "label": None,  # you will fill this in later
            "start": round(float(s), 3),
            "end": round(float(e), 3),
            "meta": meta,
        }
        rows.append(row)
        saved += 1

    if rows:
        with LABELS_PATH.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    return {"saved": saved, "labels_file": str(LABELS_PATH), "clips_dir": str(CLIPS_DIR)}