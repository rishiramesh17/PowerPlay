"""
Stage 1 of the event-first pipeline: find the deliveries.

Why this exists at all: identity-first detection is structurally biased against
action. The main camera watches the striker from in front, so his number is
hidden exactly when he is playing a shot -- jersey OCR finds him reliably while
he is standing around, and misses him while he bats. Segmenting the match by
*delivery* and attributing the striker afterwards inverts that.

Delivery segmentation is also the one stage shared by batting and bowling reels:
every ball is both a batsman event and a bowler event. Segment once, attribute
twice.

Two steps, deliberately separated because they have very different confidence:

  `propose_regions`  -- reliable. The broadcast returns to one resting framing
      between balls, so clustering camera shots surfaces it without any labels.
      What comes back is "a delivery plus the bowler walking back to his mark".

  `localize_release` -- the harder half. Inside a region, find the run-up: the
      one person moving fast and directionally while everyone else shuffles.
      This is deliberately geometry-agnostic (no assumption about which way the
      bowler runs in frame) because that varies per broadcaster -- this footage
      is a wide square-on camera, not the behind-the-arm framing you would get
      from a professional production.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

#: Sampling rate for the framing pass. Camera shots last seconds, so this is
#: about finding cut points, not motion -- 2 Hz is plenty and keeps a 4-hour
#: match tractable.
FRAMING_FPS = 2.0

#: Sampling rate for the run-up pass. A delivery stride is a fraction of a
#: second; below ~5 Hz the peak is indistinguishable from its neighbours.
RUNUP_FPS = 5.0

#: Camera shots shorter than this are cuts and stings, not play.
MIN_SHOT_SEC = 2.0

#: A region has to be long enough to contain a run-up plus its aftermath.
MIN_REGION_SEC = 4.0

#: How far past the dominant cluster's own radius a shot may sit and still be
#: proposed. Slack here costs a little compute; too little slack costs a
#: boundary, which is the whole point of the reel.
REGION_RADIUS_TOLERANCE = 1.15

#: How far the run-up peak must stand above the region's own background motion.
#: A ratio rather than an absolute speed: measured peaks run ~1.0 body-lengths/s
#: against a ~0.2 background on this wide square-on footage, but a tighter
#: broadcast framing scales both together, and the ratio survives that.
RUNUP_PROMINENCE = 2.5

#: Sanity floor so a dead region with near-zero motion cannot produce a huge
#: ratio out of rounding noise.
RUNUP_SPEED_FLOOR = 0.4

#: A run-up is sustained, not a single frame of detector jitter.
RUNUP_MIN_SEC = 0.6

#: Relative change in the bowler's box height across his run-up needed to call
#: which end he is bowling from. A run-up is ~18m, so a camera behind the stumps
#: sees him grow or shrink substantially; a square-on camera sees neither, and
#: the signal then correctly reports "unknown" rather than guessing.
END_HEIGHT_TREND = 0.15

#: Fraction of a region's typical on-camera headcount below which the frame is
#: not showing the pitch. When the camera leaves to track a ball to the rope,
#: the count collapses (measured 5 -> 0 on a six). Speeds from those frames are
#: meaningless -- one distant fielder's box jitters enough to swamp a real
#: run-up once it is normalized by his tiny height.
PITCH_CREW_RATIO = 0.6


@dataclass
class Region:
    """A span of the match in the resting camera framing."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class ReleaseEstimate:
    """Where the ball was released inside a region, and how sure we are."""

    release_t: Optional[float]
    #: Peak sustained run-up speed in body-lengths/sec. Raw evidence, not a
    #: probability, so callers can threshold it themselves.
    speed: float
    #: Peak divided by the region's background motion. This is what decides
    #: whether a release is reported.
    prominence: float
    #: Seconds the camera spent away from the pitch (headcount collapsed).
    #: A ball tracked to the boundary produces several seconds here; a defended
    #: ball produces none, which makes this a Stage 2 outcome feature.
    away_sec: float

    #: Relative change in the bowler's apparent height across his run-up.
    #: Positive means he grew, i.e. ran toward the camera.
    height_trend: float = 0.0

    #: Which end he bowled from, as seen by this camera: "near" (he ran away
    #: from it), "far" (he ran toward it), or None when the camera is square-on
    #: and cannot tell.
    bowling_end: Optional[str] = None

    @property
    def striker_faces_camera(self) -> Optional[bool]:
        """
        Whether the striker's front is toward the camera -- and so whether his
        number is hidden.

        The striker stands at the opposite end from the bowler and faces him.
        With a single camera behind one end, that makes the answer alternate
        with the bowling end, and therefore with every over:

          bowler ran AWAY  -> bowling from the near end -> striker is far away
                              and faces the camera -> number HIDDEN
          bowler ran TOWARD-> bowling from the far end -> striker is near and
                              turned away -> number VISIBLE

        This is why "the striker's number is never readable" was too pessimistic
        -- it is readable for roughly half the overs, and elimination via the
        non-striker covers the rest.
        """
        if self.bowling_end is None:
            return None
        return self.bowling_end == "near"


