"""
Measure the scoreboard reader against a source it did not produce.

Every accuracy figure this project had for the scoreboard reader was circular:
the ground truth was OCR output, so the reader was grading its own homework. The
fusion layer's calibration contract exists precisely to refuse numbers like that,
and it was correctly refusing this one -- at the cost of the reader's entire
recall contribution.

A CricClubs ball-by-ball page breaks the circle. It is produced by a human scorer
sitting at the ground, independently of the broadcast graphics the reader parses,
and it lists every delivery with its outcome.

    python -m tools.calibrate_scoreboard \
        --scorecard "~/Downloads/match.html" \
        --ground-truth reports/gt_milc_y7L8tkw4aQI_18_45.json

What it can and cannot settle:

  CAN  -- whether the reader counts deliveries correctly, which is the only
          thing the fusion layer asks of it.
  CANNOT -- the graphics lag. Scorecard clocks are minute-resolution and carry
          the scorer's own delay on top; measured offsets on this match spread
          over 177 seconds. SCOREBOARD_LAG_SEC stays provisional until somebody
          hand-labels releases against video.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing.scoreboard import build_timeline  # noqa: E402

#: A delivery block in the CricClubs markup: the over.ball label, the commentary
#: line, and the wall-clock stamp. Matched structurally rather than by class name
#: soup, so a styling change does not silently return zero deliveries -- an empty
#: parse is treated as a hard error below for the same reason.
DELIVERY_BLOCK = re.compile(
    r'<div class="text-md font-semibold">(\d{1,2}\.\d)</div>.*?'
    r'<div class="text-md text-gray-900[^"]*">(.*?)</div>.*?'
    r'<span>(\d{1,2}:\d{2}\s*[AP]M)</span>',
    re.S,
)

#: Runs credited to the batting side by a delivery description. Extras are
#: written as "WIDE" (one run) or "N WIDES", and a no-ball that is hit reads
#: "5 runs FOUR NO BALL" -- the four plus the penalty, already summed.
_RUNS = re.compile(r",\s*(\d+)\s*runs?\b", re.I)
_MULTI_WIDE = re.compile(r"\b(\d+)\s*wides\b", re.I)
_WIDE = re.compile(r"\bwide\b", re.I)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _runs_scored(desc: str) -> int:
    total = 0
    m = _RUNS.search(desc)
    if m:
        total += int(m.group(1))
    multi = _MULTI_WIDE.search(desc)
    if multi:
        total += int(multi.group(1))
    elif _WIDE.search(desc):
        total += 1
    return total


def _is_extra(desc: str) -> bool:
    """Wides and no-balls do not advance the ball counter."""
    upper = desc.upper()
    return "WIDE" in upper or "NO BALL" in upper or "NOBALL" in upper


def parse_scorecard(markup: str) -> List[Dict]:
    """
    Walk a saved ball-by-ball page into a per-legal-delivery timeline.

    Returns cumulative runs and wickets after each legal ball, which is what the
    broadcast scoreboard is displaying and therefore the only basis on which the
    reader's output can be checked.
    """
    balls = runs = wickets = 0
    timeline: List[Dict] = []
    for match in DELIVERY_BLOCK.finditer(markup):
        over_ball, desc = match.group(1), _text(match.group(2))
        runs += _runs_scored(desc)
        if "OUT!" in desc.upper():
            wickets += 1
        if _is_extra(desc):
            continue
        balls += 1
        timeline.append({
            "balls": balls,
            "over_ball": over_ball,
            "runs": runs,
            "wickets": wickets,
            "clock": match.group(3).strip(),
            "desc": desc,
        })
    if not timeline:
        raise ValueError(
            "no deliveries found -- the page markup has changed, or the save "
            "captured a Cloudflare challenge rather than the scorecard"
        )
    return timeline


def wilson_lower(successes: int, trials: int, z: float = 1.96) -> float:
    """
    Lower bound of the 95% confidence interval for a proportion.

    A perfect score on a small sample is not evidence of perfection, and this is
    the number that says so: 29 for 29 supports a true rate of 0.88, not 1.00.
    Using the point estimate as a confidence would be exactly the overclaiming
    the calibration contract exists to prevent.
    """
    if trials == 0:
        return 0.0
    p = successes / trials
    d = 1 + z * z / trials
    centre = p + z * z / (2 * trials)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * trials)) / trials)
    return max(0.0, (centre - margin) / d)


def compare(timeline_rows: List[Dict], truth: List[Dict]) -> Dict:
    """
    Score the reader's delivery count against the scorecard.

    Only the span the reader actually observed is judged. Deliveries outside the
    analysed video window are not misses -- the reader was never shown them, and
    counting them would make the window length the thing being measured.
    """
    by_ball: Dict[int, Dict] = {row["balls"]: row for row in truth}
    claimed = sorted({row["balls"] for row in timeline_rows})
    if not claimed:
        return {"error": "reader produced no readings"}

    lo, hi = claimed[0], claimed[-1]
    expected = [n for n in range(lo, hi + 1) if n in by_ball]

    missed = [n for n in expected if n not in claimed]
    spurious = [n for n in claimed if n not in by_ball]

    first_seen: Dict[int, float] = {}
    for row in timeline_rows:
        first_seen.setdefault(row["balls"], row["t"])

    runs_ok, runs_bad = [], []
    for n in claimed:
        if n not in by_ball:
            continue
        read = {row["runs"] for row in timeline_rows if row["balls"] == n}
        (runs_ok if by_ball[n]["runs"] in read else runs_bad).append(n)

    found = len(expected) - len(missed)
    return {
        "window_balls": [lo, hi],
        "expected": len(expected),
        "found": found,
        "missed": missed,
        "spurious": spurious,
        "recall": found / len(expected) if expected else 0.0,
        "precision": (len(claimed) - len(spurious)) / len(claimed),
        "recall_lower_95": wilson_lower(found, len(expected)),
        "runs_agree": len(runs_ok),
        "runs_disagree": runs_bad,
        "first_seen": first_seen,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scorecard", required=True, help="saved CricClubs ball-by-ball HTML")
    ap.add_argument("--ground-truth", required=True, help="gt_*.json from build_ground_truth")
    ap.add_argument("--step", type=float, default=3.0, help="OCR sampling interval, seconds")
    ap.add_argument("--out", help="write the parsed scorecard timeline here")
    args = ap.parse_args(argv)

    markup = Path(args.scorecard).expanduser().read_text(encoding="utf-8", errors="replace")
    truth = parse_scorecard(markup)

    gt = json.loads(Path(args.ground_truth).read_text())
    timeline = build_timeline(list(gt["samples"]), step=args.step)
    result = compare(timeline.rows, truth)

    print(f"scorecard: {len(truth)} legal deliveries, overs "
          f"{truth[0]['over_ball']}-{truth[-1]['over_ball']}")
    print(f"reader:    {timeline.summary()}")
    print()
    lo, hi = result["window_balls"]
    print(f"window judged: balls {lo}-{hi} ({result['expected']} deliveries)")
    print(f"  recall    {result['recall']:.3f}  ({result['found']}/{result['expected']}"
          f", 95% CI lower bound {result['recall_lower_95']:.3f})")
    print(f"  precision {result['precision']:.3f}")
    if result["missed"]:
        print(f"  MISSED deliveries: {result['missed']}")
    if result["spurious"]:
        print(f"  SPURIOUS ball numbers: {result['spurious']}")
    print(f"  runs reading agrees on {result['runs_agree']}/"
          f"{result['expected']} balls; disagrees on {result['runs_disagree']}")

    if args.out:
        Path(args.out).write_text(json.dumps({
            "source": args.scorecard,
            "deliveries": truth,
            "comparison": {k: v for k, v in result.items() if k != "first_seen"},
        }, indent=1))
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
