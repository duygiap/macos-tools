from pathlib import Path

from video_sales_flow.config import Settings
from video_sales_flow.engines.google_flow import (
    FlowSelectors,
    contains_purchase_text,
    safe_asset_filename,
)


def test_settings_default_to_mock_and_google_flow_url(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "VIDEO_SALES_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "VIDEO_SALES_PROFILE_DIR": str(tmp_path / "profile"),
        }
    )

    assert settings.engine == "mock"
    assert settings.flow_url == "https://flow.google/"
    assert settings.max_videos == 10
    assert settings.max_outfits == 10
    assert settings.profile_dir == (tmp_path / "profile").resolve()


def test_flow_selectors_can_be_overridden_from_environment() -> None:
    selectors = FlowSelectors.from_env(
        {
            "VIDEO_SALES_FLOW_PROMPT_SELECTOR": "[data-test=prompt]",
            "VIDEO_SALES_FLOW_UPLOAD_SELECTOR": "input.custom-upload",
            "VIDEO_SALES_FLOW_GENERATE_SELECTOR": "button.go",
            "VIDEO_SALES_FLOW_DOWNLOAD_SELECTOR": "button.save",
        }
    )

    assert selectors.prompt == "[data-test=prompt]"
    assert selectors.upload == "input.custom-upload"
    assert selectors.generate == "button.go"
    assert selectors.download == "button.save"


def test_purchase_guard_blocks_common_english_and_vietnamese_credit_prompts() -> None:
    assert contains_purchase_text("Buy more credits to continue")
    assert contains_purchase_text("Purchase AI credits")
    assert contains_purchase_text("Mua thêm tín dụng AI")
    assert contains_purchase_text("Nâng cấp để tiếp tục")
    assert not contains_purchase_text("Generate video with Veo 3.1")


def test_safe_asset_filename_is_deterministic_and_removes_unsafe_characters() -> None:
    assert safe_asset_filename("video 01 / pose", ".mp4") == "video-01-pose.mp4"
    assert safe_asset_filename("Áo nữ ###", "png") == "o-n.png"


def test_new_download_index_only_accepts_a_download_added_after_generation() -> None:
    from video_sales_flow.engines.google_flow import new_download_index

    assert new_download_index(2, 2) is None
    assert new_download_index(2, 1) is None
    assert new_download_index(2, 3) == 2
    assert new_download_index(0, 1) == 0
