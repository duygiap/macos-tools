# Video Sales Flow

`video-sales-flow` creates short apparel-sales video batches from:

- one model image;
- one or more garment reference images;
- a requested number of videos;
- optional motion/tone/product metadata.

The production workflow can now run as:

```text
Telegram photos
  -> Google AI Studio try-on
  -> image quality / watermark review
  -> reject + regenerate when needed
  -> approved still only
  -> Google Flow video generation
  -> Telegram finished video
```

The Google integrations deliberately use **Google AI Studio and Google Flow in Chromium via Playwright** with the capabilities already available to the signed-in Google account. They do **not** fall back to paid Gemini/Veo APIs, reverse engineer private APIs, buy credits, or upgrade a plan automatically.

## Safety defaults

- Video engine defaults to `mock`; mock mode consumes no AI credits.
- Try-on engine defaults to `legacy`, preserving the existing behavior until `VIDEO_SALES_TRYON_ENGINE` is explicitly enabled.
- Real video generation requires explicit `--engine google-flow` or `VIDEO_SALES_ENGINE=google-flow`.
- Default local limits are 10 videos and 10 outfit references per job.
- Try-on review defaults to 512x512 minimum dimensions and at most 3 generation attempts.
- A try-on image rejected by review is **regenerated**. The tool does not remove or conceal watermarks.
- Google Flow video generation does not begin until every required try-on still has been approved.
- Purchase/upgrade dialogs in Google AI Studio or Flow are detected and the operation aborts rather than clicking them.
- Google credentials remain only in the local persistent browser profile; the tool does not export cookies or passwords.
- Telegram bot tokens are read only from `TELEGRAM_BOT_TOKEN`; they are never persisted into manifests or source files.
- Telegram `google-flow` mode refuses to start unless `TELEGRAM_ALLOWED_CHAT_IDS` is set, preventing an unknown chat from consuming Flow credits.
- Generation is sequential inside each Telegram worker to avoid accidental concurrent browser/profile use and credit bursts.

> Google AI Studio and Google Flow are live third-party web UIs. Their DOM can change. Important selectors are environment-overridable so UI changes can be fixed without changing the job orchestration layer.

## Requirements

- Python 3.11+
- macOS for the intended authenticated Google AI Studio/Flow workflow (mock tests also work on Linux)
- Chromium/Chrome usable by Playwright
- A Google account that can use Google AI Studio and Google Flow
- Optional: a Telegram Bot API token from BotFather for Telegram image-in/video-out mode

## Install

```bash
cd tools/video-sales-flow
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m playwright install chromium
```

## 1. Inspect the legacy workflow without spending credits

```bash
video-sales-flow generate \
  --model ~/Pictures/model.jpg \
  --outfit ~/Pictures/shirt.jpg \
  --outfit ~/Pictures/jacket.jpg \
  --count 5 \
  --motion auto \
  --brand 'My Shop' \
  --product 'Áo sơ mi nữ' \
  --audience 'Nữ 18-30 tuổi' \
  --engine mock
```

Outputs are written to `./outputs/<job-id>/`. The default `VIDEO_SALES_TRYON_ENGINE=legacy` keeps existing mock/Flow image behavior unchanged.

To test the new reviewed try-on orchestration without Gemini or Flow network calls:

```bash
video-sales-flow generate \
  --model ~/Pictures/model.jpg \
  --outfit ~/Pictures/shirt.jpg \
  --count 2 \
  --engine mock \
  --tryon-engine mock \
  --tryon-review-mode local
```

The mock try-on engine creates deterministic PNG images, local review approves them, and CI can test the complete gating behavior without external accounts or credits.

## 2. Prepare the shared Google browser profile

The Google AI Studio and Flow adapters can share one persistent Chromium profile.

Choose a stable profile directory:

```bash
export VIDEO_SALES_PROFILE_DIR="$HOME/.local/share/video-sales-flow/chrome"
```

Sign in / prepare Google Flow:

```bash
video-sales-flow login
```

Sign in / prepare Google AI Studio:

```bash
video-sales-flow gemini-login
```

Both commands open the relevant Google site with the configured persistent profile. Sign in directly with Google in that browser. No password or cookie export is written into this repository.

A custom AI Studio URL or browser executable can be supplied when needed:

```bash
video-sales-flow gemini-login \
  --gemini-url 'https://aistudio.google.com/prompts/new_chat' \
  --browser-executable '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
```

## 3. Generate a reviewed try-on image before Flow video

