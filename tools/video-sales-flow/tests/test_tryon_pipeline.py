from __future__ import annotations

from pathlib import Path

from PIL import Image

from video_sales_flow.tryon.base import TryOnReviewResult
from video_sales_flow.tryon.mock import MockTryOnEngine
from video_sales_flow.tryon.pipeline import TryOnPipeline
from video_sales_flow.tryon.review import TryOnReviewer


class ScriptedEngine:
    name = "scripted"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_tryon(
        self,
        *,
        model_image: Path,
        outfit_image: Path,
        prompt: str,
        output_dir: Path,
        stem: str,
    ) -> Path:
        self.prompts.append(prompt)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{stem}.png"
        Image.new("RGB", (1024, 1024), "white").save(path)
        return path


class ScriptedReviewer:
    def __init__(self, results: list[TryOnReviewResult]) -> None:
        self.results = list(results)
        self.calls = 0

    def review(self, image_path: Path) -> TryOnReviewResult:
        result = self.results[self.calls]
        self.calls += 1
        return result


def test_pipeline_retries_with_review_feedback_then_stops_on_approval(tmp_path: Path):
    engine = ScriptedEngine()
    reviewer = ScriptedReviewer(
        [
            TryOnReviewResult(
                approved=False,
                issues=["watermark detected"],
                retry_hint="Generate without watermark or overlaid text.",
            ),
            TryOnReviewResult(approved=True, metadata={"width": 1024, "height": 1024}),
        ]
    )
    pipeline = TryOnPipeline(engine=engine, reviewer=reviewer, max_attempts=3)

    result = pipeline.run(
        model_image=tmp_path / "model.jpg",
        outfit_image=tmp_path / "shirt.jpg",
        base_prompt="Preserve model identity and replace only the outfit.",
        output_dir=tmp_path / "tryon",
        stem="tryon-01",
    )

    assert result.approved is True
    assert result.approved_path is not None
    assert len(result.attempts) == 2
    assert len(engine.prompts) == 2
    assert "Generate without watermark" in engine.prompts[1]
    assert "watermark detected" in engine.prompts[1]


def test_pipeline_exhausts_attempts_without_approving_rejected_images(tmp_path: Path):
    engine = ScriptedEngine()
    reviewer = ScriptedReviewer(
        [
            TryOnReviewResult(approved=False, issues=["bad anatomy"], retry_hint="Fix anatomy."),
            TryOnReviewResult(approved=False, issues=["bad anatomy"], retry_hint="Fix anatomy."),
        ]
    )
    pipeline = TryOnPipeline(engine=engine, reviewer=reviewer, max_attempts=2)

    result = pipeline.run(
        model_image=tmp_path / "model.jpg",
        outfit_image=tmp_path / "shirt.jpg",
        base_prompt="Try on the outfit.",
        output_dir=tmp_path / "tryon",
        stem="tryon-01",
    )

    assert result.approved is False
    assert result.approved_path is None
    assert len(result.attempts) == 2
    assert len(engine.prompts) == 2


def test_mock_tryon_engine_produces_an_image_that_local_review_can_approve(tmp_path: Path):
    engine = MockTryOnEngine(width=768, height=1024)
    output = engine.generate_tryon(
        model_image=tmp_path / "model.jpg",
        outfit_image=tmp_path / "outfit.jpg",
        prompt="mock prompt",
        output_dir=tmp_path / "out",
        stem="tryon",
    )

    result = TryOnReviewer(min_width=512, min_height=512).review(output)

    assert output.suffix == ".png"
    assert result.approved is True
