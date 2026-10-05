"""
Tests for multi-detector fusion.

These are the capability evals from .claude/evals/fusion-layer.md, written
before the implementation. They are structural rather than statistical: each
pins a property that must hold regardless of how well any detector performs.

The behaviours that matter are the ones that let a wrong answer through quietly.
A bowling-end reader once returned the same verdict for every over of a match
because it had no way to say "this camera cannot support me" -- fusion must make
that state expressible, and must refuse such a detector before it runs.
"""

import pytest

from processing import fusion as fz
from processing.stream_profile import StreamProfile


def _profile(**kw):
    base = dict(width=1280, height=720, fps=30.0, duration_sec=600.0)
    base.update(kw)
    return StreamProfile(**base)


def _det(name, signals, requires=(), calibrated=True):
    """
    Calibrated by default HERE because these tests exercise merge arithmetic.
    In production the default is the opposite: a detector is untrusted until its
    confidence has been shown to predict correctness.
    """
    return fz.Detector(name=name, run=lambda: signals,
                       requires=requires, calibrated=calibrated)


def _sig(name, t, conf=0.8, sigma=1.0):
    return fz.Signal(detector=name, t=t, confidence=conf, time_sigma=sigma)


# --- eval 3: preconditions enforced before execution ------------------------

def test_a_detector_the_stream_cannot_support_is_never_run():
    """
    The measured failure: a perspective-based reader ran to completion on a
    square-on camera and returned a constant answer for a whole match. It must
    now be refused, not merely disbelieved.
    """
    ran = []

    def explode():
        ran.append(True)
        return [_sig("perspective", 10.0)]

    flat = _profile(depth_variation=0.02)          # square-on
    report = fz.fuse([fz.Detector("perspective", explode, ("perspective",))], flat)
    assert ran == [], "detector ran despite an unmet precondition"
    assert "perspective" in report.skipped
    assert report.events == []


def test_a_detector_the_stream_supports_does_run():
    deep = _profile(depth_variation=0.47)
    report = fz.fuse([_det("perspective", [_sig("perspective", 10.0)], ("perspective",))], deep)
    assert report.eligible == ["perspective"]
    assert len(report.events) == 1


def test_unmeasured_capability_blocks_rather_than_permits():
    """depth_variation of 0 means "nobody measured", which must not grant."""
    unknown = _profile()
    eligible, skipped = fz.select_detectors(
        [fz.Detector("p", lambda: [], ("perspective",))], unknown
    )
    assert eligible == [] and "p" in skipped


# --- eval 2: abstention is not disagreement ---------------------------------

def test_abstaining_does_not_change_the_fused_answer():
    sigs = [_sig("scoreboard", 100.0, 0.9)]
    solo = fz.fuse([_det("scoreboard", sigs)], _profile())
    with_abstainer = fz.fuse(
        [_det("scoreboard", sigs), fz.Detector("runup", lambda: None)], _profile()
    )
    assert len(solo.events) == len(with_abstainer.events) == 1
    assert solo.events[0].confidence == pytest.approx(with_abstainer.events[0].confidence)
    assert solo.events[0].t == pytest.approx(with_abstainer.events[0].t)
    assert with_abstainer.abstained == ["runup"]


def test_abstaining_is_distinct_from_reporting_nothing():
    """
    "I cannot judge this stream" and "I looked and found none" are different
    facts. Conflating them is what produced a constant bowling-end verdict.
    """
    abstain = fz.fuse([fz.Detector("d", lambda: None)], _profile())
    empty = fz.fuse([fz.Detector("d", lambda: [])], _profile())
    assert abstain.abstained == ["d"] and "d" not in abstain.agreement_rate
    assert empty.abstained == [] and empty.agreement_rate["d"] == 0.0


# --- eval 1: fusion must not destroy information ----------------------------

def test_agreeing_detectors_reinforce():
    """Two independent sources on the same ball must beat either alone."""
    a = fz.fuse([_det("a", [_sig("a", 50.0, 0.6)])], _profile())
    both = fz.fuse(
        [_det("a", [_sig("a", 50.0, 0.6)]), _det("b", [_sig("b", 52.0, 0.6)])], _profile()
    )
    assert len(both.events) == 1, "signals 2s apart describe the same delivery"
    assert both.events[0].confidence > a.events[0].confidence
    assert both.events[0].corroborated


def test_one_detector_cannot_stack_with_itself_into_certainty():
    """
    Noisy-OR across *distinct* detectors only. A single source firing repeatedly
    inside one window is one opinion, not three.
    """
    spam = fz.fuse([_det("a", [_sig("a", 50.0, 0.6), _sig("a", 51.0, 0.6),
                               _sig("a", 52.0, 0.6)])], _profile())
    assert len(spam.events) == 1
    assert spam.events[0].confidence == pytest.approx(0.6)
    assert not spam.events[0].corroborated


