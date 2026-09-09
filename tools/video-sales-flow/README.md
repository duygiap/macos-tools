# Video Sales Flow

`video-sales-flow` creates short apparel-sales video batches from one model image plus one or more garment reference images.

Recommended production flow:

```text
Telegram photos
  -> Google AI Studio / Gemini API try-on
  -> local + optional API semantic review
  -> reject + regenerate when needed
  -> approved still only
  -> Google Flow video generation
  -> Telegram finished video
```

The try-on stage now supports the official `google-genai` SDK with `GEMINI_API_KEY`. Google Flow video generation remains browser-based because that is a separate stage. The previous Google AI Studio browser adapter remains available as `gemini-web` for backwards compatibility.

## Safety defaults

- Video engine defaults to `mock`; mock mode consumes no AI/Flow credits.
- Try-on engine defaults to `legacy` until explicitly enabled.
- Real video generation requires `--engine google-flow` or `VIDEO_SALES_ENGINE=google-flow`.
- Default local limits are 10 videos and 10 outfit references per job.
- Try-on review defaults to minimum dimensions of 512x512 and at most 3 attempts.
- A rejected try-on image is regenerated. The tool does **not** remove, crop, hide, or inpaint watermarks.
- Google Flow does not start until every required try-on still is approved.
- `GEMINI_API_KEY` and `TELEGRAM_BOT_TOKEN` are read from the environment and are never persisted in manifests.
- Telegram `google-flow` mode refuses to start unless `TELEGRAM_ALLOWED_CHAT_IDS` is set.
- Generation remains sequential in the Telegram worker to avoid accidental concurrent Flow/browser use.

## Requirements

- Python 3.11+
- `GEMINI_API_KEY` from your Google AI Studio / Gemini API account for `ai-studio-api`
- Chrome/Chromium + a signed-in Google Flow session for the video stage
- Optional Telegram Bot API token from BotFather

## Install

```bash
cd tools/video-sales-flow
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m playwright install chromium
```

The package installs `google-genai>=2.22,<3` for the official Gemini Interactions API path.

## 1. Test locally without spending generation credits

Legacy/mock job:

```bash
video-sales-flow generate \
  --model ~/Pictures/model.jpg \
  --outfit ~/Pictures/shirt.jpg \
  --outfit ~/Pictures/jacket.jpg \
  --count 3 \
  --engine mock
```

Test the reviewed try-on orchestration without external calls:

```bash
video-sales-flow generate \
  --model ~/Pictures/model.jpg \
  --outfit ~/Pictures/shirt.jpg \
  --count 2 \
  --engine mock \
  --tryon-engine mock \
  --tryon-review-mode local
```

The mock try-on engine creates deterministic images so CI can verify review/retry and Flow gating without any API key.

## 2. Configure AI Studio API try-on

Copy the provided template:

```bash
cp .env.example .env
```

Set your own key in `.env`:

```dotenv
GEMINI_API_KEY='your-own-api-key'

VIDEO_SALES_TRYON_ENGINE='ai-studio-api'
VIDEO_SALES_TRYON_REVIEW_MODE='ai-studio-api'
VIDEO_SALES_TRYON_MAX_ATTEMPTS='3'

VIDEO_SALES_AI_STUDIO_API_MODEL='models/gemini-3.1-flash-lite-image'
VIDEO_SALES_AI_STUDIO_API_ASPECT_RATIO='9:16'
VIDEO_SALES_AI_STUDIO_API_IMAGE_SIZE='1K'
VIDEO_SALES_AI_STUDIO_API_THINKING_LEVEL='high'
VIDEO_SALES_AI_STUDIO_API_TEMPERATURE='1'
VIDEO_SALES_AI_STUDIO_API_TOP_P='1'
VIDEO_SALES_AI_STUDIO_API_MAX_OUTPUT_TOKENS='65536'
```

The CLI loads `.env` automatically. Exported process variables take precedence over values in `.env`.

Do not commit `.env`, the Gemini API key, Telegram token, Google cookies, or browser-profile data.

### What the API request does

For every outfit, the try-on engine sends three multimodal inputs to the configured Gemini image model:

