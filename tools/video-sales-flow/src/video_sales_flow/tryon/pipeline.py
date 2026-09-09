from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import TryOnImageEngine, TryOnReviewResult


@dataclass(frozen=True)
class TryOnAttempt:
    attempt: int
    path: Path
    prompt: str
    review: TryOnReviewResult


@dataclass(frozen=True)
class TryOnPipelineResult:
    approved_path: Path | None
    attempts: list[TryOnAttempt] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.approved_path is not None

    @property
    def last_review(self) -> TryOnReviewResult | None:
        return self.attempts[-1].review if self.attempts else None


class TryOnPipeline:
    def __init__(self, engine: TryOnImageEngine, reviewer: Any, max_attempts: int = 3) -> None:
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        self.engine = engine
        self.reviewer = reviewer
        self.max_attempts = max_attempts

    @staticmethod
    def _retry_prompt(base_prompt: str, previous: TryOnReviewResult | None) -> str:
        if previous is None:
            return base_prompt
        details = "; ".join(previous.issues) or "previous image was rejected"
        hint = previous.retry_hint or "Correct the review issues and regenerate a clean image."
        return (
            f"{base_prompt}\n\n"
            "The previous generated try-on image was rejected by quality review.\n"
            f"Review issues: {details}\n"
            f"Retry instruction: {hint}\n"
            "Do not add watermarks, stock-source marks, captions, or unrelated text."
        )

    def run(
        self,
        *,
        model_image: Path,
        outfit_image: Path,
        base_prompt: str,
        output_dir: Path,
        stem: str,
    ) -> TryOnPipelineResult:
        attempts: list[TryOnAttempt] = []
        previous_review: TryOnReviewResult | None = None

        for attempt in range(1, self.max_attempts + 1):
            prompt = self._retry_prompt(base_prompt, previous_review)
            path = self.engine.generate_tryon(
                model_image=model_image,
                outfit_image=outfit_image,
                prompt=prompt,
                output_dir=output_dir,
                stem=f"{stem}-attempt-{attempt:02d}",
            ).expanduser().resolve()
            review = self.reviewer.review(path)
            attempts.append(TryOnAttempt(attempt=attempt, path=path, prompt=prompt, review=review))
            if review.approved:
                return TryOnPipelineResult(approved_path=path, attempts=attempts)
            previous_review = review

        return TryOnPipelineResult(approved_path=None, attempts=attempts)
