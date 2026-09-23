"""
Combine several detectors' opinions about when deliveries happened.

The case for fusion here is specific, not general enthusiasm for ensembles: the
available signals fail on *different footage for different reasons*. A scoreboard
reader is excellent where an overlay exists and useless where it does not. A
run-up localizer reads motion and cares nothing for graphics. Perspective cues
work looking down the wicket and not at all square-on. Uncorrelated failure is
the condition under which combining helps, and it holds.

Three rules, each earned:

  Abstention is not disagreement. A detector that cannot judge a stream must
  contribute nothing -- not a low score, not a default. A bowling-end reader
  once returned the same verdict for every over of a match because it had no way
  to say "this camera cannot support me", and cricket does not permit an end
  that never changes.

  Preconditions are checked before execution, against a measured stream profile,
  so that detector is refused in milliseconds instead of running to completion
  and being believed.

  Attribution survives the merge. Five votes producing a wrong answer is far
  harder to debug than one detector being wrong, so every fused event carries
  the signals that formed it and the evidence behind each.

Weights are deliberately equal. There is not enough data to fit them -- two
streams, one held out -- and a weight invented now would be the same mistake as
a threshold fitted to a single video. `agreement_rate` records what would be
needed to measure them later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .stream_profile import StreamProfile

logger = logging.getLogger(__name__)

#: Two signals within this many seconds are treated as describing the same ball.
#:
#: Has to exceed the scoreboard's own lag, which was measured at 3-11 seconds on
#: hand-verified deliveries: a board tick and a vision release describing the
#: same ball can sit that far apart, and a narrower window would split one
#: delivery into two events. Still comfortably under the shortest observed gap
#: between real deliveries (21s), so it cannot chain across balls.
AGREEMENT_WINDOW_SEC = 14.0

#: Minimum fused confidence for an event to be reported. Favours precision: for
#: a highlight reel a missed boundary is survivable, a clip of nothing happening
#: is not.
MIN_FUSED_CONFIDENCE = 0.45

#: What an uncalibrated detector's signals are worth.
#:
#: Measured, not chosen: the run-up localizer's confidence scores an AUC of
#: 0.384 (p=0.89) at predicting whether its own detection is real -- correct
#: detections averaged 4.67 and false ones 4.69. None of its other features
#: reached significance either. Passing that through noisy-OR would let noise
#: argue as loudly as evidence, and fusion's respectable machinery would make
#: the failure very hard to see.
#:
#: So an uncalibrated detector contributes *presence*, not certainty. Its
#: signals say "I saw something here" at a fixed weight, and corroboration
#: between independent detectors does the discriminating instead. Set just below
#: the reporting threshold so one such detector alone cannot carry an event, but
#: two agreeing can.
UNCALIBRATED_CONFIDENCE = 0.40


@dataclass(frozen=True)
class Signal:
    """One detector's opinion about one moment."""

    detector: str
    t: float
    #: 0-1. The detector's own view of how sure it is. Never a probability the
    #: fusion layer invented on its behalf.
    confidence: float
    #: Seconds of uncertainty about *when*, which is a different quantity from
    #: confidence about *whether*. A scoreboard is certain a ball was bowled and
    #: vague about the moment -- its tick trails the delivery by a measured 3-11
    #: seconds. A motion detector is the reverse: unsure the event is real, but
    #: accurate to a fraction of a second once it fires. Collapsing both into one
    #: number would let the surer detector drag the timestamp away from the more
    #: precise one, which is backwards.
    time_sigma: float = 1.0
    #: Raw values behind the opinion, kept for debugging. Fusion must never be
    #: the reason a failure becomes unexplainable.
    evidence: Dict[str, float] = field(default_factory=dict)


@dataclass
class FusedEvent:
    """A delivery, and every signal that argued for it."""

    t: float
    confidence: float
    signals: Tuple[Signal, ...]

    @property
    def detectors(self) -> Tuple[str, ...]:
        return tuple(s.detector for s in self.signals)

    @property
    def corroborated(self) -> bool:
        """Did more than one independent detector see this?"""
        return len(set(self.detectors)) > 1

    def explain(self) -> str:
        """Human-readable attribution, for when a result looks wrong."""
        parts = [
            f"{s.detector}@{s.t:.1f}s(conf={s.confidence:.2f}"
            + (", " + ", ".join(f"{k}={v:.2f}" for k, v in s.evidence.items())
               if s.evidence else "")
            + ")"
            for s in self.signals
        ]
        return f"t={self.t:.1f}s conf={self.confidence:.2f} <- " + " + ".join(parts)


@dataclass
class Detector:
    """
    A source of signals, plus what it needs from a stream to be trustworthy.

    `requires` names capabilities checked against a StreamProfile. Anything not
    satisfied means the detector is never run -- the difference between a
    detector that is wrong and one that was never allowed to be wrong.
    """

    name: str
    run: Callable[[], Optional[Sequence[Signal]]]
    requires: Tuple[str, ...] = ()

    #: Whether this detector's confidence has been shown to predict correctness.
    #: Defaults to False because that is the honest prior: a score is not a
    #: probability until something measured it against ground truth. An
    #: uncalibrated detector's signals are flattened to UNCALIBRATED_CONFIDENCE
    #: so its self-assessment cannot outvote a detector that earned its number.
    calibrated: bool = False


