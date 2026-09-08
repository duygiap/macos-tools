from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .base import GeneratedAsset, GenerationEngine
from ..config import Settings
from ..models import PlannedPrompt


_PURCHASE_PATTERNS = (
    "buy more credits",
    "buy credits",
    "purchase ai credits",
    "purchase credits",
    "top up credits",
    "top-up credits",
    "upgrade to continue",
    "mua thêm tín dụng",
    "mua tín dụng",
    "nâng cấp để tiếp tục",
)


class GoogleFlowError(RuntimeError):
    pass


class FlowLoginRequired(GoogleFlowError):
    pass


class CreditPurchaseBlocked(GoogleFlowError):
    pass


@dataclass(frozen=True)
class FlowSelectors:
    prompt: str = "textarea, [contenteditable='true'][role='textbox']"
    upload: str = "input[type='file']"
    upload_trigger: str = (
        "button:has-text('Upload'), button:has-text('Add'), "
        "button[aria-label*='Upload'], button[aria-label*='Add']"
    )
    generate: str = (
        "button:has-text('Generate'), button:has-text('Create'), "
        "button[aria-label*='Generate'], button[aria-label*='Create']"
    )
    download: str = (
        "button:has-text('Download'), button[aria-label*='Download'], a[download]"
    )
    dialog: str = "[role='dialog']:visible"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "FlowSelectors":
        source = os.environ if env is None else env
        defaults = cls()
        return cls(
            prompt=source.get("VIDEO_SALES_FLOW_PROMPT_SELECTOR", defaults.prompt),
            upload=source.get("VIDEO_SALES_FLOW_UPLOAD_SELECTOR", defaults.upload),
            upload_trigger=source.get(
                "VIDEO_SALES_FLOW_UPLOAD_TRIGGER_SELECTOR", defaults.upload_trigger
            ),
            generate=source.get("VIDEO_SALES_FLOW_GENERATE_SELECTOR", defaults.generate),
            download=source.get("VIDEO_SALES_FLOW_DOWNLOAD_SELECTOR", defaults.download),
            dialog=source.get("VIDEO_SALES_FLOW_DIALOG_SELECTOR", defaults.dialog),
        )


