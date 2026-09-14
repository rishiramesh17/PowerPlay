# processing/ml/identity_labels.py
"""
Turn every identity review into a durable labelled example.

The review step already asks a human the one question a re-ID model needs
answered — "is this the same player?" — and until now that answer lived only in
the job row, next to crops sitting in `outputs/`, which is disposable scratch.
This module copies the crops somewhere permanent and appends one JSONL row per
candidate, so a few weeks of ordinary use accumulates the training set that
replaces the hand-tuned jersey/colour heuristics in `detect_player.py`.

Nothing here is allowed to break a user's job. A label that fails to write is a
lost training example; a review that fails to submit is a lost run, and the
second is far more expensive. Every entry point swallows its errors and logs.
"""
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

logger = logging.getLogger("processing.ml.identity_labels")

#: Bumped whenever the row shape changes, so an old file stays readable instead
#: of silently mixing two schemas in one training run.
SCHEMA_VERSION = 1

#: Kept out of `outputs/` deliberately: that directory holds rendered artifacts
#: and gets wiped without a second thought. This one is the dataset.
DEFAULT_DATASET_DIR = "datasets/reid"

LABELS_FILENAME = "labels.jsonl"
CROPS_SUBDIR = "crops"

#: The label a candidate carries into training.
POSITIVE = "positive"
NEGATIVE = "negative"


def dataset_root(override: Optional[Path] = None) -> Path:
    """Where the dataset lives. `PP_REID_DATASET_DIR` moves it off the app disk."""
    if override is not None:
        return Path(override)
    return Path(os.getenv("PP_REID_DATASET_DIR", DEFAULT_DATASET_DIR))


def labels_path(root: Optional[Path] = None) -> Path:
    return dataset_root(root) / LABELS_FILENAME


def label_for_candidate(
    candidate_id: str,
    approved: bool,
    rejected_ids: Sequence[str],
) -> str:
    """
    Decide what a single crop is worth as training data.

    An approved run means "yes, that is my player" for everything the user did
    *not* strike out, so the unstruck crops are positives and the struck ones are
    the hard negatives we care most about — same match, same kit, wrong person.

    A rejected run condemns the whole set regardless of what was struck out:
    the verdict was that the pipeline followed the wrong player throughout.
    """
    if not approved:
        return NEGATIVE
    return NEGATIVE if candidate_id in set(rejected_ids or ()) else POSITIVE


def _recorded_job_ids(path: Path) -> set:
    """
    Jobs already present in the file.

    The API returns 409 on a second decision, so a duplicate should be
    impossible — but a half-written file after a crash, or a future caller that
    replays decisions, must not double-count the same crops into the dataset.
    """
    if not path.exists():
        return set()

    seen = set()
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    seen.add(json.loads(line).get("job_id"))
                except json.JSONDecodeError:
                    # One corrupt line should not make the whole file unusable.
                    continue
    except OSError as exc:
        logger.warning(f"[identity_labels] Could not read {path}: {exc}")
    return seen


def _crop_source(candidate: Dict[str, Any], outputs_dir: Path) -> Optional[Path]:
    """
    Resolve a candidate's served URL back to the file on disk.

    Reading the URL rather than rebuilding the path keeps this working if the
    review layout ever changes: `/outputs/...` is the contract the browser is
    already relying on.
    """
    url = str(candidate.get("url") or "")
    prefix = "/outputs/"
    if not url.startswith(prefix):
        return None
    relative = url[len(prefix):]
    if not relative or ".." in relative:
        return None
    return Path(outputs_dir) / relative


def _player_descriptor(request: Dict[str, Any]) -> Dict[str, Any]:
    """The identity cues the user gave us, which a model conditions on."""
    player = request.get("player_data")
    return dict(player) if isinstance(player, dict) else {}


def _source_video(request: Dict[str, Any]) -> Optional[str]:
    """
    A stable handle for "which video did this crop come from".

    Only the basename of a local upload is kept: the absolute path is the
    worker's private filesystem layout, and grouping is all the dataset needs.
    """
    if request.get("youtube_url"):
        return str(request["youtube_url"])
    video_path = request.get("video_path")
    return Path(str(video_path)).name if video_path else None


