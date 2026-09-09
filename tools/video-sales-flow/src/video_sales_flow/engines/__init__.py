from __future__ import annotations

from ..config import Settings
from .base import GenerationEngine
from .mock import MockEngine


def build_engine(name: str, settings: Settings) -> GenerationEngine:
    normalized = name.strip().lower()
    if normalized == "mock":
        engine: GenerationEngine = MockEngine()
    elif normalized == "google-flow":
        from .google_flow import GoogleFlowEngine

        engine = GoogleFlowEngine(settings=settings)
    else:
        raise ValueError(f"unknown engine: {name}")

    # Runtime callers such as the Telegram bot already construct the generation
    # engine from Settings before creating JobService. Attach the independently
    # configured try-on pipeline so JobService can inherit it without coupling
    # Telegram transport code to the Gemini implementation.
    from ..tryon import build_tryon_pipeline

    setattr(engine, "tryon_pipeline", build_tryon_pipeline(settings))
    return engine


__all__ = ["GenerationEngine", "MockEngine", "build_engine"]
