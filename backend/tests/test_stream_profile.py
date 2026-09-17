"""
Tests for stream capability profiling.

The profile exists to stop detectors running on footage that cannot support
them. The failure it was built in response to: a bowling-end reader inferred
which end the bowler came from by watching his apparent size change, which is
real perspective on a camera looking down the wicket and meaningless on a
square-on one. It returned the same answer for every over of a match -- which
cricket does not permit -- and nothing in the code could have known better.

So the behaviours worth pinning are the honest ones: saying "unknown", refusing
to claim a capability, and not mistaking a still field for a graphic.
"""

import numpy as np

from processing import stream_profile as sp


def _field(h=360, w=640, shade=90):
    """A plausible outfield: uniform, smooth, and perfectly still."""
    rng = np.random.default_rng(0)
    img = np.full((h, w, 3), shade, dtype=np.uint8)
    # Grass texture, but low-contrast -- the thing that must NOT read as a caption.
    noise = rng.integers(-4, 5, size=(h, w, 1)).astype(np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _with_caption(frame, y0=300, y1=330):
    """Stamp a hard-edged text-like band across the bottom."""
    out = frame.copy()
    out[y0:y1, :] = 20
    for x in range(10, out.shape[1] - 10, 14):       # glyph-ish vertical strokes
        out[y0 + 4:y1 - 4, x:x + 5] = 245
    return out


def test_a_still_field_is_not_mistaken_for_a_scoreboard():
    """
    The measured bug: on a 20-minute single-camera clip the framing barely
    changes, so grass is as static as a graphic. Staying still alone reported
    the ENTIRE frame as a scoreboard at 0.80 confidence.
    """
    frames = [_field() for _ in range(20)]
    roi, _ = sp.find_overlay(frames)
    if roi is not None:
        x1, y1, x2, y2 = roi
        area = (x2 - x1) * (y2 - y1)
        assert area < 0.5 * 640 * 360, f"claimed most of the frame as overlay: {roi}"


def test_a_persistent_caption_is_found():
    frames = [_with_caption(_field(shade=90 + 3 * i)) for i in range(20)]
    roi, conf = sp.find_overlay(frames)
    assert roi is not None, "a hard-edged persistent band should be found"
    _, y1, _, y2 = roi
    assert y1 < 330 and y2 > 300, f"band {y1}-{y2} misses the caption at 300-330"
    assert conf > 0.0


def test_too_few_frames_refuses_rather_than_guesses():
    assert sp.find_overlay([_field() for _ in range(3)]) == (None, 0.0)


def test_depth_is_unknown_not_false_when_unmeasured():
    """
    The distinction the bowling-end bug turned on. A stream nobody measured is
    not a stream without perspective, and callers must be able to tell those
    apart.
    """
    p = sp.StreamProfile(width=1280, height=720, fps=30.0, duration_sec=600.0)
    assert p.depth_variation == 0.0
    assert p.looks_along_pitch is None
    assert p.supports("perspective") is False, "unknown must never grant a capability"


def test_measured_depth_produces_a_verdict_either_way():
    flat = sp.StreamProfile(1280, 720, 30.0, 600.0, depth_variation=0.02)
    deep = sp.StreamProfile(1280, 720, 30.0, 600.0, depth_variation=0.47)
    assert flat.looks_along_pitch is False and not flat.supports("perspective")
    assert deep.looks_along_pitch is True and deep.supports("perspective")


def test_a_silent_audio_track_does_not_count_as_audio():
    """Re-encoded uploads routinely carry an empty track; presence is not use."""
    silent = sp.StreamProfile(1280, 720, 30.0, 600.0, has_audio=True, audio_rms=0.0)
    loud = sp.StreamProfile(1280, 720, 30.0, 600.0, has_audio=True, audio_rms=0.05)
    assert silent.supports("audio") is False
    assert loud.supports("audio") is True


def test_no_scoreboard_means_the_capability_is_refused():
    p = sp.StreamProfile(1280, 720, 30.0, 600.0)
    assert p.supports("scoreboard") is False
    p.scoreboard_roi = (430, 610, 880, 670)
    assert p.supports("scoreboard") is True


def test_an_unknown_requirement_is_refused_not_granted():
    """Default-deny: a typo in a detector's precondition must not enable it."""
    p = sp.StreamProfile(1280, 720, 30.0, 600.0, scoreboard_roi=(0, 0, 10, 10))
    assert p.supports("scorebaord") is False
    assert p.supports("") is False


def test_summary_is_honest_about_what_was_not_found():
    p = sp.StreamProfile(1280, 720, 60.0, 600.0)
    text = p.summary()
    assert "no scoreboard found" in text
    assert "depth unknown" in text
    assert "no usable audio" in text


def test_the_depth_threshold_separates_the_two_measured_streams():
    """
    Guards a constant fitted to n=2. The measurements were 0.02 and 0.47; the
    cut point must sit strictly between them with room on both sides, so that
    revisiting it later is an explicit decision rather than a silent drift.
    """
    assert 0.02 < sp.DEPTH_CORRELATION_STRONG < 0.47
