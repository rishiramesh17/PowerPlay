# PowerPlay Product Requirements Document

Status: working draft based on the implemented repository state as of 2026-04-24.

Source of truth for this document:
- `frontend/app/page.tsx`
- `frontend/app/upload/page.tsx`
- `frontend/app/practice-mode/page.tsx`
- `frontend/app/how-it-works/page.tsx`
- `backend/main.py`
- `backend/worker.py`
- `backend/processing/practice_mode.py`

Important note: the repository still contains legacy Node/Express documentation and starter files. This PRD describes the currently active product behavior represented by the Next.js frontend and Python/FastAPI processing backend.

## 1. Product Summary

PowerPlay is an AI-assisted cricket video platform that turns long match footage and practice recordings into short, player-focused highlight outputs.

The current product has two primary workflows:

1. Match Highlights
2. Practice Mode

Match Highlights is built around identifying a player or team in match footage, finding relevant batting or bowling segments, and compiling a final highlight reel. Practice Mode is built around removing dead time from long training videos by detecting movement and exporting only the actions that matter.

## 2. Problem Statement

Cricket players, coaches, clubs, and content creators regularly work with long-form video:

- Full match recordings are slow to review manually.
- Practice videos often contain long stretches of non-action footage.
- Recruiting and player development require short, polished clips, not raw recordings.
- Existing editing workflows are time-intensive and require manual trimming.

PowerPlay reduces manual editing time by automating discovery, extraction, and compilation of relevant cricket clips.

## 3. Target Users

### Primary users

- Individual players building personal highlight reels
- Coaches reviewing batting or bowling performance
- Clubs and academies managing shared footage across multiple users
- Sports content creators producing player-specific clips

### Secondary users

- Recruiters and scouts consuming the output reels
- Parents or team managers collecting footage for players

## 4. Product Goals

### Core goals

- Convert long videos into usable highlight outputs in minutes instead of hours
- Support both uploaded files and YouTube-sourced footage
- Let users target a specific player or switch to broader team-mode collection
- Support both match footage and practice sessions
- Return downloadable outputs with understandable progress feedback

### Quality goals

- Maintain enough context around the action so clips feel watchable, not abruptly cut
- Surface progress clearly for long-running jobs
- Keep the workflow simple enough for non-technical users

## 5. Non-Goals For The Current Version

- Real-time live-stream analysis
- Multi-sport parity beyond the current cricket-focused workflow
- Fully authenticated multi-tenant production account management
- Rich collaboration features such as shared annotations or commenting
- Editorial timeline controls inside the product

## 6. Core User Flows

### A. Match Highlights

1. User opens the upload flow.
2. User enters player information:
   - player name
   - jersey number
   - optional jersey, helmet, pad, and glove colors
3. User selects action type:
   - batting
   - bowling
4. User selects scope:
   - player mode
   - team mode
5. User provides source footage:
   - local video upload
   - YouTube URL
6. User optionally narrows the video with start and end timestamps.
7. User submits the job.
8. PowerPlay queues the work and exposes job status updates.
9. Backend downloads or saves the source, detects candidate segments, tracks the player, scores/selects segments, compiles the final output, and stores the result.
10. User reviews the generated highlight reel in-browser and downloads it.

### B. Practice Mode

1. User opens the practice mode flow.
2. User uploads a practice recording or pastes a YouTube URL.
3. User selects batting or bowling practice.
4. User tunes movement sensitivity and padding values.
5. User chooses output mode:
   - individual clips
   - compiled highlights
6. Backend detects motion-driven action windows, removes inactive footage, and returns output files.
7. User reviews the resulting clips and efficiency metrics.

## 7. Functional Requirements

### Match Highlights requirements

- FR-1: The system must accept either a local video file or a YouTube URL.
- FR-2: The system must collect player-identifying metadata, including jersey number and optional appearance cues.
- FR-3: The system must support batting and bowling analysis modes.
- FR-4: The system must support both player mode and team mode.
- FR-5: The system must allow optional start and end timestamps to constrain processing.
- FR-6: The system must queue long-running work and return a job ID immediately.
- FR-7: The system must expose job status, progress, stage text, and failure messages.
- FR-8: The system must compile a final downloadable highlight video when processing succeeds.
- FR-9: The system should return detected segments to help users understand what was selected.
- FR-10: The system should support a developer test mode for faster validation passes.

### Practice Mode requirements

- FR-11: The system must detect movement-based action segments in long practice recordings.
- FR-12: The system must allow movement threshold and padding controls.
- FR-13: The system must export either multiple clips or a compiled highlight file.
- FR-14: The system should return analysis metadata such as segment count and efficiency.

## 8. User Experience Requirements

- UX-1: The main upload flow must communicate long-running stages clearly.
- UX-2: The product must support both desktop review and simple download behavior.
- UX-3: The flow should stay understandable for first-time users without requiring video-editing knowledge.
- UX-4: The marketing site should clearly position PowerPlay as cricket-specialized and useful for players, coaches, clubs, and creators.

## 9. Pricing And Packaging Reflected In The Current Frontend

The current landing page presents three pricing tiers:

- Solo: lower-cost individual plan with limited highlight generation
- Pro: single-user full-access plan
- Group: team-oriented shared-access plan with multiple users

These plans appear in the UI today, but billing and entitlement logic are not fully represented in the active Python backend. They should be treated as product intent rather than fully enforced runtime behavior.

## 10. Success Metrics

Recommended product KPIs for the current scope:

- Upload-to-result completion rate
- Median processing time by source type:
  - local upload
  - YouTube source
- Percentage of jobs that finish without manual retries
- Download rate of completed highlights
- Practice mode efficiency improvement:
  - minutes removed from raw footage
- Precision of selected highlight segments, measured against curated review sets

## 11. Constraints And Risks

- The repo contains stale architecture docs that can mislead contributors.
- The active backend depends on heavyweight CV/media tooling such as FFmpeg, OpenCV, yt-dlp, and YOLO-related packages.
- Long YouTube videos introduce download-format variability and runtime risk.
- Practice mode is currently synchronous from the API route, unlike the queued match-highlight flow.
- The current storage model is local-disk oriented and uses SQLite for job state, which is fine for local development but limited for multi-user production scaling.

## 12. Prioritized Roadmap

### Near-term

- Unify product documentation around the active Python backend
- Add stable unit test coverage for pure pipeline utilities
- Add integration tests around job creation and status polling
- Improve production-grade storage and deployment assumptions

### Mid-term

- Harden ranking/selection quality with benchmark datasets
- Add authenticated user accounts and persistent media ownership
- Expand team workflows and admin controls

### Longer-term

- Better highlight explainability
- More robust coaching analytics
- Additional sports or configurable templates once cricket quality is strong