def test_separate_deliveries_stay_separate():
    """Real deliveries are >=21s apart; the window must not chain across them."""
    report = fz.fuse([_det("a", [_sig("a", 50.0), _sig("a", 95.0)])], _profile())
    assert [round(e.t) for e in report.events] == [50, 95]


def test_the_timestamp_follows_timing_precision_not_confidence():
    """
    These are different quantities. A scoreboard is certain a ball was bowled
    and vague about when -- its tick trails the delivery by a measured 3-11s. A
    motion detector is unsure the event is real but accurate to a fraction of a
    second. The precise one must set the moment even when the sure one disagrees,
    or the fused time is dragged toward the worse estimate.
    """
    report = fz.fuse(
        [_det("board", [_sig("board", 107.0, conf=0.95, sigma=4.0)]),
         _det("vision", [_sig("vision", 100.0, conf=0.30, sigma=0.5)])], _profile()
    )
    assert len(report.events) == 1
    assert report.events[0].t < 101.0, "the precise detector should set the time"


# --- eval 5: precision favoured ---------------------------------------------

def test_weak_lone_signals_are_dropped():
    """A reel with junk in it is worse than a reel missing a ball."""
    report = fz.fuse([_det("a", [_sig("a", 10.0, 0.2)])], _profile())
    assert report.events == []


def test_the_same_weak_signal_corroborated_survives():
    """Two weak independent sources agreeing is real evidence; one is not."""
    report = fz.fuse(
        [_det("a", [_sig("a", 10.0, 0.3)]), _det("b", [_sig("b", 11.0, 0.3)])], _profile()
    )
    assert len(report.events) == 1 and report.events[0].corroborated


# --- eval 4: attribution survives -------------------------------------------

def test_every_event_names_its_contributors_and_evidence():
    sig = fz.Signal("runup", 50.0, 0.7, 1.0, {"prominence": 6.4, "speed": 1.04})
    report = fz.fuse([_det("runup", [sig])], _profile())
    ev = report.events[0]
    assert ev.detectors == ("runup",)
    assert ev.signals[0].evidence["prominence"] == 6.4
    text = ev.explain()
    assert "runup" in text and "prominence" in text


def test_agreement_is_recorded_but_not_acted_on():
    """
    Weights must stay equal until there is data to fit them. Agreement rates are
    collected so that calibration is possible later, not used to weight now.
    """
    report = fz.fuse(
        [_det("good", [_sig("good", 50.0, 0.9)]),
         _det("noisy", [_sig("noisy", 50.5, 0.9), _sig("noisy", 300.0, 0.1)])],
        _profile(),
    )
    assert report.agreement_rate["good"] == pytest.approx(1.0)
    assert report.agreement_rate["noisy"] == pytest.approx(0.5)


def test_summary_reports_what_was_skipped_and_why():
    report = fz.fuse(
        [fz.Detector("p", lambda: [], ("perspective",)),
         fz.Detector("r", lambda: None)],
        _profile(depth_variation=0.02),
    )
    text = report.summary()
    assert "skipped" in text and "perspective" in text
    assert "abstained" in text and "r" in text


def test_no_detectors_at_all_is_an_empty_report_not_a_crash():
    report = fz.fuse([], _profile())
    assert report.events == [] and report.eligible == []


# --- the calibration contract -----------------------------------------------
# Measured: the run-up localizer's confidence predicts its own correctness at
# AUC 0.384 (p=0.89) -- correct detections averaged 4.67, false ones 4.69. None
# of its other features reached significance. Passing that through noisy-OR
# would let noise argue as loudly as evidence, and fusion's respectable
# machinery would make that failure very hard to see.


def test_a_detector_is_untrusted_until_measured():
    """The honest default: a score is not a probability until something checked."""
    assert fz.Detector("d", lambda: []).calibrated is False


def test_an_uncalibrated_detectors_confidence_is_flattened():
    loud = fz.Detector("brash", lambda: [_sig("brash", 50.0, 0.99)], calibrated=False)
    report = fz.fuse([loud], _profile())
    assert report.uncalibrated == ["brash"]
    # 0.99 would have cleared the bar alone; flattened, it cannot.
    assert report.events == []


