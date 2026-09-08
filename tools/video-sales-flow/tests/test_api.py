from pathlib import Path

from fastapi.testclient import TestClient

from video_sales_flow.api import create_app
from video_sales_flow.config import Settings
from video_sales_flow.engines.mock import MockEngine


def test_api_accepts_model_and_multiple_outfits_and_exposes_completed_manifest(tmp_path: Path) -> None:
    settings = Settings(
        output_root=(tmp_path / "outputs").resolve(),
        profile_dir=(tmp_path / "profile").resolve(),
        engine="mock",
        max_videos=5,
    )
    client = TestClient(create_app(settings=settings, engine=MockEngine()))

    response = client.post(
        "/jobs",
        data={
            "video_count": "2",
            "motions": "pose,catwalk",
            "tone": "premium",
            "product_name": "Áo sơ mi nữ",
        },
        files=[
            ("model_image", ("model.jpg", b"model", "image/jpeg")),
            ("outfit_images", ("shirt.png", b"shirt", "image/png")),
            ("outfit_images", ("jacket.png", b"jacket", "image/png")),
        ],
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    status = client.get(f"/jobs/{job_id}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "completed"
    assert len([a for a in payload["assets"] if a["asset_type"] == "edited_image"]) == 2
    assert len([a for a in payload["assets"] if a["asset_type"] == "video"]) == 2


def test_api_rejects_job_above_local_video_guard(tmp_path: Path) -> None:
    settings = Settings(
        output_root=(tmp_path / "outputs").resolve(),
        profile_dir=(tmp_path / "profile").resolve(),
        engine="mock",
        max_videos=1,
    )
    client = TestClient(create_app(settings=settings, engine=MockEngine()))

    response = client.post(
        "/jobs",
        data={"video_count": "2"},
        files=[
            ("model_image", ("model.jpg", b"model", "image/jpeg")),
            ("outfit_images", ("shirt.png", b"shirt", "image/png")),
        ],
    )

    assert response.status_code == 422
    assert "safety limit" in response.text
