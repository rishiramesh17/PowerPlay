"""
Work out what a stream actually offers before trying to analyse it.

Streams vary enormously: one locked-off camera behind the stumps, a square-on
camera at the boundary, a cut broadcast with replays and full-screen graphics,
with or without a scoreboard overlay, with or without usable audio. A detector
that is excellent on one of those is worthless or -- worse -- confidently wrong
on another.

The measured example: the run-up localizer reads which end the bowler came from
by watching his apparent size change. On a camera looking along the pitch that
is real perspective. On a square-on camera there is no depth to read, and it
returned the same answer for every over of a match, which cricket does not
allow. Nothing in the code could tell the difference, so the failure only
surfaced hours later against ground truth.

A profile makes that a precondition instead of a surprise. Each detector
declares what it needs; the profile says whether this stream has it.

Nothing here decides anything on its own. The profile is a *prior*: it selects
and weights detectors, and callers are expected to let footage evidence override
it. Users may confirm or correct it, but a declaration is never treated as
truth -- a wrong one would silently poison every downstream stage, which is the
failure mode this module exists to prevent.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

#: Frames sampled across the whole stream to find burnt-in overlays. They must
#: span the entire runtime, not a contiguous stretch: the trick is that the
#: underlying scene changes completely between them -- different camera angles,
#: replays, graphics, innings -- while an overlay stays in the same pixels. Too
#: few frames and ordinary grass looks static too.
OVERLAY_SAMPLES = 48

#: Per-pixel tolerance, in 8-bit grey levels, for calling two samples "the same".
#: Generous enough to absorb compression noise and the overlay's own changing
#: digits, tight enough that moving field content fails it.
OVERLAY_TOLERANCE = 18

#: Fraction of sampled frames a pixel must stay put in to count as overlay.
#: Below 1.0 so that full-screen graphics, which briefly cover the scoreboard,
#: do not disqualify it.
OVERLAY_PERSISTENCE = 0.80

#: Fraction of a row's pixels that must qualify before the row is considered
#: part of an overlay band.
OVERLAY_ROW_DENSITY = 0.35

#: Once a band is found, it is grown outward while rows stay above this
#: fraction of the entry threshold. A single cut-off is too blunt: only the
#: sharpest rows of a caption clear it, so the band stopped 20px tall where the
#: text was 34-60px and OCR lost the lower line entirely. Entering strict and
#: leaving loose is the same hysteresis Canny uses on edges.
OVERLAY_BAND_HYSTERESIS = 0.45

#: Staying still is not enough on its own. A locked-off camera over a uniform
#: outfield holds just as steady as a graphic, and on a 20-minute single-camera
#: clip that produced a "scoreboard" covering the entire frame at 0.80
#: confidence. Overlays are also *sharp* -- text and panel borders carry strong
#: local gradients that grass does not -- so a pixel must be both static and
#: edge-rich. This is the percentile of gradient magnitude it must exceed.
OVERLAY_EDGE_PERCENTILE = 80.0

#: Where in the file to sample audio from, and for how long. Offset past any
#: title card; long enough to average over a quiet passage of play.
AUDIO_PROBE_OFFSET = 60.0
AUDIO_PROBE_SECONDS = 120.0

#: Above this mean amplitude the track carries real content. -60 dBFS is about
#: 0.001; measured broadcast commentary sits near -22 dB (0.074), and a genuinely
#: empty track sits at or below the noise floor.
AUDIO_SILENCE_FLOOR = 0.001

#: Analysis width for the overlay pass. Coordinates are scaled back to full
#: resolution on the way out.
OVERLAY_WIDTH = 640

#: Correlation between a person's height in frame and their vertical position,
#: above which the camera is judged to be looking *along* the pitch. When the
#: camera looks down the wicket, distant players sit high in frame and are
#: small, so the two are strongly related. Square-on, everyone is about the same
#: distance away and the relationship collapses.
#:
#: PROVISIONAL: calibrated against exactly two streams, which measured 0.02
#: (square-on) and 0.47 (end-on). The separation is 20x and unambiguous; the
#: cut point between them is not. Treat `depth_variation` as the real output
#: and this boolean as a convenience until more streams have been measured.
DEPTH_CORRELATION_STRONG = 0.30


@dataclass
class StreamProfile:
    """What this stream can and cannot support."""

    width: int
    height: int
    fps: float
    duration_sec: float

    #: Pixel box of the burnt-in score overlay, if one was found. This is the
    #: single most valuable thing a stream can have: it is the only signal so
    #: far that transferred between two unrelated broadcasters unchanged.
    scoreboard_roi: Optional[Tuple[int, int, int, int]] = None
    scoreboard_confidence: float = 0.0

    #: How much depth the camera can see, as |correlation| between person size
    #: and position in frame. Deliberately a measurement rather than an
    #: "end-on"/"square-on" label: what perspective-based detectors actually
    #: need is depth range, so reporting the quantity keeps the caller honest
    #: about how much there is.
    depth_variation: float = 0.0

    #: Share of runtime spent outside the dominant camera framing. A high value
    #: means replays, graphics and cutaways, which is what fragments shot-based
    #: segmentation. Zero until a caller measures it -- see `stable_framing`,
    #: which is why `supports()` treats an unmeasured stream as stable.
    dynamic_fraction: float = 0.0

    has_audio: bool = False
    audio_rms: float = 0.0

    notes: List[str] = field(default_factory=list)

    @property
    def looks_along_pitch(self) -> Optional[bool]:
        """
        Whether perspective cues are usable, or None when it cannot be told.

        None is a real answer and callers must handle it. Guessing here is what
        produced a bowling-end reading that never changed across a whole match.
        """
        if self.depth_variation <= 0.0:
            return None
        return self.depth_variation >= DEPTH_CORRELATION_STRONG

    def supports(self, requirement: str) -> bool:
        """Cheap capability check for a detector's preconditions."""
        return {
            "scoreboard": self.scoreboard_roi is not None,
            "perspective": self.looks_along_pitch is True,
            "audio": self.has_audio and self.audio_rms > AUDIO_SILENCE_FLOOR,
            "stable_framing": self.dynamic_fraction < 0.5,
        }.get(requirement, False)

    def summary(self) -> str:
        """One-line description, suitable for asking a user to confirm."""
        bits = [f"{self.width}x{self.height}@{self.fps:.0f}"]
        if self.scoreboard_roi:
            x1, y1, x2, y2 = self.scoreboard_roi
            bits.append(f"scoreboard at ({x1},{y1})-({x2},{y2})")
        else:
            bits.append("no scoreboard found")
        along = self.looks_along_pitch
        bits.append(
            "looks along the pitch" if along
            else "square-on / little depth" if along is False
            else "depth unknown"
        )
        bits.append("audio present" if self.supports("audio") else "no usable audio")
        return " · ".join(bits)