def test_flattening_preserves_the_original_score_as_evidence():
    """Distrusted, not hidden -- the raw number stays available for debugging."""
    d = fz.Detector("brash", lambda: [_sig("brash", 50.0, 0.99)], calibrated=False)
    other = _det("solid", [_sig("solid", 51.0, 0.5)])
    report = fz.fuse([d, other], _profile())
    assert len(report.events) == 1
    raw = [s.evidence.get("raw_confidence") for s in report.events[0].signals
           if s.detector == "brash"]
    assert raw == [0.99]


def test_two_uncalibrated_detectors_agreeing_still_count():
    """
    Corroboration does the discriminating when self-assessment cannot. One
    uncalibrated detector is not evidence; two independent ones agreeing is.
    """
    a = fz.Detector("a", lambda: [_sig("a", 50.0, 0.9)], calibrated=False)
    b = fz.Detector("b", lambda: [_sig("b", 52.0, 0.9)], calibrated=False)
    assert fz.fuse([a], _profile()).events == []
    both = fz.fuse([a, b], _profile())
    assert len(both.events) == 1 and both.events[0].corroborated


def test_an_uncalibrated_detector_cannot_outvote_a_calibrated_one():
    """
    A detector that earned its number must not be dragged off the ball by one
    that merely asserts a big one.
    """
    brash = fz.Detector("brash", lambda: [_sig("brash", 60.0, 0.99)], calibrated=False)
    solid = _det("solid", [_sig("solid", 54.0, 0.95)])
    report = fz.fuse([brash, solid], _profile())
    assert len(report.events) == 1
    # Its inflated confidence is discarded; with equal timing precision the two
    # contribute equally to the moment rather than the loud one winning.
    assert report.events[0].t == pytest.approx(57.0)
    assert report.uncalibrated == ["brash"]


def test_the_flat_value_sits_below_the_reporting_threshold():
    """
    One unmeasured detector must not carry an event by itself, while two
    agreeing must clear the bar. That is what makes the constant a contract
    rather than a number.
    """
    assert fz.UNCALIBRATED_CONFIDENCE < fz.MIN_FUSED_CONFIDENCE
    pair = 1.0 - (1.0 - fz.UNCALIBRATED_CONFIDENCE) ** 2
    assert pair >= fz.MIN_FUSED_CONFIDENCE


def test_summary_names_detectors_whose_confidence_was_distrusted():
    report = fz.fuse(
        [fz.Detector("brash", lambda: [_sig("brash", 50.0, 0.9)], calibrated=False)],
        _profile(),
    )
    assert "uncalibrated" in report.summary() and "brash" in report.summary()


def test_a_vague_detector_barely_moves_a_precise_one():
    """Inverse-variance weighting: 4s of uncertainty against 0.5s is 64x less."""
    report = fz.fuse(
        [_det("board", [_sig("board", 120.0, sigma=4.0)]),
         _det("vision", [_sig("vision", 110.0, sigma=0.5)])], _profile()
    )
    assert report.events[0].t == pytest.approx(110.15, abs=0.1)


def test_the_agreement_window_spans_the_scoreboard_lag():
    """
    A board tick and a vision release describing the same ball sit 3-11s apart.
    A narrower window would split one delivery into two events; a much wider one
    would chain across real deliveries, which are >=21s apart.
    """
    assert fz.AGREEMENT_WINDOW_SEC > 11.0
    assert fz.AGREEMENT_WINDOW_SEC < 21.0


def test_vision_must_not_outweigh_the_scoreboard_on_timing():
    """
    The measured ordering, pinned.

    Vision's time_sigma was 0.4s on no evidence, against the board's measured
    2.2s. Inverse-variance weighting turned that into 30x the board's say over
    the fused timestamp, and made fusion worse than the board alone (4.22s mean
    error against 2.07s). Vision was then measured at 7.4s. Any future edit that
    makes vision look more precise than a visible scoreboard is reintroducing
    that bug, so it fails here rather than quietly degrading timing.
    """
    from processing.delivery_detect import RUNUP_TIME_SIGMA
    from processing.scoreboard_detect import SCOREBOARD_TIME_SIGMA

    assert RUNUP_TIME_SIGMA > SCOREBOARD_TIME_SIGMA


def test_the_more_precise_detector_sets_the_fused_moment():
    """Inverse-variance weighting, stated as behaviour rather than arithmetic."""
    precise = fz.Signal(detector="board", t=100.0, confidence=0.886, time_sigma=2.2)
    vague = fz.Signal(detector="vision", t=120.0, confidence=0.5, time_sigma=7.4)

    fused = fz._fuse_cluster([precise, vague])

    # Must land nearer the precise detector than the midpoint of the two.
    assert abs(fused.t - 100.0) < abs(fused.t - 110.0)
