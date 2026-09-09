from __future__ import annotations

import base64
from pathlib import Path

from video_sales_flow.tryon.gemini_web import (
    GeminiWebClient,
    GeminiSelectors,
    contains_purchase_text,
    is_ai_studio_url,
    is_login_url,
    parse_review_json,
    safe_image_filename,
)


def test_gemini_selectors_can_be_overridden_from_environment():
    selectors = GeminiSelectors.from_env(
        {
            "VIDEO_SALES_GEMINI_PROMPT_SELECTOR": "#prompt",
            "VIDEO_SALES_GEMINI_UPLOAD_SELECTOR": "#upload",
            "VIDEO_SALES_GEMINI_UPLOAD_MENU_SELECTOR": "#upload-menu",
            "VIDEO_SALES_GEMINI_UPLOAD_MENU_ITEM_SELECTOR": "#upload-menu-item",
            "VIDEO_SALES_GEMINI_UPLOAD_MENU_INPUT_SELECTOR": "#upload-menu-input",
            "VIDEO_SALES_GEMINI_SEND_SELECTOR": "#send",
            "VIDEO_SALES_AI_STUDIO_MODEL_SELECTOR": "#model",
            "VIDEO_SALES_AI_STUDIO_RESOLUTION_SELECTOR": "#resolution",
            "VIDEO_SALES_GEMINI_DOWNLOAD_SELECTOR": "#download",
            "VIDEO_SALES_GEMINI_RESPONSE_SELECTOR": "#response",
        }
    )

    assert selectors.prompt == "#prompt"
    assert selectors.upload == "#upload"
    assert selectors.upload_menu == "#upload-menu"
    assert selectors.upload_menu_item == "#upload-menu-item"
    assert selectors.upload_menu_input == "#upload-menu-input"
    assert selectors.send == "#send"
    assert selectors.model == "#model"
    assert selectors.resolution == "#resolution"
    assert selectors.download == "#download"
    assert selectors.response == "#response"


def test_login_url_detection_rejects_google_signin_pages():
    assert is_login_url("https://accounts.google.com/v3/signin/identifier") is True
    assert is_login_url("https://gemini.google.com/app/abc123") is False


def test_default_selectors_target_google_ai_studio_controls():
    selectors = GeminiSelectors()

    assert "Enter a prompt" in selectors.prompt
    assert "add-media-button" in selectors.upload_menu
    assert "Upload files" in selectors.upload_menu_item
    assert "ctrl-enter-submits" in selectors.send
    assert "ms-model-selector" in selectors.model
    assert "Resolution" in selectors.resolution
    assert "mattooltip" in selectors.download
    assert "data-test-id" in selectors.download
    assert "ms-chat-turn" in selectors.response
    assert "img.loaded-image" in selectors.generated_image
    assert "blob:" in selectors.generated_image
    assert is_ai_studio_url("https://aistudio.google.com/prompts/new_chat") is True
    assert is_ai_studio_url("https://gemini.google.com/app") is False


def test_purchase_guard_detects_upgrade_and_credit_language():
    assert contains_purchase_text("Upgrade your plan to continue") is True
    assert contains_purchase_text("Mua gói để tiếp tục") is True
    assert contains_purchase_text("Create an image of the model") is False


def test_safe_image_filename_removes_unsafe_characters_and_normalizes_suffix():
    assert safe_image_filename("Try on áo / 01", ".PNG") == "Try-on-o-01.png"
    assert safe_image_filename("***", "webp") == "asset.webp"


def test_download_capture_helper_tries_all_visible_controls_until_one_downloads(tmp_path):
    class _Download:
        suggested_filename = "tryon.webp"

        def save_as(self, destination: str) -> None:
            Path(destination).write_bytes(b"image")

    class _DownloadInfo:
        value = _Download()

    class _DownloadExpectation:
        def __enter__(self):
            return _DownloadInfo()

        def __exit__(self, *_args):
            return False

    class _Control:
        def __init__(self, downloads: bool) -> None:
            self.downloads = downloads

        def is_visible(self) -> bool:
            return True

        def click(self) -> None:
            if not self.downloads:
                raise RuntimeError("not a downloadable response asset")

    class _Controls:
        def __init__(self) -> None:
            self.items = [_Control(True), _Control(False)]

        def count(self) -> int:
            return len(self.items)

        def nth(self, index: int):
            return self.items[index]

    class _Page:
        def expect_download(self, **_kwargs):
            return _DownloadExpectation()

    destination = GeminiWebClient._download_from_visible_controls(
        _Page(), _Controls(), output_dir=tmp_path, stem="tryon-01"
    )

    assert destination == tmp_path / "tryon-01.webp"
    assert destination.read_bytes() == b"image"