def _sample_frames(cap: cv2.VideoCapture, count: int, duration: float) -> List[np.ndarray]:
    """Grab `count` frames spread evenly across the whole runtime."""
    frames = []
    for i in range(count):
        # Avoid the very start and end, which are often title cards or dead air.
        t = duration * (i + 0.5) / count
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    return frames


def find_overlay(frames: List[np.ndarray]) -> Tuple[Optional[Tuple[int, int, int, int]], float]:
    """
    Locate a burnt-in graphic by finding pixels that refuse to change.

    Across samples spanning the full match the scene is completely different
    every time, so anything holding still is composited on top rather than
    filmed. Persistence is measured against the per-pixel median instead of a
    mean so that a handful of full-screen graphics -- which do cover the
    scoreboard -- cannot veto an otherwise permanent overlay.
    """
    if len(frames) < 8:
        return None, 0.0

    h, w = frames[0].shape[:2]
    scale = OVERLAY_WIDTH / float(w)
    small = np.stack([
        cv2.cvtColor(cv2.resize(f, (OVERLAY_WIDTH, int(h * scale))), cv2.COLOR_BGR2GRAY)
        for f in frames
    ]).astype(np.int16)

    median = np.median(small, axis=0)
    persistent = (np.abs(small - median) <= OVERLAY_TOLERANCE).mean(axis=0)
    static = persistent >= OVERLAY_PERSISTENCE

    # Sharpness, measured on the median image so it describes what persists
    # rather than whatever one frame happened to show.
    med8 = median.astype(np.uint8)
    grad = np.abs(cv2.Sobel(med8, cv2.CV_32F, 1, 0, ksize=3)) + \
           np.abs(cv2.Sobel(med8, cv2.CV_32F, 0, 1, ksize=3))
    # Pool locally: a glyph is a cluster of edges, not one pixel of one.
    grad = cv2.blur(grad, (5, 5))
    edgy = grad >= np.percentile(grad, OVERLAY_EDGE_PERCENTILE)

    static = static & edgy
    row_density = static.mean(axis=1)
    rows = np.where(row_density >= OVERLAY_ROW_DENSITY)[0]
    if len(rows) == 0:
        return None, 0.0

    # Take the largest contiguous run of qualifying rows. Overlays are bands;
    # scattered single rows are usually a static horizon or a sight screen.
    best: Tuple[int, int] = (rows[0], rows[0])
    start = prev = rows[0]
    for r in rows[1:]:
        if r - prev > 2:
            if prev - start > best[1] - best[0]:
                best = (start, prev)
            start = r
        prev = r
    if prev - start > best[1] - best[0]:
        best = (start, prev)

    y1, y2 = best
    if y2 - y1 < 3:
        return None, 0.0

    # Grow the band outward at the relaxed threshold so the whole caption is
    # captured, not just its sharpest rows.
    loose = OVERLAY_ROW_DENSITY * OVERLAY_BAND_HYSTERESIS
    while y1 > 0 and row_density[y1 - 1] >= loose:
        y1 -= 1
    while y2 + 1 < len(row_density) and row_density[y2 + 1] >= loose:
        y2 += 1

    band = static[y1:y2 + 1]
    cols = np.where(band.mean(axis=0) >= OVERLAY_ROW_DENSITY)[0]
    if len(cols) == 0:
        return None, 0.0

    inv = 1.0 / scale
    roi = (
        int(cols[0] * inv), int(y1 * inv),
        int((cols[-1] + 1) * inv), int((y2 + 1) * inv),
    )
    confidence = float(band.mean())
    return roi, confidence


