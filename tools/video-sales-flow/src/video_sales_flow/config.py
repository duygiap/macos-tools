from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def _parse_bool(value: str, default: bool) -> bool:
    if value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


@dataclass(frozen=True)
class Settings:
    output_root: Path
    profile_dir: Path
    flow_url: str = "https://flow.google/"
    engine: str = "mock"
    max_videos: int = 10
    max_outfits: int = 10
    headless: bool = False
    timeout_seconds: int = 300

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        output_root = Path(source.get("VIDEO_SALES_OUTPUT_ROOT", "./outputs")).expanduser().resolve()
        profile_dir = Path(
            source.get("VIDEO_SALES_PROFILE_DIR", "./.browser-profile")
        ).expanduser().resolve()
        max_videos = int(source.get("VIDEO_SALES_MAX_VIDEOS", "10"))
        if max_videos < 1:
            raise ValueError("VIDEO_SALES_MAX_VIDEOS must be at least 1")
        max_outfits = int(source.get("VIDEO_SALES_MAX_OUTFITS", "10"))
        if max_outfits < 1:
            raise ValueError("VIDEO_SALES_MAX_OUTFITS must be at least 1")
        timeout_seconds = int(source.get("VIDEO_SALES_FLOW_TIMEOUT_SECONDS", "300"))
        if timeout_seconds < 30:
            raise ValueError("VIDEO_SALES_FLOW_TIMEOUT_SECONDS must be at least 30")
        engine = source.get("VIDEO_SALES_ENGINE", "mock").strip().lower()
        if engine not in {"mock", "google-flow"}:
            raise ValueError("VIDEO_SALES_ENGINE must be 'mock' or 'google-flow'")
        return cls(
            output_root=output_root,
            profile_dir=profile_dir,
            flow_url=source.get("VIDEO_SALES_FLOW_URL", "https://flow.google/").strip(),
            engine=engine,
            max_videos=max_videos,
            max_outfits=max_outfits,
            headless=_parse_bool(source.get("VIDEO_SALES_HEADLESS", "false"), False),
            timeout_seconds=timeout_seconds,
        )