1. model/person image;
2. outfit/garment image;
3. the identity-preserving apparel prompt created by the existing planner.

Generation uses the Interactions API and requests a PNG image response. The default image response settings are `9:16` and `1K`.

The returned image bytes are saved into the job's `tryon/` directory and then passed through the existing review/retry pipeline.

## 3. Review and retry behavior

For each outfit:

1. Generate a try-on still through `ai-studio-api`.
2. Run mandatory local validation with Pillow: real image decode, non-empty file, and minimum dimensions.
3. If `VIDEO_SALES_TRYON_REVIEW_MODE=ai-studio-api`, send the generated still to the same API client for semantic review.
4. Reject visible watermark/stock-source text, unrelated overlaid text, serious face/hand/body distortion, broken garment geometry, or an implausible outfit result.
5. Append review issues and the retry hint to the next generation prompt.
6. Regenerate up to `VIDEO_SALES_TRYON_MAX_ATTEMPTS`.
7. Only an approved still is passed to Google Flow as the video image reference.

If you only want local file/size validation and do not want a second API review call, use:

```dotenv
VIDEO_SALES_TRYON_REVIEW_MODE='local'
```

### Watermark policy

The tool does **not** remove watermarks. A watermark/stock-source finding causes the current image to fail review and triggers generation of a new clean image.

## 4. Prepare Google Flow

The recommended API try-on path does **not** require a Gemini/AI Studio browser login. A persistent browser profile is still needed for Google Flow video generation.

```bash
export VIDEO_SALES_PROFILE_DIR="$HOME/.local/share/video-sales-flow/chrome"
video-sales-flow login
```

Sign in to Google Flow in the browser opened by the command, then return to the terminal.

The old browser try-on path remains available if needed:

```bash
video-sales-flow gemini-login
```

and can be selected with:

```dotenv
VIDEO_SALES_TRYON_ENGINE='gemini-web'
VIDEO_SALES_TRYON_REVIEW_MODE='gemini-web'
```

`gemini-web` is a compatibility/fallback mode; `ai-studio-api` is the recommended try-on path.

## 5. Generate reviewed stills and Flow videos

Recommended environment:

```dotenv
GEMINI_API_KEY='your-own-api-key'
VIDEO_SALES_ENGINE='google-flow'
VIDEO_SALES_TRYON_ENGINE='ai-studio-api'
VIDEO_SALES_TRYON_REVIEW_MODE='ai-studio-api'
VIDEO_SALES_TRYON_MAX_ATTEMPTS='3'
VIDEO_SALES_PROFILE_DIR="$HOME/.local/share/video-sales-flow/chrome"
```

Run:

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
  --tryon-engine ai-studio-api \
  --tryon-review-mode ai-studio-api
```

Rejected attempts are retained as `debug` assets in the job manifest. Approved attempts are stored as `edited_image` assets. Credentials are not stored in asset metadata.

## 6. Telegram: model/outfit images in, finished videos out

Telegram uses long polling; no public webhook, domain, inbound port, or Cloudflare Tunnel is required.

Example `.env`:

```dotenv
GEMINI_API_KEY='your-own-api-key'
TELEGRAM_BOT_TOKEN='123456:replace-with-your-bot-token'
TELEGRAM_ALLOWED_CHAT_IDS='123456789'

VIDEO_SALES_ENGINE='google-flow'
VIDEO_SALES_TRYON_ENGINE='ai-studio-api'
VIDEO_SALES_TRYON_REVIEW_MODE='ai-studio-api'
VIDEO_SALES_TRYON_MAX_ATTEMPTS='3'
VIDEO_SALES_PROFILE_DIR="$HOME/.local/share/video-sales-flow/chrome"
```

If you do not yet know your Telegram chat ID, send the bot one message and inspect it once:

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
  --tryon-engine ai-studio-api \
  --tryon-review-mode ai-studio-api
```

Chat flow:

1. First photo = model/person.
2. Later photos = garment/outfit references.
3. Send `/make 3 premium` (or `/make`).
4. The bot persists the job and clears pending inputs.
5. Gemini API generates/reviews the try-on stills and retries rejected outputs.
6. Google Flow generates video only from approved stills.
7. Completed videos are uploaded back to the same `chat_id` and reply to the original `/make` message.

