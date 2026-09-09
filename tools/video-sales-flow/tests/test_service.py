import json
from pathlib import Path

import pytest

from video_sales_flow.engines.base import GeneratedAsset, GenerationEngine
from video_sales_flow.engines.mock import MockEngine
from video_sales_flow.models import JobOptions, JobStatus, PlannedPrompt
from video_sales_flow.service import JobService
from video_sales_flow.tryon.base import TryOnReviewResult
from video_sales_flow.tryon.mock import MockTryOnEngine
from video_sales_flow.tryon.pipeline import TryOnPipeline


def _file(path: Path, content: bytes = b"x") -> Path:
    path.write_bytes(content)
    return path


def test_run_copies_inputs_and_generates_one_tryon_per_outfit_and_n_videos(tmp_path: Path) -> None:
    model = _file(tmp_path / "model.jpg", b"model")
    outfit1 = _file(tmp_path / "shirt.png", b"shirt")
    outfit2 = _file(tmp_path / "jacket.webp", b"jacket")
    output_root = tmp_path / "outputs"
    service = JobService(output_root=output_root, engine=MockEngine(), max_videos=10)

    manifest = service.run(
        model_image=model,
        outfit_images=[outfit1, outfit2],
        options=JobOptions(video_count=3),
    )

    assert manifest.status is JobStatus.COMPLETED
    job_dir = output_root / manifest.job_id
    assert (job_dir / "inputs" / "model.jpg").read_bytes() == b"model"
    assert (job_dir / "inputs" / "outfit-01-shirt.png").read_bytes() == b"shirt"
    assert (job_dir / "inputs" / "outfit-02-jacket.webp").read_bytes() == b"jacket"
    assert len([a for a in manifest.assets if a.asset_type == "edited_image"]) == 2
    assert len([a for a in manifest.assets if a.asset_type == "video"]) == 3
    assert len(manifest.prompts) == 5
    persisted = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "completed"
    assert persisted["job_id"] == manifest.job_id


def test_create_job_rejects_requested_count_above_local_guard_before_engine_use(tmp_path: Path) -> None:
    model = _file(tmp_path / "model.jpg")
    outfit = _file(tmp_path / "shirt.png")
    engine = CountingEngine()
    service = JobService(output_root=tmp_path / "outputs", engine=engine, max_videos=2)

    with pytest.raises(ValueError, match="exceeds local safety limit"):
        service.run(
            model_image=model,
            outfit_images=[outfit],
            options=JobOptions(video_count=3),
        )

    assert engine.image_calls == 0
    assert engine.video_calls == 0


def test_engine_failure_is_persisted_as_failed_manifest_and_keeps_completed_assets(tmp_path: Path) -> None:
    model = _file(tmp_path / "model.jpg")
    outfit = _file(tmp_path / "shirt.png")
    service = JobService(output_root=tmp_path / "outputs", engine=FailingVideoEngine(), max_videos=10)

    manifest = service.run(
        model_image=model,
        outfit_images=[outfit],
        options=JobOptions(video_count=2),
    )

    assert manifest.status is JobStatus.FAILED
    assert "synthetic video failure" in (manifest.error or "")
    assert len([a for a in manifest.assets if a.asset_type == "edited_image"]) == 1
    persisted = service.load_manifest(manifest.job_id)
    assert persisted.status is JobStatus.FAILED
    assert persisted.error == manifest.error


class CountingEngine(GenerationEngine):
    name = "counting"

    def __init__(self) -> None:
        self.image_calls = 0
        self.video_calls = 0
        self.video_prompts: list[PlannedPrompt] = []

    def generate_image(self, prompt: PlannedPrompt, output_dir: Path, stem: str) -> GeneratedAsset:
        self.image_calls += 1
        path = output_dir / f"{stem}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        return GeneratedAsset(asset_type="edited_image", path=str(path))

    def generate_video(self, prompt: PlannedPrompt, output_dir: Path, stem: str) -> GeneratedAsset:
        self.video_calls += 1
        self.video_prompts.append(prompt)
        path = output_dir / f"{stem}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")
        return GeneratedAsset(asset_type="video", path=str(path))


