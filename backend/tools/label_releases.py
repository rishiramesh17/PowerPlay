"""
Cut short clips around each delivery so release times can be hand-labelled.

The pipeline can say a ball was bowled and cannot say when. The scoreboard tick
trails the delivery by a lag measured on exactly two balls -- 3.4s on a defended
ball, 10.9s on a six -- and `SCOREBOARD_LAG_SEC` is the midpoint of those two
numbers, which is a guess wearing a constant's clothing.

Two things need settling, and one is far more interesting than the other:

  1. What the lag actually is.
  2. Whether it depends on the OUTCOME. The six was slow because the camera
     tracked it to the rope before the operator updated. If that holds, then
     since the board already tells us the outcome, each ball can be corrected
     individually instead of every ball receiving the same average.

So the sample is stratified by outcome rather than taken in order: labelling
fifteen consecutive singles would measure the lag precisely and say nothing
about what drives it.

    # 1. cut the clips and write a template to fill in
    python -m tools.label_releases clips \
        --video downloads/match.mp4 \
        --ground-truth reports/gt_milc_y7L8tkw4aQI_18_45.json \
        --out-dir outputs/labelling

    # 2. watch each clip, read the burnt-in timestamp at the moment of release,
    #    type it into labels.json

    # 3. measure
    python -m tools.label_releases analyse --labels outputs/labelling/labels.json

Each clip has the absolute video timestamp burnt into the corner, so the number
to record is read off the screen rather than computed from a seek bar. Getting
that arithmetic wrong by a few seconds would corrupt the very quantity being
measured, and would do so invisibly.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing.scoreboard import build_timeline  # noqa: E402
from processing.scoreboard_detect import SCOREBOARD_LAG_SEC  # noqa: E402

#: Seconds before the scoreboard tick to start each clip. Must comfortably
#: exceed the largest plausible lag, or the release happens before the clip does
#: and the label is silently impossible to give.
LEAD_SEC = 22.0

#: Seconds after the tick to keep, for context on what the ball did.
TRAIL_SEC = 4.0

#: A usable timestamp font. macOS ships both; the first that exists is used.
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _font() -> Optional[str]:
    return next((f for f in FONT_CANDIDATES if Path(f).exists()), None)


def outcome_of(delta: int, wicket: bool) -> str:
    """Bucket a delivery by what it did, which is the hypothesised driver of lag."""
    if wicket:
        return "wicket"
    return {0: "dot", 1: "single", 2: "two", 3: "three", 4: "four", 6: "six"}.get(
        delta, f"+{delta}")


def deliveries_from(gt: Dict, step: float) -> List[Dict]:
    """Every delivery the board saw, tagged with its outcome."""
    timeline = build_timeline(list(gt["samples"]), step=step)
    out: List[Dict] = []
    prev = None
    for row in timeline.rows:
        if prev is not None and row["balls"] > prev["balls"] and row["innings"] == prev["innings"]:
            out.append({
                "ball": row["balls"],
                "tick_t": row["t"],
                "runs_delta": row["runs"] - prev["runs"],
                "outcome": outcome_of(row["runs"] - prev["runs"],
                                      row["wickets"] > prev["wickets"]),
            })
        prev = row
    return out


def stratify(deliveries: List[Dict], per_bucket: int) -> List[Dict]:
    """
    Take a spread across outcomes rather than the first N.

    Rare outcomes are the informative ones: there may be one wicket and three
    sixes in a window, and those are precisely the balls expected to lag most.
    Sampling in order would fill the budget with singles.
    """
    buckets: Dict[str, List[Dict]] = defaultdict(list)
    for d in deliveries:
        buckets[d["outcome"]].append(d)
    picked: List[Dict] = []
    for name in sorted(buckets):
        group = buckets[name]
        # Spread within the bucket too, so the sample is not all from one over.
        stride = max(1, len(group) // per_bucket)
        picked.extend(group[::stride][:per_bucket])
    return sorted(picked, key=lambda d: d["tick_t"])


def cut_clips(video: Path, picks: List[Dict], out_dir: Path) -> List[Dict]:
    """Write one clip per delivery, with the absolute video time burnt in."""
    out_dir.mkdir(parents=True, exist_ok=True)
    font = _font()
    if not font:
        raise RuntimeError(
            "no usable font found for the timestamp overlay; without it the clips "
            "cannot be labelled, so this fails rather than writing unusable video"
        )

    rows: List[Dict] = []
    for i, d in enumerate(picks, 1):
        start = max(0.0, d["tick_t"] - LEAD_SEC)
        name = f"{i:02d}_ball{d['ball']}_{d['outcome']}.mp4"
        dest = out_dir / name
        # `start` is added back to the clip-local clock so the burnt-in number is
        # a time in the ORIGINAL video -- the only frame of reference the rest of
        # the pipeline uses.
        label = (
            f"drawtext=fontfile={font}:"
            f"text='%{{eif\\:trunc({start}+t)\\:d}}.%{{eif\\:trunc(mod(({start}+t)*10,10))\\:d}}s':"
            "x=20:y=20:fontsize=48:fontcolor=yellow:box=1:boxcolor=black@0.6:boxborderw=10"
        )
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(video),
             "-t", f"{LEAD_SEC + TRAIL_SEC:.2f}", "-vf", label,
             "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", str(dest)],
            check=True,
        )
        rows.append({
            "clip": name,
            "ball": d["ball"],
            "outcome": d["outcome"],
            "runs_delta": d["runs_delta"],
            "tick_t": d["tick_t"],
            # The thing to fill in: the video time the ball leaves the hand.
            "release_t": None,
        })
    return rows


def analyse(labels: List[Dict]) -> Dict:
    """
    Turn filled labels into a lag measurement, per outcome and overall.

    Reports the per-outcome spread because that is the decision: if the buckets
    separate, the lag is predictable from something already known and should be
    corrected per ball. If they overlap, one constant is all the data supports.
    """
    done = [r for r in labels if r.get("release_t") is not None]
    if not done:
        return {"error": "no labels filled in yet"}

    for r in done:
        r["lag"] = r["tick_t"] - r["release_t"]

    by_outcome: Dict[str, List[float]] = defaultdict(list)
    for r in done:
        by_outcome[r["outcome"]].append(r["lag"])

    lags = [r["lag"] for r in done]
    result = {
        "n": len(done),
        "overall": {
            "mean": statistics.mean(lags),
            "median": statistics.median(lags),
            "sd": statistics.pstdev(lags) if len(lags) > 1 else 0.0,
            "min": min(lags),
            "max": max(lags),
        },
        "by_outcome": {
            k: {"n": len(v), "mean": statistics.mean(v),
                "sd": statistics.pstdev(v) if len(v) > 1 else 0.0}
            for k, v in sorted(by_outcome.items())
        },
        "current_constant": SCOREBOARD_LAG_SEC,
    }

    # Does knowing the outcome buy anything? Compare the spread left after
    # correcting per bucket against the spread left by a single constant. Only
    # meaningful once several buckets have more than one sample in them.
    usable = {k: v for k, v in by_outcome.items() if len(v) > 1}
    if len(usable) > 1:
        overall_sd = statistics.pstdev(lags)
        residuals = [x - statistics.mean(v) for v in usable.values() for x in v]
        within_sd = statistics.pstdev(residuals) if len(residuals) > 1 else 0.0
        result["outcome_dependence"] = {
            "sd_one_constant": overall_sd,
            "sd_per_outcome": within_sd,
            "improvement": (overall_sd - within_sd) / overall_sd if overall_sd else 0.0,
        }
    return result


def _cmd_clips(args) -> int:
    gt = json.loads(Path(args.ground_truth).read_text())
    deliveries = deliveries_from(gt, args.step)
    picks = stratify(deliveries, args.per_outcome)
    print(f"{len(deliveries)} deliveries available; sampling {len(picks)}")
    for d in picks:
        print(f"  ball {d['ball']:>3}  tick {d['tick_t']:>7.1f}s  {d['outcome']}")

    out_dir = Path(args.out_dir)
    rows = cut_clips(Path(args.video), picks, out_dir)
    labels_path = out_dir / "labels.json"
    labels_path.write_text(json.dumps(rows, indent=1))

    print(f"\nwrote {len(rows)} clips to {out_dir}/")
    print(f"fill in `release_t` for each entry in {labels_path}")
    print("\nFor each clip: play it, find the frame the ball leaves the bowler's")
    print("hand, and type the yellow number in the corner into `release_t`.")
    print("Leave any you cannot judge as null -- a guess is worse than a gap.")
    return 0


def _cmd_analyse(args) -> int:
    labels = json.loads(Path(args.labels).read_text())
    result = analyse(labels)
    if "error" in result:
        print(result["error"])
        return 1

    o = result["overall"]
    print(f"labelled {result['n']} deliveries")
    print(f"\nlag overall: mean {o['mean']:.1f}s  median {o['median']:.1f}s  "
          f"sd {o['sd']:.1f}s  range {o['min']:.1f}-{o['max']:.1f}s")
    print(f"current constant in code: {result['current_constant']}s")

    print(f"\n{'outcome':<10}{'n':>4}{'mean lag':>10}{'sd':>8}")
    for name, stats in result["by_outcome"].items():
        print(f"{name:<10}{stats['n']:>4}{stats['mean']:>10.1f}{stats['sd']:>8.1f}")

    dep = result.get("outcome_dependence")
    if dep:
        print(f"\none constant for all balls:  sd {dep['sd_one_constant']:.1f}s")
        print(f"corrected per outcome:       sd {dep['sd_per_outcome']:.1f}s")
        print(f"improvement: {dep['improvement']:.0%}")
        if dep["improvement"] > 0.25:
            print("\n-> outcome predicts lag. Correct per ball; the board already")
            print("   reports the outcome, so this costs nothing at runtime.")
        else:
            print("\n-> outcome does not explain the spread. Keep one constant,")
            print("   set to the measured median, and leave time_sigma wide.")
    else:
        print("\n(need >1 sample in at least two outcome buckets to test whether")
        print(" outcome predicts lag)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("clips", help="cut labelling clips and write a template")
    c.add_argument("--video", required=True)
    c.add_argument("--ground-truth", required=True)
    c.add_argument("--out-dir", default="outputs/labelling")
    c.add_argument("--per-outcome", type=int, default=3,
                   help="deliveries to sample per outcome bucket")
    c.add_argument("--step", type=float, default=3.0)
    c.set_defaults(func=_cmd_clips)

    a = sub.add_parser("analyse", help="measure the lag from filled labels")
    a.add_argument("--labels", required=True)
    a.set_defaults(func=_cmd_analyse)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
