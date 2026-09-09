import base64
import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .base import GeneratedAsset, GenerationEngine
from ..config import Settings, detect_browser_executable
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
    prompt: str = "textarea, [contenteditable='true'], .ProseMirror"
    upload: str = "input[type='file']"
    upload_trigger: str = (
        "button[aria-label*='Thêm thành phần'], button[aria-label*='Add element'], "
        "button:has-text('Upload'), button:has-text('Add'), "
        "button[aria-label*='Upload'], button[aria-label*='Add'], "
        "button:has-text('Tải nội dung')"
    )
    generate: str = (
        "button[aria-label*='Bắt đầu tạo'], button[aria-label*='Generate'], button[aria-label*='Create'], "
        "button:has-text('Generate'), button:has-text('Create'), button:has-text('arrow_forward')"
    )
    download: str = (
        "button:has-text('Download'), button[aria-label*='Download'], a[download], "
        "button[aria-label*='Tải xuống'], button:has-text('Tải xuống')"
    )
    dialog: str = "[role='dialog']:visible, [aria-modal='true']:visible"

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

    def _get_launch_options(self, headless: bool) -> dict[str, Any]:
        options: dict[str, Any] = {
            "user_data_dir": str(self.settings.profile_dir),
            "headless": headless,
            "accept_downloads": True,
            "ignore_default_args": ["--enable-automation"],
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
            ],
        }
        executable = self.settings.browser_executable or detect_browser_executable()
        if executable:
            options["executable_path"] = str(executable)
        return options

    def login(self, use_native: bool = True) -> None:
        self.settings.profile_dir.mkdir(parents=True, exist_ok=True)
        executable = self.settings.browser_executable or detect_browser_executable()

        if use_native and executable and executable.exists():
            print(f"Opening native browser for Google sign-in: {executable}")
            print(f"Profile directory: {self.settings.profile_dir}")
            print(
                "\nGoogle Flow is opening in a genuine browser window (no automation flags).\n"
                "1. Sign in with your Google account directly in the browser.\n"
                "2. Confirm Google Flow loads and shows your account.\n"
                "3. Close the browser window, then return here and press Enter.\n"
            )
            cmd = [
                str(executable),
                f"--user-data-dir={self.settings.profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                self.settings.flow_url,
            ]
            proc = subprocess.Popen(cmd)
            try:
                input("Press Enter once you have signed in and closed the browser window... ")
            finally:
                if proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        try:
                            proc.kill()
                            proc.wait(timeout=2)
                        except Exception:
                            pass
            return

        sync_playwright = self._sync_playwright()
        options = self._get_launch_options(headless=False)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(**options)
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
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
        path = self._generate(prompt, output_dir, stem, expected_suffix=".png", mode="image")
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
        path = self._generate(prompt, output_dir, stem, expected_suffix=".mp4", mode="video")
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
        mode: str = "video",
    ) -> Path:
        sync_playwright = self._sync_playwright()
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        self.settings.profile_dir.mkdir(parents=True, exist_ok=True)
        debug_path = output_dir / safe_asset_filename(f"debug-{stem}", ".png")

        context = None
        try:
            options = self._get_launch_options(headless=self.settings.headless)
            if self.settings.headless:
                options["headless"] = False
                args = list(options.get("args", []))
                if "--headless=new" not in args:
                    args.append("--headless=new")
                options["args"] = args
            with sync_playwright() as playwright:

                context = playwright.chromium.launch_persistent_context(**options)
                context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(
                    self.settings.flow_url,
                    wait_until="domcontentloaded",
                    timeout=self.settings.timeout_seconds * 1000,
                )
                self._ensure_logged_in(page)
                self._ensure_in_project(page)
                self._assert_no_purchase_dialog(page)
                self._set_generation_mode(page, mode)
                self._upload_references(page, prompt.reference_paths)
                self._fill_prompt(page, prompt.prompt)
                self._assert_no_purchase_dialog(page)

                # Wait for uploads and DOM to fully settle before measuring baseline
                page.wait_for_timeout(6000)

                finished_selector = ".container:has(img.image, img.thumbnail)"
                baseline_finished_count = page.locator(finished_selector).count()


                self._click_generate_once(page)
                target_card_btn = self._wait_for_card_generation(
                    page, baseline_finished_count, finished_selector
                )
                self._assert_no_purchase_dialog(page)

                destination = self._download_card_asset(
                    page, target_card_btn, output_dir, stem, expected_suffix
                )

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

    def _ensure_in_project(self, page) -> None:
        try:
            page.wait_for_url(lambda u: "flow.google.com" in u or "/project/" in u, timeout=15_000)
        except Exception:
            pass

        self._dismiss_announcements(page)
        if "/project/" not in page.url:
            create_selector = (
                "button:has-text('Start Creating'), button:has-text('Dự án mới'), "
                "button:has-text('New project'), button[aria-label*='Dự án mới'], "
                "[role='button']:has-text('Dự án mới')"
            )
            try:
                page.wait_for_selector(create_selector, timeout=15_000)
            except Exception:
                pass

            create_btn = self._first_visible(page.locator(create_selector))
            if create_btn is not None:
                create_btn.click()
                try:
                    page.wait_for_url("**/project/**", timeout=20_000)
                except Exception:
                    page.wait_for_timeout(4_000)

        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        self._dismiss_announcements(page)
        try:
            page.wait_for_selector(self.selectors.prompt, timeout=15_000)
        except Exception:
            pass

    def _dismiss_announcements(self, page) -> None:
        try:
            dismiss_btn = self._first_visible(
                page.locator(
                    "button:has-text('Bắt đầu'), button:has-text('Get started'), "
                    "button:has-text('Got it'), button:has-text('Đã hiểu')"
                )
            )
            if dismiss_btn is not None and dismiss_btn.is_visible():
                dismiss_btn.click()
                page.wait_for_timeout(1_000)
        except Exception:
            pass

    def _set_generation_mode(self, page, mode: str) -> None:
        try:
            settings_btn = page.locator(
                "button.settings-trigger-button, button[aria-label*='cài đặt'], button[aria-label*='settings']"
            ).first
            if settings_btn.count() == 0 or not settings_btn.is_visible():
                return
            btn_text = settings_btn.inner_text().strip().lower()

            if mode == "image":
                if any(k in btn_text for k in ("hình ảnh", "image", "nano banana")):
                    return
                settings_btn.click()
                page.wait_for_timeout(800)
                img_opt = self._first_visible(
                    page.locator(
                        ".cdk-overlay-pane button:has-text('Hình ảnh'), "
                        ".cdk-overlay-pane [role='menuitem']:has-text('Hình ảnh'), "
                        ".cdk-overlay-pane button:has-text('Image')"
                    )
                )
                if img_opt is not None:
                    img_opt.click()
                    page.wait_for_timeout(800)
            elif mode == "video":
                if "video" in btn_text or "veo" in btn_text:
                    return
                settings_btn.click()
                page.wait_for_timeout(800)
                video_opt = self._first_visible(
                    page.locator(
                        ".cdk-overlay-pane button:has-text('Video'), "
                        ".cdk-overlay-pane [role='menuitem']:has-text('Video')"
                    )
                )
                if video_opt is not None:
                    video_opt.click()
                    page.wait_for_timeout(800)

            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
            except Exception:
                pass
        except Exception:
            pass

    def _upload_references(self, page, paths: list[str]) -> None:
        if not paths:
            return
        resolved = [str(Path(path).expanduser().resolve()) for path in paths]
        for path in resolved:
            if not Path(path).is_file():
                raise GoogleFlowError(f"reference file does not exist: {path}")

        upload_inputs = page.locator(self.selectors.upload)
        if upload_inputs.count() > 0 and upload_inputs.last.is_visible():
            upload_inputs.last.set_input_files(resolved)
            self._handle_upload_confirmation(page)
            return

        trigger = self._first_visible(page.locator(self.selectors.upload_trigger))
        if trigger is None:
            raise GoogleFlowError(
                "could not find a Flow upload input; set VIDEO_SALES_FLOW_UPLOAD_SELECTOR "
                "or VIDEO_SALES_FLOW_UPLOAD_TRIGGER_SELECTOR"
            )

        trigger.click()
        page.wait_for_timeout(1_500)

        upload_action = self._first_visible(
            page.locator(
                "button:has-text('Tải nội dung'), div:has-text('Tải nội dung'), "
                "[role='button']:has-text('Tải nội dung'), button:has-text('Upload'), "
                "input[type='file']"
            )
        )
        if upload_action is not None and upload_action.evaluate("e => e.tagName") == "INPUT":
            upload_action.set_input_files(resolved)
        elif upload_action is not None:
            with page.expect_file_chooser(timeout=15_000) as chooser_info:
                upload_action.click()
            chooser_info.value.set_files(resolved)
        else:
            with page.expect_file_chooser(timeout=15_000) as chooser_info:
                trigger.click()
            chooser_info.value.set_files(resolved)

        self._handle_upload_confirmation(page)
        page.wait_for_timeout(8_000)

    def _handle_upload_confirmation(self, page) -> None:

        page.wait_for_timeout(2_000)
        try:
            agree_btn = self._first_visible(
                page.locator(
                    "button:has-text('Tôi đồng ý'), button:has-text('I agree'), button:has-text('Agree')"
                )
            )
            if agree_btn is not None and agree_btn.is_visible():
                agree_btn.click()
                page.wait_for_timeout(2_000)
        except Exception:
            pass

        try:
            insert_btn = self._first_visible(
                page.locator(
                    "button:has-text('Thêm vào câu lệnh'), button:has-text('Add to prompt'), "
                    "button:has-text('Chèn')"
                )
            )
            if insert_btn is not None and insert_btn.is_visible():
                insert_btn.click()
                page.wait_for_timeout(1_500)
        except Exception:
            pass

        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass

    def _fill_prompt(self, page, text: str) -> None:
        prompt_box = self._first_visible(page.locator(self.selectors.prompt))
        if prompt_box is None:
            raise GoogleFlowError(
                "could not find the Flow prompt box; set VIDEO_SALES_FLOW_PROMPT_SELECTOR"
            )
        try:
            prompt_box.click()
            ctrl_key = "Meta+A" if platform.system().lower() in {"darwin", "ios", "macos"} else "Control+A"
            page.keyboard.press(ctrl_key)
            page.keyboard.press("Backspace")
            page.keyboard.insert_text(text)
        except Exception:
            prompt_box.click()
            page.keyboard.insert_text(text)

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

    def _wait_for_card_generation(self, page, baseline_count: int, finished_selector: str):
        deadline = time.monotonic() + self.settings.timeout_seconds
        card_more_selector = (
            "button[aria-label='Tuỳ chọn khác'], button[aria-label*='Tuỳ chọn khác'], "
            "button[aria-label*='More options'], button[aria-label='More options']"
        )
        progress_selector = "*:has-text('%'):visible, mat-progress-spinner:visible, [role='progressbar']:visible"
        while time.monotonic() < deadline:
            self._assert_no_purchase_dialog(page)
            curr = page.locator(finished_selector).count()
            has_progress = page.locator(progress_selector).count() > 0
            if curr > baseline_count and not has_progress:
                # Generation complete! Wait a moment for canvas DOM stability
                page.wait_for_timeout(2000)
                return page.locator(card_more_selector).first
            time.sleep(2)
        raise GoogleFlowError(
            f"timed out after {self.settings.timeout_seconds}s waiting for a generated asset on canvas"
        )



    def _download_card_asset(
        self,
        page,
        card_more_btn,
        output_dir: Path,
        stem: str,
        expected_suffix: str,
    ) -> Path:
        more_btn = page.locator(
            "button[aria-label='Tuỳ chọn khác'], button[aria-label*='Tuỳ chọn khác'], "
            "button[aria-label*='More options'], button[aria-label='More options']"
        ).first
        more_btn.click(force=True)
        page.wait_for_timeout(1000)


        download_item = self._first_visible(
            page.locator(
                ".cdk-overlay-pane [role='menuitem']:has-text('Tải xuống'), "
                ".cdk-overlay-pane button:has-text('Tải xuống'), "
                ".cdk-overlay-pane [role='menuitem']:has-text('Download'), "
                ".cdk-overlay-pane button:has-text('Download')"
            )
        )
        if download_item is None:
            download_item = self._first_visible(page.locator(self.selectors.download))
        if download_item is None:
            raise GoogleFlowError("could not find download option in asset menu")

        try:
            download_item.hover()
            download_item.click()
            page.wait_for_timeout(1000)
        except Exception:
            pass

        res_btn = self._first_visible(
            page.locator(
                ".cdk-overlay-pane [role='menuitem']:not([disabled]):has-text('gốc'), "
                ".cdk-overlay-pane [role='menuitem']:not([disabled]):has-text('Kích thước'), "
                ".cdk-overlay-pane [role='menuitem']:not([disabled]):has-text('Original'), "
                ".cdk-overlay-pane [role='menuitem']:not([disabled]):has-text('1K'), "
                ".cdk-overlay-pane [role='menuitem']:not([disabled]):has-text('720p')"
            )
        )
        trigger = res_btn if res_btn is not None else download_item

        with page.expect_download(timeout=self.settings.timeout_seconds * 1000) as info:
            trigger.click()
        download = info.value
        suffix = Path(download.suggested_filename or "").suffix or expected_suffix
        if suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov"}:
            suffix = expected_suffix
        destination = output_dir / safe_asset_filename(stem, suffix)

        if download.url.startswith("blob:"):
            b64_data = page.evaluate(
                """async (url) => {
                    const resp = await fetch(url);
                    const buf = await resp.arrayBuffer();
                    let binary = '';
                    const bytes = new Uint8Array(buf);
                    for (let i = 0; i < bytes.byteLength; i++) {
                        binary += String.fromCharCode(bytes[i]);
                    }
                    return btoa(binary);
                }""",
                download.url,
            )
            raw_bytes = base64.b64decode(b64_data)
            destination.write_bytes(raw_bytes)
        else:
            download.save_as(str(destination))

        return destination

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
