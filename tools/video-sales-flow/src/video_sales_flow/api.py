from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from .config import Settings
from .engines import build_engine
from .engines.base import GenerationEngine
from .models import JobOptions, Motion, Tone
from .service import JobService
from .tryon import build_tryon_pipeline


def _parse_motions(value: str) -> list[Motion]:
    parts = [part.strip().lower() for part in value.split(",") if part.strip()]
    return [Motion(part) for part in parts] if parts else [Motion.AUTO]


def _safe_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if not suffix or len(suffix) > 10 or any(ch not in ".abcdefghijklmnopqrstuvwxyz0123456789" for ch in suffix):
        return ".bin"
    return suffix


def create_app(
    settings: Settings | None = None,
    engine: GenerationEngine | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = engine or build_engine(settings.engine, settings)
    service = JobService(
        output_root=settings.output_root,
        engine=engine,
        max_videos=settings.max_videos,
        max_outfits=settings.max_outfits,
        tryon_pipeline=build_tryon_pipeline(settings),
    )

    app = FastAPI(title="Video Sales Flow", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str | int]:
        return {
            "status": "ok",
            "engine": engine.name,
            "max_videos": settings.max_videos,
            "max_outfits": settings.max_outfits,
        }

    @app.post("/jobs", status_code=202)
    async def create_job(
        background_tasks: BackgroundTasks,
        model_image: UploadFile = File(...),
        outfit_images: list[UploadFile] = File(...),
        video_count: int = Form(3),
        motions: str = Form("auto"),
        tone: str = Form(Tone.ENERGETIC.value),
        brand_name: str | None = Form(None),
        product_name: str | None = Form(None),
        target_audience: str | None = Form(None),
        cta_text: str | None = Form("Mua ngay"),
        aspect_ratio: str = Form("9:16"),
        duration_seconds: int = Form(8),
        background_style: str = Form("clean modern fashion studio"),
    ) -> dict[str, str]:
        stage_dir = Path(tempfile.mkdtemp(prefix="video-sales-upload-"))
        uploads = [model_image, *outfit_images]
        try:
            model_path = stage_dir / f"model{_safe_suffix(model_image.filename)}"
            model_path.write_bytes(await model_image.read())
            outfit_paths: list[Path] = []
            for index, upload in enumerate(outfit_images, start=1):
                path = stage_dir / f"outfit-{index:02d}{_safe_suffix(upload.filename)}"
                path.write_bytes(await upload.read())
                outfit_paths.append(path)

            try:
                options = JobOptions(
                    video_count=video_count,
                    motions=_parse_motions(motions),
                    tone=Tone(tone),
                    brand_name=brand_name,
                    product_name=product_name,
                    target_audience=target_audience,
                    cta_text=cta_text,
                    aspect_ratio=aspect_ratio,
                    duration_seconds=duration_seconds,
                    background_style=background_style,
                )
                manifest = service.create_job(model_path, outfit_paths, options)
            except (ValueError, ValidationError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            for upload in uploads:
                await upload.close()
            shutil.rmtree(stage_dir, ignore_errors=True)

        background_tasks.add_task(service.execute, manifest.job_id)
        return {"job_id": manifest.job_id, "status": manifest.status.value}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return service.load_manifest(job_id).model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()
