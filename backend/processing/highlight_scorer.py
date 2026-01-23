
import os
import json
import base64
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

OpenAI = None
try:
    from openai import OpenAI  
except Exception:
    OpenAI = None

_client = None


def _get_openai_client():
    global _client
    if _client is None:
        if OpenAI is None:
            raise RuntimeError("openai package not installed. Install: pip install 'openai>=1.0.0'")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        _client = OpenAI(api_key=api_key)
    return _client


def _extract_frame(video_path: str, timestamp: float, out_path: Path) -> None:
    """
    Use ffmpeg to extract a single frame at `timestamp` seconds into `out_path`.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]
    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _encode_image_b64(image_path: Path) -> str:
    with image_path.open("rb") as f:
        data = f.read()
    return base64.b64encode(data).decode("utf-8")


def _score_single_frame_boundary(b64_jpeg: str) -> float:
    """
    Call OpenAI vision model on a single frame and return a float in [0,1]
    representing how likely this frame is part of a BOUNDARY (4 or 6).
    """
    client = _get_openai_client()
    model = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")

    completion = client.chat.completions.create(
        model=model,
        temperature=0.0,
        max_tokens=60,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a cricket video analyst. "
                    "You look at a *single frame* from a cricket match video and estimate "
                    "how likely it is that this frame comes from a BALL where the batter "
                    "hit a BOUNDARY (a four or six that reaches the rope). "
                    "You DO NOT care about dot balls, singles, or random non-play shots."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are given one frame from a cricket match video. "
                            "Based ONLY on this image, estimate how likely it is that this "
                            "frame shows or is part of a ball where the batter hits a boundary "
                            "(four or six that reaches the boundary rope). "
                            "Return STRICT JSON of the form:\n"
                            "{ \"boundary_chance\": 0.0 to 1.0, \"reason\": \"short explanation\" }"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_jpeg}"
                        },
                    },
                ],
            },
        ],
    )

    content = completion.choices[0].message.content or ""
    try:
        data = json.loads(content)
        score = float(data.get("boundary_chance", 0.0))
    except Exception:
        score = 0.0
        try:
            import re
            m = re.search(r"([01](?:\.\d+)?)", content)
            if m:
                score = float(m.group(1))
        except Exception:
            score = 0.0

    score = max(0.0, min(1.0, score))
    return score


def score_segments_with_ai(
    video_path: str,
    segments: List[Tuple[float, float]],
    max_segments_for_ai: int = 40,
) -> List[Tuple[float, float, float]]:
    """
    Given a list of [start, end] segments, sample 1 mid-frame per segment,
    score it with OpenAI vision, and return (start, end, score) list.
    """
    if not segments:
        return []

    video_p = Path(video_path)
    if not video_p.exists():
        raise FileNotFoundError(f"Video not found for scoring: {video_path}")

    segments_to_score = segments[:max_segments_for_ai]
    scored: List[Tuple[float, float, float]] = []

    with tempfile.TemporaryDirectory(prefix="pp_ai_frames_") as tmp_dir:
        tmp_dir_p = Path(tmp_dir)

        for idx, (start, end) in enumerate(segments_to_score):
            mid = (start + end) / 2.0
            if mid < 0:
                mid = 0.0

            frame_path = tmp_dir_p / f"seg_{idx:03d}.jpg"

            try:
                _extract_frame(str(video_p), mid, frame_path)
                b64 = _encode_image_b64(frame_path)
                score = _score_single_frame_boundary(b64)
            except Exception as e:
                print(f"[highlight_scorer] Failed to score segment {idx}: {e}")
                score = 0.0

            scored.append((start, end, score))

    if len(segments) > len(segments_to_score):
        for (start, end) in segments[len(segments_to_score) :]:
            scored.append((start, end, 0.0))

    return scored


def filter_segments_by_score(
    scored_segments: List[Tuple[float, float, float]],
    min_score: float = 0.55,
    max_segments: int = 10,
    max_total_duration: float = 120.0,
) -> List[Tuple[float, float]]:
    """
    Take (start, end, score) and:
      - drop segments below min_score
      - sort by score descending
      - keep up to max_segments
      - respect max_total_duration (seconds)
    Return plain (start, end) list.
    """
    if not scored_segments:
        return []

    filtered = [seg for seg in scored_segments if seg[2] >= min_score]
    if not filtered:
        return []

    filtered.sort(key=lambda s: (s[2], s[1] - s[0]), reverse=True)

    out: List[Tuple[float, float]] = []
    total = 0.0

    for (start, end, score) in filtered:
        duration = max(0.0, end - start)
        if duration <= 0:
            continue

        if len(out) >= max_segments:
            break

        if total + duration > max_total_duration:
            if not out:
                end = start + max_total_duration
                duration = max_total_duration
            else:
                break

        out.append((start, end))
        total += duration

    return out