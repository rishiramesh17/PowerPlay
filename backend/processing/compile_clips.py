import os
import ffmpeg
import logging
from moviepy import VideoFileClip, concatenate_videoclips
from pathlib import Path
from typing import List, Tuple
from .utils import get_video_duration, clamp_segments, limit_total_duration

logger = logging.getLogger(__name__)

'''
cd backend
source venv/bin/activate
uvicorn main:app --reload
http://localhost:8000/docs
'''

def compile_highlight(
    video_path: str,
    segments: List[Tuple[float, float]],
    output_dir: str = "outputs",
    show_progress: bool = False
) -> str:
    """
    Compile highlight by:
      1) Clamping segments to video duration.
      2) Limiting total highlight time to a maximum (e.g. 120s).
      3) Extracting each segment with ffmpeg (stream copy).
      4) Concatenating them with ffmpeg concat demuxer (no moviepy).
    """
    logger.info(f"🎬 Starting highlight compilation from {len(segments)} segments")

    # Clamp segments to video duration as a safety guard
    duration = get_video_duration(video_path)
    segments = clamp_segments(segments, duration)

    # 🔹 Enforce a global highlight length cap (adjust if you want)
    MAX_HIGHLIGHT_DURATION = 120.0  # seconds => ~2 minutes
    segments = limit_total_duration(segments, MAX_HIGHLIGHT_DURATION)

    if not segments:
        raise RuntimeError("No valid segments to compile after clamping and duration limit.")

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    base_name = Path(video_path).stem
    temp_dir = Path(output_dir) / f"{base_name}_clips"
    temp_dir.mkdir(parents=True, exist_ok=True)

    clip_paths = []
    total_duration = sum(end - start for start, end in segments)
    logger.info(f"⏱️ Total highlight duration (capped): {total_duration:.1f} seconds")

    # 1) Extract individual clips (stream copy)
    logger.info("✂️ Extracting individual clips with ffmpeg...")
    for i, (start, end) in enumerate(segments):
        duration = end - start
        logger.info(f"📹 Extracting clip {i+1}/{len(segments)}: {start:.1f}s-{end:.1f}s ({duration:.1f}s)")

        clip_path = temp_dir / f"clip_{i}.mp4"
        try:
            (
                ffmpeg
                .input(video_path, ss=start, to=end)
                .output(
                    str(clip_path),
                    c="copy",  # no re-encode
                    reset_timestamps=1,
                    loglevel="info" if show_progress else "error"
                )
                .overwrite_output()
                .run(quiet=not show_progress)
            )
            clip_paths.append(str(clip_path))
            logger.info(f"✅ Clip {i+1} extracted successfully")
        except Exception as e:
            logger.error(f"❌ Failed to extract clip {i+1}: {e}")
            continue

    logger.info(f"📦 Successfully extracted {len(clip_paths)} clips")

    if not clip_paths:
        raise RuntimeError("No clips to concatenate!")

    # 2) Concatenate via ffmpeg concat demuxer
    highlight_path = Path(output_dir) / f"{base_name}_highlight.mp4"
    concat_list_path = temp_dir / "clips_list.txt"

    # Build concat list file
    with open(concat_list_path, "w") as f:
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    logger.info("🎞️ Concatenating clips into final highlight with ffmpeg concat...")
    try:
        (
            ffmpeg
            .input(str(concat_list_path), format="concat", safe=0)
            .output(
                str(highlight_path),
                c="copy",  # still stream copy; very fast
                loglevel="info" if show_progress else "error"
            )
            .overwrite_output()
            .run(quiet=not show_progress)
        )
    except Exception as e:
        logger.error(f"❌ ffmpeg concat failed: {e}")
        raise

    final_size_mb = highlight_path.stat().st_size / (1024 * 1024)
    logger.info("✅ Highlight compilation completed!")
    logger.info(f"📊 Final file size: {final_size_mb:.1f} MB")
    logger.info(f"🎥 Saved as: {highlight_path.name}")

    return str(highlight_path)