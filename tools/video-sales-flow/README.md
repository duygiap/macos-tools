# Video Sales Flow

`video-sales-flow` creates short apparel-sales video batches from:

- one model image;
- one or more garment reference images;
- a requested number of videos;
- optional motion/tone/product metadata.

It automatically builds a virtual-try-on prompt for each garment and diversified video prompts for posing, catwalk, turns, a light jump, or mixed fashion movement.

The real Google integration deliberately uses **Google Flow in Chromium via Playwright** and the Flow credits already available to the signed-in account. It does **not** call the paid Gemini/Veo API, reverse engineer a private API, or buy/top-up credits automatically.

## Safety defaults

- Engine defaults to `mock`; mock mode consumes no AI credits.
- Real generation requires explicit `--engine google-flow` or `VIDEO_SALES_ENGINE=google-flow`.
- Default local limits are 10 videos and 10 outfit references per job.
- Purchase/upgrade dialogs are detected and generation aborts rather than clicking them.
- Google credentials are kept only in the local Playwright browser profile; `.browser-profile/` is gitignored.
- Telegram bot tokens are read only from `TELEGRAM_BOT_TOKEN`; they are never persisted into manifests or source files.
- Telegram `google-flow` mode refuses to start unless `TELEGRAM_ALLOWED_CHAT_IDS` is set, preventing an unknown chat from consuming Flow credits.
- Generation is sequential inside each job to avoid an accidental burst of credit usage.

> Google Flow is a live third-party web UI. Its DOM can change. All important selectors can be overridden with environment variables without changing the planner/job code.

## Requirements

- Python 3.11+
- macOS for the intended Google Flow workflow (mock tests also work on Linux)
- Chromium installed by Playwright
- A Google account that can use Google Flow
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

## 1. Inspect prompts without spending credits

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

Outputs are written to `./outputs/<job-id>/`. In mock mode, the try-on/video assets are JSON prompt artifacts so the complete plan can be reviewed before any Flow credit is used.

## 2. Sign in to Google Flow once

```bash
video-sales-flow login
```

This opens `https://flow.google/` in a persistent Chromium profile at `.browser-profile/`. Sign in directly with Google in that browser, confirm Flow opens, return to the terminal, and press Enter. No password or cookie export is written into this repository.

A custom profile location is supported:

```bash
VIDEO_SALES_PROFILE_DIR="$HOME/.local/share/video-sales-flow/chrome" \
  video-sales-flow login
```

## 3. Generate real assets through Google Flow

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
  --engine google-flow
```

`auto` rotates through `pose`, `catwalk`, `turn`, `mixed`, and `jump`. You can force/cycle motions instead:

```bash
video-sales-flow generate \
  --model model.jpg \
  --outfit shirt.jpg \
  --count 4 \
  --motion catwalk \
  --motion pose \
  --engine google-flow
```

## Telegram: send images, receive finished videos

Telegram mode uses long polling, so the Mac does **not** need a public HTTP port, webhook, Cloudflare Tunnel, or public domain.

Set the bot token only in the process environment:

```bash
export TELEGRAM_BOT_TOKEN='123456:replace-with-your-bot-token'
export VIDEO_SALES_ENGINE='google-flow'
export VIDEO_SALES_PROFILE_DIR="$HOME/.local/share/video-sales-flow/chrome"
```

Before starting the long-polling bot, send one message to the bot and read your chat ID once:

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

Real `google-flow` mode requires an allowlist so another Telegram user cannot consume your Flow credits:

```bash
export TELEGRAM_ALLOWED_CHAT_IDS='123456789'
```

Comma-separated chat IDs are supported for multiple authorized chats.

Start the bot:

```bash
video-sales-flow telegram --engine google-flow
```

The chat flow is:

1. Send the model image. The first image in the current session becomes the model.
2. Send one or more garment/outfit images.
3. Send `/make 3 premium` (or just `/make` for 3 energetic videos).
4. The bot creates a persisted job, clears only the pending input session, and runs generation in a single background worker.
5. Each completed video is uploaded back to the **same `chat_id`** and replies to the original `/make` message.

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

Telegram Bot API currently allows bots to download incoming files through `getFile` up to 20 MB and send video uploads through `sendVideo` up to 50 MB. Keep source photos and generated clips within those limits when using the hosted Bot API. The client rejects local video files larger than 50 MB before attempting an upload.

## Output layout

```text
outputs/<job-id>/
├── manifest.json
├── inputs/
│   ├── model.jpg
│   └── outfit-01-shirt.jpg
├── tryon/
│   └── tryon-01.*
└── videos/
    ├── video-01.*
    └── video-02.*
