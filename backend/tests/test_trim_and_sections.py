"""
Regression tests for the video time-range path.

These cover three bugs that silently produced the wrong output window:
  1. `-ss` was placed after `-i`, forcing ffmpeg to decode from frame 0.
  2. An end time with no start time was dropped entirely, so the video
     came back untrimmed.
  3. A YouTube range cut server-side by yt-dlp was then trimmed a second
     time with the same absolute offsets, returning the wrong window.
"""

from pathlib import Path

import pytest

import main


@pytest.fixture
def captured_ffmpeg(monkeypatch):
    """Capture the ffmpeg argv that trim_with_ffmpeg would run, without running it."""
    calls = []
    monkeypatch.setattr(main.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))
    return calls


def _trim(calls, start, end):
    main.trim_with_ffmpeg(Path("/tmp/does-not-need-to-exist.mp4"), start, end)
    assert len(calls) == 1, "expected exactly one ffmpeg invocation"
    return calls[0]


def test_seek_is_placed_before_input(captured_ffmpeg):
    """-ss before -i is input seeking; after -i it decodes every frame from 0."""
    cmd = _trim(captured_ffmpeg, 600.0, 1800.0)
    assert cmd.index("-ss") < cmd.index("-i")


def test_duration_is_a_span_not_an_endpoint(captured_ffmpeg):
    """-t is measured from the seek point, so it must be end - start."""
    cmd = _trim(captured_ffmpeg, 600.0, 1800.0)
    assert cmd[cmd.index("-t") + 1] == str(1200.0)


def test_end_without_start_still_trims(captured_ffmpeg):
    """Previously -t was only added when start was also set, silently no-opping."""
    cmd = _trim(captured_ffmpeg, None, 1800.0)
    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == str(1800.0)
    assert "-ss" not in cmd


def test_start_without_end_runs_to_end_of_video(captured_ffmpeg):
    cmd = _trim(captured_ffmpeg, 600.0, None)
    assert cmd.index("-ss") < cmd.index("-i")
    assert "-t" not in cmd


def test_no_range_is_a_no_op(captured_ffmpeg):
    source = Path("/tmp/does-not-need-to-exist.mp4")
    assert main.trim_with_ffmpeg(source, None, None) == source
    assert captured_ffmpeg == []


@pytest.mark.parametrize("start,end", [(1800.0, 600.0), (600.0, 600.0)])
def test_inverted_range_is_rejected(captured_ffmpeg, start, end):
    with pytest.raises(RuntimeError, match="Invalid trim range"):
        main.trim_with_ffmpeg(Path("/tmp/does-not-need-to-exist.mp4"), start, end)
    assert captured_ffmpeg == []


def test_download_result_reports_whether_range_was_already_cut():
    """
    The worker keys its trim decision off this flag. If it is wrong, a range
    already cut by yt-dlp gets cut again and the user gets the wrong window.
    """
    cut = main.YouTubeDownload(Path("/tmp/clip.mp4"), True)
    full = main.YouTubeDownload(Path("/tmp/full.mp4"), False)
    assert cut.section_applied is True
    assert full.section_applied is False
    assert cut.path == Path("/tmp/clip.mp4")


# --- appearance descriptor -------------------------------------------------
# detect_player pulls in torch/ultralytics/easyocr. Skip cleanly when that stack
# is unavailable — including when it is installed but broken, which importorskip
# deliberately will not swallow — rather than failing collection for every test
# in this module.
try:
    from processing import detect_player
except ImportError as exc:  # pragma: no cover - environment dependent
    detect_player = None
    _cv_stack_error = exc
else:
    _cv_stack_error = None

requires_cv_stack = pytest.mark.skipif(
    detect_player is None,
    reason=f"requires the torch/ultralytics/easyocr stack ({_cv_stack_error})",
)


@requires_cv_stack
def test_region_weights_are_a_normalised_distribution():
    weights = detect_player.REGION_DESCRIPTOR_WEIGHTS
    assert set(weights) == {"helmet", "torso", "lower", "glove_left", "glove_right"}
    assert sum(weights.values()) == pytest.approx(1.0)
    # The jersey is the strongest identity cue and must outweigh every other
    # region; the old running-mean bug made glove_right dominate instead.
    assert weights["torso"] == max(weights.values())
    assert weights["torso"] > weights["glove_right"]


@requires_cv_stack
def test_descriptor_is_dominated_by_the_torso():
    """
    Feed a distinct solid colour per region and confirm the combined descriptor
    sits closest to the torso's own histogram.
    """
    import numpy as np

    def solid(bgr):
        patch = np.zeros((40, 40, 3), dtype=np.uint8)
        patch[:, :] = bgr
        return patch

    regions = {
        "helmet": solid((0, 0, 255)),
        "torso": solid((255, 0, 0)),
        "lower": solid((0, 255, 0)),
        "glove_left": solid((0, 255, 255)),
        "glove_right": solid((255, 0, 255)),
    }

    combined = detect_player.combine_region_histograms(regions)
    assert combined is not None

    similarities = {
        name: detect_player.hist_similarity(
            combined, detect_player.compute_color_histogram(patch)
        )
        for name, patch in regions.items()
    }
    assert max(similarities, key=similarities.get) == "torso", similarities


@requires_cv_stack
def test_missing_regions_renormalise_instead_of_skewing():
    """A partially visible player must still yield a unit-norm descriptor."""
    import numpy as np

    patch = np.zeros((40, 40, 3), dtype=np.uint8)
    patch[:, :] = (255, 0, 0)

    combined = detect_player.combine_region_histograms({"torso": patch})
    assert combined is not None
    assert float(np.linalg.norm(combined)) == pytest.approx(1.0, abs=1e-5)


@requires_cv_stack
def test_no_usable_regions_returns_none():
    import numpy as np

    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    assert detect_player.combine_region_histograms({"torso": empty, "helmet": None}) is None
    assert detect_player.combine_region_histograms({}) is None