def build_label_rows(
    job_id: str,
    review: Dict[str, Any],
    request: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Build one row per reviewed candidate. Pure — no filesystem, so it is testable
    and so a bad row can never leave a half-copied crop behind.
    """
    candidates = review.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return []

    decision = review.get("decision")
    if decision not in ("approved", "rejected"):
        # An undecided review carries no supervision; recording it would poison
        # the dataset with unlabelled rows that look labelled.
        return []

    approved = decision == "approved"
    rejected_ids = review.get("rejected_ids") or []
    player = _player_descriptor(request)
    source_video = _source_video(request)
    now = time.time()

    rows: List[Dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("id") or "")
        if not candidate_id:
            continue
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "job_id": job_id,
                "candidate_id": candidate_id,
                "label": label_for_candidate(candidate_id, approved, rejected_ids),
                "decision": decision,
                "note": review.get("note"),
                "decided_at": review.get("decided_at"),
                "recorded_at": now,
                # What the user asked for — the query side of a re-ID pair.
                "player": player,
                "action": request.get("action"),
                "team_mode": bool(request.get("team_mode")),
                "source": request.get("source"),
                "source_video": source_video,
                # What the pipeline believed, so a later model can be compared
                # against the heuristic it is replacing on the same crops.
                "time_s": candidate.get("time_s"),
                "bbox": candidate.get("bbox"),
                "score": candidate.get("score"),
                "identity_strength": candidate.get("identity_strength"),
                "ocr_match": bool(candidate.get("ocr_match")),
                "scene_id": candidate.get("scene_id"),
                "seed_count": review.get("seed_count"),
                "demo_mode": bool(review.get("demo_mode")),
            }
        )
    return rows


def record_review_labels(
    job_id: str,
    review: Dict[str, Any],
    request: Optional[Dict[str, Any]],
    outputs_dir: Path,
    root: Optional[Path] = None,
) -> int:
    """
    Persist the labelled crops for one decided review. Returns rows written.

    Never raises: see the module docstring. A return of 0 means "nothing was
    worth recording", which is a normal outcome for a review with no crops.
    """
    try:
        return _record_review_labels(job_id, review, request or {}, outputs_dir, root)
    except Exception as exc:
        logger.warning(
            f"[identity_labels] Failed to record labels for job {job_id}: {exc}",
            exc_info=True,
        )
        return 0


def _record_review_labels(
    job_id: str,
    review: Dict[str, Any],
    request: Dict[str, Any],
    outputs_dir: Path,
    root: Optional[Path],
) -> int:
    rows = build_label_rows(job_id, review, request)
    if not rows:
        return 0

    base = dataset_root(root)
    path = base / LABELS_FILENAME
    if job_id in _recorded_job_ids(path):
        logger.info(f"[identity_labels] Job {job_id} already recorded; skipping")
        return 0

    crop_dir = base / CROPS_SUBDIR / job_id
    crop_dir.mkdir(parents=True, exist_ok=True)

    candidates_by_id = {
        str(c.get("id")): c for c in review.get("candidates", []) if c.get("id")
    }

    kept: List[Dict[str, Any]] = []
    for row in rows:
        source = _crop_source(candidates_by_id[row["candidate_id"]], outputs_dir)
        if source is None or not source.exists():
            # A label with no image cannot train anything, and a row pointing at
            # a missing file would fail silently at load time instead of here.
            logger.warning(
                f"[identity_labels] Crop missing for {job_id}/{row['candidate_id']}; "
                "dropping that label"
            )
            continue
        destination = crop_dir / f"{row['candidate_id']}{source.suffix or '.jpg'}"
        shutil.copyfile(source, destination)
        row["crop_path"] = str(destination.relative_to(base))
        kept.append(row)

    if not kept:
        return 0

    # One line appended per row: the API process is the only writer, and
    # a line-at-a-time append keeps a partial write from corrupting earlier rows.
    with path.open("a", encoding="utf-8") as fh:
        for row in kept:
            fh.write(json.dumps(row) + "\n")

    positives = sum(1 for r in kept if r["label"] == POSITIVE)
    logger.info(
        f"[identity_labels] Job {job_id}: recorded {len(kept)} labels "
        f"({positives} positive, {len(kept) - positives} negative)"
    )
    return len(kept)


def iter_labels(root: Optional[Path] = None) -> Iterator[Dict[str, Any]]:
    """Stream the dataset. Corrupt lines are skipped with a warning, not fatal."""
    path = labels_path(root)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"[identity_labels] Skipping unreadable line {number}")


def load_labels(root: Optional[Path] = None) -> List[Dict[str, Any]]:
    return list(iter_labels(root))


def split_by_job(
    rows: Iterable[Dict[str, Any]],
    val_fraction: float = 0.2,
    seed: int = 0,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Train/validation split grouped by job, never by row.

    Six crops from one job are six views of one player in one match under one
    camera. Splitting them individually puts near-duplicates on both sides and
    reports a validation score that has nothing to do with unseen footage.
    """
    import random

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("job_id")), []).append(row)

    job_ids = sorted(grouped)
    random.Random(seed).shuffle(job_ids)

    val_count = int(round(len(job_ids) * max(0.0, min(1.0, val_fraction))))
    # With few jobs, rounding can claim all of them for validation and leave
    # training empty, which fails much later and much more confusingly.
    val_count = min(val_count, max(0, len(job_ids) - 1))
    val_jobs = set(job_ids[:val_count])

    train: List[Dict[str, Any]] = []
    val: List[Dict[str, Any]] = []
    for job_id in job_ids:
        (val if job_id in val_jobs else train).extend(grouped[job_id])
    return {"train": train, "val": val}


def summarize(rows: Sequence[Dict[str, Any]], root: Optional[Path] = None) -> Dict[str, Any]:
    """Counts a human needs to answer 'do I have enough data to train yet?'."""
    base = dataset_root(root)
    positives = sum(1 for r in rows if r.get("label") == POSITIVE)
    jobs = {r.get("job_id") for r in rows}
    videos = {r.get("source_video") for r in rows if r.get("source_video")}

    def player_key(row: Dict[str, Any]) -> str:
        player = row.get("player") or {}
        return "|".join(
            str(player.get(k, "")).strip().lower()
            for k in ("jersey_number", "jersey_color", "helmet_color")
        )

    missing = [
        r for r in rows
        if r.get("crop_path") and not (base / str(r["crop_path"])).exists()
    ]

    return {
        "root": str(base),
        "rows": len(rows),
        "positives": positives,
        "negatives": len(rows) - positives,
        "jobs": len(jobs),
        "rejected_jobs": len({r.get("job_id") for r in rows if r.get("decision") == "rejected"}),
        "videos": len(videos),
        "players": len({player_key(r) for r in rows}),
        "missing_crops": len(missing),
    }