@dataclass
class Delivery:
    """A proposed delivery, with a release time when one could be localized."""

    region: Region
    release: ReleaseEstimate

    @property
    def release_t(self) -> Optional[float]:
        return self.release.release_t

    @property
    def localized(self) -> bool:
        return self.release.release_t is not None


def _descriptor(frame: np.ndarray, scoreboard_rows: int) -> np.ndarray:
    """
    A thumbnail that captures framing while ignoring the players inside it.

    The scoreboard strip is cropped off first: it is static burnt-in graphics
    that would otherwise dominate the similarity between two very different
    shots.
    """
    body = frame[:-scoreboard_rows] if scoreboard_rows else frame
    small = cv2.resize(body, (32, 18))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    return np.concatenate(
        [
            small.astype(np.float32).ravel() / 255.0,
            hsv[:, :, 0].astype(np.float32).ravel() / 180.0,
        ]
    )


def _kmeans(points: np.ndarray, k: int, seeds: int = 6, iters: int = 25) -> np.ndarray:
    """Plain Lloyd's with restarts. Avoids a scikit-learn dependency for this."""
    best = None
    for seed in range(seeds):
        rng = np.random.default_rng(seed)
        centres = points[rng.choice(len(points), size=min(k, len(points)), replace=False)].copy()
        labels = np.zeros(len(points), dtype=int)
        for _ in range(iters):
            labels = np.argmin(((points[:, None, :] - centres[None]) ** 2).sum(-1), axis=1)
            for c in range(len(centres)):
                if (labels == c).any():
                    centres[c] = points[labels == c].mean(axis=0)
        inertia = ((points - centres[labels]) ** 2).sum()
        if best is None or inertia < best[0]:
            best = (inertia, labels.copy())
    return best[1]