Recommended production configuration:

```bash
export VIDEO_SALES_ENGINE='google-flow'
export VIDEO_SALES_TRYON_ENGINE='gemini-web'
export VIDEO_SALES_TRYON_REVIEW_MODE='gemini-web'
export VIDEO_SALES_TRYON_MAX_ATTEMPTS='3'
export VIDEO_SALES_TRYON_MIN_WIDTH='512'
export VIDEO_SALES_TRYON_MIN_HEIGHT='512'
export VIDEO_SALES_PROFILE_DIR="$HOME/.local/share/video-sales-flow/chrome"
```

Then run:

```bash
video-sales-flow generate \
  --model ~/Pictures/model.jpg \
  --outfit ~/Pictures/shirt.jpg \
  --count 3 \
  --motion auto \
  --tone premium \
  --brand 'My Shop' \
  --product 'Áo sơ mi nữ' \
  --cta 'Mua ngay' \
  --engine google-flow \
  --tryon-engine gemini-web \
  --tryon-review-mode gemini-web
```

For each outfit the service now performs this order:

1. Build the existing identity-preserving apparel try-on prompt.
2. In Google AI Studio, select **Upload files** and upload the model image plus that outfit reference.
3. Select the configured image model (default: **Nano Banana 2 Lite**) and **1K** resolution, then run the prompt in AI Studio to generate the model wearing the referenced garment.
4. Download the original generated file; AI Studio thumbnail screenshots are never used as try-on assets.
5. Run mandatory local validation: real image decode, non-empty file, and minimum dimensions.
6. When `VIDEO_SALES_TRYON_REVIEW_MODE=gemini-web`, upload that generated still to AI Studio again for semantic review.
7. Reject visible watermark/stock-source text, unrelated overlaid text, serious face/hand/body distortion, broken garment geometry, or an implausible try-on result.
8. If rejected, append the review issues and retry hint to the next generation prompt and regenerate, up to `VIDEO_SALES_TRYON_MAX_ATTEMPTS`.
9. Only the approved still becomes Reference Image A for Google Flow video generation.

Rejected attempts are retained as `debug` assets in the job manifest for diagnosis. Approved attempts are stored as `edited_image` assets with metadata such as `stage=tryon`, attempt number, review result, dimensions, and image engine. No account credential or token is stored in this metadata.

### Watermark policy

The tool does **not** remove, crop out, hide, or inpaint a watermark. If local/semantic review reports a visible watermark or stock-source marker, that attempt is rejected and a clean image is regenerated. This keeps watermark handling separate from content alteration.

## 4. Telegram: send model/outfit images, receive finished videos

Telegram mode uses long polling, so the Mac does **not** need a public HTTP port, webhook, Cloudflare Tunnel, or public domain.

Create `.env` in the workspace root (it is ignored by Git). The CLI loads it automatically,
so you do not need to export these values in every terminal:

```bash
TELEGRAM_BOT_TOKEN='123456:replace-with-your-bot-token'
TELEGRAM_ALLOWED_CHAT_IDS='123456789'
VIDEO_SALES_ENGINE='google-flow'
VIDEO_SALES_TRYON_ENGINE='gemini-web'
VIDEO_SALES_TRYON_REVIEW_MODE='gemini-web'
VIDEO_SALES_TRYON_MAX_ATTEMPTS='3'
VIDEO_SALES_PROFILE_DIR="$HOME/.local/share/video-sales-flow/chrome"
```

If you do not yet know your chat ID, send one message to the bot and inspect it once:

```bash
python - <<'PY'
import os
import httpx

result = httpx.get(
    f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/getUpdates",
    timeout=20,
).json()["result"]
for update in result:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    if "id" in chat:
        print(chat["id"])
PY
```

Start the bot:

```bash
video-sales-flow telegram \
  --engine google-flow \
  --tryon-engine gemini-web \
  --tryon-review-mode gemini-web
```

The chat flow is:

1. Send the model image. The first image in the current session becomes the model.
2. Send one or more garment/outfit images. Each later image becomes an outfit reference.
3. Send `/make 3 premium` (or `/make` for 3 energetic videos).
4. The bot creates a persisted job and clears only the pending input session.
5. Google AI Studio creates and reviews the try-on still(s), retrying rejected results before Flow starts.
6. Google Flow generates video only from approved try-on stills.
7. Each completed video is uploaded back to the **same `chat_id`** and replies to the original `/make` message.

Commands:

