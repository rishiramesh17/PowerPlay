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

---

## Measured deficiency: detector confidence is uninformative

Recorded here rather than fixed, per the held-out discipline above.

The gap-filler rested on a claim: a scoreboard counter jump says how many
deliveries a gap hides, so ranking candidates by confidence and keeping the top
N should beat open-ended search. Measured on the Minor League stream by
simulating gaps over spans where the board *was* visible (real gaps cannot be
used -- their ground truth comes from the occluded scoreboard, so measuring
timing against it would be measuring the blind spot itself):

| span | mode | precision | recall |
|---|---|---|---|
| 90s | unconstrained | 0.42 | 0.62 |
| 90s | constrained to N | 0.48 | **0.41** |
| 150s | unconstrained | 0.38 | 0.62 |
| 150s | constrained to N | 0.41 | **0.38** |

Recall collapsed 21-24 points to buy 3-6 points of precision. That small gain is
the mechanical effect of truncating a list, not selection working.

The cause, measured directly:

    correct detections   prominence 4.67 +/- 3.97   (n=18)
    false detections     prominence 4.69 +/- 2.11   (n=24)
    AUC 0.384, permutation p = 0.893

**Prominence carries no information about whether a detection is real.** The
means are identical and the ranking is indistinguishable from shuffling.

Two consequences, both structural:

1. It explains precision stuck near 0.40 across all three broadcasts regardless
   of production quality. There is no internal signal separating good detections
   from bad, so no threshold can help.
2. **The fusion layer's confidence contract is unsatisfied by its own first
   detector.** Noisy-OR combination and MIN_FUSED_CONFIDENCE both assume
   calibrated input. Feeding prominence in would weight noise equally with
   signal. Until a detector reports a confidence that predicts correctness, its
   signals should carry a flat value and fusion should rely on agreement between
   independent detectors rather than on any one of them being sure.

This does not invalidate inverting the pipeline. The scoreboard identifies every
delivery it can see, and inside a known event window the question is "when,
within these 25 seconds" rather than "which N of K" -- a different task that this
result does not speak to. What it rules out is using the current detector to
*choose* among candidates.

---

## Capability eval 1: FAILED (measured on Minor League Cricket)

| detector | precision | recall |
|---|---|---|
| vision (run-up) standalone | 0.43 | 0.62 |
| scoreboard standalone | 0.76* | 1.00* |
| **fused** | **0.95** | 0.62 |

\* circular: this ground truth was produced by the same scoreboard reader, so
those numbers grade it against itself. Upper bound, not a result.

Against vision, fusion passes handsomely -- precision 0.43 to 0.95 at identical
recall. Requiring two independent detectors to agree removed 23 of 24 false
positives, which is exactly the behaviour the layer was built for.

Against the scoreboard it fails. Fusion loses 11 deliveries of recall, because
with both detectors marked uncalibrated neither may report alone, so every ball
the board saw and vision missed is discarded.

The cause is structural rather than a tuning problem. The scoreboard is the
strongest detector measured and is being silenced for lacking independent
validation -- correctly, since its only score comes from grading itself. The
corroboration requirement then costs precisely the recall the board was bringing.

This is not fixed by weakening the calibration contract, which exists because an
uncalibrated confidence measured AUC 0.384 at predicting its own correctness.
It is fixed by calibrating the scoreboard against a source it did not produce.
Minor League Cricket publishes full ball-by-ball scorecards on CricClubs, which
is exactly such a source: independent, authoritative, and free.

Until then the honest reading is that fusion is a large precision win over
vision and a recall regression against the board, and the system is blocked on
external validation rather than on more detector work.

---

## Capability eval 1: PASSED, after external calibration

The failure above was diagnosed as "blocked on external validation, not on more
detector work". That diagnosis held.

### The independent source

CricClubs publishes a ball-by-ball page for this match, kept by a human scorer at
the ground. It is independent of the broadcast graphics the reader parses -- a
different person, a different system, a different moment of recording. Measured
by `tools/calibrate_scoreboard.py`:

| | |
|---|---|
| deliveries in the analysed window (balls 8-37) | 30 |
| found by the reader | **30** |
| invented by the reader | **0** |
| recall / precision | 1.000 / 1.000 |
| 95% CI lower bound on that rate | 0.886 |
| runs reading also correct | 28/30 |

