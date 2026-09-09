from __future__ import annotations

from video_sales_flow.tryon.gemini_web import (
    GeminiSelectors,
    contains_purchase_text,
    is_login_url,
    parse_review_json,
    safe_image_filename,
)


def test_gemini_selectors_can_be_overridden_from_environment():
    selectors = GeminiSelectors.from_env(
        {
            "VIDEO_SALES_GEMINI_PROMPT_SELECTOR": "#prompt",
            "VIDEO_SALES_GEMINI_UPLOAD_SELECTOR": "#upload",
            "VIDEO_SALES_GEMINI_SEND_SELECTOR": "#send",
            "VIDEO_SALES_GEMINI_DOWNLOAD_SELECTOR": "#download",
            "VIDEO_SALES_GEMINI_RESPONSE_SELECTOR": "#response",
        }
    )

    assert selectors.prompt == "#prompt"
    assert selectors.upload == "#upload"
    assert selectors.send == "#send"
    assert selectors.download == "#download"
    assert selectors.response == "#response"


def test_login_url_detection_rejects_google_signin_pages():
    assert is_login_url("https://accounts.google.com/v3/signin/identifier") is True
    assert is_login_url("https://gemini.google.com/app/abc123") is False


def test_purchase_guard_detects_upgrade_and_credit_language():
    assert contains_purchase_text("Upgrade your plan to continue") is True
    assert contains_purchase_text("Mua gói để tiếp tục") is True
    assert contains_purchase_text("Create an image of the model") is False


def test_safe_image_filename_removes_unsafe_characters_and_normalizes_suffix():
    assert safe_image_filename("Try on áo / 01", ".PNG") == "Try-on-o-01.png"
    assert safe_image_filename("***", "webp") == "asset.webp"


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
