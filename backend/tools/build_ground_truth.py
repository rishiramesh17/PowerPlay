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

# Where the score block sits in a 1280x720 broadcast frame. This is the one
# genuinely broadcaster-specific constant in here; a different producer means a
# different crop, which is why it is exposed as a flag rather than buried.
DEFAULT_ROI = (430, 610, 880, 670)  # x1, y1, x2, y2

# Broadcasters do not share a scoreboard layout, so the parser carries one entry
# per vendor and tries each in turn. Two are confirmed from real footage:
#
#   CricCenter (MLC U21, college cricket):  "SLA V BRO 91 - 3  12.1 OVERS"
#   CricClubs  (Minor League Cricket):      "MPT 80/0 RR 16.55 OVERS 4.5"
#
# The hypothesis that one template would cover the market was wrong: three
# broadcasts, two vendors, and the senior league uses the one the original
# pattern cannot read at all.


def _parse_overs(whole: str, frac: Optional[str]) -> Optional[int]:
    """
    Turn an over reading into a count of legal deliveries.

    The decimal point is the first thing OCR loses at this size -- "3.1" comes
    back as "31" and "4.0" as "4" -- so when it is missing the last digit is
    treated as balls-within-the-over, which is only valid for 0-5. A reading
    that cannot be interpreted that way is rejected rather than guessed at.
    """
    if frac is not None:
        balls = int(frac)
        return int(whole) * 6 + balls if balls <= 5 else None
    digits = whole
    if len(digits) == 1:
        return int(digits) * 6
    over, balls = int(digits[:-1]), int(digits[-1])
    if balls <= 5 and over <= MAX_OVERS:
        return over * 6 + balls
    return None


#: No limited-overs innings runs longer than this, so a larger "over number" is
#: a misread rather than a match.
MAX_OVERS = 50


@dataclass(frozen=True)
class ScoreboardLayout:
    """One broadcaster's way of writing the score."""

    name: str
    pattern: "re.Pattern[str]"
    #: Group indices for runs, wickets, whole overs, fractional overs.
    groups: Tuple[int, int, int, int]


LAYOUTS: Tuple[ScoreboardLayout, ...] = (
    # "91 - 3  12.1 OVERS". The separator is one glyph and OCR renders it as
    # -, I, ~, O, C, F and sometimes a digit, so it is matched as a single
    # throwaway token and the match is anchored on the rigid "N.N OVERS" tail.
    # Making it optional once let "66 2 2 10.0 OVERS" match at the second 2 and
    # report a score of 2, alternating with the correct parse.
    ScoreboardLayout(
        "criccenter",
        re.compile(r"(\d{1,3})\s*\S?\s*(\d)\s+(\d{1,2})\s*[.,]\s*(\d)\s*OVERS", re.I),
        (1, 2, 3, 4),
    ),
    # "MPT 80/0 RR 16.55 OVERS 4.5". Runs and overs sit on separate rows with a
    # run rate between them, so the gap is matched permissively -- it contains
    # digits, which a \D run cannot cross.
    ScoreboardLayout(
        "cricclubs",
        re.compile(r"(\d{1,3})\s*/\s*(\d).{0,40}?OVERS\s*(\d{1,3})(?:\s*[.,]\s*(\d))?", re.I),
        (1, 2, 3, 4),
    ),
)


def parse_scoreboard(flat: str) -> Optional[Tuple[int, int, int, str]]:
    """First layout that reads this text: (runs, wickets, balls, layout name)."""
    for layout in LAYOUTS:
        m = layout.pattern.search(flat)
        if not m:
            continue
        gr, gw, go, gf = layout.groups
        balls = _parse_overs(m.group(go), m.group(gf))
        if balls is None:
            continue
        return int(m.group(gr)), int(m.group(gw)), balls, layout.name
    return None


#: A batting side's score never falls, and no single delivery yields more than 7
#: (six plus an overthrow). Anything outside that is an OCR misread, not cricket.
MAX_RUNS_PER_BALL = 7

#: How far the ball counter must fall to count as an innings change rather than
#: a misread digit. Comfortably above OCR jitter, far below an innings length.
RESET_BALL_DROP = 12

#: ...and where it must land. A new innings starts near zero; a garbled reading
#: of "11.4 OVERS" does not.
RESET_BALL_CEILING = 12

#: Consecutive low readings required before believing an innings actually
#: changed. A real break lasts minutes -- dozens of samples; a misread lasts one.
#: Without this, a single bad frame at ball 60 split one innings into two.
RESET_CONFIRM_SAMPLES = 5


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


def _is_innings_reset(last: dict, cur: dict) -> bool:
    """
    A genuine innings change, as opposed to a one-off OCR misread.

    Both counters must fall together and land near zero. Requiring *both* is
    what separates a reset from a transposed digit, which moves one field only.
    """
    return (
        cur["balls"] < last["balls"] - RESET_BALL_DROP
        and cur["runs"] < last["runs"]
        and cur["balls"] <= RESET_BALL_CEILING
    )


def _reset_is_confirmed(samples: List[dict], at: dict) -> bool:
    """
    Does the low reading persist, or was it one bad frame?

    An innings break is minutes long, so the next several parsed samples must
    also read low. A transposed digit is gone by the next sample.
    """
    seen = 0
    for s in samples:
        if s["t"] <= at["t"] or s["balls"] is None:
            continue
        if s["balls"] > RESET_BALL_CEILING:
            return False
        seen += 1
        if seen >= RESET_CONFIRM_SAMPLES:
            return True
    return seen > 0


def clean(samples: List[dict]) -> List[dict]:
    """
    Drop physically impossible readings, and tag each with its innings.

    A single transposed digit (116 read as 16) would otherwise register as a
    hundred-run swing and manufacture dozens of phantom boundaries, so the
    monotonicity check matters more than the raw parse rate.

    The exception that has to be handled explicitly is the innings break, where
    both counters legitimately reset to zero. Treating that as a backwards
    scoreboard does not merely lose the break -- it strands the baseline at the
    first innings' closing score, so every later sample also reads as backwards
    and the whole second innings silently disappears. That is exactly what the
    first full-match scan did: 110 deliveries, every one of them from innings
    one, with no error anywhere to suggest half the match was missing.
    """
    out: List[dict] = []
    last: Optional[dict] = None
    innings = 0
    for s in samples:
        if s["runs"] is None or s["balls"] is None:
            continue
        if last is not None:
            balls_advanced = s["balls"] - last["balls"]
            runs_advanced = s["runs"] - last["runs"]
            if _is_innings_reset(last, s) and _reset_is_confirmed(samples, s):
                innings += 1
            elif balls_advanced < 0 or runs_advanced < 0:
                continue  # the scoreboard never goes backwards mid-innings
            # Innings are ~120 balls; a jump that large is a misread, not a gap.
            elif balls_advanced > 6 or runs_advanced > MAX_RUNS_PER_BALL * max(balls_advanced, 1):
                continue
        out.append({**s, "innings": innings})
        last = s
    return out


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
