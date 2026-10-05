"""
Capability eval 1: fusion must never underperform its best available detector.

Recorded as a script rather than an ad-hoc run because the first time this was
measured it failed, and a failing eval that cannot be re-run on demand is an
anecdote. See `.claude/evals/fusion-layer.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing import scoreboard_detect  # noqa: E402
from processing.delivery_detect import RUNUP_TIME_SIGMA  # noqa: E402
from processing.fusion import Detector, Signal, fuse  # noqa: E402
from processing.stream_profile import StreamProfile  # noqa: E402
from tools.calibrate_scoreboard import parse_scorecard  # noqa: E402

#: How close a reported event must be to a true delivery to count as finding it.
#: Wide enough to absorb the board's 3-11s graphics lag, since a detector should
#: not be marked wrong for an offset the pipeline already declares and corrects.
MATCH_WINDOW_SEC = 14.0


def score(events_t: List[float], truth_t: List[float]) -> Dict[str, float]:
    """Greedy one-to-one matching: no single detection may cover two deliveries."""
    unused = sorted(truth_t)
    hits = 0
    for t in sorted(events_t):
        for i, gt in enumerate(unused):
            if abs(t - gt) <= MATCH_WINDOW_SEC:
                hits += 1
                unused.pop(i)
                break
    return {
        "precision": hits / len(events_t) if events_t else 0.0,
        "recall": hits / len(truth_t) if truth_t else 0.0,
        "hits": hits,
        "reported": len(events_t),
        "truth": len(truth_t),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ground-truth", required=True)
    ap.add_argument("--scorecard", required=True)
    ap.add_argument("--vision", help="json list of detected release times")
    ap.add_argument("--step", type=float, default=3.0)
    args = ap.parse_args(argv)

    gt = json.loads(Path(args.ground_truth).read_text())
    samples = gt["samples"]

    board = scoreboard_detect.make_detector(samples, step=args.step)
    board_signals = list(board.run() or [])

    # Truth times: the board's own tick, lag-corrected. Independent of the
    # scorecard, which has no usable timestamps -- so this eval measures agreement
    # on *which* deliveries, with the window absorbing timing disagreement.
    truth_t = [s.t for s in board_signals if not s.evidence.get("occluded")]
    card = parse_scorecard(Path(args.scorecard).expanduser()
                           .read_text(encoding="utf-8", errors="replace"))
    print(f"scorecard confirms {len(card)} legal deliveries in the match")

    vision_t: List[float] = []
    if args.vision:
        vision_t = json.loads(Path(args.vision).read_text())

    def vision_run():
        return [
            Signal("vision", t, 0.5, time_sigma=RUNUP_TIME_SIGMA) for t in vision_t
        ]

    vision = Detector(name="vision", run=vision_run, calibrated=False)
    profile = StreamProfile(
        width=1920, height=1080, fps=30.0,
        duration_sec=max(s["t"] for s in samples),
        scoreboard_roi=tuple(gt["roi"]), scoreboard_confidence=1.0,
    )

    report = fuse([vision, board], profile)
    fused_t = [e.t for e in report.events]

    rows = [("vision standalone", score(vision_t, truth_t)) if vision_t else None,
            ("scoreboard standalone", score([s.t for s in board_signals], truth_t)),
            ("FUSED", score(fused_t, truth_t))]
    print(f"\n{'detector':<24}{'precision':>10}{'recall':>9}{'reported':>10}")
    for row in rows:
        if not row:
            continue
        name, m = row
        print(f"{name:<24}{m['precision']:>10.2f}{m['recall']:>9.2f}{m['reported']:>10}")
    print(f"\n{report.summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
