from pathlib import Path

from video_sales_flow.config import Settings, load_environment_file
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


def test_load_environment_file_preserves_exported_values_and_parses_quoted_values(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# local runtime configuration\n"
        "TELEGRAM_BOT_TOKEN=from-file\n"
        "VIDEO_SALES_ENGINE='google-flow'\n",
        encoding="utf-8",
    )
    environment = {"TELEGRAM_BOT_TOKEN": "from-shell"}

    loaded = load_environment_file(dotenv, environment)

    assert loaded == dotenv.resolve()
    assert environment == {
        "TELEGRAM_BOT_TOKEN": "from-shell",
        "VIDEO_SALES_ENGINE": "google-flow",
    }


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


def test_get_browser_candidates_returns_platform_specific_paths() -> None:
    from video_sales_flow.config import get_browser_candidates

    win_candidates = [str(p) for p in get_browser_candidates(system="windows")]
    assert any("chrome.exe" in p.lower() for p in win_candidates)
    assert any("msedge.exe" in p.lower() for p in win_candidates)

    mac_candidates = [str(p) for p in get_browser_candidates(system="darwin")]
    assert any("Google Chrome.app" in p for p in mac_candidates)
    assert any("Chromium.app" in p for p in mac_candidates)

    linux_candidates = [p.as_posix() for p in get_browser_candidates(system="linux")]
    assert "/usr/bin/google-chrome" in linux_candidates
    assert "/usr/bin/chromium" in linux_candidates


def test_detect_browser_executable_custom_path(tmp_path: Path) -> None:
    from video_sales_flow.config import detect_browser_executable

    custom = tmp_path / "custom-browser.exe"
    assert detect_browser_executable(str(custom)) == custom.resolve()


def test_detect_browser_executable_finds_existing_candidate(tmp_path: Path, monkeypatch) -> None:
    from video_sales_flow import config

    fake_chrome = tmp_path / "chrome.exe"
    fake_chrome.write_text("dummy")

    monkeypatch.setattr(
        config,
        "get_browser_candidates",
        lambda system=None, env=None: [tmp_path / "nonexistent.exe", fake_chrome],
    )

    detected = config.detect_browser_executable()
    assert detected == fake_chrome.resolve()


def test_settings_reads_browser_executable_from_env(tmp_path: Path) -> None:
    custom_bin = tmp_path / "my-chrome"
    settings = Settings.from_env(
        {
            "VIDEO_SALES_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "VIDEO_SALES_PROFILE_DIR": str(tmp_path / "profile"),
            "VIDEO_SALES_BROWSER_EXECUTABLE": str(custom_bin),
        }
    )
    assert settings.browser_executable == custom_bin.resolve()


def test_google_flow_engine_launch_options(tmp_path: Path) -> None:
    from video_sales_flow.engines.google_flow import GoogleFlowEngine

    custom_bin = tmp_path / "chrome.exe"
    settings = Settings(
        output_root=tmp_path / "outputs",
        profile_dir=tmp_path / "profile",
        headless=True,
        browser_executable=custom_bin,
    )
    engine = GoogleFlowEngine(settings=settings)
    options = engine._get_launch_options(headless=True)

    assert options["user_data_dir"] == str(tmp_path / "profile")
    assert options["headless"] is True
    assert options["accept_downloads"] is True
    assert options["executable_path"] == str(custom_bin)
    assert options["ignore_default_args"] == ["--enable-automation"]
    assert "--disable-blink-features=AutomationControlled" in options["args"]


def test_login_uses_native_browser(tmp_path: Path, monkeypatch) -> None:
    from unittest.mock import MagicMock
    from video_sales_flow.engines.google_flow import GoogleFlowEngine

    custom_bin = tmp_path / "chrome.exe"
    custom_bin.write_text("dummy")

    settings = Settings(
        output_root=tmp_path / "outputs",
        profile_dir=tmp_path / "profile",
        browser_executable=custom_bin,
    )
    engine = GoogleFlowEngine(settings=settings)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_popen = MagicMock(return_value=mock_proc)
    monkeypatch.setattr("subprocess.Popen", mock_popen)
    monkeypatch.setattr("builtins.input", lambda _: "")

    engine.login(use_native=True)

    assert mock_popen.called
    cmd_args = mock_popen.call_args[0][0]
    assert cmd_args[0] == str(custom_bin)
    assert f"--user-data-dir={tmp_path / 'profile'}" in cmd_args
    assert "https://flow.google/" in cmd_args
