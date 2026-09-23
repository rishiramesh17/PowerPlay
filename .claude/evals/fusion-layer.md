# EVAL: fusion-layer

Written **before** implementation, deliberately. The failure this guards against
is documented: after two fixes driven by the second broadcast, that broadcast had
quietly become the tuning set and its score stopped meaning anything. Freezing
the criteria and the baselines first is what makes a later number honest.

## What the fusion layer is

Multiple detectors each emit opinions about when a delivery occurred. They fail
on different footage for different reasons -- that is the whole point, and the
only condition under which combining them helps. The layer selects detectors a
stream can actually support, collects their signals, and merges them while
keeping every contributor attributable.

## Frozen baselines (measured before any fusion work)

Single-detector performance, `delivery_detect.detect_deliveries`:

| Stream | Window | Recall | Precision |
|---|---|---|---|
| LeWhJo3vgO8 (square-on, graphics-light) | 900-3000s | 21/36 = 0.58 | 21/58 = 0.36 |
| fvl87Duq4a4 (end-on, graphics-heavy) | 0-600s | 9/15 = 0.60 | 9/16 = 0.56 |

Scoreboard reader, `tools/build_ground_truth.py`:

| Stream | Parsed | Deliveries found |
|---|---|---|
| LeWhJo3vgO8 | 4066/4433 = 0.92 | 223 across 2 innings |
| fvl87Duq4a4 | 324/400 = 0.81 | 24 |

Profile detection, `stream_profile.detect_profile`:

| Stream | Scoreboard ROI found | depth_variation |
|---|---|---|
| LeWhJo3vgO8 | yes, unaided | 0.02 |
| fvl87Duq4a4 | yes, unaided | 0.47 |

## Capability evals

1. **Fusion never underperforms its best available detector.** On each stream,
   fused recall and precision must be >= the best single eligible detector.
   This is the whole justification for the layer; failing it means the merge is
   destroying information.
2. **Abstention does not count as disagreement.** A detector that returns
   "I cannot judge this stream" must not move the fused answer at all. Pinned by
   construction: an abstaining detector contributes to neither numerator nor
   denominator.
3. **Preconditions are enforced before execution.** A detector requiring
   `perspective` must not run on LeWhJo3vgO8 (depth 0.02). Today's bowling-end
   failure ran to completion and returned a constant answer for an entire match;
   it should now be refused in milliseconds.
4. **Every fused result is attributable.** For any output, which detectors
   contributed, their individual confidences, and their raw evidence must be
   recoverable. Fusion's danger is hiding failure -- five votes producing a wrong
   answer is far harder to debug than one detector being wrong.
5. **Precision is favoured over recall.** For a highlight reel a missed boundary
   is survivable; a clip of nothing happening is not. Where the two trade off,
   the fused output must move precision up even at some cost to recall.

## Regression evals

Baseline: commit `889ef86`.

- `pytest backend/tests/` stays green (114 passing at baseline).
- Scoreboard reader output on both streams is unchanged by fusion work.
- `stream_profile` still locates both ROIs unaided.
- `delivery_detect` standalone numbers are unchanged -- fusion wraps detectors,
  it does not silently retune them.

## Held-out discipline

**LeWhJo3vgO8 is the tuning stream. fvl87Duq4a4 is held out.**

No constant may be adjusted in response to a fvl87Duq4a4 result. If a change is
motivated by that stream, it is recorded here as a known deficiency rather than
fixed, until a third stream exists. This rule is the reason the current 0.60 on
that stream is already softer evidence than it looks.

## Explicitly NOT in scope

- **Calibrated per-detector weights.** There is no data to fit them: two streams,
  one of them held out. Fusion starts with equal weight for every eligible
  detector and *records* agreement rates so weights can be measured later. A
  weight invented now is the same class of mistake as a threshold fitted to one
  video, and today produced four of those.
- Outcome classification (boundary vs dot), striker attribution, clip cutting.

## Success threshold

Capability evals 1-4 must pass outright; they are structural, not statistical.
Eval 5 is judged on the fused numbers against the frozen baselines above.

Ship criterion: fused precision on the tuning stream materially above 0.36 with
recall not below 0.58, and the held-out stream reported untouched -- whatever it
says.
