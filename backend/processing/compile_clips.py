import os
import shutil
import uuid
import ffmpeg
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from .utils import get_video_duration, clamp_segments, limit_total_duration

logger = logging.getLogger(__name__)

# Default ceiling on total highlight length. Kept in sync with the worker's
# PP_MAX_TOTAL_HIGHLIGHT_SEC so the two cannot silently disagree: this module
# used to hardcode 120s and re-cap after the worker had already applied the
# env value, which made any setting above 120 a no-op.
DEFAULT_MAX_HIGHLIGHT_DURATION = 130.0


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        logger.warning(f"Invalid float in {name}; falling back to {default}")
        return default


def _extract_clip(
    video_path: str,
    start: float,
    end: float,
    clip_path: Path,
    show_progress: bool,
) -> None:
    """
    Cut a single clip.

    Stream copy cannot cut mid-GOP, so it snaps the start back to the preceding
    keyframe - often seconds early, sometimes opening on a frozen frame. For
    3-7 second highlights that is the difference between catching the moment and
    missing it, so we re-encode by default and keep stream copy as an opt-in
    fast path via PP_COMPILE_STREAM_COPY.

    Placing -ss before the input still gives fast seeking; because we decode,
    ffmpeg lands on the exact requested frame rather than the keyframe.
    """
    loglevel = "info" if show_progress else "error"
    duration = end - start

    if os.getenv("PP_COMPILE_STREAM_COPY", "false").strip().lower() in ("1", "true", "yes"):
        (
            ffmpeg
            .input(video_path, ss=start, t=duration)
            .output(str(clip_path), c="copy", reset_timestamps=1, loglevel=loglevel)
            .overwrite_output()
            .run(quiet=not show_progress)
        )
        return

    preset = os.getenv("PP_COMPILE_PRESET", "veryfast")
    crf = int(_env_float("PP_COMPILE_CRF", 20))

    try:
        (
            ffmpeg
            .input(video_path, ss=start, t=duration)
            .output(
                str(clip_path),
                vcodec="libx264",
                preset=preset,
                crf=crf,
                acodec="aac",
                audio_bitrate="128k",
                pix_fmt="yuv420p",
                reset_timestamps=1,
                loglevel=loglevel,
            )
            .overwrite_output()
            .run(quiet=not show_progress)
        )
    except ffmpeg.Error:
        # Better an imprecise clip than a missing one.
        logger.warning(
            f"Re-encode failed for {start:.1f}s-{end:.1f}s; retrying with stream copy "
            "(cut will snap to the nearest keyframe)"
        )
        (
            ffmpeg
            .input(video_path, ss=start, t=duration)
            .output(str(clip_path), c="copy", reset_timestamps=1, loglevel=loglevel)
            .overwrite_output()
            .run(quiet=not show_progress)
        )


def compile_highlight(
    video_path: str,
    segments: List[Tuple[float, float]],
    output_dir: str = "outputs",
    show_progress: bool = False,
    max_total_duration: Optional[float] = None,
    output_name: Optional[str] = None,
) -> str:
    """
    Compile a highlight reel by:
      1) Clamping segments to the video duration.
      2) Limiting total highlight time.
      3) Cutting each segment with ffmpeg (frame-accurate by default).
      4) Concatenating with the ffmpeg concat demuxer.

    `max_total_duration` defaults to PP_MAX_TOTAL_HIGHLIGHT_SEC. `output_name`
    should be unique per job - pass the job id - otherwise two runs against the
    same source overwrite each other's output.
    """
    logger.info(f"🎬 Starting highlight compilation from {len(segments)} segments")

    if max_total_duration is None:
        max_total_duration = _env_float(
            "PP_MAX_TOTAL_HIGHLIGHT_SEC", DEFAULT_MAX_HIGHLIGHT_DURATION
        )

    video_duration = get_video_duration(video_path)
    segments = clamp_segments(segments, video_duration)
    if max_total_duration > 0:
        segments = limit_total_duration(segments, max_total_duration)

    if not segments:
        raise RuntimeError("No valid segments to compile after clamping and duration limit.")

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    base_name = Path(video_path).stem
    # Unique per invocation so concurrent jobs cannot collide on scratch space.
    run_id = uuid.uuid4().hex[:8]
    temp_dir = Path(output_dir) / f"{base_name}_{run_id}_clips"
    temp_dir.mkdir(parents=True, exist_ok=True)

    clip_paths: List[str] = []
    total_duration = sum(end - start for start, end in segments)
    logger.info(f"⏱️ Total highlight duration (capped): {total_duration:.1f} seconds")

    try:
        logger.info("✂️ Extracting individual clips with ffmpeg...")
        for i, (start, end) in enumerate(segments):
            clip_duration = end - start
            logger.info(
                f"📹 Extracting clip {i+1}/{len(segments)}: "
                f"{start:.1f}s-{end:.1f}s ({clip_duration:.1f}s)"
            )

            clip_path = temp_dir / f"clip_{i}.mp4"
            try:
                _extract_clip(video_path, start, end, clip_path, show_progress)
                clip_paths.append(str(clip_path))
                logger.info(f"✅ Clip {i+1} extracted successfully")
            except Exception as e:
                logger.error(f"❌ Failed to extract clip {i+1}: {e}")
                continue

        logger.info(f"📦 Successfully extracted {len(clip_paths)}/{len(segments)} clips")

        if not clip_paths:
            raise RuntimeError("No clips to concatenate!")

        if output_name:
            final_name = output_name if output_name.endswith(".mp4") else f"{output_name}.mp4"
        else:
            final_name = f"{base_name}_{run_id}_highlight.mp4"
        highlight_path = Path(output_dir) / final_name
        concat_list_path = temp_dir / "clips_list.txt"

        with open(concat_list_path, "w") as f:
            for p in clip_paths:
                f.write(f"file '{os.path.abspath(p)}'\n")

        logger.info("🎞️ Concatenating clips into final highlight with ffmpeg concat...")
        # Stream copy is safe here: every clip was written with identical codec
        # parameters above, which is exactly what the concat demuxer requires.
        (
            ffmpeg
            .input(str(concat_list_path), format="concat", safe=0)
            .output(
                str(highlight_path),
                c="copy",
                loglevel="info" if show_progress else "error",
            )
            .overwrite_output()
            .run(quiet=not show_progress)
        )

        final_size_mb = highlight_path.stat().st_size / (1024 * 1024)
        logger.info("✅ Highlight compilation completed!")
        logger.info(f"📊 Final file size: {final_size_mb:.1f} MB")
        logger.info(f"🎥 Saved as: {highlight_path.name}")

        return str(highlight_path)

    finally:
        # Scratch clips were previously left behind on every run, so outputs/
        # accumulated a copy of every segment of every job indefinitely.
        if os.getenv("PP_KEEP_COMPILE_TEMP", "false").strip().lower() not in ("1", "true", "yes"):
            shutil.rmtree(temp_dir, ignore_errors=True)
