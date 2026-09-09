# Gemini Try-On Review Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate model+outfit try-on stills with the user's Gemini web session, review and retry them before any Google Flow video generation, then keep the existing Telegram video delivery path.

**Architecture:** Add a focused `tryon` package with an image-engine interface, deterministic mock engine, Gemini Playwright adapter, reviewer, and retry pipeline. Inject that pipeline into `JobService` while keeping the existing legacy image path as the default for backward compatibility.

**Tech Stack:** Python 3.11+, Pydantic, Playwright, Pillow, pytest, existing Google Flow and Telegram integrations.

**Spec:** `docs/superpowers/specs/2026-09-09-gemini-tryon-review-flow-design.md`

## Global Constraints

- Never remove watermarks; detect/reject/regenerate instead.
- Never persist Google cookies, credentials, Telegram tokens, or browser-session secrets in manifests or source.
- Do not invoke paid Gemini/Veo APIs automatically; production image generation uses the authenticated Gemini web UI.
- Do not start Google Flow video generation until a try-on still is approved.
- Keep Telegram `google-flow` allowlist safety unchanged.
- CI must use mock engines only and consume no Google/Telegram credits.

---

### Task 1: Settings and review model

**Files:**
- Modify: `tools/video-sales-flow/src/video_sales_flow/config.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/tryon/__init__.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/tryon/base.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/tryon/review.py`
- Test: `tools/video-sales-flow/tests/test_tryon_review.py`

**Interfaces:**
- Produces: `TryOnReviewResult`, `TryOnImageEngine`, new `Settings` try-on fields.

- [ ] **Step 1: Write failing settings/reviewer tests** for defaults, invalid attempts, valid PNG approval, too-small image rejection, and watermark-token rejection.
- [ ] **Step 2: Run `python -m pytest -q tests/test_tryon_review.py`** and verify imports/settings fail before implementation.
- [ ] **Step 3: Implement settings and reviewer** using Pillow decoding and deterministic local checks.
- [ ] **Step 4: Re-run the focused tests** and verify they pass.
- [ ] **Step 5: Commit** with `feat: add try-on review primitives`.

### Task 2: Retry pipeline and mock image engine

**Files:**
- Create: `tools/video-sales-flow/src/video_sales_flow/tryon/mock.py`
- Create: `tools/video-sales-flow/src/video_sales_flow/tryon/pipeline.py`
- Test: `tools/video-sales-flow/tests/test_tryon_pipeline.py`

**Interfaces:**
- Consumes: `TryOnReviewResult`, `TryOnImageEngine`.
- Produces: `TryOnPipeline`, `TryOnPipelineResult`, `MockTryOnEngine`.

- [ ] **Step 1: Write failing tests** proving rejection triggers another attempt, review feedback is appended to retry prompts, success stops retries, and exhaustion raises no video-side effects.
- [ ] **Step 2: Run focused tests** and verify failure because pipeline types do not exist.
- [ ] **Step 3: Implement the minimal pipeline** with max-attempt guard and per-attempt asset metadata.
- [ ] **Step 4: Re-run focused tests** until green.
- [ ] **Step 5: Commit** with `feat: add reviewed try-on retry pipeline`.

### Task 3: JobService integration

**Files:**
- Modify: `tools/video-sales-flow/src/video_sales_flow/service.py`
- Modify: `tools/video-sales-flow/src/video_sales_flow/models.py`
- Test: `tools/video-sales-flow/tests/test_service.py`

**Interfaces:**
- Consumes: optional `TryOnPipeline`.
- Produces: approved still paths passed to existing `PromptPlanner.plan_videos`.

- [ ] **Step 1: Add failing service tests** proving video generation is not called when try-on review exhausts retries and that an approved try-on image becomes the only reference for video prompts.
- [ ] **Step 2: Run focused service tests** and verify the new assertions fail.
- [ ] **Step 3: Inject optional try-on pipeline into `JobService`**; preserve existing behavior when absent; persist attempt metadata without new secret fields.
- [ ] **Step 4: Re-run service tests and existing suite**.
- [ ] **Step 5: Commit** with `feat: gate video generation on approved try-on`.

### Task 4: Gemini web image engine

**Files:**
- Create: `tools/video-sales-flow/src/video_sales_flow/tryon/gemini_web.py`
- Test: `tools/video-sales-flow/tests/test_gemini_tryon_engine.py`

**Interfaces:**
- Consumes: `Settings`, `TryOnImageEngine`.
- Produces: `GeminiWebTryOnEngine.generate_tryon(...)`.

- [ ] **Step 1: Write failing unit tests** for selector env overrides, login-redirect detection, purchase-text guard, and safe output filename behavior without launching a browser.
- [ ] **Step 2: Run focused tests** and verify module/functions are missing.
- [ ] **Step 3: Implement Playwright adapter** using persistent profile/browser detection, upload references, one submit per attempt, wait/download generated image, debug screenshot on failure, and no purchase/upgrade clicks.
- [ ] **Step 4: Run focused tests and compile package**.
- [ ] **Step 5: Commit** with `feat: add Gemini web try-on engine`.

### Task 5: Runtime wiring, CLI/Telegram compatibility, docs

**Files:**
- Modify: `tools/video-sales-flow/src/video_sales_flow/engines/__init__.py` only if shared builder support is needed.
- Modify: `tools/video-sales-flow/src/video_sales_flow/cli.py`
- Modify: `tools/video-sales-flow/src/video_sales_flow/telegram_bot.py`
- Modify: `tools/video-sales-flow/README.md`
- Modify: `tools/video-sales-flow/pyproject.toml`
- Test: `tools/video-sales-flow/tests/test_cli.py`
- Test: `tools/video-sales-flow/tests/test_telegram_bot.py`

**Interfaces:**
- Produces: runtime builder that selects `legacy|mock|gemini-web` from settings and wires `TryOnPipeline` into CLI/Telegram jobs.

- [ ] **Step 1: Write failing wiring tests** for new CLI/env selection and `google-flow + gemini-web` configuration.
- [ ] **Step 2: Run focused tests** and verify failure before wiring.
- [ ] **Step 3: Add Pillow runtime dependency, builder/wiring, and README commands**. Document `video-sales-flow login` as the shared Google profile bootstrap and the new Gemini env variables.
- [ ] **Step 4: Run `python -m pytest -q` and `python -m compileall -q src`**.
- [ ] **Step 5: Commit** with `feat: wire Gemini try-on into Telegram video flow`.

### Task 6: PR verification and merge

**Files:** none beyond fixes required by verification.

- [ ] **Step 1: Open PR to `main`** with TDD/safety summary.
- [ ] **Step 2: Confirm GitHub Actions runs the entire package test suite**.
- [ ] **Step 3: Fix any CI failures on the feature branch and rerun**.
- [ ] **Step 4: Review the final diff for credential leakage, watermark-removal behavior, and accidental paid-API fallbacks**.
- [ ] **Step 5: Squash-merge only when CI is green and head SHA is unchanged**.