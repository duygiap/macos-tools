from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .config import Settings
from .engines import build_engine
from .engines.google_flow import GoogleFlowEngine
from .models import JobOptions, JobStatus, Motion, Tone
from .service import JobService


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
    telegram.add_argument(
        "--poll-timeout",
        type=int,
        default=25,
        help="Telegram getUpdates long-poll timeout in seconds (1-50).",
    )

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
    if getattr(args, "max_videos", None) is not None:
        updates["max_videos"] = args.max_videos
    if getattr(args, "max_outfits", None) is not None:
        updates["max_outfits"] = args.max_outfits
    if getattr(args, "timeout_seconds", None) is not None:
        updates["timeout_seconds"] = args.timeout_seconds
    if getattr(args, "engine", None):
        updates["engine"] = args.engine
    return replace(settings, **updates) if updates else settings


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = _apply_common_overrides(Settings.from_env(), args)
        if args.command == "login":
            GoogleFlowEngine(settings=replace(settings, engine="google-flow", headless=False)).login()
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
        engine = build_engine(engine_name, replace(settings, engine=engine_name))
        service = JobService(
            output_root=settings.output_root,
            engine=engine,
            max_videos=settings.max_videos,
            max_outfits=settings.max_outfits,
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
