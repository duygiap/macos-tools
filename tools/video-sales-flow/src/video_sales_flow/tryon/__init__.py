from __future__ import annotations

from ..config import Settings
from .ai_studio_api import (
    AIStudioAPIClient,
    AIStudioAPIError,
    AIStudioAPIKeyMissing,
    AIStudioAPITryOnEngine,
    AIStudioAPITryOnReviewer,
)
from .base import TryOnGenerationError, TryOnImageEngine, TryOnReviewResult
from .gemini_web import GeminiWebClient, GeminiWebTryOnEngine, GeminiWebTryOnReviewer
from .mock import MockTryOnEngine
from .pipeline import TryOnAttempt, TryOnPipeline, TryOnPipelineResult
from .review import TryOnReviewer


def build_tryon_pipeline(settings: Settings) -> TryOnPipeline | None:
    if settings.tryon_engine == "legacy":
        return None

    local_reviewer = TryOnReviewer(
        min_width=settings.tryon_min_width,
        min_height=settings.tryon_min_height,
    )
    gemini_client: GeminiWebClient | None = None
    api_client: AIStudioAPIClient | None = None

    if settings.tryon_engine == "mock":
        engine = MockTryOnEngine()
    elif settings.tryon_engine == "gemini-web":
        gemini_client = GeminiWebClient(settings=settings)
        engine = GeminiWebTryOnEngine(client=gemini_client)
    elif settings.tryon_engine == "ai-studio-api":
        api_client = AIStudioAPIClient(settings=settings)
        engine = AIStudioAPITryOnEngine(client=api_client)
    else:  # Settings validation normally makes this unreachable.
        raise ValueError(f"unsupported try-on engine: {settings.tryon_engine}")

    if settings.tryon_review_mode == "gemini-web":
        gemini_client = gemini_client or GeminiWebClient(settings=settings)
        reviewer = GeminiWebTryOnReviewer(
            local_reviewer=local_reviewer,
            client=gemini_client,
        )
    elif settings.tryon_review_mode == "ai-studio-api":
        api_client = api_client or AIStudioAPIClient(settings=settings)
        reviewer = AIStudioAPITryOnReviewer(
            local_reviewer=local_reviewer,
            client=api_client,
        )
    else:
        reviewer = local_reviewer

    return TryOnPipeline(
        engine=engine,
        reviewer=reviewer,
        max_attempts=settings.tryon_max_attempts,
    )


__all__ = [
    "AIStudioAPIClient",
    "AIStudioAPIError",
    "AIStudioAPIKeyMissing",
    "AIStudioAPITryOnEngine",
    "AIStudioAPITryOnReviewer",
    "GeminiWebClient",
    "GeminiWebTryOnEngine",
    "GeminiWebTryOnReviewer",
    "MockTryOnEngine",
    "TryOnAttempt",
    "TryOnGenerationError",
    "TryOnImageEngine",
    "TryOnPipeline",
    "TryOnPipelineResult",
    "TryOnReviewResult",
    "TryOnReviewer",
    "build_tryon_pipeline",
]
