from __future__ import annotations

import os
import platform
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


def get_browser_candidates(
    system: str | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    sys_name = (system or platform.system()).lower()
    source = os.environ if env is None else env
    candidates: list[Path] = []

    if sys_name == "windows" or sys_name.startswith("win"):
        local_app_data = source.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        program_files = source.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = source.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")

        candidates.extend(
            [
                Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                Path(program_files) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ]
        )
    elif sys_name in {"darwin", "ios", "macos"}:
        home = Path.home()
        candidates.extend(
            [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"),
                Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
                home / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome",
                home / "Applications" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ]
        )
    elif sys_name.startswith("linux"):
        candidates.extend(
            [
                Path("/usr/bin/google-chrome"),
                Path("/usr/bin/google-chrome-stable"),
                Path("/usr/bin/chromium"),
                Path("/usr/bin/chromium-browser"),
                Path("/snap/bin/chromium"),
            ]
        )

    return candidates


def detect_browser_executable(
    custom_path: str | Path | None = None,
    system: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    if custom_path:
        return Path(custom_path).expanduser().resolve()

    for candidate in get_browser_candidates(system=system, env=env):
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


@dataclass(frozen=True)
class Settings:
    output_root: Path
    profile_dir: Path
    flow_url: str = "https://flow.google/"
    engine: str = "mock"
    max_videos: int = 10
    max_outfits: int = 10
    headless: bool = True
    timeout_seconds: int = 300
    browser_executable: Path | None = None
    tryon_engine: str = "legacy"
    gemini_url: str = "https://gemini.google.com/app"
    tryon_max_attempts: int = 3
    tryon_min_width: int = 512
    tryon_min_height: int = 512
    tryon_review_mode: str = "local"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        output_root = Path(source.get("VIDEO_SALES_OUTPUT_ROOT", "./outputs")).expanduser().resolve()
        profile_dir_raw = source.get("VIDEO_SALES_PROFILE_DIR")
        if profile_dir_raw:
            profile_dir = Path(profile_dir_raw).expanduser().resolve()
        elif (Path.cwd() / ".browser-profile").exists():
            profile_dir = (Path.cwd() / ".browser-profile").resolve()
        elif (Path.cwd().parent.parent / ".browser-profile").exists():
            profile_dir = (Path.cwd().parent.parent / ".browser-profile").resolve()
        else:
            profile_dir = Path("./.browser-profile").expanduser().resolve()
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

        tryon_engine = source.get("VIDEO_SALES_TRYON_ENGINE", "legacy").strip().lower()
        if tryon_engine not in {"legacy", "mock", "gemini-web"}:
            raise ValueError(
                "VIDEO_SALES_TRYON_ENGINE must be 'legacy', 'mock', or 'gemini-web'"
            )
        tryon_max_attempts = int(source.get("VIDEO_SALES_TRYON_MAX_ATTEMPTS", "3"))
        if tryon_max_attempts < 1 or tryon_max_attempts > 5:
            raise ValueError("VIDEO_SALES_TRYON_MAX_ATTEMPTS must be between 1 and 5")
        tryon_min_width = int(source.get("VIDEO_SALES_TRYON_MIN_WIDTH", "512"))
        tryon_min_height = int(source.get("VIDEO_SALES_TRYON_MIN_HEIGHT", "512"))
        if tryon_min_width < 1:
            raise ValueError("VIDEO_SALES_TRYON_MIN_WIDTH must be at least 1")
        if tryon_min_height < 1:
            raise ValueError("VIDEO_SALES_TRYON_MIN_HEIGHT must be at least 1")
        tryon_review_mode = source.get("VIDEO_SALES_TRYON_REVIEW_MODE", "local").strip().lower()
        if tryon_review_mode not in {"local", "gemini-web"}:
            raise ValueError("VIDEO_SALES_TRYON_REVIEW_MODE must be 'local' or 'gemini-web'")

        browser_exec_env = source.get("VIDEO_SALES_BROWSER_EXECUTABLE") or source.get(
            "VIDEO_SALES_CHROME_PATH"
        )
        browser_executable = (
            Path(browser_exec_env).expanduser().resolve()
            if browser_exec_env
            else detect_browser_executable(env=source)
        )
        return cls(
            output_root=output_root,
            profile_dir=profile_dir,
            flow_url=source.get("VIDEO_SALES_FLOW_URL", "https://flow.google/").strip(),
            engine=engine,
            max_videos=max_videos,
            max_outfits=max_outfits,
            headless=_parse_bool(source.get("VIDEO_SALES_HEADLESS", "true"), True),
            timeout_seconds=timeout_seconds,
            browser_executable=browser_executable,
            tryon_engine=tryon_engine,
            gemini_url=source.get("VIDEO_SALES_GEMINI_URL", "https://gemini.google.com/app").strip(),
            tryon_max_attempts=tryon_max_attempts,
            tryon_min_width=tryon_min_width,
            tryon_min_height=tryon_min_height,
            tryon_review_mode=tryon_review_mode,
        )
