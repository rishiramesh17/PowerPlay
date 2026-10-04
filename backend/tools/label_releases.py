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
import hashlib
import json
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing.scoreboard import build_timeline  # noqa: E402
from processing.scoreboard_detect import SCOREBOARD_LAG_SEC  # noqa: E402

#: Seconds before the scoreboard tick to start each clip. Must comfortably
#: exceed the largest plausible lag, or the release happens before the clip does
#: and the label is silently impossible to give.
LEAD_SEC = 22.0

#: Seconds after the tick to keep, for context on what the ball did.
TRAIL_SEC = 4.0

#: How far before the board goes dark to start a clip.
#:
#: Hand-labelling exposed the real shape of the problem. On a boundary the
#: broadcast cuts to replay, which hides the scoreboard; the "tick" we record is
#: therefore not the operator updating but the board REAPPEARING afterwards. On
#: one four the board was dark for 81 seconds, so a clip led by 22s opened with
#: the ball already halfway to the rope and the release long past.
#:
#: The release precedes the cut-to-replay, which itself follows the shot, so a
#: clip must start before the darkness rather than before the tick.
PRE_DARK_SEC = 20.0

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


def dark_since(tick: float, gaps: Sequence, step: float) -> Optional[float]:
    """
    When the board last went dark before reappearing at `tick`, or None.

    Occlusion arrives as a run of separate gaps separated by a single readable
    frame, so they are chained: treating only the final gap would place the start
    of a 81-second blackout at 18 seconds and miss the delivery entirely.
    """
    current = next((g for g in gaps if abs(g.end - tick) <= step + 0.1), None)
    if current is None:
        return None
    start, moved = current.start, True
    while moved:
        moved = False
        for g in gaps:
            if abs(g.end - start) <= step + 0.1 and g.start < start:
                start, moved = g.start, True
    return start


def deliveries_from(gt: Dict, step: float) -> List[Dict]:
    """Every delivery the board saw, tagged with its outcome and search window."""
    timeline = build_timeline(list(gt["samples"]), step=step)
    out: List[Dict] = []
    prev = None
    prev_tick = 0.0
    for row in timeline.rows:
        if prev is not None and row["balls"] > prev["balls"] and row["innings"] == prev["innings"]:
            tick = row["t"]
            dark = dark_since(tick, timeline.gaps, step)
            start = tick - LEAD_SEC
            if dark is not None:
                start = min(start, dark - PRE_DARK_SEC)
            # The previous delivery's tick is a hard floor: the ball cannot have
            # been bowled before the one before it was recorded, and without this
            # a long blackout produces a clip spanning two deliveries, which
            # cannot be labelled unambiguously.
            start = max(start, prev_tick)
            out.append({
                "ball": row["balls"],
                "tick_t": tick,
                "clip_start": max(0.0, start),
                "dark_since": dark,
                "runs_delta": row["runs"] - prev["runs"],
                "outcome": outcome_of(row["runs"] - prev["runs"],
                                      row["wickets"] > prev["wickets"]),
            })
            prev_tick = tick
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
        start = d["clip_start"]
        length = d["tick_t"] + TRAIL_SEC - start
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
             "-t", f"{length:.2f}", "-vf", label,
             "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", str(dest)],
            check=True,
        )
        rows.append({
            "clip": name,
            "ball": d["ball"],
            "outcome": d["outcome"],
            "runs_delta": d["runs_delta"],
            "tick_t": d["tick_t"],
            # Stored rather than recomputed: the page turns a playhead position
            # into absolute video time with it, and a clip start it had to infer
            # could drift from the one ffmpeg actually used.
            "clip_start": start,
            "dark_since": d["dark_since"],
            # The thing to fill in: the video time the ball leaves the hand.
            "release_t": None,
        })
    return rows


