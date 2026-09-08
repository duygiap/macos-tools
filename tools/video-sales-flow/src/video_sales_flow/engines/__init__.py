from __future__ import annotations

from ..config import Settings
from .base import GenerationEngine
from .mock import MockEngine


def build_engine(name: str, settings: Settings) -> GenerationEngine:
    normalized = name.strip().lower()
    if normalized == "mock":
        return MockEngine()
    if normalized == "google-flow":
        from .google_flow import GoogleFlowEngine

        return GoogleFlowEngine(settings=settings)
    raise ValueError(f"unknown engine: {name}")


__all__ = ["GenerationEngine", "MockEngine", "build_engine"]