class FailingVideoEngine(CountingEngine):
    name = "failing"

    def generate_video(self, prompt: PlannedPrompt, output_dir: Path, stem: str) -> GeneratedAsset:
        self.video_calls += 1
        raise RuntimeError("synthetic video failure")


class AlwaysApproveReviewer:
    def review(self, image_path: Path) -> TryOnReviewResult:
        return TryOnReviewResult(approved=True, metadata={"width": 768, "height": 1024})


class AlwaysRejectReviewer:
    def review(self, image_path: Path) -> TryOnReviewResult:
        return TryOnReviewResult(
            approved=False,
            issues=["visible watermark"],
            retry_hint="Regenerate without watermark or overlaid text.",
        )


def test_create_job_rejects_too_many_outfits_before_engine_use(tmp_path: Path) -> None:
    model = _file(tmp_path / "model.jpg")
    outfit1 = _file(tmp_path / "shirt.png")
    outfit2 = _file(tmp_path / "jacket.png")
    engine = CountingEngine()
    service = JobService(
        output_root=tmp_path / "outputs",
        engine=engine,
        max_videos=10,
        max_outfits=1,
    )

    with pytest.raises(ValueError, match="outfits exceeds local safety limit"):
        service.run(
            model_image=model,
            outfit_images=[outfit1, outfit2],
            options=JobOptions(video_count=1),
        )

    assert engine.image_calls == 0
    assert engine.video_calls == 0


def test_reviewed_tryon_is_used_as_video_reference_instead_of_legacy_image_generation(
    tmp_path: Path,
) -> None:
    model = _file(tmp_path / "model.jpg", b"model")
    outfit = _file(tmp_path / "shirt.jpg", b"shirt")
    engine = CountingEngine()
    tryon_pipeline = TryOnPipeline(
        engine=MockTryOnEngine(width=768, height=1024),
        reviewer=AlwaysApproveReviewer(),
        max_attempts=2,
    )
    service = JobService(
        output_root=tmp_path / "outputs",
        engine=engine,
        tryon_pipeline=tryon_pipeline,
    )

    manifest = service.run(
        model_image=model,
        outfit_images=[outfit],
        options=JobOptions(video_count=1),
    )

    assert manifest.status is JobStatus.COMPLETED
    assert engine.image_calls == 0
    assert engine.video_calls == 1
    assert len(engine.video_prompts) == 1
    video_reference = Path(engine.video_prompts[0].reference_paths[0])
    assert video_reference.name == "tryon-01-attempt-01.png"
    approved_assets = [
        asset
        for asset in manifest.assets
        if asset.asset_type == "edited_image" and asset.metadata.get("stage") == "tryon"
    ]
    assert len(approved_assets) == 1
    assert Path(approved_assets[0].path) == video_reference
    assert approved_assets[0].metadata["approved"] is True


def test_rejected_tryon_exhaustion_fails_job_before_any_video_generation(tmp_path: Path) -> None:
    model = _file(tmp_path / "model.jpg", b"model")
    outfit = _file(tmp_path / "shirt.jpg", b"shirt")
    engine = CountingEngine()
    tryon_pipeline = TryOnPipeline(
        engine=MockTryOnEngine(width=768, height=1024),
        reviewer=AlwaysRejectReviewer(),
        max_attempts=2,
    )
    service = JobService(
        output_root=tmp_path / "outputs",
        engine=engine,
        tryon_pipeline=tryon_pipeline,
    )

    manifest = service.run(
        model_image=model,
        outfit_images=[outfit],
        options=JobOptions(video_count=1),
    )

    assert manifest.status is JobStatus.FAILED
    assert "try-on review rejected" in (manifest.error or "")
    assert engine.image_calls == 0
    assert engine.video_calls == 0
    assert not [asset for asset in manifest.assets if asset.asset_type == "video"]
    rejected_assets = [
        asset
        for asset in manifest.assets
        if asset.asset_type == "debug" and asset.metadata.get("stage") == "tryon"
    ]
    assert len(rejected_assets) == 2
    assert all(asset.metadata["approved"] is False for asset in rejected_assets)