The two runs disagreements are both in over 4.2, where a no-ball was hit for four
and the next legal ball went for six -- eleven runs inside about three seconds.
The board was mid-update. No delivery was missed.

`DELIVERY_CONFIDENCE` is therefore **0.886, not 1.00**. A perfect score on thirty
deliveries is consistent with a true rate near 0.89, and quoting the point
estimate would be the same overclaiming the calibration contract exists to stop.

### Result

| detector | precision | recall |
|---|---|---|
| scoreboard standalone | 0.76 | 1.00 |
| **fused** | **1.00** | **1.00** |

Fusion now equals or beats its best detector on both axes. Eval 1 passes.

The mechanism is the one the layer was designed around and is worth naming: a
calibrated detector may report alone, so the eleven deliveries previously lost
are back; the occluded-span signals that cost the board its 0.76 precision get
absorbed into the direct ticks they duplicate rather than reported separately.

### What calibration did NOT settle

`SCOREBOARD_LAG_SEC` is unchanged and still n=2. Scorecard clocks are
minute-resolution and carry the scorer's own delay: mapping them onto video time
across all 30 deliveries gave offsets spreading over 177 seconds, with one ball
162s out. That is three orders of magnitude too coarse to resolve a 3-11s
graphics lag.

So the calibration is **of counting, not of timing** -- which is exactly the
split `Signal.confidence` and `Signal.time_sigma` were separated to express. The
board may now assert that a ball was bowled. It still may not assert when.

Settling the lag needs hand-labelled releases against video. Roughly a dozen
deliveries would do it, and until that exists the fused timestamp on any
board-only event carries a declared +/-4s that nothing has verified.

### Sample size

One window, one match, one vendor. 30 deliveries. This is enough to unblock
fusion and not enough to call the reader solved; the CI lower bound is the
honest summary, and it is what the code now uses.

### Three-way, with vision re-measured

| detector | precision | recall | reported |
|---|---|---|---|
| vision (run-up) standalone | 0.46 | 0.66 | 41 |
| scoreboard standalone | 0.76 | 1.00 | 38 |
| **fused** | **1.00** | **1.00** | **29** |

Fusion beats both detectors on both axes, which is the whole justification for
the layer. Note the honesty limit on the fused row: truth times here are the
board's own lag-corrected ticks, so this measures *agreement about which
deliveries*, not absolute timing. What makes the chain non-circular is the step
underneath it -- the board was validated at 30/30 against the scorecard, by a
different person on a different system.

Vision remains uncalibrated and flattened, unchanged at 0.46 / 0.66. That is
correct and should stay: its confidence scored AUC 0.384 at predicting its own
correctness. It contributes timing precision and corroboration, not judgement.

---

## Measured: the "lag" is an occlusion artifact, and it is worst on highlights

Found by hand-labelling, which is the point of hand-labelling. Five of fifteen
clips could not be labelled at all; four were a four or a six and one was the
wicket.

`SCOREBOARD_LAG_SEC` encodes a theory: the graphics operator updates the counter
a few seconds after the ball. On a boundary that theory is wrong. The broadcast
cuts to replay, the replay hides the board, and what we record as the tick is the
board REAPPEARING. Measured on the MiLC window, time the board was dark
immediately before each tick:

| delivery | outcome | dark for |
|---|---|---|
| ball 18 | four | **81s** |
| ball 32 | wicket | 21s |
| ball 20 | six | 24s |
| ball 24 | six | 18s |
| ball 11 | four | 18s |

Against measured medians of 32-46s between deliveries, an 81-second blackout is
longer than two balls.

Three consequences:

1. **`SCOREBOARD_LAG_SEC = 7.0` is not merely imprecise, it is the wrong shape.**
   A single constant cannot express "a few seconds normally, tens of seconds when
   the broadcast cuts away". Correcting per outcome -- the plan going into the
   labelling -- is still right, but the effect is an order of magnitude larger
   than the 3.4s/10.9s that motivated it.

2. **It is anti-correlated with what the product needs.** Timing is worst exactly
   on fours, sixes and wickets, which are the deliveries a highlight reel is made
   of. Dots and singles, which nobody clips, are timed well.

3. **The gap START is better evidence than the gap END.** The board goes dark
   because the broadcast cut away, which happens shortly after the shot. So
   `dark_since` sits far closer to the delivery than the tick does, and is
   already being used to place the labelling clips. Whether it is good enough to
   time a clip is the next thing to measure, and the hand labels will say.

