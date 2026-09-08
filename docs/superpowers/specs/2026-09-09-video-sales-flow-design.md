# Video Sales Flow Design

## Goal

Add an isolated `tools/video-sales-flow` utility to `macos-tools` that turns one model image plus one or more garment reference images into a configurable batch of short apparel-sales videos. The tool automatically plans suitable motions (pose, catwalk, turn, light jump, or mixed), generates virtual-try-on and video prompts, runs those prompts through a pluggable engine, and persists auditable job manifests and output assets.

## Scope

The first production slice provides:

- explicit model-image and garment-image inputs;
- one or many garment references per job;
- requested video count with a hard local safety limit;
- automatic or user-selected motion planning;
- Vietnamese-friendly sales metadata (brand, product, audience, CTA) while prompts are emitted in English for model adherence;
- a deterministic prompt planner that preserves model identity and garment appearance;
- a mock engine for zero-credit local/CI testing;
- a Google Flow browser engine using the user's own persistent Chromium profile and included Flow credits, not the paid Gemini/Veo API;
- a CLI for login/profile bootstrap and job generation;
- a small FastAPI surface for uploads, background execution, and job status;
- JSON manifests for status, prompts, outputs, and failures;
- no password, OAuth token, cookie export, or Google credential stored in git.

Out of scope for this slice: automated social-network publishing, voice-over generation, music licensing, payment/checkout, product-catalog integrations, and reverse engineering of private Google APIs.

## Architecture

`video_sales_flow` is a Python package under `tools/video-sales-flow/src/`. Pure planning and job orchestration are isolated from external generation engines. `PromptPlanner` converts validated job input into one try-on prompt per garment and N video prompt variants. `JobService` owns filesystem layout, engine calls, status transitions, and manifest persistence. Engines implement a narrow interface so prompt logic remains testable without consuming credits.

The Google Flow engine uses Playwright `launch_persistent_context` against a local profile directory outside version control. It opens `https://flow.google/` by default, uploads reference files, fills the agent prompt, initiates generation, waits for a downloadable result, and copies the downloaded asset into the job output directory. UI selectors are centralized and overridable through environment variables because Flow is a web application whose DOM may change. On automation failure the engine saves a screenshot and raises a diagnostic error instead of retrying unboundedly.

## Data flow

1. Validate the model image, garment images, requested count, duration, and local credit guard.
2. Copy inputs into `outputs/<job-id>/inputs/` so the manifest is self-contained.
3. For each garment, build a virtual-try-on prompt and ask the engine for one edited still image.
4. Plan N motion variants. `auto` rotates through pose, catwalk, turn, mixed, and light-jump directions to avoid near-duplicate clips.
5. Build one video prompt per variant, attaching the corresponding edited still as the reference.
6. Ask the engine to generate/download each video sequentially. Sequential generation is intentional to reduce accidental credit bursts and simplify recovery.
7. Update `manifest.json` atomically after every stage so interrupted jobs remain inspectable.
8. Expose the same service through CLI and API adapters.

## Google Flow automation safety

- Default engine is `mock`; real credit use requires `--engine google-flow` or `VIDEO_SALES_ENGINE=google-flow`.
- The job limit defaults to 10 videos and can only be lowered or explicitly raised with `VIDEO_SALES_MAX_VIDEOS`.
- The engine never clicks buttons whose accessible text includes purchase/upgrade/top-up terms.
- No billing API or automatic credit purchase is implemented.
- Login is interactive and headful: `video-sales-flow login` opens the persistent Chromium profile for the user to authenticate directly with Google.
- Job automation fails closed if a known purchase/upgrade modal is detected.
- Generated content remains subject to Google Flow's current availability, credits, and product rules.

## Prompt policy

Try-on prompts must:

- preserve face, identity, skin tone, hair, body proportions, and pose unless a change is needed for garment fit;
- transfer the garment's color, construction, visible graphics, silhouette, and material cues from the garment reference;
- avoid inventing logos, text, accessories, or garment details;
- produce a commercially usable fashion still with realistic fabric folds and anatomy.

Video prompts must:

- preserve identity and garment consistency from the edited still;
- use realistic, physically plausible motion;
- keep the garment visible and legible throughout the key selling moments;
- use smooth short-form camera movement appropriate for vertical social video;
- vary motion/camera composition across requested variants;
- avoid embedded generated text unless explicitly enabled later; CTA text is metadata for downstream editing, not rendered by Veo in this slice.

## Components

- `models.py`: enums and dataclasses/Pydantic-compatible domain models.
- `planner.py`: motion selection plus try-on/video prompt construction.
- `storage.py`: job directory creation, input copies, atomic JSON writes, path validation.
- `service.py`: orchestration and state transitions.
- `engines/base.py`: engine protocol and generation request/result types.
- `engines/mock.py`: deterministic local engine that writes prompt artifacts.
- `engines/google_flow.py`: Playwright adapter and centralized selectors.
- `cli.py`: login and generate commands.
- `api.py`: multipart upload, background job launch, status endpoint.
- `tests/`: pure planner/service/storage tests plus browser-adapter unit tests that do not access Google.

## Error handling

Input errors fail before any engine call. Every engine failure records the current stage and message in `manifest.json`. Google Flow timeouts include a screenshot path when possible. The service never silently substitutes a paid API. Existing completed assets are retained on partial failure so a job can be diagnosed or re-run manually.

## Testing

TDD covers validation, motion distribution, prompt invariants, manifest state transitions, file copying, max-video guard, and Google Flow selector/purchase-guard behavior. CI uses only the mock engine and therefore consumes no Google credits. Real Google Flow execution is documented as a local smoke test because it requires an authenticated user session and live third-party UI.

## Compatibility

- Python 3.11+.
- macOS is the primary runtime; Linux is supported for mock-engine tests.
- Playwright Chromium is installed separately with `python -m playwright install chromium`.
- Tool files are fully contained under `tools/video-sales-flow` except feature documentation under `docs/superpowers`.
