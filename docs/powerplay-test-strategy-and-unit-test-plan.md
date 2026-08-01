# PowerPlay Test Strategy And Unit Test Plan

Status: current-state test plan plus new unit-test baseline added alongside this document.

## 1. Why This Document Exists

PowerPlay's active pipeline combines UI state, API contracts, local job persistence, external media tools, and computer-vision heuristics. That makes it easy for regressions to hide in utility code even before heavy media processing starts.

The current repository includes a few ad hoc scripts, but not a stable unit-test baseline. This document defines the immediate test strategy and records the new unit tests added with it.

## 2. Current Testing Reality

The repo already contains exploratory scripts such as:

- `backend/test_compile.py`
- `backend/test_long_video.py`
- `backend/test_opencv.py`

These are useful for manual experimentation, but they are not isolated unit tests because they depend on media files, external binaries, or the full CV pipeline.

## 3. Test Strategy

### Layer 1: Pure unit tests

Goal: validate deterministic logic with no dependency on OpenCV, FastAPI, FFmpeg, YOLO models, or network access.

Best targets:

- `backend/job_store.py`
- `backend/processing/utils.py`
- pure helper logic in `backend/processing/segment_selector.py`

### Layer 2: API contract tests

Goal: validate request/response behavior for:

- `POST /process-video`
- `GET /jobs/{job_id}`
- `POST /practice-mode`

These should be added later once the Python environment and FastAPI test tooling are standardized in the repo.

### Layer 3: Pipeline integration tests

Goal: validate end-to-end processing on short, curated fixture videos.

These should verify:

- upload path
- YouTube-disabled local path
- match highlight compilation
- practice mode clip extraction

### Layer 4: Benchmark and quality tests

Goal: measure recall, precision, and runtime across consistent manifests.

The repo already points in this direction with:

- `backend/tools/benchmark_pipeline.py`
- `backend/reports/sample_manifest.jsonl`

## 4. New Unit Tests Added

The new tests added with this document are:

- `backend/tests/test_job_store.py`
- `backend/tests/test_processing_utils.py`
- `backend/tests/test_segment_selector.py`

### Coverage summary

`test_job_store.py`
- job creation defaults
- request payload persistence
- update flow for result and error fields
- queue retrieval behavior

`test_processing_utils.py`
- timestamp-to-segment merging
- timecode parsing across accepted formats
- segment clamping to media duration
- total-duration limiting with truncation

`test_segment_selector.py`
- segment IoU math
- overlap ratio math
- neutral identity behavior when identity signals are absent
- selection ordering and duration-cap enforcement on deterministic inputs

## 5. How To Run The New Tests

From the project root:

```bash
python3 -m unittest discover -s backend/tests -v
```

You can also run a single file:

```bash
python3 -m unittest backend.tests.test_job_store -v
python3 -m unittest backend.tests.test_processing_utils -v
python3 -m unittest backend.tests.test_segment_selector -v
```

These tests are intentionally limited to pure Python modules so they can run without media fixtures or external CV dependencies.

## 6. Recommended Next Test Additions

Short-term additions:

- FastAPI route tests for `enqueue_processing_job`
- validation tests for malformed `playerData`
- practice-mode parameter validation tests

Mid-term additions:

- fixture-driven tests for clip extraction and compile behavior
- worker tests around job-stage transitions
- regression tests for replay suppression and segment ranking

Long-term additions:

- gold-set evaluation against labeled cricket footage
- performance thresholds in CI for benchmark manifests
- production smoke tests for object storage and queued workers

## 7. Exit Criteria For A Safer Release Process

PowerPlay should eventually require:

- passing pure unit tests on every change
- passing API contract tests for the active endpoints
- at least one short end-to-end media integration test
- benchmark checks for ranking quality when detection/selection logic changes
