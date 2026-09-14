#!/usr/bin/env python3
"""
Inspect and split the re-ID dataset that identity reviews accumulate.

The dataset grows one review at a time, invisibly, which makes "do I have enough
to train yet?" the question this tool exists to answer.

    python tools/reid_dataset.py stats
    python tools/reid_dataset.py split --val-fraction 0.2 --seed 0

`PP_REID_DATASET_DIR` overrides the location (default `datasets/reid`).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

# Make backend package imports work regardless of cwd.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from processing.ml.identity_labels import (  # noqa: E402
    LABELS_FILENAME,
    dataset_root,
    load_labels,
    split_by_job,
    summarize,
)

#: Below this, a trained embedding is measuring noise. Not a hard gate — just the
#: number to aim at before spending a weekend on training code.
USABLE_ROW_TARGET = 400
USABLE_JOB_TARGET = 50


def cmd_stats(root: Optional[Path]) -> int:
    rows = load_labels(root)
    base = dataset_root(root)
    if not rows:
        print(f"No labels yet at {base / LABELS_FILENAME}.")
        print("Run a job with require_review=true and answer the confirmation step.")
        return 0

    stats = summarize(rows, root)
    print(json.dumps(stats, indent=2))

    decisions = Counter(r.get("decision") for r in rows)
    print("\nBy decision: " + ", ".join(f"{k}={v}" for k, v in sorted(decisions.items(), key=str)))

    actions = Counter(r.get("action") for r in rows)
    print("By action:   " + ", ".join(f"{k}={v}" for k, v in sorted(actions.items(), key=str)))

    if stats["missing_crops"]:
        print(
            f"\n⚠️  {stats['missing_crops']} row(s) point at a crop that no longer "
            "exists. Those rows cannot be trained on."
        )

    # Negatives are the scarce half: they only appear when a user strikes out a
    # crop or rejects a run, and an embedding trained on positives alone learns
    # nothing about the lookalike it keeps drifting onto.
    if stats["negatives"] == 0:
        print("\n⚠️  No negatives yet — every review so far was a clean approval.")

    remaining_rows = max(0, USABLE_ROW_TARGET - stats["rows"])
    remaining_jobs = max(0, USABLE_JOB_TARGET - stats["jobs"])
    if remaining_rows or remaining_jobs:
        print(
            f"\nProgress toward a trainable set: {stats['rows']}/{USABLE_ROW_TARGET} rows, "
            f"{stats['jobs']}/{USABLE_JOB_TARGET} jobs."
        )
    else:
        print("\nEnough data to attempt a first embedding.")
    return 0


def cmd_split(root: Optional[Path], val_fraction: float, seed: int) -> int:
    rows = load_labels(root)
    if not rows:
        print("Nothing to split — the dataset is empty.")
        return 1

    base = dataset_root(root)
    parts = split_by_job(rows, val_fraction=val_fraction, seed=seed)
    for name, part in parts.items():
        path = base / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for row in part:
                fh.write(json.dumps(row) + "\n")
        jobs = len({r.get("job_id") for r in part})
        positives = sum(1 for r in part if r.get("label") == "positive")
        print(f"{path}: {len(part)} rows, {jobs} jobs, {positives} positive")

    if not parts["val"]:
        print(
            "\n⚠️  Validation split is empty: there are too few distinct jobs to "
            "hold any out without emptying training."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=None, help="Dataset directory override")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Counts, coverage, and whether there is enough to train")

    split = sub.add_parser("split", help="Write train.jsonl / val.jsonl, grouped by job")
    split.add_argument("--val-fraction", type=float, default=0.2)
    split.add_argument("--seed", type=int, default=0)

    args = parser.parse_args()
    if args.command == "stats":
        return cmd_stats(args.root)
    return cmd_split(args.root, args.val_fraction, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