def propose_regions(
    video_path: str,
    start: float,
    end: float,
    scoreboard_rows: int = 100,
    clusters: int = 6,
) -> List[Region]:
    """
    Return spans sitting in the broadcast's dominant (resting) camera framing.

    Cricket coverage returns to the same wide shot before every ball, so that
    framing is by a wide margin the most repeated one in the match. Clustering
    shot-average descriptors and taking the largest cluster surfaces it with no
    labels and no training. Replays, crowd cutaways, graphics stings and drinks
    breaks all land in other clusters and drop out.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    skip = max(1, int(round(src_fps / FRAMING_FPS)))

    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
    times: List[float] = []
    descs: List[np.ndarray] = []
    t = start
    while t < end:
        for _ in range(skip - 1):
            cap.grab()
        ok, frame = cap.read()
        if not ok:
            break
        descs.append(_descriptor(frame, scoreboard_rows))
        times.append(t)
        t += skip / src_fps
    cap.release()

    if len(descs) < clusters * 2:
        logger.warning("too few samples (%d) to propose regions", len(descs))
        return []

    D = np.array(descs)
    # A camera cut is a step change in the descriptor; ordinary play is smooth.
    jumps = np.linalg.norm(np.diff(D, axis=0), axis=1)
    threshold = float(np.percentile(jumps, 90) * 0.9)
    cut_idx = [0] + [i + 1 for i, v in enumerate(jumps) if v > threshold] + [len(D)]

    min_frames = max(2, int(MIN_SHOT_SEC * FRAMING_FPS))
    shots = [
        (cut_idx[i], cut_idx[i + 1])
        for i in range(len(cut_idx) - 1)
        if cut_idx[i + 1] - cut_idx[i] >= min_frames
    ]
    if len(shots) < clusters:
        logger.warning("only %d usable camera shots", len(shots))
        return []

    means = np.array([D[a:b].mean(axis=0) for a, b in shots])
    labels = _kmeans(means, clusters)
    sizes = {c: int((labels == c).sum()) for c in set(labels.tolist())}
    dominant = max(sizes, key=sizes.get)

    # Membership by distance, not by cluster label. Broadcast framing drifts
    # with zoom, so the resting shot is a continuum rather than a tight blob,
    # and k-means splits it at an arbitrary point: a six was measured at
    # distance 3.23 from the dominant centroid -- nearer than two shots the
    # labelling *did* accept -- and was dropped anyway. Missing the deliveries
    # that produced boundaries is the one failure this stage cannot have, so
    # admit anything within the cluster's own spread and let `localize_release`
    # reject what has no run-up in it.
    centroid = means[labels == dominant].mean(axis=0)
    distances = np.linalg.norm(means - centroid, axis=1)
    radius = float(distances[labels == dominant].max()) * REGION_RADIUS_TOLERANCE
    logger.info(
        "camera-shot clusters %s, dominant=%s, radius=%.2f", sizes, dominant, radius
    )

    return [
        Region(times[a], times[b - 1])
        for (a, b), dist in zip(shots, distances)
        if dist <= radius and times[b - 1] - times[a] >= MIN_REGION_SEC
    ]


def _link_tracks(
    detections: Sequence[Sequence[Tuple[float, float, float]]],
    max_jump: float = 0.08,
) -> List[List[Optional[Tuple[float, float, float]]]]:
    """
    Greedy nearest-neighbour linking of per-frame boxes into short tracks.

    Full multi-object tracking is overkill here: a run-up lasts a couple of
    seconds, so a track only has to survive that long to be measurable. Each
    detection is (cx, cy, height) normalized to frame size, so `max_jump` is a
    fraction of the frame rather than pixels.
    """
    tracks: List[List[Optional[Tuple[float, float, float]]]] = []
    for frame_idx, dets in enumerate(detections):
        claimed = set()
        for track in tracks:
            last = next((p for p in reversed(track) if p is not None), None)
            if last is None:
                track.append(None)
                continue
            best, best_d = None, max_jump
            for j, d in enumerate(dets):
                if j in claimed:
                    continue
                dist = float(np.hypot(d[0] - last[0], d[1] - last[1]))
                if dist < best_d:
                    best, best_d = j, dist
            if best is None:
                track.append(None)
            else:
                claimed.add(best)
                track.append(dets[best])
        for j, d in enumerate(dets):
            if j not in claimed:
                tracks.append([None] * frame_idx + [d])
    return tracks


def localize_release(
    video_path: str,
    region: Region,
    model,
    imgsz: int = 480,
) -> Tuple[Optional[float], float]:
    """
    Find the moment of release inside a proposed region.

    The run-up is the only time in a delivery cycle when one person moves fast
    and in a straight line while everyone else is near-stationary. That is a
    *relative* signal, which is what makes it survive a change of camera angle:
    no assumption is made about which direction the bowler runs in frame.

    Speed is measured in body-lengths per second (displacement over detected box
    height), so a bowler far from camera and one close to it score the same.
    Camera motion is removed by subtracting the median displacement of all people
    in frame -- when the camera pans everyone moves together, and only genuine
    relative motion survives.

    Release is reported at the peak of the sustained run-up, which is the
    delivery stride.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    skip = max(1, int(round(src_fps / RUNUP_FPS)))
    cap.set(cv2.CAP_PROP_POS_MSEC, region.start * 1000.0)

    times: List[float] = []
    per_frame: List[List[Tuple[float, float, float]]] = []
    t = region.start
    while t < region.end:
        for _ in range(skip - 1):
            cap.grab()
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        res = model.predict(frame, imgsz=imgsz, classes=[0], verbose=False)[0]
        dets = []
        for box in res.boxes.xyxy.cpu().numpy():
            x1, y1, x2, y2 = box
            bh = (y2 - y1) / h
            if bh < 0.02:  # too small to measure motion against reliably
                continue
            dets.append((((x1 + x2) / 2) / w, ((y1 + y2) / 2) / h, bh))
        per_frame.append(dets)
        times.append(t)
        t += skip / src_fps
    cap.release()

    if len(times) < 4:
        return ReleaseEstimate(None, 0.0, 0.0, 0.0)

    dt = skip / src_fps

    # Frames where the camera is showing the pitch. Everything downstream is
    # restricted to these: motion measured while the camera is following a ball
    # into the outfield says nothing about a run-up.
    counts = np.array([len(d) for d in per_frame], dtype=float)
    crew = float(np.median(counts))
    on_pitch = counts >= max(1.0, crew * PITCH_CREW_RATIO)
    away_sec = float((~on_pitch).sum()) * dt
    tracks = _link_tracks(per_frame)
    n_steps = len(times) - 1

    # Camera motion: the median frame-to-frame displacement across everyone.
    # A pan moves every box; a run-up moves one.
    all_steps: List[List[Tuple[float, float]]] = [[] for _ in range(n_steps)]
    for track in tracks:
        for i in range(n_steps):
            a = track[i] if i < len(track) else None
            b = track[i + 1] if i + 1 < len(track) else None
            if a is not None and b is not None:
                all_steps[i].append((b[0] - a[0], b[1] - a[1]))
    camera = [
        (float(np.median([s[0] for s in steps])), float(np.median([s[1] for s in steps])))
        if steps else (0.0, 0.0)
        for steps in all_steps
    ]

    # Per-track speed in body-lengths/sec, camera-compensated. Kept per track,
    # not collapsed to a maximum, because identifying *which* person ran is what
    # makes the bowling end readable further down.
    per_track_speed = np.zeros((len(tracks), n_steps))
    for ti, track in enumerate(tracks):
        for i in range(n_steps):
            a = track[i] if i < len(track) else None
            b = track[i + 1] if i + 1 < len(track) else None
            if a is None or b is None:
                continue
            dx = (b[0] - a[0]) - camera[i][0]
            dy = (b[1] - a[1]) - camera[i][1]
            body = max(a[2], 1e-3)
            per_track_speed[ti, i] = float(np.hypot(dx, dy)) / body / dt
    speed_at = per_track_speed.max(axis=0) if len(tracks) else np.zeros(n_steps)

    # A step is usable only if both of its frames were on the pitch.
    usable = on_pitch[:-1] & on_pitch[1:]
    speed_at = np.where(usable, speed_at, 0.0)
    if usable.sum() < 4:
        return ReleaseEstimate(None, 0.0, 0.0, away_sec)

    # Require the speed to be *sustained*: a single fast frame is detector
    # jitter, or one box swapping between two overlapping players.
    win = max(1, int(round(RUNUP_MIN_SEC / dt)))
    sustained = np.convolve(speed_at, np.ones(win) / win, mode="same") if win > 1 else speed_at

    peak_idx = int(np.argmax(np.where(usable, sustained, 0.0)))
    peak = float(sustained[peak_idx])
    # Background is the typical motion of this same region, so a busy wide shot
    # and a tight one are judged on their own terms.
    background = float(np.median(sustained[usable])) or 1e-3
    prominence = peak / background
    if peak < RUNUP_SPEED_FLOOR or prominence < RUNUP_PROMINENCE:
        return ReleaseEstimate(None, peak, prominence, away_sec)

    runner = int(np.argmax(per_track_speed[:, peak_idx])) if len(tracks) else -1
    trend, end = _bowling_end(tracks[runner], peak_idx, win) if runner >= 0 else (0.0, None)
    return ReleaseEstimate(
        times[peak_idx] + dt / 2.0, peak, prominence, away_sec,
        height_trend=trend, bowling_end=end,
    )