#: A self-contained labelling page written alongside the clips.
#:
#: The alternative is scrubbing in a video player and typing timestamps into a
#: JSON file by hand, fifteen times. That is not merely tedious: the number has
#: to be converted from a seek-bar position into original-video time, and an
#: error there corrupts the measured lag invisibly.
#:
#: Here the release time is read from the playhead rather than typed, so a label
#: cannot disagree with the frame the labeller was looking at. The timestamp
#: burnt into the video stays as the independent cross-check.
PAGE_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>PowerPlay · label release times</title>
<style>
 :root { color-scheme: dark; --bg:#13151a; --fg:#e8eaed; --dim:#9aa0a6;
         --line:#2c3038; --go:#ffd400; --ok:#34d058; }
 * { box-sizing:border-box; margin:0; padding:0 }
 body { background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system,
        BlinkMacSystemFont,"Segoe UI",sans-serif; padding:24px;
        max-width:1100px; margin:0 auto }
 h1 { font-size:19px; font-weight:600; margin-bottom:2px }
 .sub { color:var(--dim); font-size:13px; margin-bottom:18px }
 video { width:100%; border-radius:8px; background:#000; display:block }
 .bar { display:flex; gap:10px; align-items:center; flex-wrap:wrap;
        margin:14px 0; }
 button { background:#23272f; color:var(--fg); border:1px solid var(--line);
          padding:9px 16px; border-radius:7px; font-size:14px; cursor:pointer }
 button:hover { background:#2c313a }
 button.primary { background:var(--go); color:#000; border-color:var(--go);
                  font-weight:600 }
 .meta { display:flex; gap:22px; color:var(--dim); font-size:13px;
         padding:10px 0; border-top:1px solid var(--line);
         border-bottom:1px solid var(--line); flex-wrap:wrap }
 .meta b { color:var(--fg); font-weight:600 }
 .now { font-variant-numeric:tabular-nums; font-size:28px; font-weight:600;
        color:var(--go) }
 .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(112px,1fr));
         gap:7px; margin-top:18px }
 .chip { padding:8px 6px; border:1px solid var(--line); border-radius:6px;
         font-size:12px; text-align:center; cursor:pointer; background:#1a1d23 }
 .chip:hover { border-color:var(--dim) }
 .chip.cur { border-color:var(--go); background:#2a2510 }
 .chip.done { border-color:var(--ok) }
 .chip .o { color:var(--dim); display:block; font-size:11px }
 .chip .v { color:var(--ok); display:block; font-variant-numeric:tabular-nums }
 kbd { background:#23272f; border:1px solid var(--line); border-radius:4px;
       padding:1px 6px; font-size:12px; font-family:ui-monospace,monospace }
 .help { color:var(--dim); font-size:13px; margin-top:16px; line-height:2 }
 .done-box { margin-top:22px; padding:16px; border:1px solid var(--line);
             border-radius:8px; background:#1a1d23 }
 textarea { width:100%; height:120px; background:#0f1115; color:var(--fg);
            border:1px solid var(--line); border-radius:6px; padding:10px;
            font-family:ui-monospace,monospace; font-size:12px; margin-top:10px }
</style></head><body>

<h1>Label release times</h1>
<div class="sub">Find the frame the ball leaves the bowler's hand, then press
  <kbd>Enter</kbd>. The yellow number burnt into the video should match the big
  number below &mdash; that is your cross-check.</div>

<video id="v" preload="auto"></video>

<div class="bar">
  <button id="back">&larr; prev clip</button>
  <button id="play">play / pause</button>
  <button class="primary" id="mark">Mark release &amp; next &nbsp;<kbd>Enter</kbd></button>
  <button id="skip">Can't tell &mdash; skip</button>
  <button id="next">next clip &rarr;</button>
</div>

<div class="meta">
  <span>clip <b id="idx"></b></span>
  <span>outcome <b id="outcome"></b></span>
  <span>board ticked at <b id="tick"></b></span>
  <span id="darkwrap">board went dark at <b id="dark"></b></span>
  <span>labelled <b id="count"></b></span>
  <span style="margin-left:auto">video time <span class="now" id="now"></span></span>
</div>

<div class="grid" id="grid"></div>

<div class="help">
  <kbd>&larr;</kbd> <kbd>&rarr;</kbd> step one frame &nbsp;·&nbsp;
  <kbd>&#8679;</kbd>+<kbd>&larr;</kbd>/<kbd>&rarr;</kbd> half a second &nbsp;·&nbsp;
  <kbd>space</kbd> play/pause &nbsp;·&nbsp;
  <kbd>Enter</kbd> mark release &nbsp;·&nbsp;
  <kbd>S</kbd> skip
</div>

<div class="done-box">
  <button class="primary" id="save">Download labels.json</button>
  <span style="color:var(--dim);font-size:13px">&nbsp; then replace the file in
    this folder and run the analyse command</span>
  <div id="status" style="color:var(--ok);font-size:13px;margin-top:10px"></div>
  <textarea id="out" readonly></textarea>
</div>

<script>
const ROWS = __ROWS__;
const LEAD = __LEAD__;
// Keyed on the clips AND their current labels, so a re-cut or a deliberate
// server-side clear invalidates the saved copy. Autosave must protect against
// losing work inside one version of this page -- never against a correction
// made outside it.
const KEY = 'powerplay-labels-__FINGERPRINT__';

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(ROWS.map(r => r.release_t))); }
  catch (e) { /* private browsing: autosave is a convenience, not the record */ }
}

function restore() {
  let raw; try { raw = localStorage.getItem(KEY); } catch (e) { return false; }
  if (!raw) return false;
  let saved; try { saved = JSON.parse(raw); } catch (e) { return false; }
  if (!Array.isArray(saved) || saved.length !== ROWS.length) return false;
  let n = 0;
  saved.forEach((v, i) => { if (v !== null && v !== undefined) { ROWS[i].release_t = v; n++; } });
  return n;
}
const FRAME = 1/30;
let i = 0;
const v = document.getElementById('v');
const $ = id => document.getElementById(id);

// Absolute time in the ORIGINAL video, which is the only frame of reference the
// pipeline uses. Computed from the playhead rather than typed, so a label cannot
// disagree with the frame the labeller was actually looking at. clip_start comes
// from the cutter rather than being re-derived here: clips are no longer a fixed
// lead before the tick, because a replay can hide the board for over a minute.
const clipStart = r => r.clip_start;
const absNow = () => clipStart(ROWS[i]) + v.currentTime;

function load(n) {
  i = Math.max(0, Math.min(ROWS.length - 1, n));
  const r = ROWS[i];
  v.src = r.clip;
  v.currentTime = 0;
  $('idx').textContent = `${i + 1} / ${ROWS.length}`;
  $('outcome').textContent = r.outcome;
  $('tick').textContent = r.tick_t.toFixed(1) + 's';
  $('darkwrap').style.display = r.dark_since === null ? 'none' : '';
  if (r.dark_since !== null) $('dark').textContent = r.dark_since.toFixed(1) + 's';
  draw();
}

function draw() {
  $('now').textContent = absNow().toFixed(2) + 's';
  $('count').textContent = ROWS.filter(r => r.release_t !== null).length
                         + ' / ' + ROWS.length;
  $('grid').innerHTML = ROWS.map((r, n) =>
    `<div class="chip ${n === i ? 'cur' : ''} ${r.release_t !== null ? 'done' : ''}"
          data-n="${n}">ball ${r.ball}<span class="o">${r.outcome}</span>
      <span class="v">${r.release_t !== null ? r.release_t.toFixed(1) + 's' : '&nbsp;'}</span>
     </div>`).join('');
  $('out').value = JSON.stringify(ROWS, null, 1);
}

function mark() {
  ROWS[i].release_t = Math.round(absNow() * 100) / 100;
  save();
  draw();
  if (i < ROWS.length - 1) load(i + 1);
}

v.addEventListener('timeupdate', () => $('now').textContent = absNow().toFixed(2) + 's');
v.addEventListener('seeked',     () => $('now').textContent = absNow().toFixed(2) + 's');
$('grid').addEventListener('click', e => {
  const c = e.target.closest('.chip'); if (c) load(+c.dataset.n);
});
$('mark').onclick = mark;
$('next').onclick = () => load(i + 1);
$('back').onclick = () => load(i - 1);
$('play').onclick = () => v.paused ? v.play() : v.pause();
$('skip').onclick = () => { ROWS[i].release_t = null; save(); draw(); load(i + 1); };
$('save').onclick = () => {
  const b = new Blob([JSON.stringify(ROWS, null, 1)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b); a.download = 'labels.json'; a.click();
};

addEventListener('keydown', e => {
  if (e.target.tagName === 'TEXTAREA') return;
  const step = e.shiftKey ? 0.5 : FRAME;
  if (e.key === 'ArrowLeft')  { v.pause(); v.currentTime -= step; e.preventDefault(); }
  if (e.key === 'ArrowRight') { v.pause(); v.currentTime += step; e.preventDefault(); }
  if (e.key === ' ')     { v.paused ? v.play() : v.pause(); e.preventDefault(); }
  if (e.key === 'Enter') { mark(); e.preventDefault(); }
  if (e.key.toLowerCase() === 's') { ROWS[i].release_t = null; save(); draw(); load(i + 1); }
});

const restored = restore();
load(0);
if (restored) {
  $('status').textContent = `restored ${restored} autosaved label(s) from this browser`;
}
addEventListener('beforeunload', e => {
  if (ROWS.some(r => r.release_t !== null) && !window.__saved) {
    e.preventDefault(); e.returnValue = '';
  }
});
$('save').addEventListener('click', () => { window.__saved = true; });
</script></body></html>
"""


def write_page(rows: List[Dict], out_dir: Path) -> Path:
    """Write the labelling page, with the clip list baked in.

    Inlined rather than fetched: a page opened over file:// cannot read a
    sibling JSON file, and a labelling tool that silently shows no clips is
    worse than one that does not exist.
    """
    fingerprint = hashlib.sha1(
        json.dumps([[r["clip"], r.get("clip_start"), r.get("release_t")] for r in rows],
                   sort_keys=True).encode()
    ).hexdigest()[:12]
    page = (PAGE_TEMPLATE
            .replace("__ROWS__", json.dumps(rows))
            .replace("__LEAD__", repr(LEAD_SEC))
            .replace("__FINGERPRINT__", fingerprint))
    dest = out_dir / "label.html"
    dest.write_text(page, encoding="utf-8")
    return dest


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

    # Does a grouping explain the lag, or does it only look like it?
    #
    # The first version of this compared variance before and after grouping and
    # reported any reduction as structure. It twice declared that outcome
    # predicts lag, and both times it was wrong: splitting n=15 into six buckets
    # reduces variance whatever the labels say, and a bucket of one reduces it to
    # zero. A permutation test asks the question that actually matters -- would
    # shuffling the labels do this well? -- and answered p = 0.19 for outcome
    # against p = 0.005 for occlusion.
    for name, keyf in (("outcome", lambda r: r["outcome"]),
                       ("occlusion", lambda r: r.get("dark_since") is not None)):
        if len({keyf(r) for r in done}) > 1:
            result[f"{name}_dependence"] = _group_significance(done, keyf)
    return result


def _between_group_variance(items: List[Dict], keyf) -> float:
    groups: Dict[object, List[float]] = defaultdict(list)
    for r in items:
        groups[keyf(r)].append(r["lag"])
    grand = statistics.mean(r["lag"] for r in items)
    return sum(len(v) * (statistics.mean(v) - grand) ** 2 for v in groups.values())


def _group_significance(items: List[Dict], keyf, trials: int = 20000) -> Dict:
    """
    How often would shuffled labels separate the lags this well?

    Deliberately a permutation test rather than an F-test: fifteen samples across
    six unequal buckets is not where distributional assumptions are safe, and the
    whole point is to avoid being convinced by a pattern that is not there.
    """
    rng = random.Random(0)
    observed = _between_group_variance(items, keyf)
    labels = [keyf(r) for r in items]
    lags = [r["lag"] for r in items]
    hits = 0
    for _ in range(trials):
        rng.shuffle(lags)
        shuffled = [{"lag": lag, "_k": k} for lag, k in zip(lags, labels)]
        if _between_group_variance(shuffled, lambda r: r["_k"]) >= observed:
            hits += 1
    p = (hits + 1) / (trials + 1)
    means = defaultdict(list)
    for r in items:
        means[keyf(r)].append(r["lag"])
    return {
        "p_value": p,
        "significant": p < 0.05,
        "groups": {str(k): {"n": len(v), "mean": statistics.mean(v),
                            "sd": statistics.pstdev(v) if len(v) > 1 else 0.0}
                   for k, v in sorted(means.items(), key=lambda kv: str(kv[0]))},
    }


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
    page = write_page(rows, out_dir)

    print(f"\nwrote {len(rows)} clips to {out_dir}/")
    print(f"\n  open {page}")
    print("\nStep to the frame the ball leaves the bowler's hand and press Enter.")
    print("Leave any you cannot judge as null -- a guess is worse than a gap.")
    print(f"Download the result over {labels_path}, then run `analyse`.")
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

    for name in ("occlusion", "outcome"):
        dep = result.get(f"{name}_dependence")
        if not dep:
            continue
        verdict = "EXPLAINS the lag" if dep["significant"] else "does not explain the lag"
        print(f"\ndoes {name} explain the lag?  p = {dep['p_value']:.3f}  -> {verdict}")
        for k, g in dep["groups"].items():
            print(f"    {k:<10} n={g['n']:<3} mean {g['mean']:>5.1f}s  sd {g['sd']:>4.1f}s")
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