def measure_depth_variation(frames: List[np.ndarray], model) -> float:
    """
    How strongly a person's size in frame tracks their position in it.

    Looking down the wicket, distant players sit high in the image and appear
    small, so size and height are tightly related. Square-on, everyone is
    roughly equidistant and the relationship falls apart. Returning the
    correlation rather than a verdict keeps the quantity visible to callers,
    because "how much perspective is there" is the question detectors actually
    have.
    """
    ys: List[float] = []
    hs: List[float] = []
    for frame in frames:
        fh, fw = frame.shape[:2]
        res = model.predict(frame, imgsz=480, classes=[0], verbose=False)[0]
        for box in res.boxes.xyxy.cpu().numpy():
            x1, y1, x2, y2 = box
            bh = (y2 - y1) / fh
            if bh < 0.02:
                continue
            ys.append(((y1 + y2) / 2) / fh)
            hs.append(bh)
    if len(ys) < 20:
        return 0.0
    # Guard against a degenerate frame where every box is identical.
    if np.std(ys) < 1e-6 or np.std(hs) < 1e-6:
        return 0.0
    return float(abs(np.corrcoef(ys, hs)[0, 1]))


def audio_info(video_path: str) -> Tuple[bool, float]:
    """Whether the file carries audio, and how loud it is on average."""
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "json", video_path],
            capture_output=True, text=True, timeout=30,
        )
        streams = json.loads(probe.stdout or "{}").get("streams", [])
        if not streams:
            return False, 0.0
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        logger.warning("audio probe failed for %s: %s", video_path, exc)
        return False, 0.0

    # A track can exist and be silent, which is common on re-encoded uploads --
    # so presence alone is not enough to promise an audio detector anything.
    try:
        # `-v info`, not `-v error`: volumedetect reports its summary at info
        # level, so quietening ffmpeg suppressed the measurement and every
        # stream came back "silent". A track measured at -22.6 dB was reported
        # as having no usable audio for two days.
        #
        # Sampled from inside the file rather than the head, which is often a
        # title card or dead air before the broadcast settles.
        out = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "info", "-ss", str(AUDIO_PROBE_OFFSET),
             "-t", str(AUDIO_PROBE_SECONDS), "-i", video_path,
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=180,
        )
        for line in out.stderr.splitlines():
            if "mean_volume:" in line:
                db = float(line.split("mean_volume:")[1].split("dB")[0].strip())
                return True, float(10 ** (db / 20.0))
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        logger.warning("volume probe failed for %s: %s", video_path, exc)
    return True, 0.0


def detect_profile(
    video_path: str,
    model=None,
    samples: int = OVERLAY_SAMPLES,
) -> StreamProfile:
    """
    Inspect a stream and report what it supports.

    `model` is an optional YOLO person detector; without it depth variation is
    left at zero and `looks_along_pitch` reports None, which callers must treat
    as "unknown" rather than "no".
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = frame_count / fps if fps else 0.0

    frames = _sample_frames(cap, samples, duration)
    cap.release()

    profile = StreamProfile(
        width=width, height=height, fps=fps, duration_sec=duration,
    )
    if not frames:
        profile.notes.append("no frames could be read")
        return profile

    profile.scoreboard_roi, profile.scoreboard_confidence = find_overlay(frames)
    if profile.scoreboard_roi is None:
        profile.notes.append("no burnt-in overlay found; scoreboard signals unavailable")

    if model is not None:
        profile.depth_variation = measure_depth_variation(frames, model)
        if profile.looks_along_pitch is False:
            profile.notes.append(
                "little depth variation: perspective cues such as bowling-end "
                "detection are not supported on this stream"
            )
    else:
        profile.notes.append("no detector supplied; depth variation not measured")

    profile.has_audio, profile.audio_rms = audio_info(video_path)
    if profile.has_audio and not profile.supports("audio"):
        profile.notes.append("audio track present but silent")

    return profile
