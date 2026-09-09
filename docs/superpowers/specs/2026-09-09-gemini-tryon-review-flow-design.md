# Gemini Try-On Review Flow Design

## Goal

Extend `tools/video-sales-flow` so a Telegram user can send one model image followed by one or more outfit images, have each outfit composited onto the model through the user's authenticated Gemini web session, review the generated still before spending Google Flow video credits, and only pass approved stills to Google Flow for video generation.

## User flow

1. Telegram receives the first image as the model and subsequent images as outfit references.
2. `/make [count] [tone]` creates the existing persisted job.
3. For every outfit, the job creates a try-on prompt using the existing `PromptPlanner.plan_tryon` semantics.
4. A dedicated image engine generates the try-on still. Production uses Gemini web with the same persistent Google browser profile; CI uses a deterministic mock image engine.
5. The generated still is reviewed before video generation.
6. Review rejects missing/corrupt files, unsupported image files, images below configured dimensions, and outputs that are reported to contain watermark/overlaid stock text. The system does not remove watermarks.
7. Rejected stills are regenerated up to `VIDEO_SALES_TRYON_MAX_ATTEMPTS`; each retry appends the review reason to the next prompt.
8. Only an approved still is passed into `PromptPlanner.plan_videos` and then `GoogleFlowEngine.generate_video`.
9. Telegram returns generated videos to the originating chat using the existing delivery path.

## Architecture

### Image generation abstraction

Create a focused `tryon` package independent of the video engine:

- `tryon/base.py`: `TryOnImageEngine` protocol and `TryOnGenerationError`.
- `tryon/mock.py`: deterministic valid PNG generator for tests/CI.
- `tryon/gemini_web.py`: Playwright adapter for `https://gemini.google.com/app`, using `Settings.profile_dir` and browser detection already used by Google Flow.
- `tryon/review.py`: structural image validation plus pluggable semantic review result.
- `tryon/pipeline.py`: retry orchestration and review feedback.

`JobService` receives an optional `tryon_engine` and `tryon_reviewer`. When omitted, legacy behavior is preserved by using the existing generation engine for image generation. CLI/Telegram production wiring explicitly selects the new Gemini try-on pipeline when configured.

### Gemini web adapter

Gemini web automation uses the authenticated persistent Chromium profile and does not export credentials/cookies. It will:

- navigate to `VIDEO_SALES_GEMINI_URL` (default `https://gemini.google.com/app`);
- detect Google sign-in redirects and fail with a clear login-required error;
- upload the model and outfit references through a configurable file-input selector;
- fill the configured prompt textbox;
- submit exactly once per attempt;
- wait for a newly rendered/downloadable generated image;
- download the image to the job's try-on directory;
- save a debug screenshot on failures;
- never click plan upgrades, purchases, or paid API controls.

Selectors remain environment-overridable so UI changes can be fixed without changing the orchestration layer.

### Review policy

The reviewer returns `TryOnReviewResult(approved, issues, retry_hint, metadata)`.

Local structural checks are mandatory and deterministic:

- file exists and is non-empty;
- decodes as PNG/JPEG/WebP through Pillow;
- minimum width/height configured by `VIDEO_SALES_TRYON_MIN_WIDTH` and `VIDEO_SALES_TRYON_MIN_HEIGHT` (defaults 512x512).

Semantic watermark/anatomy review is optional and conservative. For this iteration, Gemini web can be asked to return a short JSON review in a separate prompt when `VIDEO_SALES_TRYON_REVIEW_MODE=gemini-web`; otherwise `local` mode only performs structural checks and filename/text heuristics. Any explicit watermark/stock-text finding causes rejection and regeneration. The product never removes a watermark.

### Retry and credit safety

- `VIDEO_SALES_TRYON_MAX_ATTEMPTS` defaults to 3 and must be 1..5.
- Image retries occur before Google Flow video generation.
- Google Flow video generation is not started for an outfit unless its try-on still is approved.
- Telegram with `google-flow` continues to require `TELEGRAM_ALLOWED_CHAT_IDS`.
- Existing `VIDEO_SALES_MAX_VIDEOS` and `VIDEO_SALES_MAX_OUTFITS` limits remain authoritative.

### Manifest

Approved and rejected image attempts are persisted as `GeneratedAsset` entries using existing `asset_type="edited_image"` or `asset_type="debug"` with metadata fields such as:

- `stage=tryon`
- `attempt`
- `approved`
- `review_issues`
- `image_engine`

No token, cookie, Google account credential, or Telegram secret is written into a manifest.

## Configuration

New settings:

- `VIDEO_SALES_TRYON_ENGINE=legacy|mock|gemini-web` (default `legacy` to preserve compatibility)
- `VIDEO_SALES_GEMINI_URL=https://gemini.google.com/app`
- `VIDEO_SALES_TRYON_MAX_ATTEMPTS=3`
- `VIDEO_SALES_TRYON_MIN_WIDTH=512`
- `VIDEO_SALES_TRYON_MIN_HEIGHT=512`
- `VIDEO_SALES_TRYON_REVIEW_MODE=local|gemini-web` (default `local`)
- selector overrides prefixed with `VIDEO_SALES_GEMINI_...`

README will recommend `gemini-web` + `google-flow` for the user's production workflow.

## Testing

CI remains credential-free and credit-free. Tests cover:

- settings validation;
- structural image review;
- reject/retry/approve orchestration;
- service does not call video generation before approval;
- approved try-on paths become video references;
- Gemini selector/config helpers without network access;
- Telegram behavior remains compatible.

A real Gemini + Google Flow smoke test still requires the user's Mac, browser profile, and authenticated Google account.