def _bowling_end(
    track: Sequence[Optional[Tuple[float, float, float]]],
    peak_idx: int,
    window: int,
) -> Tuple[float, Optional[str]]:
    """
    Read which end the bowler ran from, using how his apparent size changed.

    Perspective does the work: a bowler running at the camera grows, one running
    away shrinks. Box height is the measurement, and it is immune to panning and
    to where in frame he happens to be -- unlike his screen position, which a
    camera move can reverse outright.

    A square-on camera sees a bowler who runs across rather than along the line
    of sight, so his height barely changes. That returns None, which is the
    honest answer for that framing rather than a coin flip.
    """
    lo = max(0, peak_idx - window * 2)
    heights = [track[i][2] for i in range(lo, min(peak_idx + 1, len(track))) if track[i]]
    if len(heights) < 3:
        return 0.0, None
    # Compare the ends of the run-up rather than single frames: box height is
    # noisy frame to frame, especially at the delivery stride where he is bent.
    third = max(1, len(heights) // 3)
    early = float(np.median(heights[:third]))
    late = float(np.median(heights[-third:]))
    if early <= 1e-3:
        return 0.0, None
    trend = (late - early) / early
    if trend >= END_HEIGHT_TREND:
        return trend, "far"    # grew: ran toward camera, so bowling from the far end
    if trend <= -END_HEIGHT_TREND:
        return trend, "near"   # shrank: ran away, so bowling from the near end
    return trend, None


def detect_deliveries(
    video_path: str,
    start: float,
    end: float,
    model=None,
    scoreboard_rows: int = 100,
) -> List[Delivery]:
    """Propose regions, then localize a release inside each."""
    regions = propose_regions(video_path, start, end, scoreboard_rows=scoreboard_rows)
    if model is None:
        from ultralytics import YOLO

        model = YOLO("yolov8n.pt")
    return [
        Delivery(region=region, release=localize_release(video_path, region, model))
        for region in regions
    ]
