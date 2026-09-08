from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Motion(str, Enum):
    AUTO = "auto"
    POSE = "pose"
    CATWALK = "catwalk"
    TURN = "turn"
    JUMP = "jump"
    MIXED = "mixed"


class Tone(str, Enum):
    ENERGETIC = "energetic"
    ELEGANT = "elegant"
    YOUTHFUL = "youthful"
    PREMIUM = "premium"
    MINIMAL = "minimal"


class JobOptions(BaseModel):
    video_count: int = Field(default=3, ge=1)
    motions: list[Motion] = Field(default_factory=lambda: [Motion.AUTO])
    tone: Tone = Tone.ENERGETIC
    brand_name: str | None = None
    product_name: str | None = None
    target_audience: str | None = None
    cta_text: str | None = "Mua ngay"
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    duration_seconds: int = Field(default=8, ge=4, le=8)
    background_style: str = "clean modern fashion studio"

    @field_validator("motions")
    @classmethod
    def validate_motions(cls, value: list[Motion]) -> list[Motion]:
        if not value:
            return [Motion.AUTO]
        if Motion.AUTO in value and len(value) > 1:
            raise ValueError("motion 'auto' cannot be mixed with explicit motions")
        return value


class PromptKind(str, Enum):
    TRYON = "tryon"
    VIDEO = "video"


class PlannedPrompt(BaseModel):
    kind: PromptKind
    title: str
    prompt: str
    reference_paths: list[str]
    motion: Motion | None = None


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class GeneratedAsset(BaseModel):
    asset_type: Literal["edited_image", "video", "debug"]
    path: str
    prompt_title: str | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class JobManifest(BaseModel):
    job_id: str
    status: JobStatus
    engine: str
    options: JobOptions
    model_input: str
    outfit_inputs: list[str]
    prompts: list[PlannedPrompt] = Field(default_factory=list)
    assets: list[GeneratedAsset] = Field(default_factory=list)
    error: str | None = None
