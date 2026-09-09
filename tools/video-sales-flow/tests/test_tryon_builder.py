from pathlib import Path

from video_sales_flow.config import Settings
from video_sales_flow.tryon import build_tryon_pipeline
from video_sales_flow.tryon.gemini_web import GeminiWebTryOnEngine, GeminiWebTryOnReviewer
from video_sales_flow.tryon.mock import MockTryOnEngine
from video_sales_flow.tryon.review import TryOnReviewer


def _settings(tmp_path: Path, **kwargs) -> Settings:
    values = {
        "output_root": tmp_path / "outputs",
        "profile_dir": tmp_path / "profile",
    }
    values.update(kwargs)
    return Settings(**values)


def test_legacy_tryon_engine_preserves_existing_job_service_behavior(tmp_path: Path):
    assert build_tryon_pipeline(_settings(tmp_path, tryon_engine="legacy")) is None


def test_mock_tryon_engine_builds_reviewed_pipeline_without_browser(tmp_path: Path):
    pipeline = build_tryon_pipeline(
        _settings(
            tmp_path,
            tryon_engine="mock",
            tryon_max_attempts=2,
            tryon_min_width=400,
            tryon_min_height=500,
        )
    )

    assert pipeline is not None
    assert isinstance(pipeline.engine, MockTryOnEngine)
    assert isinstance(pipeline.reviewer, TryOnReviewer)
    assert pipeline.max_attempts == 2


def test_gemini_web_tryon_with_local_review_builds_without_launching_browser(tmp_path: Path):
    pipeline = build_tryon_pipeline(
        _settings(tmp_path, tryon_engine="gemini-web", tryon_review_mode="local")
    )

    assert pipeline is not None
    assert isinstance(pipeline.engine, GeminiWebTryOnEngine)
    assert isinstance(pipeline.reviewer, TryOnReviewer)


def test_gemini_web_semantic_review_uses_same_public_web_client(tmp_path: Path):
    pipeline = build_tryon_pipeline(
        _settings(tmp_path, tryon_engine="gemini-web", tryon_review_mode="gemini-web")
    )

    assert pipeline is not None
    assert isinstance(pipeline.engine, GeminiWebTryOnEngine)
    assert isinstance(pipeline.reviewer, GeminiWebTryOnReviewer)
    assert pipeline.engine.client is pipeline.reviewer.client
