import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple

# Ensure uploads directory exists
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def get_video_duration(video_path: str) -> float:
    """
    Get video duration using FFprobe.
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        duration = float(result.stdout.strip())
        return duration
        
    except Exception as e:
        print(f"Could not get video duration for {video_path}: {e}")
        return 0.0

def save_upload_file(upload_file, destination: Path) -> Path:
    """
    Save UploadFile (from FastAPI) to disk at destination.
    Returns the saved file path.
    """
    with destination.open("wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return destination

def merge_times_to_segments(times: List[float], gap: float, pre: float, post: float) -> List[Tuple[float, float]]:
    """
    Merge individual detection timestamps into [start, end] segments with padding.
    """
    if not times:
        return []
    times = sorted(times)
    segments = []
    start = times[0]
    prev = times[0]
    for t in times[1:]:
        if t - prev > gap:
            segments.append((max(0.0, start - pre), prev + post))
            start = t
        prev = t
    segments.append((max(0.0, start - pre), prev + post))
    return segments

def parse_timecode(tc: str) -> float:
    """
    Converts a timecode string (hh:mm:ss) to seconds as a float.
    Examples:
        "01:30:45" -> 5445.0
        "12:34" -> 754.0
        "45" -> 45.0
    """
    if not tc:
        return 0.0
    parts = [float(p) for p in tc.split(":")]
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    elif len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    elif len(parts) == 1:
        return parts[0]
    else:
        raise ValueError(f"Invalid timecode format: {tc}")

def clamp_segments(segments: List[Tuple[float, float]], duration: float) -> List[Tuple[float, float]]:
    """
    Clamp all [start, end] segments to video duration to avoid out-of-bounds timestamps.
    """
    out = []
    for s, e in segments:
        if e <= 0:
            continue
        out.append((max(0.0, s), min(duration, e)))
    return out

def limit_total_duration(
    segments: List[Tuple[float, float]],
    max_total: float
) -> List[Tuple[float, float]]:
    """
    Limit total duration of segments to at most max_total seconds.
    Keeps segments in chronological order and truncates the last one if needed.
    """
    if not segments or max_total <= 0:
        return []

    segments = sorted(segments, key=lambda x: x[0])
    out: List[Tuple[float, float]] = []
    accumulated = 0.0

    for s, e in segments:
        length = max(0.0, e - s)
        if length <= 0:
            continue

        if accumulated + length <= max_total:
            out.append((s, e))
            accumulated += length
        else:
            remaining = max_total - accumulated
            if remaining > 0:
                out.append((s, s + remaining))
                accumulated += remaining
            break  # we've hit the cap

    return out