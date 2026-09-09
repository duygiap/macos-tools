from __future__ import annotations

from pathlib import Path

from .engines.base import GenerationEngine
from .models import GeneratedAsset, JobManifest, JobOptions, JobStatus
from .planner import PromptPlanner
from .storage import (
    atomic_write_json,
    copy_input,
    ensure_input_file,
    new_job_id,
    sanitized_stem,
)
from .tryon.pipeline import TryOnPipeline


class JobService:
    def __init__(
        self,
        output_root: Path,
        engine: GenerationEngine,
        max_videos: int = 10,
        max_outfits: int = 10,
        planner: PromptPlanner | None = None,
        tryon_pipeline: TryOnPipeline | None = None,
    ) -> None:
        if max_videos < 1:
            raise ValueError("max_videos must be at least 1")
        if max_outfits < 1:
            raise ValueError("max_outfits must be at least 1")
        self.output_root = output_root.expanduser().resolve()
        self.engine = engine
        self.max_videos = max_videos
        self.max_outfits = max_outfits
        self.planner = planner or PromptPlanner()
        self.tryon_pipeline = tryon_pipeline or getattr(engine, "tryon_pipeline", None)

    def create_job(
        self,
        model_image: Path,
        outfit_images: list[Path],
        options: JobOptions,
    ) -> JobManifest:
        self._validate(options, model_image, outfit_images)
        model_source = ensure_input_file(model_image)
        outfit_sources = [ensure_input_file(path) for path in outfit_images]

        job_id = new_job_id()
        job_dir = self.job_dir(job_id)
        inputs_dir = job_dir / "inputs"
        model_target = copy_input(
            model_source,
            inputs_dir / f"model{model_source.suffix.lower()}",
        )
        outfit_targets: list[Path] = []
        for index, source in enumerate(outfit_sources, start=1):
            outfit_targets.append(
                copy_input(
                    source,
                    inputs_dir
                    / f"outfit-{index:02d}-{sanitized_stem(source)}{source.suffix.lower()}",
                )
            )

        manifest = JobManifest(
            job_id=job_id,
            status=JobStatus.PENDING,
            engine=self.engine.name,
            options=options,
            model_input=str(model_target),
            outfit_inputs=[str(path) for path in outfit_targets],
        )
        self._persist(manifest)
        return manifest

    def execute(self, job_id: str) -> JobManifest:
        manifest = self.load_manifest(job_id)
        if manifest.status not in {JobStatus.PENDING, JobStatus.FAILED}:
            raise ValueError(f"job {job_id} is not executable from status {manifest.status.value}")

        manifest.status = JobStatus.RUNNING
        manifest.error = None
        self._persist(manifest)
        job_dir = self.job_dir(job_id)
        try:
            edited_paths: list[Path] = []
            for index, outfit_path in enumerate(manifest.outfit_inputs, start=1):
                prompt = self.planner.plan_tryon(
                    Path(manifest.model_input),
                    Path(outfit_path),
                    manifest.options,
                )
                manifest.prompts.append(prompt)

                if self.tryon_pipeline is None:
                    asset = self.engine.generate_image(
                        prompt,
                        job_dir / "tryon",
                        f"tryon-{index:02d}",
                    )
                    manifest.assets.append(asset)
                    edited_paths.append(Path(asset.path))
                    self._persist(manifest)
                    continue

                result = self.tryon_pipeline.run(
                    model_image=Path(manifest.model_input),
                    outfit_image=Path(outfit_path),
                    base_prompt=prompt.prompt,
                    output_dir=job_dir / "tryon",
                    stem=f"tryon-{index:02d}",
                )
                for attempt in result.attempts:
                    approved = attempt.review.approved
                    metadata: dict[str, str | int | float | bool | None] = {
                        "stage": "tryon",
                        "attempt": attempt.attempt,
                        "approved": approved,
                        "review_issues": "; ".join(attempt.review.issues),
                        "image_engine": self.tryon_pipeline.engine.name,
                    }
                    for key, value in attempt.review.metadata.items():
                        if key not in metadata:
                            metadata[key] = value
                    manifest.assets.append(
                        GeneratedAsset(
                            asset_type="edited_image" if approved else "debug",
                            path=str(attempt.path),
                            prompt_title=prompt.title,
                            metadata=metadata,
                        )
                    )
                    self._persist(manifest)

                if not result.approved or result.approved_path is None:
                    last_review = result.last_review
                    issues = "; ".join(last_review.issues) if last_review else "unknown review failure"
                    raise RuntimeError(
                        f"try-on review rejected outfit #{index} after "
                        f"{len(result.attempts)} attempt(s): {issues}"
                    )
                edited_paths.append(result.approved_path)

            video_prompts = self.planner.plan_videos(edited_paths, manifest.options)
            for index, prompt in enumerate(video_prompts, start=1):
                manifest.prompts.append(prompt)
                asset = self.engine.generate_video(
                    prompt,
                    job_dir / "videos",
                    f"video-{index:02d}",
                )
                manifest.assets.append(asset)
                self._persist(manifest)

            manifest.status = JobStatus.COMPLETED
            self._persist(manifest)
            return manifest
        except Exception as exc:
            manifest.status = JobStatus.FAILED
            manifest.error = f"{type(exc).__name__}: {exc}"
            self._persist(manifest)
            return manifest

    def run(
        self,
        model_image: Path,
        outfit_images: list[Path],
        options: JobOptions,
    ) -> JobManifest:
        manifest = self.create_job(model_image, outfit_images, options)
        return self.execute(manifest.job_id)

    def load_manifest(self, job_id: str) -> JobManifest:
        path = self.manifest_path(job_id)
        if not path.exists():
            raise FileNotFoundError(f"job not found: {job_id}")
        return JobManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def job_dir(self, job_id: str) -> Path:
        if not job_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in job_id):
            raise ValueError("invalid job id")
        return self.output_root / job_id

    def manifest_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "manifest.json"

    def _persist(self, manifest: JobManifest) -> None:
        atomic_write_json(
            self.manifest_path(manifest.job_id),
            manifest.model_dump(mode="json"),
        )

    def _validate(
        self,
        options: JobOptions,
        model_image: Path,
        outfit_images: list[Path],
    ) -> None:
        if options.video_count > self.max_videos:
            raise ValueError(
                f"requested {options.video_count} videos exceeds local safety limit {self.max_videos}"
            )
        if not outfit_images:
            raise ValueError("at least one outfit image is required")
        if len(outfit_images) > self.max_outfits:
            raise ValueError(
                f"requested {len(outfit_images)} outfits exceeds local safety limit {self.max_outfits}"
            )
        ensure_input_file(model_image)
        for path in outfit_images:
            ensure_input_file(path)
