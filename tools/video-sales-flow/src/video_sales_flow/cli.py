from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .config import Settings, load_environment_file
from .engines import build_engine
from .engines.google_flow import GoogleFlowEngine
from .models import JobOptions, JobStatus, Motion, Tone
from .service import JobService
from .tryon import build_tryon_pipeline


def _add_tryon_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tryon-engine",
        choices=["legacy", "mock", "gemini-web", "ai-studio-api"],
        help=(
            "Try-on image engine. ai-studio-api uses the official Google GenAI SDK; "
            "gemini-web is kept for backwards compatibility."
        ),
    )
    parser.add_argument(
        "--tryon-review-mode",
        choices=["local", "gemini-web", "ai-studio-api"],
        help=(
            "Review candidates locally, through the legacy AI Studio web flow, "
            "or through the official AI Studio API."
        ),
    )
    parser.add_argument("--gemini-url", help="Google AI Studio URL override for gemini-web mode.")
    parser.add_argument("--tryon-max-attempts", type=int, help="Maximum try-on regeneration attempts (1-5).")
    parser.add_argument("--tryon-min-width", type=int, help="Minimum approved try-on image width.")
    parser.add_argument("--tryon-min-height", type=int, help="Minimum approved try-on image height.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-sales-flow",
        description="Create apparel-sales video batches from a model image and garment references.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser(
        "login",
        help="Open Google Flow in a persistent Chromium profile for interactive sign-in.",
    )
    login.add_argument("--profile-dir")
    login.add_argument("--flow-url")
    login.add_argument("--browser-executable", help="Custom browser executable path.")
    login.add_argument(
        "--use-playwright",
        action="store_true",
        help="Use automated Playwright context instead of genuine native browser window.",
    )

    gemini_login = subparsers.add_parser(
        "gemini-login",
        help="Open Google AI Studio in the shared persistent Chromium profile for legacy web setup.",
    )
    gemini_login.add_argument("--profile-dir")
    gemini_login.add_argument("--gemini-url")
    gemini_login.add_argument("--browser-executable", help="Custom browser executable path.")

    generate = subparsers.add_parser("generate", help="Create a video-sales job.")
    generate.add_argument("--model", required=True, help="Model image path.")
    generate.add_argument(
        "--outfit",
        dest="outfits",
        action="append",
        required=True,
        help="Garment reference image. Repeat for multiple outfits.",
    )
    generate.add_argument("--count", type=int, default=3, help="Number of videos to create.")
    generate.add_argument(
        "--motion",
        dest="motions",
        action="append",
        choices=[motion.value for motion in Motion],
        help="Motion direction. Repeat to cycle explicit motions; omit for auto.",
    )
    generate.add_argument(
        "--tone", choices=[tone.value for tone in Tone], default=Tone.ENERGETIC.value
    )
    generate.add_argument("--brand")
    generate.add_argument("--product")
    generate.add_argument("--audience")
    generate.add_argument("--cta", default="Mua ngay")
    generate.add_argument("--aspect-ratio", choices=["9:16", "16:9"], default="9:16")
    generate.add_argument("--duration", type=int, default=8)
    generate.add_argument("--background", default="clean modern fashion studio")
    generate.add_argument("--engine", choices=["mock", "google-flow"])
    generate.add_argument("--output-root")
    generate.add_argument("--profile-dir")
    generate.add_argument("--max-videos", type=int)
    generate.add_argument("--max-outfits", type=int)
    generate.add_argument("--flow-url")
    generate.add_argument("--timeout-seconds", type=int)
    generate.add_argument("--browser-executable", help="Custom browser executable path.")
    _add_tryon_arguments(generate)

    telegram = subparsers.add_parser(
        "telegram",
        help="Run the Telegram long-polling bot for image-in/video-out jobs.",
    )
    telegram.add_argument("--engine", choices=["mock", "google-flow"])
    telegram.add_argument("--output-root")
    telegram.add_argument("--profile-dir")
    telegram.add_argument("--max-videos", type=int)
    telegram.add_argument("--max-outfits", type=int)
    telegram.add_argument("--flow-url")
    telegram.add_argument("--timeout-seconds", type=int)
    telegram.add_argument("--browser-executable", help="Custom browser executable path.")
    telegram.add_argument(
        "--poll-timeout",
        type=int,
        default=25,
        help="Telegram getUpdates long-poll timeout in seconds (1-50).",
    )
    _add_tryon_arguments(telegram)

    status = subparsers.add_parser("status", help="Print a persisted job manifest.")
    status.add_argument("job_id")
    status.add_argument("--output-root")

    return parser