Commands:

```text
/start                 show instructions
/help                  show instructions
/make [count] [tone]   create the job; e.g. /make 3 premium
/status                show status of the last job in this chat
/reset                 clear pending model/outfit images
/resend [job_id]       resend completed video assets (last job if omitted)
```

Supported tone values: `energetic`, `elegant`, `youthful`, `premium`, `minimal`.

Telegram session state:

```text
outputs/_telegram/
├── sessions/<chat-id>.json
└── media/<chat-id>/...
```

The session JSON stores local media paths and the last job ID, not the bot token. The client rejects local video files larger than 50 MB before trying hosted Bot API `sendVideo`.

## Output layout

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

`manifest.json` is atomically updated after generation/review steps and includes status, options, prompts, generated assets, review metadata, and job errors.

```bash
video-sales-flow status <job-id>
```

## Local HTTP API

Start:

```bash
uvicorn video_sales_flow.api:app --host 127.0.0.1 --port 8099
```

The API uses the same environment-configured pipeline as CLI and Telegram:

```bash
GEMINI_API_KEY='your-own-api-key' \
VIDEO_SALES_ENGINE=google-flow \
VIDEO_SALES_TRYON_ENGINE=ai-studio-api \
VIDEO_SALES_TRYON_REVIEW_MODE=ai-studio-api \
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
| `GEMINI_API_KEY` | none | Required by `ai-studio-api`; keep secret |
| `VIDEO_SALES_ENGINE` | `mock` | Video engine: `mock` or `google-flow` |
| `VIDEO_SALES_TRYON_ENGINE` | `legacy` | `legacy`, `mock`, `gemini-web`, or recommended `ai-studio-api` |
| `VIDEO_SALES_TRYON_REVIEW_MODE` | `local` | `local`, `gemini-web`, or `ai-studio-api` |
| `VIDEO_SALES_AI_STUDIO_API_MODEL` | `models/gemini-3.1-flash-lite-image` | Gemini image model used by official API |
| `VIDEO_SALES_AI_STUDIO_API_ASPECT_RATIO` | `9:16` | Requested generated-image aspect ratio |
| `VIDEO_SALES_AI_STUDIO_API_IMAGE_SIZE` | `1K` | Requested generated-image size |
| `VIDEO_SALES_AI_STUDIO_API_THINKING_LEVEL` | `high` | API thinking level |
| `VIDEO_SALES_AI_STUDIO_API_TEMPERATURE` | `1` | Generation temperature |
| `VIDEO_SALES_AI_STUDIO_API_TOP_P` | `1` | Generation top-p |
| `VIDEO_SALES_AI_STUDIO_API_MAX_OUTPUT_TOKENS` | `65536` | Generation output-token limit |
| `VIDEO_SALES_TRYON_MAX_ATTEMPTS` | `3` | Generate/review attempts per outfit; valid 1-5 |
| `VIDEO_SALES_TRYON_MIN_WIDTH` | `512` | Minimum approved still width |
| `VIDEO_SALES_TRYON_MIN_HEIGHT` | `512` | Minimum approved still height |
| `VIDEO_SALES_OUTPUT_ROOT` | `./outputs` | Job/output directory |
| `VIDEO_SALES_PROFILE_DIR` | `./.browser-profile` | Persistent Chromium profile used by Google Flow |
| `VIDEO_SALES_FLOW_URL` | `https://flow.google/` | Flow URL |
| `VIDEO_SALES_MAX_VIDEOS` | `10` | Per-job video guard |
| `VIDEO_SALES_MAX_OUTFITS` | `10` | Per-job outfit guard |
| `VIDEO_SALES_FLOW_TIMEOUT_SECONDS` | `300` | Flow browser timeout |
| `VIDEO_SALES_HEADLESS` | `true` | Use headless browser after interactive Flow login |
| `VIDEO_SALES_BROWSER_EXECUTABLE` | auto-detected | Override Chrome/Chromium executable |
| `TELEGRAM_BOT_TOKEN` | none | Telegram bot token |
| `TELEGRAM_ALLOWED_CHAT_IDS` | none | Required for `google-flow`; comma-separated allowlist |

