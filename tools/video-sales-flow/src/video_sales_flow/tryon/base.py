from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class TryOnGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TryOnReviewResult:
    approved: bool
    issues: list[str] = field(default_factory=list)
    retry_hint: str | None = None
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)


class TryOnImageEngine(Protocol):
    name: str

    def generate_tryon(
        self,
        *,
        model_image: Path,
        outfit_image: Path,
        prompt: str,
        output_dir: Path,
        stem: str,
    ) -> Path:
        ...
