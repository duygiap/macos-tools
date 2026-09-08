from __future__ import annotations

import json
from pathlib import Path

from .base import GeneratedAsset, GenerationEngine
from ..models import PlannedPrompt


class MockEngine(GenerationEngine):
    """Deterministic engine for tests and prompt inspection; consumes no AI credits."""

    name = "mock"

    def generate_image(
        self,
        prompt: PlannedPrompt,
        output_dir: Path,
        stem: str,
    ) -> GeneratedAsset:
        return self._write(prompt, output_dir, stem, "edited_image")

    def generate_video(
        self,
        prompt: PlannedPrompt,
        output_dir: Path,
        stem: str,
    ) -> GeneratedAsset:
        return self._write(prompt, output_dir, stem, "video")

    @staticmethod
    def _write(
        prompt: PlannedPrompt,
        output_dir: Path,
        stem: str,
        asset_type: str,
    ) -> GeneratedAsset:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = (output_dir / f"{stem}.prompt.json").resolve()
        path.write_text(
            json.dumps(prompt.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return GeneratedAsset(
            asset_type=asset_type,
            path=str(path),
            prompt_title=prompt.title,
            metadata={"mock": True},
        )