def test_image_download_response_detection_accepts_original_image_or_attachment():
    class _Response:
        def __init__(self, content_type: str, content_disposition: str = "") -> None:
            self.status = 200
            self.headers = {
                "content-type": content_type,
                "content-disposition": content_disposition,
            }

    assert GeminiWebClient._is_download_asset_response(_Response("image/png")) is True
    assert GeminiWebClient._is_download_asset_response(
        _Response("application/octet-stream", "attachment; filename=tryon.png")
    ) is True
    assert GeminiWebClient._is_download_asset_response(_Response("application/json")) is False


def test_ai_studio_blob_image_capture_writes_the_original_blob_bytes(tmp_path):
    original = b"original-image-bytes"

    class _BlobImage:
        def evaluate(self, _script: str):
            return {
                "mime": "image/webp",
                "base64": base64.b64encode(original).decode("ascii"),
            }

    destination = GeminiWebClient._save_ai_studio_blob_image(
        _BlobImage(), output_dir=tmp_path, stem="tryon-01"
    )

    assert destination == tmp_path / "tryon-01.webp"
    assert destination.read_bytes() == original


def test_parse_review_json_accepts_fenced_response_and_rejects_visible_watermark():
    result = parse_review_json(
        """```json
        {"approved": true, "watermark_detected": true, "issues": ["visible stock watermark"], "retry_hint": "regenerate clean"}
        ```"""
    )

    assert result.approved is False
    assert "visible stock watermark" in result.issues
    assert result.retry_hint == "regenerate clean"


def test_parse_review_json_approves_clean_image_response():
    result = parse_review_json(
        '{"approved": true, "watermark_detected": false, "issues": [], "retry_hint": null}'
    )

    assert result.approved is True
    assert result.issues == []


class _FakeUploadPage:
    def __init__(self, selectors: GeminiSelectors) -> None:
        self.selectors = selectors
        self.upload_input_available = False
        self.menu_clicks = 0
        self.menu_item_clicks = 0
        self.uploaded_paths: list[list[str]] = []

    def locator(self, selector: str):
        if selector == self.selectors.upload:
            return _FakeLocator(self, "input")
        if selector == self.selectors.upload_menu:
            return _FakeLocator(self, "menu")
        if selector == self.selectors.upload_menu_item:
            return _FakeLocator(self, "menu-item")
        if selector == self.selectors.upload_menu_input:
            return _FakeLocator(self, "menu-input")
        return _FakeLocator(self, "missing")


class _FakeLocator:
    def __init__(self, page: _FakeUploadPage, kind: str) -> None:
        self.page = page
        self.kind = kind

    def count(self) -> int:
        if self.kind == "input":
            return 0
        if self.kind == "menu-item":
            return 1 if self.page.menu_clicks else 0
        if self.kind == "menu-input":
            return 1 if self.page.upload_input_available else 0
        return 1 if self.kind == "menu" else 0

    @property
    def last(self):
        return self

    @property
    def first(self):
        return self

    def nth(self, _index: int):
        return self

    def is_visible(self) -> bool:
        return self.kind == "menu" or (self.kind == "menu-item" and self.page.menu_clicks > 0)

    def click(self) -> None:
        if self.kind == "menu":
            self.page.menu_clicks += 1
            return
        assert self.kind == "menu-item"
        self.page.menu_item_clicks += 1
        self.page.upload_input_available = True

    def wait_for(self, **_kwargs) -> None:
        if self.kind == "menu":
            return
        if self.kind == "menu-item":
            assert self.page.menu_clicks
            return
        assert self.kind == "menu-input"
        assert self.page.upload_input_available

    def set_input_files(self, paths: list[str]) -> None:
        assert self.kind == "menu-input"
        assert self.page.upload_input_available
        self.page.uploaded_paths.append(paths)


def test_gemini_upload_uses_the_file_input_scoped_to_the_upload_menu_item(tmp_path):
    client = GeminiWebClient(
        selectors=GeminiSelectors(
            upload="#upload",
            upload_menu="#menu",
            upload_menu_item="#menu-item",
            upload_menu_input="#menu-input",
        )
    )
    page = _FakeUploadPage(client.selectors)
    paths = [tmp_path / "model.jpg", tmp_path / "outfit.jpg"]

    client._upload_files(page, paths)

    assert page.menu_clicks == 1
    assert page.menu_item_clicks == 1
    assert page.uploaded_paths == [[str(path.resolve()) for path in paths]]