```text
/start                 show instructions
/help                  show instructions
/make [count] [tone]   create the job; e.g. /make 3 premium
/status                show status of the last job in this chat
/reset                 clear pending model/outfit images
/resend [job_id]       resend completed video assets (last job if omitted)
```

Supported tone values are `energetic`, `elegant`, `youthful`, `premium`, and `minimal`.

Telegram session state is persisted under:

```text
outputs/_telegram/
├── sessions/<chat-id>.json
└── media/<chat-id>/...
```

The session JSON stores local media paths and the last job ID, **not** the bot token. `/reset` clears pending images but retains the last job ID so `/resend` still works.

The hosted Telegram Bot API has file-size limits. The current client rejects local video files larger than 50 MB before attempting `sendVideo`.

## Output layout

With reviewed try-on enabled:

```text
outputs/<job-id>/
├── manifest.json
├── inputs/
│   ├── model.jpg
│   └── outfit-01-shirt.jpg
├── tryon/
│   ├── tryon-01-attempt-01.png
│   └── tryon-01-attempt-02.png
└── videos/
    ├── video-01.mp4
    └── video-02.mp4
```

`manifest.json` is atomically updated after every generation/review step and includes status, options, prompts, generated assets, review metadata, and the job error if one occurs.

Check a previous job:

```bash
video-sales-flow status <job-id>
```

## API

Start the local API:

```bash
uvicorn video_sales_flow.api:app --host 127.0.0.1 --port 8099
```

The API uses the same environment-configured try-on pipeline as CLI/Telegram. For example:

```bash
VIDEO_SALES_ENGINE=google-flow \
VIDEO_SALES_TRYON_ENGINE=gemini-web \
VIDEO_SALES_TRYON_REVIEW_MODE=gemini-web \
VIDEO_SALES_PROFILE_DIR="$HOME/.local/share/video-sales-flow/chrome" \
uvicorn video_sales_flow.api:app --host 127.0.0.1 --port 8099
```

Create a job:

```bash
curl -X POST http://127.0.0.1:8099/jobs \
  -F 'model_image=@model.jpg' \
  -F 'outfit_images=@shirt.jpg' \
  -F 'outfit_images=@jacket.jpg' \
  -F 'video_count=4' \
  -F 'motions=pose,catwalk' \
  -F 'tone=premium' \
  -F 'product_name=Áo sơ mi nữ'
```

Read status:

```bash
curl http://127.0.0.1:8099/jobs/<job-id>
```

Do not expose this local API directly to the Internet without authentication and request limits; a remote caller could initiate account-backed generation.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VIDEO_SALES_ENGINE` | `mock` | Video engine: `mock` or `google-flow` |
| `VIDEO_SALES_TRYON_ENGINE` | `legacy` | Try-on stage: `legacy`, `mock`, or `gemini-web` |
| `VIDEO_SALES_TRYON_REVIEW_MODE` | `local` | Review mode: `local` or `gemini-web` |
| `VIDEO_SALES_GEMINI_URL` | `https://aistudio.google.com/prompts/new_chat` | Google AI Studio URL (the compatibility variable name remains unchanged) |
| `VIDEO_SALES_AI_STUDIO_IMAGE_MODEL` | `Nano Banana 2 Lite` | Image model selected before every try-on |
| `VIDEO_SALES_AI_STUDIO_IMAGE_RESOLUTION` | `1K` | Image resolution selected before every try-on |
| `VIDEO_SALES_TRYON_MAX_ATTEMPTS` | `3` | Generate/review attempts per outfit; valid 1-5 |
| `VIDEO_SALES_TRYON_MIN_WIDTH` | `512` | Minimum approved still width |
| `VIDEO_SALES_TRYON_MIN_HEIGHT` | `512` | Minimum approved still height |
| `VIDEO_SALES_OUTPUT_ROOT` | `./outputs` | Job/output directory |
| `VIDEO_SALES_PROFILE_DIR` | `./.browser-profile` | Shared persistent Chromium profile |
| `VIDEO_SALES_FLOW_URL` | `https://flow.google/` | Flow URL |
| `VIDEO_SALES_MAX_VIDEOS` | `10` | Hard per-job video guard |
| `VIDEO_SALES_MAX_OUTFITS` | `10` | Hard per-job outfit/try-on guard |
| `VIDEO_SALES_FLOW_TIMEOUT_SECONDS` | `300` | Browser generation/review timeout |
| `VIDEO_SALES_HEADLESS` | `true` | Use Chromium new-headless mode after interactive login/setup |
| `VIDEO_SALES_BROWSER_EXECUTABLE` | auto-detected | Override Chrome/Chromium executable path |
| `TELEGRAM_BOT_TOKEN` | none | Telegram bot token; required by `telegram` |
| `TELEGRAM_ALLOWED_CHAT_IDS` | none | Required for `google-flow`; comma-separated allowlist |

