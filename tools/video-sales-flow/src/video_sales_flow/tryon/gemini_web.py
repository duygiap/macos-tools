from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config import Settings, detect_browser_executable
from .base import TryOnGenerationError, TryOnReviewResult
from .review import TryOnReviewer


_PURCHASE_PATTERNS = (
    "upgrade your plan",
    "upgrade to continue",
    "buy more",
    "buy credits",
    "purchase credits",
    "purchase a plan",
    "get google ai pro",
    "get google ai ultra",
    "mua gói",
    "mua thêm",
    "nâng cấp để tiếp tục",
    "nâng cấp gói",
)


class GeminiWebError(TryOnGenerationError):
    pass


class GeminiLoginRequired(GeminiWebError):
    pass


class GeminiPurchaseBlocked(GeminiWebError):
    pass


@dataclass(frozen=True)
class GeminiSelectors:
    prompt: str = (
        "textarea, [contenteditable='true'][role='textbox'], "
        ".ql-editor[contenteditable='true'], .ProseMirror[contenteditable='true']"
    )
    upload: str = "input[type='file']"
    upload_trigger: str = (
        "button[aria-label*='Add files'], button[aria-label*='Upload'], "
        "button[aria-label*='Thêm tệp'], button[aria-label*='Tải tệp'], "
        "button:has-text('Add files'), button:has-text('Upload files'), "
        "button:has-text('Thêm tệp'), button:has-text('Tải tệp')"
    )
    send: str = (
        "button[aria-label*='Submit'], button[aria-label*='Send'], "
        "button[aria-label*='Gửi'], button:has-text('Submit'), button:has-text('Send')"
    )
    download: str = (
        "button[aria-label*='Download'], button:has-text('Download'), "
        "button[aria-label*='Tải xuống'], button:has-text('Tải xuống'), a[download]"
    )
    generated_image: str = (
        "message-content img, .model-response img, [data-test-id*='response'] img, "
        "main article img, main img[src^='blob:']"
    )
    response: str = (
        "message-content, .model-response-text, .model-response, "
        "[data-test-id*='response-content'], main article"
    )
    dialog: str = "[role='dialog']:visible, [aria-modal='true']:visible"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "GeminiSelectors":
        source = os.environ if env is None else env
        defaults = cls()
        return cls(
            prompt=source.get("VIDEO_SALES_GEMINI_PROMPT_SELECTOR", defaults.prompt),
            upload=source.get("VIDEO_SALES_GEMINI_UPLOAD_SELECTOR", defaults.upload),
            upload_trigger=source.get(
                "VIDEO_SALES_GEMINI_UPLOAD_TRIGGER_SELECTOR", defaults.upload_trigger
            ),
            send=source.get("VIDEO_SALES_GEMINI_SEND_SELECTOR", defaults.send),
            download=source.get("VIDEO_SALES_GEMINI_DOWNLOAD_SELECTOR", defaults.download),
            generated_image=source.get(
                "VIDEO_SALES_GEMINI_GENERATED_IMAGE_SELECTOR", defaults.generated_image
            ),
            response=source.get("VIDEO_SALES_GEMINI_RESPONSE_SELECTOR", defaults.response),
            dialog=source.get("VIDEO_SALES_GEMINI_DIALOG_SELECTOR", defaults.dialog),
        )


