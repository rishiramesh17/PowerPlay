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


def _det(name, signals, requires=()):
    return fz.Detector(name=name, run=lambda: signals, requires=requires)


def _sig(name, t, conf=0.8):
    return fz.Signal(detector=name, t=t, confidence=conf)


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


def test_a_confident_detector_is_not_dragged_off_by_a_hesitant_one():
    report = fz.fuse(
        [_det("sure", [_sig("sure", 100.0, 0.95)]),
         _det("vague", [_sig("vague", 106.0, 0.10)])], _profile()
    )
    assert len(report.events) == 1
    assert report.events[0].t < 101.0, "weighted toward the confident signal"


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
    sig = fz.Signal("runup", 50.0, 0.7, {"prominence": 6.4, "speed": 1.04})
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
