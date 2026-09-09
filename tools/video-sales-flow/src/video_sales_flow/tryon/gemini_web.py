from __future__ import annotations

import base64
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
    # Google AI Studio's visible controls on /prompts/new_chat. Environment
    # overrides are retained below for a future UI change.
    prompt: str = (
        "textarea[aria-label='Enter a prompt'], "
        "textarea[placeholder*='Start typing a prompt']"
    )
    upload: str = "input[type='file'].file-input, input[type='file'][accept*='image']"
    upload_menu: str = (
        "button[data-test-id='add-media-button'], "
        "button[aria-label*='Insert images, videos, audio, or files']"
    )
    upload_menu_item: str = "button[aria-label='Upload files'], button:has-text('Upload files')"
    upload_menu_input: str = "input[type='file'].file-input"
    upload_trigger: str = "button[aria-label='Upload files'], button:has-text('Upload files')"
    send: str = "button.ctrl-enter-submits, button:has-text('Run')"
    model: str = "ms-model-selector button"
    resolution: str = "[role='combobox'][aria-label='Resolution']"
    download: str = (
        "button[aria-label*='Download'], button[mattooltip*='Download'], "
        "button[title*='Download'], button:has-text('Download'), "
        "button:has-text('download'), [aria-label*='Download'], "
        "[mattooltip*='Download'], [title*='Download'], "
        "[data-test-id*='download'], [data-testid*='download'], "
        "button[aria-label*='Tải xuống'], button:has-text('Tải xuống'), a[download]"
    )
    generated_image: str = (
        "img.loaded-image[src^='blob:'], img[src^='blob:']"
    )
    response: str = (
        "ms-chat-turn, message-content, .model-response-text, .model-response, "
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
            upload_menu=source.get(
                "VIDEO_SALES_GEMINI_UPLOAD_MENU_SELECTOR", defaults.upload_menu
            ),
            upload_menu_item=source.get(
                "VIDEO_SALES_GEMINI_UPLOAD_MENU_ITEM_SELECTOR", defaults.upload_menu_item
            ),
            upload_menu_input=source.get(
                "VIDEO_SALES_GEMINI_UPLOAD_MENU_INPUT_SELECTOR", defaults.upload_menu_input
            ),
            upload_trigger=source.get(
                "VIDEO_SALES_GEMINI_UPLOAD_TRIGGER_SELECTOR", defaults.upload_trigger
            ),
            send=source.get("VIDEO_SALES_GEMINI_SEND_SELECTOR", defaults.send),
            model=source.get("VIDEO_SALES_AI_STUDIO_MODEL_SELECTOR", defaults.model),
            resolution=source.get(
                "VIDEO_SALES_AI_STUDIO_RESOLUTION_SELECTOR", defaults.resolution
            ),
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


def is_ai_studio_url(url: str) -> bool:
    return "aistudio.google.com" in url.casefold()


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
                "Google AI Studio opened in the persistent Google browser profile. "
                "Sign in/accept first-use prompts, confirm AI Studio is usable, then return here."
            )
            input("Press Enter to close Chromium after Google AI Studio is ready... ")
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
                self._configure_ai_studio_image_generation(page)
                self._upload_files(page, [model, outfit])
                self._fill_prompt(page, prompt)
                self._assert_no_purchase_dialog(page)

                responses = page.locator(self.selectors.response)
                images = page.locator(self.selectors.generated_image)
                downloads = page.locator(self.selectors.download)
                baseline_responses = responses.count()
                baseline_images = images.count()
                baseline_downloads = downloads.count()
                self._click_send_once(page)
                destination = self._wait_and_capture_generated_image(
                    page,
                    output_dir=output_dir,
                    stem=stem,
                    baseline_responses=baseline_responses,
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
                "Google AI Studio session is not authenticated; run "
                "'video-sales-flow gemini-login' first"
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

    def _configure_ai_studio_image_generation(self, page) -> None:
        if not is_ai_studio_url(page.url):
            return

        model_button = self._wait_for_first_visible(page, self.selectors.model, timeout=30_000)
        if model_button is None:
            raise GeminiWebError(
                "could not find the Google AI Studio model selector; set "
                "VIDEO_SALES_AI_STUDIO_MODEL_SELECTOR"
            )
        desired_model = self.settings.ai_studio_image_model
        try:
            selected_model = model_button.inner_text()
        except Exception:
            selected_model = ""
        if desired_model.casefold() not in selected_model.casefold():
            model_button.click()
            try:
                option = page.get_by_role(
                    "button", name=re.compile(rf"^{re.escape(desired_model)}", re.IGNORECASE)
                )
                option.wait_for(state="visible", timeout=10_000)
                option.click()
                page.locator(self.selectors.model).filter(has_text=desired_model).first.wait_for(
                    state="visible", timeout=10_000
                )
            except Exception as exc:
                raise GeminiWebError(
                    f"could not select AI Studio image model {desired_model!r}; "
                    "set VIDEO_SALES_AI_STUDIO_IMAGE_MODEL or "
                    "VIDEO_SALES_AI_STUDIO_MODEL_SELECTOR"
                ) from exc

        resolution = self._wait_for_first_visible(page, self.selectors.resolution, timeout=10_000)
        if resolution is None:
            raise GeminiWebError(
                "could not find the Google AI Studio Resolution control; set "
                "VIDEO_SALES_AI_STUDIO_RESOLUTION_SELECTOR"
            )
        desired_resolution = self.settings.ai_studio_image_resolution
        try:
            selected_resolution = resolution.inner_text()
        except Exception:
            selected_resolution = ""
        if desired_resolution.casefold() in selected_resolution.casefold():
            return
        try:
            resolution.click()
            option = page.get_by_role("option", name=desired_resolution, exact=True)
            option.wait_for(state="visible", timeout=10_000)
            option.click()
            page.locator(self.selectors.resolution).filter(has_text=desired_resolution).first.wait_for(
                state="visible", timeout=10_000
            )
        except Exception as exc:
            raise GeminiWebError(
                f"could not select AI Studio image resolution {desired_resolution!r}; "
                "set VIDEO_SALES_AI_STUDIO_IMAGE_RESOLUTION or "
                "VIDEO_SALES_AI_STUDIO_RESOLUTION_SELECTOR"
            ) from exc

    def _upload_files(self, page, paths: list[Path]) -> None:
        resolved = [str(path.resolve()) for path in paths]
        # Follow the same user-visible path as AI Studio: Add media -> Upload files.
        # The menu-scoped input accepts both references in a single selection; a generic
        # input remains only as an accessible fallback if the UI is changed.
        upload_menu = self._wait_for_first_visible(
            page, self.selectors.upload_menu, timeout=10_000
        )
        if upload_menu is not None:
            upload_menu.click()
            upload_menu_item = self._wait_for_first_visible(
                page, self.selectors.upload_menu_item, timeout=10_000
            )
            if upload_menu_item is not None:
                upload_menu_item.click()
                menu_input = page.locator(self.selectors.upload_menu_input)
                try:
                    menu_input.first.wait_for(state="attached", timeout=10_000)
                except Exception:
                    pass
                if self._set_input_files(menu_input, resolved):
                    return

        if self._set_upload_input_files(page, resolved):
            return

        for path in resolved:
            if self._set_upload_input_files(page, [path]):
                continue
            trigger = self._first_visible(page.locator(self.selectors.upload_trigger))
            if trigger is None:
                raise GeminiWebError(
                    "could not find Google AI Studio file upload; set "
                    "VIDEO_SALES_GEMINI_UPLOAD_SELECTOR "
                    "or VIDEO_SALES_GEMINI_UPLOAD_TRIGGER_SELECTOR"
                )
            with page.expect_file_chooser(timeout=10_000) as chooser_info:
                trigger.click()
            chooser_info.value.set_files(path)
            page.wait_for_timeout(1_200)

    def _set_upload_input_files(self, page, paths: list[str]) -> bool:
        return self._set_input_files(page.locator(self.selectors.upload), paths, use_last=True)

    @staticmethod
    def _set_input_files(inputs, paths: list[str], *, use_last: bool = False) -> bool:
        if inputs.count() == 0:
            return False
        try:
            (inputs.last if use_last else inputs.first).set_input_files(paths)
            return True
        except Exception:
            # A few older Gemini layouts expose only a single-file input. The caller then
            # retries each file separately before falling back to the file chooser path.
            return False

    @staticmethod
    def _wait_for_first_visible(page, selector: str, *, timeout: int):
        locator = page.locator(selector)
        try:
            locator.first.wait_for(state="visible", timeout=timeout)
        except Exception:
            return None
        return GeminiWebClient._first_visible(locator)

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
        baseline_responses: int,
        baseline_images: int,
        baseline_downloads: int,
    ) -> Path:
        deadline = time.monotonic() + self.settings.timeout_seconds
        requires_download = is_ai_studio_url(page.url) or is_ai_studio_url(self.settings.gemini_url)
        response_count = 0
        image_count = 0
        download_count = 0
        while time.monotonic() < deadline:
            self._assert_no_purchase_dialog(page)
            responses = page.locator(self.selectors.response)
            response_count = responses.count()
            response = None
            if responses.count() > baseline_responses:
                response = self._last_visible(responses)
                if response is not None:
                    # In AI Studio the icon strip belongs to the response card, not always
                    # to its inner image. Hover the new card first to reveal Download.
                    try:
                        response.hover(timeout=1_000)
                    except Exception:
                        pass

            images = page.locator(self.selectors.generated_image)
            image_count = images.count()
            image = None
            if images.count() > baseline_images:
                image = self._last_visible(images)
                if image is not None:
                    if requires_download:
                        # AI Studio renders the generated result as a blob URL. Fetching
                        # that blob inside the page returns the original image bytes, while
                        # a locator screenshot would only preserve the tiny on-screen preview.
                        destination = self._save_ai_studio_blob_image(
                            image, output_dir=output_dir, stem=stem
                        )
                        if destination is not None:
                            return destination
                    # AI Studio exposes the Download action when the generated image is hovered.
                    # Its original file, unlike this visual element, is safe for quality review.
                    try:
                        image.hover(timeout=1_000)
                    except Exception:
                        pass

            downloads = page.locator(self.selectors.download)
            download_count = downloads.count()
            generation_observed = response is not None or image is not None
            if downloads.count() > baseline_downloads or generation_observed:
                # AI Studio can expose more than one download-looking control. Prefer
                # controls inside the newly generated response, so reference uploads
                # never become the try-on asset, then try every visible action there.
                scoped_downloads = response.locator(self.selectors.download) if response else None
                candidates = (
                    scoped_downloads
                    if scoped_downloads is not None and scoped_downloads.count()
                    else downloads
                )
                destination = self._download_from_visible_controls(
                    page, candidates, output_dir=output_dir, stem=stem
                )
                if destination is not None:
                    return destination

            if image is not None and not requires_download:
                try:
                    destination = output_dir / safe_image_filename(stem, ".png")
                    image.screenshot(path=str(destination))
                    return destination
                except Exception:
                    pass
            page.wait_for_timeout(1_000)
        capture_requirement = "a full-resolution AI Studio download" if requires_download else "a new image"
        raise GeminiWebError(
            f"timed out waiting for {capture_requirement}; "
            "update generated-image/download selectors "
            f"(responses={response_count}/{baseline_responses}, "
            f"images={image_count}/{baseline_images}, "
            f"downloads={download_count}/{baseline_downloads})"
        )

    @staticmethod
    def _download_from_visible_controls(page, controls, *, output_dir: Path, stem: str) -> Path | None:
        for index in range(controls.count() - 1, -1, -1):
            control = controls.nth(index)
            try:
                if not control.is_visible():
                    continue
                with page.expect_download(timeout=10_000) as download_info:
                    control.click()
                download = download_info.value
                suffix = Path(download.suggested_filename).suffix or ".png"
                destination = output_dir / safe_image_filename(stem, suffix)
                download.save_as(str(destination))
                return destination
            except Exception:
                # AI Studio may fulfil its download action through a normal image
                # response rather than a browser download event. Capture that exact
                # response, which preserves the original file instead of a thumbnail.
                try:
                    with page.expect_response(
                        GeminiWebClient._is_download_asset_response, timeout=10_000
                    ) as response_info:
                        control.click()
                    response = response_info.value
                    payload = response.body()
                    if not payload:
                        continue
                    destination = output_dir / safe_image_filename(
                        stem, GeminiWebClient._response_suffix(response)
                    )
                    destination.write_bytes(payload)
                    return destination
                except Exception:
                    continue
        return None

    @staticmethod
    def _save_ai_studio_blob_image(image, *, output_dir: Path, stem: str) -> Path | None:
        try:
            payload = image.evaluate(
                """async element => {
                    if (!element.src.startsWith('blob:')) return null;
                    const response = await fetch(element.src);
                    if (!response.ok) throw new Error(`blob fetch failed: ${response.status}`);
                    const blob = await response.blob();
                    const bytes = new Uint8Array(await blob.arrayBuffer());
                    const chunks = [];
                    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
                        chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 0x8000)));
                    }
                    return {mime: blob.type, base64: btoa(chunks.join(''))};
                }"""
            )
            if not isinstance(payload, dict):
                return None
            encoded = payload.get("base64")
            if not isinstance(encoded, str) or not encoded:
                return None
            data = base64.b64decode(encoded, validate=True)
            if not data:
                return None
            destination = output_dir / safe_image_filename(
                stem, GeminiWebClient._mime_suffix(payload.get("mime"))
            )
            destination.write_bytes(data)
            return destination
        except Exception:
            return None

    @staticmethod
    def _is_download_asset_response(response) -> bool:
        try:
            headers = response.headers
            content_type = headers.get("content-type", "").casefold()
            content_disposition = headers.get("content-disposition", "").casefold()
            return response.status == 200 and (
                content_type.startswith("image/") or "attachment" in content_disposition
            )
        except Exception:
            return False

    @staticmethod
    def _response_suffix(response) -> str:
        return GeminiWebClient._mime_suffix(response.headers.get("content-type", ""))

    @staticmethod
    def _mime_suffix(content_type: object) -> str:
        normalized = str(content_type).split(";", 1)[0].casefold()
        return {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(normalized, ".png")

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