def contains_purchase_text(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    return any(pattern in normalized for pattern in _PURCHASE_PATTERNS)


def new_download_index(previous_count: int, current_count: int) -> int | None:
    if current_count <= previous_count:
        return None
    return current_count - 1


def safe_asset_filename(stem: str, suffix: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "asset"
    normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    normalized_suffix = re.sub(r"[^A-Za-z0-9.]", "", normalized_suffix)
    if not normalized_suffix.startswith(".") or normalized_suffix == ".":
        normalized_suffix = ".bin"
    return f"{cleaned}{normalized_suffix.lower()}"


class GoogleFlowEngine(GenerationEngine):
    """Drive Google Flow through its public web UI using the user's browser session.

    This adapter intentionally performs a single generation click per requested asset and
    never interacts with credit purchase/upgrade UI. The web UI is third-party and may
    change; selectors are therefore centralized and environment-overridable.
    """

    name = "google-flow"

    def __init__(
        self,
        settings: Settings | None = None,
        selectors: FlowSelectors | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.selectors = selectors or FlowSelectors.from_env()

    def login(self) -> None:
        sync_playwright = self._sync_playwright()
        self.settings.profile_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.settings.profile_dir),
                headless=False,
                accept_downloads=True,
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(self.settings.flow_url, wait_until="domcontentloaded")
            print(
                "Google Flow opened in the persistent browser profile. "
                "Sign in directly with Google, confirm Flow opens, then return here."
            )
            input("Press Enter to save the browser session and close Chromium... ")
            context.close()

    def generate_image(
        self,
        prompt: PlannedPrompt,
        output_dir: Path,
        stem: str,
    ) -> GeneratedAsset:
        path = self._generate(prompt, output_dir, stem, expected_suffix=".png")
        return GeneratedAsset(
            asset_type="edited_image",
            path=str(path),
            prompt_title=prompt.title,
            metadata={"engine": self.name},
        )

    def generate_video(
        self,
        prompt: PlannedPrompt,
        output_dir: Path,
        stem: str,
    ) -> GeneratedAsset:
        path = self._generate(prompt, output_dir, stem, expected_suffix=".mp4")
        return GeneratedAsset(
            asset_type="video",
            path=str(path),
            prompt_title=prompt.title,
            metadata={"engine": self.name},
        )

    def _generate(
        self,
        prompt: PlannedPrompt,
        output_dir: Path,
        stem: str,
        expected_suffix: str,
    ) -> Path:
        sync_playwright = self._sync_playwright()
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        self.settings.profile_dir.mkdir(parents=True, exist_ok=True)
        debug_path = output_dir / safe_asset_filename(f"debug-{stem}", ".png")

        context = None
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.settings.profile_dir),
                    headless=self.settings.headless,
                    accept_downloads=True,
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(
                    self.settings.flow_url,
                    wait_until="domcontentloaded",
                    timeout=self.settings.timeout_seconds * 1000,
                )
                self._ensure_logged_in(page)
                self._assert_no_purchase_dialog(page)
                self._upload_references(page, prompt.reference_paths)
                self._fill_prompt(page, prompt.prompt)
                self._assert_no_purchase_dialog(page)
                baseline_download_count = page.locator(self.selectors.download).count()
                self._click_generate_once(page)
                download_locator = self._wait_for_download_action(page, baseline_download_count)
                self._assert_no_purchase_dialog(page)

                with page.expect_download(timeout=self.settings.timeout_seconds * 1000) as info:
                    download_locator.click()
                download = info.value
                suffix = Path(download.suggested_filename or "").suffix or expected_suffix
                if suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov"}:
                    suffix = expected_suffix
                destination = output_dir / safe_asset_filename(stem, suffix)
                download.save_as(str(destination))
                context.close()
                context = None
                return destination.resolve()
        except Exception as exc:
            if context is not None:
                try:
                    page = context.pages[0] if context.pages else None
                    if page is not None:
                        page.screenshot(path=str(debug_path), full_page=True)
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
            if isinstance(exc, GoogleFlowError):
                raise
            raise GoogleFlowError(
                f"Google Flow automation failed for {prompt.title}: {exc}. "
                f"If the UI changed, inspect {debug_path} and override VIDEO_SALES_FLOW_*_SELECTOR."
            ) from exc

    def _ensure_logged_in(self, page) -> None:
        current_url = page.url.casefold()
        if "accounts.google.com" in current_url or "/signin" in current_url:
            raise FlowLoginRequired(
                "Google Flow session is not authenticated; run 'video-sales-flow login' first"
            )

    def _assert_no_purchase_dialog(self, page) -> None:
        dialogs = page.locator(self.selectors.dialog)
        for index in range(dialogs.count()):
            dialog = dialogs.nth(index)
            try:
                if dialog.is_visible() and contains_purchase_text(dialog.inner_text()):
                    raise CreditPurchaseBlocked(
                        "Google Flow requested a credit purchase or plan upgrade; generation aborted"
                    )
            except CreditPurchaseBlocked:
                raise
            except Exception:
                continue

    def _upload_references(self, page, paths: list[str]) -> None:
        resolved = [str(Path(path).expanduser().resolve()) for path in paths]
        for path in resolved:
            if not Path(path).is_file():
                raise GoogleFlowError(f"reference file does not exist: {path}")

        upload_inputs = page.locator(self.selectors.upload)
        if upload_inputs.count() > 0:
            upload_inputs.last.set_input_files(resolved)
            return

        trigger = self._first_visible(page.locator(self.selectors.upload_trigger))
        if trigger is None:
            raise GoogleFlowError(
                "could not find a Flow upload input; set VIDEO_SALES_FLOW_UPLOAD_SELECTOR "
                "or VIDEO_SALES_FLOW_UPLOAD_TRIGGER_SELECTOR"
            )
        with page.expect_file_chooser(timeout=15_000) as chooser_info:
            trigger.click()
        chooser_info.value.set_files(resolved)

    def _fill_prompt(self, page, text: str) -> None:
        prompt_box = self._first_visible(page.locator(self.selectors.prompt))
        if prompt_box is None:
            raise GoogleFlowError(
                "could not find the Flow prompt box; set VIDEO_SALES_FLOW_PROMPT_SELECTOR"
            )
        prompt_box.fill(text)

    def _click_generate_once(self, page) -> None:
        button = self._first_visible(page.locator(self.selectors.generate))
        if button is None:
            raise GoogleFlowError(
                "could not find the Flow generate button; set VIDEO_SALES_FLOW_GENERATE_SELECTOR"
            )
        label = ""
        try:
            label = " ".join(
                filter(
                    None,
                    [
                        button.inner_text(),
                        button.get_attribute("aria-label") or "",
                        button.get_attribute("title") or "",
                    ],
                )
            )
        except Exception:
            pass
        if contains_purchase_text(label):
            raise CreditPurchaseBlocked(
                "generation control appears to be a purchase/upgrade action; click blocked"
            )
        button.click()

    def _wait_for_download_action(self, page, baseline_count: int):
        deadline = time.monotonic() + self.settings.timeout_seconds
        while time.monotonic() < deadline:
            self._assert_no_purchase_dialog(page)
            downloads = page.locator(self.selectors.download)
            index = new_download_index(baseline_count, downloads.count())
            if index is not None:
                candidate = downloads.nth(index)
                try:
                    if candidate.is_visible():
                        return candidate
                except Exception:
                    pass
            time.sleep(2)
        raise GoogleFlowError(
            f"timed out after {self.settings.timeout_seconds}s waiting for a generated asset download"
        )

    @staticmethod
    def _first_visible(locator, prefer_last: bool = False):
        count = locator.count()
        indexes = range(count - 1, -1, -1) if prefer_last else range(count)
        for index in indexes:
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue
        return None

    @staticmethod
    def _sync_playwright():
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise GoogleFlowError(
                "Playwright is not installed; install the package and run "
                "'python -m playwright install chromium'"
            ) from exc
        return sync_playwright