def contains_purchase_text(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    return any(pattern in normalized for pattern in _PURCHASE_PATTERNS)


def is_login_url(url: str) -> bool:
    normalized = url.casefold()
    return "accounts.google.com" in normalized or "/signin" in normalized


def safe_image_filename(stem: str, suffix: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "asset"
    normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    normalized_suffix = re.sub(r"[^A-Za-z0-9.]", "", normalized_suffix).lower()
    if normalized_suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        normalized_suffix = ".png"
    return f"{cleaned}{normalized_suffix}"


def parse_review_json(text: str) -> TryOnReviewResult:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.IGNORECASE | re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        candidate = match.group(0) if match else stripped
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as exc:
        return TryOnReviewResult(
            approved=False,
            issues=[f"Gemini review did not return valid JSON: {type(exc).__name__}"],
            retry_hint="Regenerate the image and review it again.",
        )

    issues_raw = payload.get("issues", [])
    issues = [str(item) for item in issues_raw] if isinstance(issues_raw, list) else [str(issues_raw)]
    watermark_detected = bool(payload.get("watermark_detected", False))
    approved = bool(payload.get("approved", False)) and not watermark_detected
    if watermark_detected and not any("watermark" in item.casefold() for item in issues):
        issues.append("visible watermark detected")
    retry_hint = payload.get("retry_hint")
    return TryOnReviewResult(
        approved=approved,
        issues=issues,
        retry_hint=str(retry_hint) if retry_hint else None,
        metadata={"semantic_review": True, "watermark_detected": watermark_detected},
    )


class GeminiWebClient:
    def __init__(
        self,
        settings: Settings | None = None,
        selectors: GeminiSelectors | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.selectors = selectors or GeminiSelectors.from_env()

    def _sync_playwright(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise GeminiWebError("Playwright is required for Gemini web automation") from exc
        return sync_playwright

    def _launch_options(self, *, headless: bool) -> dict[str, Any]:
        options: dict[str, Any] = {
            "user_data_dir": str(self.settings.profile_dir),
            "headless": headless,
            "accept_downloads": True,
            "ignore_default_args": ["--enable-automation"],
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
            ],
        }
        executable = self.settings.browser_executable or detect_browser_executable()
        if executable:
            options["executable_path"] = str(executable)
        return options

    def login(self) -> None:
        self.settings.profile_dir.mkdir(parents=True, exist_ok=True)
        sync_playwright = self._sync_playwright()
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                **self._launch_options(headless=False)
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(self.settings.gemini_url, wait_until="domcontentloaded")
            print(
                "Gemini opened in the persistent Google browser profile. "
                "Sign in/accept first-use prompts, confirm Gemini is usable, then return here."
            )
            input("Press Enter to close Chromium after Gemini login is ready... ")
            context.close()

    def generate_image(
        self,
        *,
        model_image: Path,
        outfit_image: Path,
        prompt: str,
        output_dir: Path,
        stem: str,
    ) -> Path:
        model = model_image.expanduser().resolve()
        outfit = outfit_image.expanduser().resolve()
        for path in (model, outfit):
            if not path.is_file():
                raise FileNotFoundError(f"Gemini reference image not found: {path}")
        output_dir = output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        debug_path = output_dir / safe_image_filename(f"debug-{stem}", ".png")

        sync_playwright = self._sync_playwright()
        context = None
        try:
            options = self._launch_options(headless=self.settings.headless)
            if self.settings.headless:
                # Native Chrome is more reliable with the new headless implementation.
                options["headless"] = False
                args = list(options.get("args", []))
                if "--headless=new" not in args:
                    args.append("--headless=new")
                options["args"] = args
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(**options)
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(
                    self.settings.gemini_url,
                    wait_until="domcontentloaded",
                    timeout=self.settings.timeout_seconds * 1000,
                )
                self._ensure_logged_in(page)
                self._assert_no_purchase_dialog(page)
                self._upload_files(page, [model, outfit])
                self._fill_prompt(page, prompt)
                self._assert_no_purchase_dialog(page)

                images = page.locator(self.selectors.generated_image)
                downloads = page.locator(self.selectors.download)
                baseline_images = images.count()
                baseline_downloads = downloads.count()
                self._click_send_once(page)
                destination = self._wait_and_capture_generated_image(
                    page,
                    output_dir=output_dir,
                    stem=stem,
                    baseline_images=baseline_images,
                    baseline_downloads=baseline_downloads,
                )
                self._assert_no_purchase_dialog(page)
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
            if isinstance(exc, GeminiWebError):
                raise
            raise GeminiWebError(
                f"Gemini web try-on failed: {type(exc).__name__}: {exc}. "
                f"Inspect {debug_path} and override VIDEO_SALES_GEMINI_*_SELECTOR if the UI changed."
            ) from exc

    def review_image(self, image_path: Path) -> TryOnReviewResult:
        image = image_path.expanduser().resolve()
        if not image.is_file():
            return TryOnReviewResult(approved=False, issues=["review image does not exist"])
        prompt = (
            "Review this fashion try-on image for production use. Return ONLY one JSON object with "
            'keys: {"approved": boolean, "watermark_detected": boolean, "issues": [string], '
            '"retry_hint": string|null}. Reject if there is any visible watermark, stock-source text, '
            "unrelated overlaid text, distorted face/hands/body, obviously broken garment geometry, "
            "or the outfit is not plausibly worn by the person. Do not suggest removing a watermark; "
            "if one exists, require regeneration of a clean image."
        )
        sync_playwright = self._sync_playwright()
        context = None
        try:
            options = self._launch_options(headless=self.settings.headless)
            if self.settings.headless:
                options["headless"] = False
                args = list(options.get("args", []))
                if "--headless=new" not in args:
                    args.append("--headless=new")
                options["args"] = args
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(**options)
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(
                    self.settings.gemini_url,
                    wait_until="domcontentloaded",
                    timeout=self.settings.timeout_seconds * 1000,
                )
                self._ensure_logged_in(page)
                self._assert_no_purchase_dialog(page)
                self._upload_files(page, [image])
                responses = page.locator(self.selectors.response)
                baseline = responses.count()
                self._fill_prompt(page, prompt)
                self._click_send_once(page)
                text = self._wait_for_new_response_text(page, baseline)
                self._assert_no_purchase_dialog(page)
                context.close()
                context = None
                return parse_review_json(text)
        except Exception as exc:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if isinstance(exc, GeminiWebError):
                raise
            raise GeminiWebError(f"Gemini semantic review failed: {type(exc).__name__}: {exc}") from exc

    def _ensure_logged_in(self, page) -> None:
        if is_login_url(page.url):
            raise GeminiLoginRequired(
                "Gemini session is not authenticated; run 'video-sales-flow gemini-login' first"
            )

    def _assert_no_purchase_dialog(self, page) -> None:
        dialogs = page.locator(self.selectors.dialog)
        for index in range(dialogs.count()):
            dialog = dialogs.nth(index)
            try:
                if dialog.is_visible() and contains_purchase_text(dialog.inner_text()):
                    raise GeminiPurchaseBlocked(
                        "Gemini requested a plan purchase/upgrade; operation aborted without clicking it"
                    )
            except GeminiPurchaseBlocked:
                raise
            except Exception:
                continue

    def _upload_files(self, page, paths: list[Path]) -> None:
        resolved = [str(path.resolve()) for path in paths]
        inputs = page.locator(self.selectors.upload)
        if inputs.count() > 0:
            try:
                inputs.last.set_input_files(resolved)
                page.wait_for_timeout(1_500)
                return
            except Exception:
                # Some Gemini builds expose a single-file input. Fall back to one at a time.
                pass

        for path in resolved:
            inputs = page.locator(self.selectors.upload)
            if inputs.count() > 0:
                try:
                    inputs.last.set_input_files(path)
                    page.wait_for_timeout(1_200)
                    continue
                except Exception:
                    pass
            trigger = self._first_visible(page.locator(self.selectors.upload_trigger))
            if trigger is None:
                raise GeminiWebError(
                    "could not find Gemini file upload; set VIDEO_SALES_GEMINI_UPLOAD_SELECTOR "
                    "or VIDEO_SALES_GEMINI_UPLOAD_TRIGGER_SELECTOR"
                )
            with page.expect_file_chooser(timeout=10_000) as chooser_info:
                trigger.click()
            chooser_info.value.set_files(path)
            page.wait_for_timeout(1_200)

    def _fill_prompt(self, page, text: str) -> None:
        locator = self._first_visible(page.locator(self.selectors.prompt))
        if locator is None:
            raise GeminiWebError(
                "could not find Gemini prompt box; set VIDEO_SALES_GEMINI_PROMPT_SELECTOR"
            )
        try:
            locator.fill(text)
        except Exception:
            locator.click()
            page.keyboard.press("ControlOrMeta+A")
            page.keyboard.type(text)

    def _click_send_once(self, page) -> None:
        button = self._first_visible(page.locator(self.selectors.send))
        if button is None:
            raise GeminiWebError(
                "could not find Gemini submit button; set VIDEO_SALES_GEMINI_SEND_SELECTOR"
            )
        button.click()

    def _wait_and_capture_generated_image(
        self,
        page,
        *,
        output_dir: Path,
        stem: str,
        baseline_images: int,
        baseline_downloads: int,
    ) -> Path:
        deadline = time.monotonic() + self.settings.timeout_seconds
        while time.monotonic() < deadline:
            self._assert_no_purchase_dialog(page)
            downloads = page.locator(self.selectors.download)
            if downloads.count() > baseline_downloads:
                button = self._last_visible(downloads)
                if button is not None:
                    try:
                        with page.expect_download(timeout=10_000) as download_info:
                            button.click()
                        download = download_info.value
                        suffix = Path(download.suggested_filename).suffix or ".png"
                        destination = output_dir / safe_image_filename(stem, suffix)
                        download.save_as(str(destination))
                        return destination
                    except Exception:
                        pass

            images = page.locator(self.selectors.generated_image)
            if images.count() > baseline_images:
                image = self._last_visible(images)
                if image is not None:
                    try:
                        destination = output_dir / safe_image_filename(stem, ".png")
                        image.screenshot(path=str(destination))
                        return destination
                    except Exception:
                        pass
            page.wait_for_timeout(1_000)
        raise GeminiWebError(
            "timed out waiting for a newly generated Gemini image; update generated-image/download selectors"
        )

    def _wait_for_new_response_text(self, page, baseline: int) -> str:
        deadline = time.monotonic() + self.settings.timeout_seconds
        last_text = ""
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            self._assert_no_purchase_dialog(page)
            responses = page.locator(self.selectors.response)
            if responses.count() > baseline:
                response = self._last_visible(responses)
                if response is not None:
                    try:
                        text = response.inner_text().strip()
                    except Exception:
                        text = ""
                    if text:
                        if text != last_text:
                            last_text = text
                            stable_since = time.monotonic()
                        elif time.monotonic() - stable_since >= 1.5:
                            return last_text
            page.wait_for_timeout(500)
        if last_text:
            return last_text
        raise GeminiWebError(
            "timed out waiting for Gemini review response; set VIDEO_SALES_GEMINI_RESPONSE_SELECTOR"
        )

    @staticmethod
    def _first_visible(locator):
        for index in range(locator.count()):
            item = locator.nth(index)
            try:
                if item.is_visible():
                    return item
            except Exception:
                continue
        return None

    @staticmethod
    def _last_visible(locator):
        for index in range(locator.count() - 1, -1, -1):
            item = locator.nth(index)
            try:
                if item.is_visible():
                    return item
            except Exception:
                continue
        return None


class GeminiWebTryOnEngine:
    name = "gemini-web"

    def __init__(
        self,
        settings: Settings | None = None,
        selectors: GeminiSelectors | None = None,
        client: GeminiWebClient | None = None,
    ) -> None:
        self.client = client or GeminiWebClient(settings=settings, selectors=selectors)

    def login(self) -> None:
        self.client.login()

    def generate_tryon(
        self,
        *,
        model_image: Path,
        outfit_image: Path,
        prompt: str,
        output_dir: Path,
        stem: str,
    ) -> Path:
        return self.client.generate_image(
            model_image=model_image,
            outfit_image=outfit_image,
            prompt=prompt,
            output_dir=output_dir,
            stem=stem,
        )


class GeminiWebTryOnReviewer:
    def __init__(
        self,
        *,
        local_reviewer: TryOnReviewer,
        client: GeminiWebClient,
    ) -> None:
        self.local_reviewer = local_reviewer
        self.client = client

    def review(self, image_path: Path) -> TryOnReviewResult:
        local = self.local_reviewer.review(image_path)
        if not local.approved:
            return local
        semantic = self.client.review_image(image_path)
        metadata = dict(local.metadata)
        metadata.update(semantic.metadata)
        return TryOnReviewResult(
            approved=semantic.approved,
            issues=semantic.issues,
            retry_hint=semantic.retry_hint,
            metadata=metadata,
        )
