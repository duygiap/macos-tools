# Video Sales Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested local apparel-video generation workflow with automatic virtual-try-on/video prompts and an optional Google Flow browser engine that uses the user's existing Flow subscription credits.

**Architecture:** A pure prompt planner feeds a filesystem-backed job service through a narrow generation-engine interface. Mock generation provides deterministic CI coverage; a Playwright persistent-profile adapter handles authenticated Google Flow UI automation without storing Google credentials in git.

**Tech Stack:** Python 3.11+, Pydantic 2, FastAPI, Uvicorn, Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-video-sales-flow-design.md`

## Global Constraints

- Default engine is `mock`; Google Flow credit consumption requires explicit opt-in.
- No paid Gemini/Veo API integration and no private Google API reverse engineering.
- No Google passwords, OAuth tokens, cookies, or browser-profile contents committed to git.
- Default maxima are 10 requested videos and 10 outfit references per job.
- Browser automation must abort rather than interact with purchase, upgrade, or top-up UI.
- Tests and CI must never consume Google Flow credits.

---

### Task 1: Package, domain validation, and prompt planner

**Files:**
- Create: `tools/video-sales-flow/pyproject.toml`
- Create: `tools/video-sales-flow/src/video_sales_flow/__init__.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/models.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/planner.py`
- Create: `tools/video-sales-flow/tests/test_planner.py`

**Interfaces:**
- Produces `Motion`, `Tone`, `JobOptions`, `PlannedPrompt`, `VideoPlan`.
- Produces `PromptPlanner.plan_tryon(...)` and `PromptPlanner.plan_videos(...)`.

- [ ] Write failing tests for identity/garment invariants, automatic motion diversity, requested count, and explicit-motion cycling.
- [ ] Run `pytest tests/test_planner.py -q` and observe RED because package types do not exist.
- [ ] Implement the minimum domain models and planner.
- [ ] Re-run focused tests and confirm GREEN.

### Task 2: Storage and job orchestration

**Files:**
- Create: `tools/video-sales-flow/src/video_sales_flow/storage.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/service.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/engines/base.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/engines/mock.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/engines/__init__.py`
- Create: `tools/video-sales-flow/tests/test_service.py`

**Interfaces:**
- `GenerationEngine.generate_image(request) -> GeneratedAsset`
- `GenerationEngine.generate_video(request) -> GeneratedAsset`
- `JobService.run(...) -> JobManifest`

- [ ] Write failing tests for copied inputs, max-video/max-outfit guards, one try-on per garment, N video outputs, and failed-manifest persistence.
- [ ] Run focused tests and observe RED.
- [ ] Implement storage, engine protocol, mock engine, and service minimally.
- [ ] Re-run focused and full tests and confirm GREEN.

### Task 3: Google Flow Playwright engine

**Files:**
- Create: `tools/video-sales-flow/src/video_sales_flow/config.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/engines/google_flow.py`
- Create: `tools/video-sales-flow/tests/test_google_flow_engine.py`

**Interfaces:**
- `GoogleFlowEngine.login() -> None`
- `GoogleFlowEngine.generate_image(...) -> GeneratedAsset`
- `GoogleFlowEngine.generate_video(...) -> GeneratedAsset`

- [ ] Write failing unit tests for selector override parsing, purchase-text blocking, new-download selection, and download naming without launching a browser.
- [ ] Run focused tests and observe RED.
- [ ] Implement centralized selectors, persistent-profile context, upload/prompt/generate/download workflow, bounded polling, purchase guard, and failure screenshot capture.
- [ ] Re-run tests and confirm GREEN.

### Task 4: CLI, API, documentation, and CI-safe verification

**Files:**
- Create: `tools/video-sales-flow/src/video_sales_flow/cli.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/api.py`
- Create: `tools/video-sales-flow/README.md`
- Create: `tools/video-sales-flow/.gitignore`
- Create: `tools/video-sales-flow/tests/test_cli.py`

**Interfaces:**
- CLI: `video-sales-flow login`, `video-sales-flow generate`.
- API: `GET /health`, `POST /jobs`, `GET /jobs/{job_id}`.

- [ ] Write failing CLI parsing tests for multi-outfit input and explicit engine selection.
- [ ] Run focused tests and observe RED.
- [ ] Implement CLI/API adapters without duplicating planner/service logic.
- [ ] Add setup, login, mock-run, real-run, output, troubleshooting, and credit-safety instructions.
- [ ] Run `python -m pytest -q` and `python -m compileall src` with zero failures.