This also sharpens the occlusion work from a nice-to-have into the critical path:
34% of runtime has no readable board, and that 34% is not randomly distributed.

---

## Generalization test 2 (Chicago Tigers v Kingsmen): the reader FAILED

Second MiLC match, different city, different production crew. Result:

    parsed 0/548 samples, 0 deliveries found

Not a degradation -- a total failure, and the most useful result so far.

The ROI detection worked and the OCR read the pixels fine. What changed is the
graphics package. The Dallas broadcast renders a compact board with an over
counter; Chicago renders a full-width banner:

    MILANTHA 35 27  MNITHIYANANDAM 51  CHT 92/0  A SHEIKH 26/0 2  POWERED BY ...

Measured across the window:

| | |
|---|---|
| team score readable | 338/548 = 62% |
| over count present | **4/548 = 1%** (3 of those are "POWERED" misread as "OVERS") |

**The over counter is not on screen.** Every delivery-detection result in this
project rests on it incrementing once per legal ball, so there is nothing here
to count.

A balls-faced fallback was tested -- the two batters' ball counts should sum to
the legal delivery total -- and does not work as read: 2/103 frames agreed with
the scorecard, because only one batter's ball count survives in most frames.
Whether that is the ROI clipping the banner or the layout itself is unresolved.

### What this overturns

The strategic premise was that targeting professional MiLC made the scoreboard
trustworthy and the problem tractable. That premise is now measured and wrong in
an important way: **MiLC is not one broadcast format.** Vendor consistency, not
production quality, is what the reader depends on, and it does not hold across
the league.

The 30/30 result stands and still means what it said -- it was never a claim
about every MiLC stream, and the Wilson bound was chosen for exactly this kind
of overreach. What has changed is the denominator it applies to.

This is also the clearest possible argument for the fusion layer's capability
gating: this stream should be detected as lacking a usable over counter and the
scoreboard detector refused, rather than running to completion and reporting
that no cricket was played.

---

## Measured: the scoreboard lag, from 15 hand-labelled releases

| regime | n | lag | sd |
|---|---|---|---|
| board stayed visible | 9 | **10.1s** | **2.2s** |
| board went dark before the tick | 6 | 21.5s | 10.0s |

Permutation tests (20k shuffles): **occlusion p = 0.004**, outcome p = 0.078.

RMS error in predicted release time, all 15 deliveries:

| model | RMS | worst |
|---|---|---|
| constant 7.0s (previous code) | 11.5s | 31.5s |
| constant 11.8s (measured median) | 9.0s | 26.7s |
| split on occlusion | 6.5s | 17.0s |

On the 9 clean deliveries alone the occlusion model is 2.2s RMS, against 3.8s
for the old constant.

### The hypothesis this was built to test was wrong

Going in, the prediction was that lag depends on OUTCOME: a six logs late
because the camera tracks it to the rope. The measurement says otherwise.

    four   [8.2, 13.6, 26.8]  mean 16.2s
    six    [25.2, 12.8, 8.2]  mean 15.4s

Indistinguishable, and within the clean subset outcome gives p = 0.19. What
looked like outcome-dependence was occlusion wearing a disguise: boundaries get
replays, replays hide the board, and the hidden board is what moves the number.

Two near-misses worth recording, because neither was caught by a test:

1. An intermediate run reported "outcome predicts lag, improvement 44%". That
   rested entirely on ONE label -- the wicket -- which the labeller had already
   said they could not mark. Removing it dropped the figure to 16% and flipped
   the conclusion. The user caught it, not the tooling.
2. The `analyse` heuristic compared variance before and after grouping and
   called any reduction structure. Splitting n=15 across six buckets reduces
   variance whatever the labels say, and a bucket of one reduces it to zero. It
   declared outcome-dependence twice. Replaced with a permutation test, and the
   singleton-bucket case is now a regression test.

### What changed in the code

`SCOREBOARD_LAG_SEC` 7.0 -> 10.1, `SCOREBOARD_TIME_SIGMA` 4.0 -> 2.2, plus
`OCCLUDED_TICK_LAG_SEC` 21.5 / `OCCLUDED_TICK_TIME_SIGMA` 10.0 applied per
delivery. The sigma is the measured sd, not a margin chosen for comfort.