```

`manifest.json` is atomically updated after every generation step and includes status, options, prompts, produced assets, and the error if a job fails.

Check a previous job:

```bash
video-sales-flow status <job-id>
```

## API

Start the local API:

```bash
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

For real Flow generation via the API, set the engine before starting Uvicorn:

```bash
VIDEO_SALES_ENGINE=google-flow \
VIDEO_SALES_PROFILE_DIR="$HOME/.local/share/video-sales-flow/chrome" \
uvicorn video_sales_flow.api:app --host 127.0.0.1 --port 8099
```

Do not expose this local API directly to the Internet without authentication and request limits; a remote caller could consume your Flow credits.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VIDEO_SALES_ENGINE` | `mock` | `mock` or `google-flow` |
| `VIDEO_SALES_OUTPUT_ROOT` | `./outputs` | Job/output directory |
| `VIDEO_SALES_PROFILE_DIR` | `./.browser-profile` | Persistent Chromium profile |
| `VIDEO_SALES_FLOW_URL` | `https://flow.google/` | Flow URL |
| `VIDEO_SALES_MAX_VIDEOS` | `10` | Hard per-job video guard |
| `VIDEO_SALES_MAX_OUTFITS` | `10` | Hard per-job outfit/try-on guard |
| `VIDEO_SALES_FLOW_TIMEOUT_SECONDS` | `300` | Max wait for a generated downloadable asset |
| `VIDEO_SALES_HEADLESS` | `false` | Run generation browser headless after login |
| `TELEGRAM_BOT_TOKEN` | none | Telegram bot token; required by `telegram` command |
| `TELEGRAM_ALLOWED_CHAT_IDS` | none | Required for `google-flow`; optional comma-separated allowlist in mock mode |
| `VIDEO_SALES_FLOW_PROMPT_SELECTOR` | built-in | Override prompt textbox selector |
| `VIDEO_SALES_FLOW_UPLOAD_SELECTOR` | built-in | Override file-input selector |
| `VIDEO_SALES_FLOW_UPLOAD_TRIGGER_SELECTOR` | built-in | Override upload-button selector |
| `VIDEO_SALES_FLOW_GENERATE_SELECTOR` | built-in | Override generation button selector |
| `VIDEO_SALES_FLOW_DOWNLOAD_SELECTOR` | built-in | Override generated-asset download selector |
| `VIDEO_SALES_FLOW_DIALOG_SELECTOR` | built-in | Override dialog selector used by credit guard |

## When Google Flow changes its UI

A failed browser run attempts to save `debug-<asset>.png` in that stage's output directory. Inspect the screenshot with Chromium DevTools and override only the selector that changed, for example:

```bash
export VIDEO_SALES_FLOW_PROMPT_SELECTOR='[data-testid="agent-input"]'
export VIDEO_SALES_FLOW_GENERATE_SELECTOR='button[data-testid="generate"]'
```

The prompt planner, job manifest, mock mode, API, and Telegram session/delivery layer remain independent of those selectors.

## Tests

Tests never log in to Google Flow, never contact Telegram, and never consume credits:

```bash
python -m pytest -q
python -m compileall -q src
```

Telegram tests use fake transport/service implementations and verify that the first image becomes the model, later images become outfits, `/make` creates a job, generated video assets are returned to the originating chat, and real Flow Telegram mode cannot start without an explicit chat allowlist.

## Current limitation

The browser adapter is intentionally based on public UI interaction rather than an undocumented/private Flow API. Google may change the Flow UI at any time, so a live authenticated smoke test on your Mac is still required after selector changes. The tool fails with diagnostics rather than falling back to a paid API.