@dataclass
class FusionReport:
    """Fused events plus the bookkeeping needed to trust or debug them."""

    events: List[FusedEvent]
    eligible: List[str]
    #: Detectors skipped because the stream could not support them, with reason.
    skipped: Dict[str, str]
    #: Detectors that ran and declined to judge.
    abstained: List[str]
    #: Detectors whose confidence was flattened because it has not been shown to
    #: predict correctness. Their original score is kept in each signal's
    #: evidence as `raw_confidence` so nothing is hidden, only distrusted.
    uncalibrated: List[str]
    #: Per-detector share of its signals that landed on a reported event. The
    #: raw material for calibrating weights once enough streams exist; recorded
    #: rather than acted on.
    agreement_rate: Dict[str, float]

    def summary(self) -> str:
        bits = [f"{len(self.events)} events from {len(self.eligible)} detectors"]
        if self.skipped:
            bits.append("skipped: " + ", ".join(
                f"{n} ({why})" for n, why in self.skipped.items()))
        if self.abstained:
            bits.append("abstained: " + ", ".join(self.abstained))
        if self.uncalibrated:
            bits.append("uncalibrated (flattened): " + ", ".join(self.uncalibrated))
        return " · ".join(bits)


def select_detectors(
    detectors: Sequence[Detector], profile: StreamProfile
) -> Tuple[List[Detector], Dict[str, str]]:
    """Split detectors into those this stream can support and those it cannot."""
    eligible, skipped = [], {}
    for d in detectors:
        missing = [r for r in d.requires if not profile.supports(r)]
        if missing:
            skipped[d.name] = "stream lacks " + ", ".join(missing)
        else:
            eligible.append(d)
    return eligible, skipped


def _cluster(signals: Sequence[Signal], window: float) -> List[List[Signal]]:
    """
    Group signals that are close enough in time to describe the same delivery.

    Single-linkage on purpose: two detectors that each nudge the estimate a few
    seconds should still merge, and real deliveries are far enough apart (21s at
    the tightest measured) that a chain cannot run between two of them.
    """
    clusters: List[List[Signal]] = []
    for s in sorted(signals, key=lambda x: x.t):
        if clusters and s.t - clusters[-1][-1].t <= window:
            clusters[-1].append(s)
        else:
            clusters.append([s])
    return clusters


def _fuse_cluster(cluster: Sequence[Signal]) -> FusedEvent:
    """
    Collapse one cluster into an event.

    Confidence combines as noisy-OR across *distinct* detectors: independent
    sources each providing partial evidence should reinforce, while one detector
    firing repeatedly inside a window must not stack with itself into false
    certainty.
    """
    best_per_detector: Dict[str, Signal] = {}
    for s in cluster:
        prev = best_per_detector.get(s.detector)
        if prev is None or s.confidence > prev.confidence:
            best_per_detector[s.detector] = s

    miss = 1.0
    for s in best_per_detector.values():
        miss *= (1.0 - max(0.0, min(1.0, s.confidence)))
    confidence = 1.0 - miss

    # Timestamp is weighted by timing precision, not by confidence: inverse
    # variance, so the detector that knows *when* best sets the moment even if
    # another is surer the event happened at all.
    weights = [1.0 / max(s.time_sigma, 1e-3) ** 2 for s in best_per_detector.values()]
    total = sum(weights) or 1.0
    t = sum(s.t * w for s, w in zip(best_per_detector.values(), weights)) / total

    return FusedEvent(
        t=t,
        confidence=confidence,
        signals=tuple(sorted(cluster, key=lambda s: (s.detector, s.t))),
    )


def fuse(
    detectors: Sequence[Detector],
    profile: StreamProfile,
    window: float = AGREEMENT_WINDOW_SEC,
    min_confidence: float = MIN_FUSED_CONFIDENCE,
) -> FusionReport:
    """
    Run every detector the stream supports and merge what they report.

    A detector may return None to abstain, which is materially different from
    returning no signals: abstaining says "I cannot judge this stream", and it
    must not count against the result or appear in agreement statistics.
    """
    eligible, skipped = select_detectors(detectors, profile)
    for name, why in skipped.items():
        logger.info("detector %s skipped: %s", name, why)

    collected: List[Signal] = []
    abstained: List[str] = []
    uncalibrated: List[str] = []
    emitted: Dict[str, int] = {}
    for d in eligible:
        produced = d.run()
        if produced is None:
            abstained.append(d.name)
            logger.info("detector %s abstained", d.name)
            continue
        emitted[d.name] = len(produced)
        if d.calibrated:
            collected.extend(produced)
        else:
            uncalibrated.append(d.name)
            collected.extend(
                Signal(s.detector, s.t, UNCALIBRATED_CONFIDENCE, s.time_sigma,
                       {**s.evidence, "raw_confidence": s.confidence})
                for s in produced
            )

    events = [
        ev for ev in (_fuse_cluster(c) for c in _cluster(collected, window))
        if ev.confidence >= min_confidence
    ]

    # How often each detector's signals ended up on a reported event. Not used
    # to weight anything yet -- this is the measurement that has to exist before
    # weighting is anything other than a guess.
    landed: Dict[str, int] = {name: 0 for name in emitted}
    for ev in events:
        for name in set(ev.detectors):
            landed[name] = landed.get(name, 0) + 1
    agreement = {
        name: (landed.get(name, 0) / count if count else 0.0)
        for name, count in emitted.items()
    }

    return FusionReport(
        events=sorted(events, key=lambda e: e.t),
        eligible=[d.name for d in eligible],
        skipped=skipped,
        abstained=abstained,
        uncalibrated=uncalibrated,
        agreement_rate=agreement,
    )
