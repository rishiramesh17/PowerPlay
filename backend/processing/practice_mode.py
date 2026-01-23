import cv2
import numpy as np
import subprocess
import tempfile
import logging
import shlex
import uuid
from pathlib import Path
from typing import List, Tuple, Optional

# logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# project util
from processing.utils import get_video_duration


def _ensure_fps(cap: cv2.VideoCapture) -> float:
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        logger.warning("Could not read FPS from video; defaulting to 30 FPS")
        return 30.0
    return fps


def detect_movement_frames_fast(video_path: str,
                                movement_threshold: float = 0.02,
                                min_movement_duration: float = 0.5,
                                padding_before: float = 1.0,
                                padding_after: float = 4.0) -> List[Tuple[float, float]]:
    logger.info(f"FAST movement detection: {video_path}")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        fps = _ensure_fps(cap)
        duration = (total_frames / fps) if fps > 0 else 0.0

        if duration > 1200:
            frame_skip = 10
        elif duration > 600:
            frame_skip = 8
        elif duration > 300:
            frame_skip = 5
        else:
            frame_skip = 3

        effective_frames = max(1, total_frames // frame_skip)
        segments: List[Tuple[float, float]] = []
        in_movement = False
        movement_start = 0.0
        consecutive_movement = 0
        consecutive_still = 0

        min_consecutive_movement = max(1, int(fps * min_movement_duration / frame_skip / 2))
        min_consecutive_still = max(1, int(fps * 0.3 / frame_skip))
        cricket_padding_after = min(padding_after, 2.5)

        frame_count = 0
        processed_frames = 0
        prev_frame = None
        progress_interval = max(1, effective_frames // 10)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_count % frame_skip != 0:
                frame_count += 1
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (0, 0), fx=0.25, fy=0.25)
            gray = cv2.GaussianBlur(gray, (15, 15), 0)

            if prev_frame is not None:
                frame_diff = cv2.absdiff(prev_frame, gray)
                movement_percentage = np.sum(frame_diff > 20) / frame_diff.size

                if movement_percentage > movement_threshold:
                    consecutive_movement += 1
                    consecutive_still = 0
                    if not in_movement:
                        movement_start = frame_count / fps
                        in_movement = True
                else:
                    consecutive_still += 1
                    consecutive_movement = 0
                    if in_movement and consecutive_still >= min_consecutive_still:
                        movement_end = frame_count / fps
                        seg_start = max(0, movement_start - padding_before)
                        seg_end = min(duration, movement_end + cricket_padding_after)
                        if seg_end - seg_start >= min_movement_duration:
                            segments.append((seg_start, seg_end))
                        in_movement = False
                        consecutive_movement = 0
                        consecutive_still = 0

            prev_frame = gray.copy()
            frame_count += 1
            processed_frames += 1

            if processed_frames % progress_interval == 0:
                progress = (processed_frames / effective_frames) * 100
                logger.info(f"Fast progress: {progress:.1f}% - {processed_frames}/{effective_frames} - found {len(segments)}")

            if processed_frames % 1000 == 0:
                import gc
                gc.collect()

        if in_movement:
            movement_end = frame_count / fps
            seg_start = max(0, movement_start - padding_before)
            seg_end = min(duration, movement_end + cricket_padding_after)
            if seg_end - seg_start >= min_movement_duration:
                segments.append((seg_start, seg_end))

        if segments:
            segments = merge_overlapping_segments_cricket(segments)
        return segments

    finally:
        cap.release()
        import gc
        gc.collect()


def detect_movement_frames(video_path: str,
                           movement_threshold: float = 0.02,
                           min_movement_duration: float = 0.5,
                           padding_before: float = 1.0,
                           padding_after: float = 4.0) -> List[Tuple[float, float]]:
    logger.info(f"Movement detection: {video_path}")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        fps = _ensure_fps(cap)
        duration = (total_frames / fps) if fps > 0 else 0.0

        frame_skip = 1
        if duration > 1200:
            frame_skip = 5
        elif duration > 600:
            frame_skip = 3
        elif duration > 300:
            frame_skip = 2

        effective_frames = max(1, total_frames // frame_skip)
        segments: List[Tuple[float, float]] = []
        in_movement = False
        movement_start = 0.0
        consecutive_movement = 0
        consecutive_still = 0
        min_consecutive_movement = max(1, int(fps * min_movement_duration / frame_skip))
        min_consecutive_still = max(1, int(fps * 0.5 / frame_skip))
        cricket_padding_after = min(padding_after, 3.0)

        frame_count = 0
        processed_frames = 0
        prev_frame = None
        progress_interval = max(1, effective_frames // 20)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_count % frame_skip != 0:
                frame_count += 1
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if prev_frame is not None:
                frame_diff = cv2.absdiff(prev_frame, gray)
                movement_percentage = np.sum(frame_diff > 25) / frame_diff.size

                if movement_percentage > movement_threshold:
                    consecutive_movement += 1
                    consecutive_still = 0
                    if not in_movement:
                        movement_start = frame_count / fps
                        in_movement = True
                else:
                    consecutive_still += 1
                    consecutive_movement = 0
                    if in_movement and consecutive_still >= min_consecutive_still:
                        movement_end = frame_count / fps
                        seg_start = max(0, movement_start - padding_before)
                        seg_end = min(duration, movement_end + cricket_padding_after)
                        if seg_end - seg_start >= min_movement_duration:
                            segments.append((seg_start, seg_end))
                        in_movement = False
                        consecutive_movement = 0
                        consecutive_still = 0

            prev_frame = gray.copy()
            frame_count += 1
            processed_frames += 1

            if processed_frames % progress_interval == 0:
                progress = (processed_frames / effective_frames) * 100
                logger.info(f"Progress: {progress:.1f}% - {processed_frames}/{effective_frames} - found {len(segments)}")

            if processed_frames % 500 == 0:
                import gc
                gc.collect()

            if processed_frames > 100000:
                logger.warning("Reached max frame limit; stopping")
                break

        if in_movement:
            movement_end = frame_count / fps
            seg_start = max(0, movement_start - padding_before)
            seg_end = min(duration, movement_end + cricket_padding_after)
            if seg_end - seg_start >= min_movement_duration:
                segments.append((seg_start, seg_end))

        if segments:
            segments = merge_overlapping_segments_cricket(segments)
        return segments

    finally:
        cap.release()
        import gc
        gc.collect()


def merge_overlapping_segments_cricket(segments: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    if not segments:
        return []
    sorted_segments = sorted(segments, key=lambda x: x[0])
    merged: List[Tuple[float, float]] = []
    current_start, current_end = sorted_segments[0]
    for start, end in sorted_segments[1:]:
        if start <= current_end + 0.2:
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
    merged.append((current_start, current_end))
    return merged


def merge_overlapping_segments(segments: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    if not segments:
        return []
    sorted_segments = sorted(segments, key=lambda x: x[0])
    merged: List[Tuple[float, float]] = []
    current_start, current_end = sorted_segments[0]
    for start, end in sorted_segments[1:]:
        if start <= current_end + 0.5:
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
    merged.append((current_start, current_end))
    return merged


def extract_video_segment(input_path: str, output_path: str, start_time: float, end_time: float) -> str:
    duration = end_time - start_time
    if duration <= 0:
        raise RuntimeError(f"Invalid segment duration: {duration}s")
    if duration > 30:
        timeout = 120
    elif duration > 15:
        timeout = 90
    elif duration > 10:
        timeout = 60
    else:
        timeout = 30

    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-ss", str(start_time),
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "fastdecode",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "96k",
        "-avoid_negative_ts", "make_zero",
        "-y",
        output_path
    ]
    logger.debug(f"FFmpeg cmd: {' '.join(shlex.quote(a) for a in cmd)}")
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout)
        if not Path(output_path).exists():
            raise RuntimeError(f"Extraction completed but file missing: {output_path}")
        size = Path(output_path).stat().st_size
        if size < 1000:
            raise RuntimeError(f"Extracted file too small ({size} bytes)")
        return str(output_path)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Extraction timed out after {timeout}s for {start_time}-{end_time}")
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg stderr: {e.stderr}")
        raise RuntimeError(f"FFmpeg extraction failed: {e.stderr}")


def extract_video_segment_alternative(input_path: str, output_path: str, start_time: float, end_time: float) -> None:
    duration = end_time - start_time
    if duration <= 0:
        raise RuntimeError(f"Invalid duration: {duration}")
    timeout = max(120, int(duration * 3))
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-ss", str(start_time),
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "96k",
        "-avoid_negative_ts", "make_zero",
        "-y",
        output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout)
        if not Path(output_path).exists():
            raise RuntimeError(f"Alternative extraction completed but file not found: {output_path}")
        size = Path(output_path).stat().st_size
        if size < 1000:
            raise RuntimeError(f"Alternative extraction file too small ({size} bytes)")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Alternative extraction timed out after {timeout}s")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Alternative FFmpeg extraction failed: {e.stderr}")


def extract_long_segment_in_chunks(video_path: str, start_time: float, end_time: float, output_dir: Path, segment_index: int) -> List[str]:
    segment_duration = end_time - start_time
    chunk_duration = 15.0
    chunks: List[str] = []
    current = start_time
    chunk_idx = 0
    while current < end_time:
        chunk_end = min(current + chunk_duration, end_time)
        fn = output_dir / f"practice_clip_{segment_index:03d}_chunk_{chunk_idx:02d}.mp4"
        try:
            extract_video_segment(video_path, str(fn), current, chunk_end)
            if fn.exists() and fn.stat().st_size > 1000:
                chunks.append(str(fn))
        except Exception as e:
            logger.warning(f"Chunk extraction failed: {e}")
        current = chunk_end
        chunk_idx += 1
    return chunks


def extract_practice_clips_batch(video_path: str,
                                 segments: List[Tuple[float, float]],
                                 output_dir: str,
                                 practice_type: str = "general",
                                 batch_size: int = 5) -> List[str]:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    if not segments:
        return []
    all_clips: List[str] = []
    total_batches = (len(segments) + batch_size - 1) // batch_size
    for batch_idx in range(total_batches):
        s = batch_idx * batch_size
        e = min(s + batch_size, len(segments))
        for i, (start_time, end_time) in enumerate(segments[s:e]):
            idx = s + i
            duration = end_time - start_time
            clip_path = out_path / f"practice_clip_{idx:03d}.mp4"
            if duration > 20:
                try:
                    split_paths = extract_long_segment_in_chunks(video_path, start_time, end_time, out_path, idx)
                    all_clips.extend(split_paths)
                    continue
                except Exception as ex:
                    logger.warning(f"Split failed: {ex}")
            try:
                extract_video_segment(video_path, str(clip_path), start_time, end_time)
                if clip_path.exists() and clip_path.stat().st_size > 1000:
                    all_clips.append(str(clip_path))
                else:
                    logger.warning(f"Clip too small or missing: {clip_path}")
            except Exception as e:
                logger.error(f"Extract failed: {e}")
                try:
                    alt = out_path / f"practice_clip_{idx:03d}_alt.mp4"
                    extract_video_segment_alternative(video_path, str(alt), start_time, end_time)
                    if alt.exists() and alt.stat().st_size > 1000:
                        all_clips.append(str(alt))
                except Exception as alt_e:
                    logger.error(f"Alt extraction failed: {alt_e}")
    return all_clips


def extract_practice_clips(video_path: str,
                           segments: List[Tuple[float, float]],
                           output_dir: str,
                           practice_type: str = "general") -> List[str]:
    return extract_practice_clips_ultra_fast(video_path, segments, output_dir, practice_type)


def extract_practice_clips_ultra_fast(video_path: str,
                                      segments: List[Tuple[float, float]],
                                      output_dir: str,
                                      practice_type: str = "general") -> List[str]:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    clip_paths: List[str] = []
    success = 0
    failed = 0
    if not segments:
        return []
    for i, (start_time, end_time) in enumerate(segments):
        duration = end_time - start_time
        clip = out_path / f"practice_clip_{i:03d}.mp4"
        try:
            extract_video_segment(video_path, str(clip), start_time, end_time)
            if clip.exists() and clip.stat().st_size > 1000:
                clip_paths.append(str(clip))
                success += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.error(f"ULTRA extraction failed for {i}: {e}")
            try:
                fallback = out_path / f"practice_clip_{i:03d}_fallback.mp4"
                cmd = [
                    "ffmpeg", "-i", video_path,
                    "-ss", str(start_time), "-t", str(duration),
                    "-c", "copy", "-avoid_negative_ts", "make_zero", "-y", str(fallback)
                ]
                subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
                if fallback.exists() and fallback.stat().st_size > 1000:
                    clip_paths.append(str(fallback))
                    success += 1
            except Exception as fb_e:
                logger.error(f"Fallback failed for {i}: {fb_e}")
        if (i + 1) % max(1, len(segments) // 4) == 0 or i == len(segments) - 1:
            logger.info(f"ULTRA progress: {(i+1)/len(segments)*100:.1f}% - success {success}, failed {failed}")
    logger.info(f"ULTRA extraction complete: {len(clip_paths)} clips")
    return clip_paths


def normalize_clip_for_concatenation(clip_path: str, output_path: str, target_fps: int = 30, target_resolution: str = "1920x1080") -> str:
    tw, th = map(int, target_resolution.split('x'))
    vf = f"fps={target_fps},scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2"
    cmd = [
        "ffmpeg", "-i", clip_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-avoid_negative_ts", "make_zero",
        "-y", output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
        if not Path(output_path).exists():
            raise RuntimeError("Normalization failed")
        return str(output_path)
    except Exception as e:
        logger.warning(f"Normalization failed for {clip_path}: {e}")
        return str(clip_path)


def concatenate_simple_method(clip_paths: List[str], output_path: str) -> str:
    clip_paths = [str(Path(p).resolve()) for p in clip_paths]
    concat_file = Path(output_path).parent / f"simple_concat_{uuid.uuid4().hex}.txt"
    with open(concat_file, 'w', encoding='utf-8') as f:
        for p in clip_paths:
            # ffmpeg concat demuxer expects paths; escape single quotes
            escaped = p.replace("'", "\\'")
            f.write(f"file '{escaped}'\n")
    cmd = [
        "ffmpeg", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c", "copy", "-avoid_negative_ts", "make_zero", "-y", str(output_path)
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
        if not Path(output_path).exists():
            raise RuntimeError("Concatenation produced no output")
        size = Path(output_path).stat().st_size
        if size < 1000:
            raise RuntimeError("Concatenated file too small")
        try:
            concat_file.unlink()
        except Exception:
            pass
        return str(Path(output_path).resolve())
    except subprocess.TimeoutExpired:
        raise RuntimeError("Simple concatenation timed out")
    except subprocess.CalledProcessError as e:
        logger.error(f"Concat stderr: {e.stderr}")
        raise RuntimeError(f"Simple concatenation failed: {e.stderr}")


def concatenate_with_alternative_method(clip_paths: List[str], output_path: str) -> str:
    clip_paths = [str(Path(p).resolve()) for p in clip_paths]
    inputs: List[str] = []
    filter_parts: List[str] = []
    for i, p in enumerate(clip_paths):
        inputs.extend(["-i", p])
        filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}];[{i}:a]asetpts=PTS-STARTPTS[a{i}]")
    video_concat = "".join(f"[v{i}]" for i in range(len(clip_paths)))
    audio_concat = "".join(f"[a{i}]" for i in range(len(clip_paths)))
    filter_parts.append(f"{video_concat}concat=n={len(clip_paths)}:v=1:a=0[outv]")
    filter_parts.append(f"{audio_concat}concat=n={len(clip_paths)}:v=0:a=1[outa]")
    filter_str = ";".join(filter_parts)

    cmd = ["ffmpeg"] + inputs + ["-filter_complex", filter_str, "-map", "[outv]", "-map", "[outa]",
                                 "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                                 "-c:a", "aac", "-b:a", "128k", "-avoid_negative_ts", "make_zero", "-y", str(output_path)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
        if not Path(output_path).exists():
            raise RuntimeError("Alternative concat produced no output")
        size = Path(output_path).stat().st_size
        if size < 1000:
            raise RuntimeError("Alternative concatenated file too small")
        return str(Path(output_path).resolve())
    except subprocess.TimeoutExpired:
        raise RuntimeError("Alternative concatenation timed out")
    except subprocess.CalledProcessError as e:
        logger.error(f"Alternative concat stderr: {e.stderr}")
        raise RuntimeError(f"Alternative concatenation failed: {e.stderr}")


def compile_practice_highlights(video_path: str,
                                output_path: str,
                                segments: List[Tuple[float, float]],
                                existing_clip_paths: Optional[List[str]] = None,
                                movement_threshold: float = 0.02,
                                min_movement_duration: float = 0.5,
                                padding_before: float = 1.0,
                                padding_after: float = 4.0) -> str:
    logger.info("Compiling practice highlights")
    if not segments:
        raise RuntimeError("No segments provided")
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if existing_clip_paths:
        clip_paths = [str(Path(p).resolve()) for p in existing_clip_paths]
        for p in clip_paths:
            if not Path(p).exists():
                raise RuntimeError(f"Existing clip missing: {p}")

        # Try simple concat first
        try:
            return concatenate_simple_method(clip_paths, str(out_path))
        except Exception as e:
            logger.warning(f"Simple concat failed: {e}, trying alternative")
            return concatenate_with_alternative_method(clip_paths, str(out_path))

    # If no existing clips provided, extract them now (safe fallback)
    temp_dir = out_path.parent / f"temp_clips_{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    clip_paths = []
    for i, (s, e) in enumerate(segments):
        clip_file = temp_dir / f"clip_{i:03d}.mp4"
        try:
            extract_video_segment(video_path, str(clip_file), s, e)
            if clip_file.exists() and clip_file.stat().st_size > 1000:
                clip_paths.append(str(clip_file.resolve()))
        except Exception as ex:
            logger.warning(f"Extraction for compilation failed for segment {i}: {ex}")

    if not clip_paths:
        raise RuntimeError("No clips available to compile")

    try:
        compiled = concatenate_simple_method(clip_paths, str(out_path))
        # cleanup temp clips
        try:
            for p in clip_paths:
                Path(p).unlink(missing_ok=True)
            temp_dir.rmdir()
        except Exception:
            pass
        return compiled
    except Exception as e:
        logger.warning(f"Simple concat failed on extracted clips: {e}, trying alternative")
        return concatenate_with_alternative_method(clip_paths, str(out_path))


def analyze_cricket_practice_session(video_path: str,
                                    output_dir: str,
                                    practice_type: str = "batting",
                                    mode: str = "clips") -> dict:
    if practice_type == "batting":
        movement_threshold = 0.015
        min_movement_duration = 0.3
        padding_before = 0.5
        padding_after = 2.0
    else:
        movement_threshold = 0.02
        min_movement_duration = 0.4
        padding_before = 0.8
        padding_after = 2.5

    segments = detect_movement_frames_fast(video_path, movement_threshold, min_movement_duration, padding_before, padding_after)
    if not segments:
        return {"status": "no_movement", "message": "No significant movement", "total_segments": 0}

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    clip_paths = extract_practice_clips(video_path, segments, str(output_path), practice_type)
    clip_paths = [str(Path(p).resolve()) for p in clip_paths]

    total_duration = get_video_duration(video_path)
    total_clip_duration = sum(e - s for s, e in segments)
    efficiency = (total_clip_duration / total_duration) if total_duration > 0 else 0.0
    estimated_balls = int(len(segments) * (0.8 if practice_type == "batting" else 0.9))
    avg_clip_duration = total_clip_duration / len(segments) if segments else 0.0

    result = {
        "status": "success",
        "total_segments": len(segments),
        "segments": segments,
        "total_highlight_duration": total_clip_duration,
        "original_duration": total_duration,
        "efficiency_percentage": efficiency * 100,
        "estimated_balls": max(1, estimated_balls),
        "average_clip_duration": avg_clip_duration,
        "practice_type": practice_type
    }

    if mode == "highlights" and clip_paths:
        try:
            highlight_file = output_path / f"cricket_{practice_type}_highlights.mp4"
            compiled = compile_practice_highlights(video_path, highlight_file, segments, existing_clip_paths=clip_paths,
                                                  movement_threshold=movement_threshold, min_movement_duration=min_movement_duration,
                                                  padding_before=padding_before, padding_after=padding_after)
            if compiled and Path(compiled).exists():
                result["output_files"] = [str(Path(compiled).resolve())]
                result["highlight_url"] = f"/outputs/practice_mode/{Path(compiled).name}"
                result["output_urls"] = [f"/outputs/practice_mode/{Path(compiled).name}"]
                result["mode"] = "highlights"
            else:
                result["output_files"] = clip_paths
                result["output_urls"] = [f"/outputs/practice_mode/{Path(clip).name}" for clip in clip_paths]
                result["mode"] = "clips"
        except Exception as e:
            logger.warning(f"Highlight compilation failed: {e}")
            result["output_files"] = clip_paths
            result["output_urls"] = [f"/outputs/practice_mode/{Path(clip).name}" for clip in clip_paths]
            result["mode"] = "clips"
    else:
        result["output_files"] = clip_paths
        result["output_urls"] = [f"/outputs/practice_mode/{Path(clip).name}" for clip in clip_paths]
        result["mode"] = "clips"
    return result


def analyze_practice_session(video_path: str,
                             output_dir: str,
                             mode: str = "clips",
                             movement_threshold: float = 0.02,
                             min_movement_duration: float = 0.5,
                             padding_before: float = 1.0,
                             padding_after: float = 4.0) -> dict:
    segments = detect_movement_frames_fast(video_path, movement_threshold, min_movement_duration, padding_before, padding_after)
    if not segments:
        return {"status": "no_movement", "message": "No movement", "total_segments": 0}
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    clip_paths = extract_practice_clips(video_path, segments, str(output_path), "general")
    clip_paths = [str(Path(p).resolve()) for p in clip_paths]

    total_duration = get_video_duration(video_path)
    total_clip_duration = sum(e - s for s, e in segments)
    efficiency = (total_clip_duration / total_duration) if total_duration > 0 else 0.0
    avg_clip_duration = total_clip_duration / len(segments) if segments else 0.0

    result = {
        "status": "success",
        "total_segments": len(segments),
        "segments": segments,
        "total_highlight_duration": total_clip_duration,
        "original_duration": total_duration,
        "efficiency_percentage": efficiency * 100,
        "average_clip_duration": avg_clip_duration,
        "practice_type": "general"
    }

    if mode == "highlights" and clip_paths:
        try:
            highlight_file = output_path / "general_practice_highlights.mp4"
            compiled = compile_practice_highlights(video_path, highlight_file, segments, existing_clip_paths=clip_paths,
                                                  movement_threshold=movement_threshold, min_movement_duration=min_movement_duration,
                                                  padding_before=padding_before, padding_after=padding_after)
            if compiled and Path(compiled).exists():
                result["output_files"] = [str(Path(compiled).resolve())]
                result["highlight_url"] = f"/outputs/practice_mode/{Path(compiled).name}"
                result["output_urls"] = [f"/outputs/practice_mode/{Path(compiled).name}"]
                result["mode"] = "highlights"
            else:
                result["output_files"] = clip_paths
                result["output_urls"] = [f"/outputs/practice_mode/{Path(clip).name}" for clip in clip_paths]
                result["mode"] = "clips"
        except Exception as e:
            logger.warning(f"Highlight compilation failed: {e}")
            result["output_files"] = clip_paths
            result["output_urls"] = [f"/outputs/practice_mode/{Path(clip).name}" for clip in clip_paths]
            result["mode"] = "clips"
    else:
        result["output_files"] = clip_paths
        result["output_urls"] = [f"/outputs/practice_mode/{Path(clip).name}" for clip in clip_paths]
        result["mode"] = "clips"
    return result


if __name__ == "__main__":
    video_path = "path/to/practice_video.mp4"
    output_dir = "practice_clips"
    try:
        res = analyze_practice_session(video_path, output_dir, mode="clips")
        print(res)
    except Exception as exc:
        print(f"Error: {exc}")