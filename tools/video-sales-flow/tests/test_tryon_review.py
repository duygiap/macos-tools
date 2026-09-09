from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from video_sales_flow.config import Settings
from video_sales_flow.tryon.review import TryOnReviewer


def _write_png(path: Path, size: tuple[int, int] = (1, 1)) -> None:
    Image.new("RGB", size, "white").save(path, format="PNG")


def test_settings_expose_safe_tryon_defaults(tmp_path: Path):
    settings = Settings.from_env(
        {
            "VIDEO_SALES_OUTPUT_ROOT": str(tmp_path / "out"),
            "VIDEO_SALES_PROFILE_DIR": str(tmp_path / "profile"),
        }
    )

    assert settings.tryon_engine == "legacy"
    assert settings.gemini_url == "https://gemini.google.com/app"
    assert settings.tryon_max_attempts == 3
    assert settings.tryon_min_width == 512
    assert settings.tryon_min_height == 512
    assert settings.tryon_review_mode == "local"


def test_settings_reject_invalid_tryon_attempt_count(tmp_path: Path):
    with pytest.raises(ValueError, match="VIDEO_SALES_TRYON_MAX_ATTEMPTS"):
        Settings.from_env(
            {
                "VIDEO_SALES_OUTPUT_ROOT": str(tmp_path / "out"),
                "VIDEO_SALES_PROFILE_DIR": str(tmp_path / "profile"),
                "VIDEO_SALES_TRYON_MAX_ATTEMPTS": "0",
            }
        )


def test_reviewer_rejects_missing_file(tmp_path: Path):
    result = TryOnReviewer(min_width=1, min_height=1).review(tmp_path / "missing.png")

    assert result.approved is False
    assert any("does not exist" in issue for issue in result.issues)


def test_reviewer_rejects_corrupt_image(tmp_path: Path):
    image = tmp_path / "corrupt.png"
    image.write_bytes(b"not-a-real-image")

    result = TryOnReviewer(min_width=1, min_height=1).review(image)

    assert result.approved is False
    assert any("valid supported image" in issue for issue in result.issues)


def test_reviewer_rejects_too_small_image(tmp_path: Path):
    image = tmp_path / "tiny.png"
    _write_png(image)

    result = TryOnReviewer(min_width=512, min_height=512).review(image)

    assert result.approved is False
    assert any("minimum" in issue for issue in result.issues)


def test_reviewer_rejects_watermark_hint_in_filename(tmp_path: Path):
    image = tmp_path / "freepik-watermark.png"
    _write_png(image)

    result = TryOnReviewer(min_width=1, min_height=1).review(image)

    assert result.approved is False
    assert any("watermark" in issue.casefold() for issue in result.issues)


def test_reviewer_approves_decodable_image_when_local_checks_pass(tmp_path: Path):
    image = tmp_path / "approved.png"
    _write_png(image)

    result = TryOnReviewer(min_width=1, min_height=1).review(image)

    assert result.approved is True
    assert result.issues == []