### Legacy `gemini-web` configuration

These settings are only needed when intentionally using the browser-based fallback:

| Variable | Default / purpose |
|---|---|
| `VIDEO_SALES_GEMINI_URL` | `https://aistudio.google.com/prompts/new_chat` |
| `VIDEO_SALES_AI_STUDIO_IMAGE_MODEL` | Browser UI model label, default `Nano Banana 2 Lite` |
| `VIDEO_SALES_AI_STUDIO_IMAGE_RESOLUTION` | Browser UI resolution, default `1K` |
| `VIDEO_SALES_GEMINI_PROMPT_SELECTOR` | Prompt textbox selector |
| `VIDEO_SALES_GEMINI_UPLOAD_SELECTOR` | File input selector |
| `VIDEO_SALES_GEMINI_UPLOAD_MENU_SELECTOR` | Insert-media menu selector |
| `VIDEO_SALES_GEMINI_UPLOAD_MENU_ITEM_SELECTOR` | Upload-files menu item selector |
| `VIDEO_SALES_GEMINI_UPLOAD_MENU_INPUT_SELECTOR` | Menu-scoped file input selector |
| `VIDEO_SALES_GEMINI_UPLOAD_TRIGGER_SELECTOR` | Upload-button fallback selector |
| `VIDEO_SALES_GEMINI_SEND_SELECTOR` | Submit/run selector |
| `VIDEO_SALES_AI_STUDIO_MODEL_SELECTOR` | Browser model-picker selector |
| `VIDEO_SALES_AI_STUDIO_RESOLUTION_SELECTOR` | Browser resolution-picker selector |
| `VIDEO_SALES_GEMINI_DOWNLOAD_SELECTOR` | Generated-image download selector |
| `VIDEO_SALES_GEMINI_GENERATED_IMAGE_SELECTOR` | Generated-image selector |
| `VIDEO_SALES_GEMINI_RESPONSE_SELECTOR` | Semantic-review response selector |
| `VIDEO_SALES_GEMINI_DIALOG_SELECTOR` | Dialog selector |

### Google Flow selector overrides

| Variable | Purpose |
|---|---|
| `VIDEO_SALES_FLOW_PROMPT_SELECTOR` | Prompt textbox |
| `VIDEO_SALES_FLOW_UPLOAD_SELECTOR` | File input |
| `VIDEO_SALES_FLOW_UPLOAD_TRIGGER_SELECTOR` | Upload-button fallback |
| `VIDEO_SALES_FLOW_GENERATE_SELECTOR` | Generate button |
| `VIDEO_SALES_FLOW_DOWNLOAD_SELECTOR` | Generated asset download control |
| `VIDEO_SALES_FLOW_DIALOG_SELECTOR` | Dialog inspected by credit/purchase guard |

If Google Flow changes its UI, inspect the generated debug screenshot and override only the affected selector. The planner, try-on API, review/retry, manifest, API, and Telegram layers remain independent of Flow DOM selectors.

## Tests

CI does not use a real Gemini key, does not log in to Google Flow, does not contact Telegram, and does not consume generation credits:

```bash
python -m pytest -q
python -m compileall -q src
```

The suite uses fake/mock SDK clients, transports, and engines to verify:

- multimodal API payload contains model image + outfit image + prompt;
- Interactions image response settings are applied;
- missing `GEMINI_API_KEY` is rejected before a real request;
- reviewed try-on generation retries rejected images with review feedback;
- watermark findings are rejected rather than removed;
- exhausted try-on review prevents video-generation calls;
- approved try-on stills become the only image references passed to Flow video prompts;
- CLI, API, and Telegram honor the configured try-on pipeline;
- real Flow Telegram mode cannot start without an explicit chat allowlist.

## Current limitation

CI validates the API adapter with fake SDK interactions; it does not prove that your account currently has quota/entitlement for the configured Gemini image model. A real smoke test on your Mac still needs your own `GEMINI_API_KEY`.

The recommended try-on path no longer depends on Google AI Studio DOM selectors. Google Flow is still a live browser UI and can change, so its selectors may still need adjustment after a Flow UI update.
