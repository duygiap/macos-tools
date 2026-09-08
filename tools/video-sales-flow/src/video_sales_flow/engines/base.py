from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import GeneratedAsset, PlannedPrompt


class GenerationEngine(ABC):
    name = "base"

    @abstractmethod
    def generate_image(
        self,
        prompt: PlannedPrompt,
        output_dir: Path,
        stem: str,
    ) -> GeneratedAsset:
        raise NotImplementedError

    @abstractmethod
    def generate_video(
        self,
        prompt: PlannedPrompt,
        output_dir: Path,
        stem: str,
    ) -> GeneratedAsset:
        raise NotImplementedError


__all__ = ["GeneratedAsset", "GenerationEngine"]