Ten seconds of uncertainty on an occluded tick is close to useless for cutting a
clip. Declaring it is what lets inverse-variance weighting hand the timing to
vision there instead -- which is the specific thing `time_sigma` was separated
from `confidence` to allow.

### Still open

Occluded deliveries are timed to +/-10s and they are disproportionately the
boundaries and wickets a highlight reel is made of. Vision must carry the timing
there, and vision's own timing accuracy has still never been measured -- the
0.4s sigma it is given is assumed. These 15 labels are the instrument for that,
and it is the next measurement.

---

## Measured: vision's timing, and the assumption it demolishes (2026-10-05)

Vision's `time_sigma` had been 0.4s since the fusion layer was written. Nothing
measured it. The 15 hand-labelled releases finally could.

Matching is greedy one-to-one inside the 14s agreement window. The first pass
was nearest-neighbour and let balls 11 and 12 claim the *same* detection at
161.06s, which flattered vision by inventing a hit; one-to-one drops vision's
recall here from 12/15 to 11/15.

| regime | n | bias | sd | mean abs | worst | within 1s |
|---|---|---|---|---|---|---|
| all matched | 11 | -0.56s | **7.40s** | 6.08s | 11.88s | 2/11 |
| board stayed visible | 6 | -0.22s | 7.46s | 5.65s | 11.88s | 1/6 |
| board went dark | 5 | -0.96s | 8.19s | 6.60s | 9.85s | 1/5 |

**The assumed 0.4s was 18x too confident.** Vision does not know when a delivery
happened to within a second; it knows to within about seven.

### Why this mattered more than the number

Fusion weights timestamps by inverse variance. At 0.4s vision carried weight
6.25 against the board's 0.207 -- **30x** -- so the *less* precise detector set
the moment on every corroborated delivery.

| timing of the fused event | all 15 | visible | dark |
|---|---|---|---|
| vision sigma 0.4 (what the code did) | 5.31s | 4.22s | 6.94s |
| vision sigma 7.4 (measured) | **3.36s** | **1.89s** | **5.56s** |
| board alone, no vision | 4.70s | 2.07s | 8.65s |

The old constant made fusion *worse than the scoreboard by itself* on
deliveries where the board was visible -- 4.22s against 2.07s. Correcting it
puts fusion ahead of both detectors in every regime, which is the first time
that claim has been true of timing rather than counting.

End-to-end, same vision timestamps, only the constant changed:

| | precision | recall |
|---|---|---|
| fused, sigma 0.4 | 0.90 | 0.97 |
| fused, sigma 7.4 | **0.94** | **1.00** |

### What it kills

The plan recorded earlier -- let vision carry the timing through occlusion --
**does not work.** On the 5 occluded deliveries vision is +/-8.2s against the
board's +/-10.9s, and misses one outright. Both are far too coarse to cut a
clip. Occluded timing remains unsolved, and the next attempt has to be
something other than this detector: audio onset inside the gap (AUC 0.62-0.81,
untested for timing) or the replay-boundary cut itself.

### A circularity found in this eval's own truth

`run_capability_eval.py` builds `truth_t` from the board's lag-corrected ticks,
using whatever `SCOREBOARD_LAG_SEC` is compiled in at the time. So changing the
lag model silently moves the yardstick: the "fused 1.00 / 1.00" recorded above
was measured against truth built from the old 7.0s constant, and does not
reproduce. On the current two-regime model the same code and the same video give
**0.94 / 1.00**, with vision standalone at 0.49 / 0.69 rather than 0.46 / 0.66.

The detector itself is deterministic -- two runs over 0-300s returned byte-equal
release times, so this is not run-to-run noise. It is the measurement moving.
Earlier rows in this document are therefore comparable to each other only where
the lag constants did not change between them.

The fix is available and not yet applied: 15 of those 30 deliveries now have
hand-labelled release times that no detector produced. Truth should come from
those where they exist, which would also let this eval report absolute timing
instead of only agreement about which deliveries.

### Code changed

- `delivery_detect.RUNUP_TIME_SIGMA = 7.4` added, with the measurement behind it
- `run_capability_eval.py` uses that constant instead of the literal 0.4
- `calibrate_scoreboard.py` no longer claims the lag is unmeasured

### Still open

- occluded-delivery timing, now with no candidate solution
- `truth_t` should prefer hand labels over board-derived ticks
- vision's 11/15 recall and 0.49 precision are unimproved and uninvestigated
