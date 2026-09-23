#!/usr/bin/env python3
"""
Derive delivery and scoring ground truth from a broadcast scoreboard.

Every detector change needs a benchmark to be scored against, and hand-labelling
deliveries is the kind of work nobody does twice. The scoreboard already encodes
the answer: the over counter increments once per legal delivery, and the team
score increments by exactly the runs conceded. Reading both on a fixed cadence
turns a match into a labelled timeline for the cost of an OCR pass.

    python tools/build_ground_truth.py downloads/match.mp4 \
        --start 900 --end 14200 --out reports/gt_match.json

What this is NOT: a delivery *timer*. The counter ticks when the graphics
operator updates it, which trails the ball by anywhere from two seconds to more
than ten (a six is only logged after the ball has been tracked to the rope and
signalled). Use these timestamps to count deliveries and to label outcomes --
never to measure release-time localisation error. See `timing_caveat` in the
emitted JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Where the score block sits in a 1280x720 broadcast frame. This is the one
# genuinely broadcaster-specific constant in here; a different producer means a
# different crop, which is why it is exposed as a flag rather than buried.
DEFAULT_ROI = (430, 610, 880, 670)  # x1, y1, x2, y2

# Parsing, cleaning and the occlusion/staleness guard live in
# processing.scoreboard so the pipeline can use them too -- this tool is only
# one caller, and the rules there are load-bearing for both.
from processing.scoreboard import (  # noqa: E402
    MAX_RUNS_PER_BALL,
    RESET_BALL_CEILING,
    RESET_BALL_DROP,
    RESET_CONFIRM_SAMPLES,
    build_timeline,
    is_innings_reset as _is_innings_reset,
    parse_scoreboard,
)






def extract_crops(
    video: Path,
    start: float,
    end: float,
    step: float,
    roi: Tuple[int, int, int, int],
    upscale: int,
    out_dir: Path,
) -> List[Path]:
    """
    Dump the upscaled score block once every `step` seconds, via one ffmpeg pass.

    Seeking per sample is the obvious implementation and is unusably slow: random
    access into a multi-gigabyte H.264 file costs far more than decoding it
    straight through, and a four-hour match measured out at ~4.8 hours of
    scanning. One sequential pass that crops and decimates in the filter graph
    turns the same work into minutes, because ffmpeg never hands full frames back
    across a process boundary.
    """
    x1, y1, x2, y2 = roi
    out_dir.mkdir(parents=True, exist_ok=True)
    vf = (
        f"crop={x2 - x1}:{y2 - y1}:{x1}:{y1},"
        f"scale=iw*{upscale}:ih*{upscale}:flags=bicubic,"
        f"fps=1/{step}"
    )
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-ss", str(start), "-to", str(end),   # before -i: seek, don't decode-and-drop
        "-i", str(video),
        "-vf", vf, "-fps_mode", "passthrough",
        str(out_dir / "%06d.png"),
    ]
    print("  extracting crops with ffmpeg...", flush=True)
    subprocess.run(cmd, check=True)
    return sorted(out_dir.glob("*.png"))


def scan(
    video: Path,
    start: float,
    end: float,
    step: float,
    roi: Tuple[int, int, int, int],
    upscale: int,
) -> List[dict]:
    """OCR the score block every `step` seconds between `start` and `end`."""
    import easyocr  # imported late: pulls in torch, and --help should stay fast

    with tempfile.TemporaryDirectory(prefix="pp_gt_") as tmp:
        crops = extract_crops(video, start, end, step, roi, upscale, Path(tmp))
        print(f"  {len(crops)} crops -> OCR", flush=True)
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        samples: List[dict] = []
        for i, crop_path in enumerate(crops):
            img = cv2.imread(str(crop_path))
            if img is None:
                continue
            flat = " ".join(w[1] for w in reader.readtext(img)).upper()
            parsed = parse_scoreboard(flat)
            samples.append(
                {
                    # ffmpeg emits the first frame at `start`, then one per step.
                    "t": round(start + i * step, 2),
                    "runs": parsed[0] if parsed else None,
                    "wickets": parsed[1] if parsed else None,
                    "balls": parsed[2] if parsed else None,
                    "layout": parsed[3] if parsed else None,
                    # Kept so the pattern can be fixed and the match re-derived
                    # offline. Recovering this cost a full 25-minute rescan once.
                    "raw": flat[:90],
                }
            )
            if (i + 1) % 200 == 0:
                print(f"  {i + 1}/{len(crops)} OCR'd", flush=True)
    return samples


def clean(samples: List[dict]) -> List[dict]:
    """Cleaned rows from the shared timeline builder, tagged with innings."""
    return build_timeline(samples, step=3.0).rows


def derive(rows: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Turn a cleaned timeline into delivery and scoring-event lists."""
    deliveries: List[dict] = []
    events: List[dict] = []
    prev: Optional[dict] = None
    for row in rows:
        # Never diff across the innings break: the new side starting at 0 would
        # otherwise read as the old side losing its entire score.
        if prev is not None and row.get("innings") != prev.get("innings"):
            prev = row
            continue
        if prev is not None:
            if row["balls"] > prev["balls"]:
                # The counter may advance more than one ball between samples;
                # only the last is locatable, so record that one.
                deliveries.append(
                    {
                        "t": row["t"],
                        "balls_bowled": row["balls"],
                        "innings": row.get("innings", 0),
                    }
                )
            delta = row["runs"] - prev["runs"]
            if delta > 0:
                events.append(
                    {
                        "t": row["t"],
                        "delta": delta,
                        "runs": row["runs"],
                        "type": {4: "FOUR", 6: "SIX"}.get(delta, f"+{delta}"),
                        "innings": row.get("innings", 0),
                    }
                )
            if row["wickets"] > prev["wickets"]:
                events.append(
                    {
                        "t": row["t"],
                        "delta": 0,
                        "runs": row["runs"],
                        "type": "WICKET",
                        "innings": row.get("innings", 0),
                    }
                )
        prev = row
    return deliveries, events


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("video", type=Path)
    p.add_argument("--start", type=float, default=0.0, help="seconds into the file")
    p.add_argument("--end", type=float, required=True)
    p.add_argument("--step", type=float, default=3.0, help="OCR cadence in seconds")
    p.add_argument("--upscale", type=int, default=3)
    p.add_argument("--roi", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"),
                   default=list(DEFAULT_ROI))
    p.add_argument("--source", default="", help="recorded in the output for provenance")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()

    print(f"scanning {a.video.name} {a.start:.0f}-{a.end:.0f}s @ {a.step}s", flush=True)
    samples = scan(a.video, a.start, a.end, a.step, tuple(a.roi), a.upscale)
    rows = clean(samples)
    deliveries, events = derive(rows)

    parsed = sum(1 for s in samples if s["balls"] is not None)
    from collections import Counter
    layouts = dict(Counter(s["layout"] for s in samples if s.get("layout")))
    boundaries = [e for e in events if e["type"] in ("FOUR", "SIX")]
    payload = {
        "source": a.source or str(a.video),
        "window": {"start_sec": a.start, "end_sec": a.end, "step_sec": a.step},
        "roi": list(a.roi),
        "layouts_matched": layouts,
        "derivation": f"scoreboard OCR @{a.step}s ({parsed}/{len(samples)} parsed, "
                      f"{len(rows)} survived cleaning)",
        "timing_caveat": (
            "Timestamps are when the scoreboard was UPDATED, not when the ball was "
            "bowled. Measured lag on this broadcast ranges from ~2s on a dot to "
            "~11s on a six, because the graphics follow ball-tracking and the "
            "umpire signal. Valid for counting and outcome labels; invalid as a "
            "release-time benchmark."
        ),
        "caveats": [
            "extras (wides, no-balls) do not increment the over counter, so legal "
            "deliveries are counted but total balls faced is undercounted",
            f"sampling is {a.step}s, so every timestamp carries at least that much "
            "quantisation error on top of the update lag",
            "the ROI is broadcaster-specific and hardcoded per source",
        ],
        "totals": {
            "deliveries": len(deliveries),
            "scoring_events": len(events),
            "boundaries": len(boundaries),
            "wickets": sum(1 for e in events if e["type"] == "WICKET"),
            "innings": len({r.get("innings", 0) for r in rows}),
        },
        # The raw per-sample readings, kept deliberately. Deriving deliveries
        # from them is milliseconds; re-OCRing a four-hour match to try a
        # different cleaning rule is half an hour, and the first version of that
        # rule silently dropped an entire innings.
        "samples": samples,
        "deliveries": deliveries,
        "scoring_events": events,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=1))
    print(f"\nparsed {parsed}/{len(samples)}, {len(rows)} usable")
    print(f"deliveries={len(deliveries)} events={len(events)} "
          f"boundaries={len(boundaries)} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