def _apply_common_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    updates = {}
    if getattr(args, "output_root", None):
        updates["output_root"] = Path(args.output_root).expanduser().resolve()
    if getattr(args, "profile_dir", None):
        updates["profile_dir"] = Path(args.profile_dir).expanduser().resolve()
    if getattr(args, "flow_url", None):
        updates["flow_url"] = args.flow_url
    if getattr(args, "gemini_url", None):
        updates["gemini_url"] = args.gemini_url
    if getattr(args, "max_videos", None) is not None:
        updates["max_videos"] = args.max_videos
    if getattr(args, "max_outfits", None) is not None:
        updates["max_outfits"] = args.max_outfits
    if getattr(args, "timeout_seconds", None) is not None:
        updates["timeout_seconds"] = args.timeout_seconds
    if getattr(args, "engine", None):
        updates["engine"] = args.engine
    if getattr(args, "tryon_engine", None):
        updates["tryon_engine"] = args.tryon_engine
    if getattr(args, "tryon_review_mode", None):
        updates["tryon_review_mode"] = args.tryon_review_mode
    if getattr(args, "tryon_max_attempts", None) is not None:
        if not 1 <= args.tryon_max_attempts <= 5:
            raise ValueError("--tryon-max-attempts must be between 1 and 5")
        updates["tryon_max_attempts"] = args.tryon_max_attempts
    if getattr(args, "tryon_min_width", None) is not None:
        if args.tryon_min_width < 1:
            raise ValueError("--tryon-min-width must be at least 1")
        updates["tryon_min_width"] = args.tryon_min_width
    if getattr(args, "tryon_min_height", None) is not None:
        if args.tryon_min_height < 1:
            raise ValueError("--tryon-min-height must be at least 1")
        updates["tryon_min_height"] = args.tryon_min_height
    if getattr(args, "browser_executable", None):
        updates["browser_executable"] = Path(args.browser_executable).expanduser().resolve()
    return replace(settings, **updates) if updates else settings


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = build_parser()
    try:
        load_environment_file()
        args = parser.parse_args(argv)
        settings = _apply_common_overrides(Settings.from_env(), args)
        if args.command == "login":
            GoogleFlowEngine(
                settings=replace(settings, engine="google-flow", headless=False)
            ).login(use_native=not getattr(args, "use_playwright", False))
            return 0

        if args.command == "gemini-login":
            from .tryon.gemini_web import GeminiWebClient

            GeminiWebClient(settings=replace(settings, headless=False)).login()
            return 0

        if args.command == "status":
            service = JobService(
                output_root=settings.output_root,
                engine=build_engine("mock", settings),
                max_videos=settings.max_videos,
                max_outfits=settings.max_outfits,
            )
            print(service.load_manifest(args.job_id).model_dump_json(indent=2))
            return 0

        if args.command == "telegram":
            if not 1 <= args.poll_timeout <= 50:
                raise ValueError("--poll-timeout must be between 1 and 50 seconds")
            from .telegram_bot import build_telegram_bot

            bot = build_telegram_bot(settings, poll_timeout=args.poll_timeout)
            try:
                bot.run_forever()
            finally:
                bot.close()
            return 0

        motions = [Motion(value) for value in args.motions] if args.motions else [Motion.AUTO]
        options = JobOptions(
            video_count=args.count,
            motions=motions,
            tone=Tone(args.tone),
            brand_name=args.brand,
            product_name=args.product,
            target_audience=args.audience,
            cta_text=args.cta,
            aspect_ratio=args.aspect_ratio,
            duration_seconds=args.duration,
            background_style=args.background,
        )
        engine_name = args.engine or settings.engine
        runtime_settings = replace(settings, engine=engine_name)
        engine = build_engine(engine_name, runtime_settings)
        service = JobService(
            output_root=runtime_settings.output_root,
            engine=engine,
            max_videos=runtime_settings.max_videos,
            max_outfits=runtime_settings.max_outfits,
            tryon_pipeline=build_tryon_pipeline(runtime_settings),
        )
        manifest = service.run(
            model_image=Path(args.model),
            outfit_images=[Path(path) for path in args.outfits],
            options=options,
        )
        print(manifest.model_dump_json(indent=2))
        return 0 if manifest.status is JobStatus.COMPLETED else 1
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