### Google AI Studio selector overrides

| Variable | Purpose |
|---|---|
| `VIDEO_SALES_GEMINI_PROMPT_SELECTOR` | Prompt textbox |
| `VIDEO_SALES_GEMINI_UPLOAD_SELECTOR` | File input |
| `VIDEO_SALES_GEMINI_UPLOAD_MENU_SELECTOR` | AI Studio button that opens the insert-media menu |
| `VIDEO_SALES_GEMINI_UPLOAD_MENU_ITEM_SELECTOR` | `Upload files` item in the insert-media menu |
| `VIDEO_SALES_GEMINI_UPLOAD_MENU_INPUT_SELECTOR` | File input scoped to that upload-files item |
| `VIDEO_SALES_GEMINI_UPLOAD_TRIGGER_SELECTOR` | Add/upload button fallback |
| `VIDEO_SALES_GEMINI_SEND_SELECTOR` | Submit/send button |
| `VIDEO_SALES_AI_STUDIO_MODEL_SELECTOR` | AI Studio image-model picker |
| `VIDEO_SALES_AI_STUDIO_RESOLUTION_SELECTOR` | AI Studio image-resolution picker |
| `VIDEO_SALES_GEMINI_DOWNLOAD_SELECTOR` | Generated-image download control |
| `VIDEO_SALES_GEMINI_GENERATED_IMAGE_SELECTOR` | Generated image element used to reveal the download control |
| `VIDEO_SALES_GEMINI_RESPONSE_SELECTOR` | Semantic review response container |
| `VIDEO_SALES_GEMINI_DIALOG_SELECTOR` | Dialog inspected for purchase/upgrade prompts |

### Google Flow selector overrides

| Variable | Purpose |
|---|---|
| `VIDEO_SALES_FLOW_PROMPT_SELECTOR` | Prompt textbox |
| `VIDEO_SALES_FLOW_UPLOAD_SELECTOR` | File input |
| `VIDEO_SALES_FLOW_UPLOAD_TRIGGER_SELECTOR` | Upload-button fallback |
| `VIDEO_SALES_FLOW_GENERATE_SELECTOR` | Generate button |
| `VIDEO_SALES_FLOW_DOWNLOAD_SELECTOR` | Generated asset download control |
| `VIDEO_SALES_FLOW_DIALOG_SELECTOR` | Dialog inspected by the credit/purchase guard |

## When Google AI Studio or Google Flow changes its UI

Browser failures attempt to save debug screenshots in the relevant job stage. Inspect the screenshot with Chromium DevTools and override only the selector that changed, for example:

```bash
export VIDEO_SALES_GEMINI_PROMPT_SELECTOR='[contenteditable="true"][role="textbox"]'
export VIDEO_SALES_GEMINI_SEND_SELECTOR='button[aria-label="Send message"]'

export VIDEO_SALES_FLOW_PROMPT_SELECTOR='[data-testid="agent-input"]'
export VIDEO_SALES_FLOW_GENERATE_SELECTOR='button[data-testid="generate"]'
```

The planner, manifest, retry/review orchestration, API, and Telegram session/delivery layers remain independent of those UI selectors.

## Tests

Tests never log in to Google AI Studio or Google Flow, never contact Telegram, and never consume Google generation credits:

```bash
python -m pytest -q
python -m compileall -q src
```

The suite uses fake/mock transports and engines to verify:

- the first Telegram image becomes the model and later images become outfits;
- reviewed try-on generation retries rejected images with review feedback;
- watermark findings are rejected rather than removed;
- exhausted try-on review prevents every video-generation call;
- approved try-on stills become the only image references passed to video prompts;
- CLI, API, and Telegram all honor the configured try-on pipeline;
- real Flow Telegram mode cannot start without an explicit chat allowlist.

## Current limitation

Google AI Studio and Google Flow adapters intentionally use their public web UIs rather than undocumented/private APIs. Google may change either UI at any time, so a live authenticated smoke test on your Mac is still required after selector changes. CI verifies the orchestration and safety behavior with mock engines only. The tool fails with diagnostics rather than falling back to a paid API or automatically purchasing/upgrading a plan.
