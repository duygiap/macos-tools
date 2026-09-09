from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

from .base import TryOnGenerationError, TryOnReviewResult
from .review import TryOnReviewer


class AIStudioAPIError(TryOnGenerationError):
    pass


class AIStudioAPIKeyMissing(AIStudioAPIError):
    pass


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned or "tryon"


def _mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed if guessed and guessed.startswith("image/") else "image/png"


def _decode_image_data(data: Any) -> bytes | None:
    if data is None:
        return None
    if isinstance(data, str):
        try:
            return base64.b64decode(data)
        except (ValueError, TypeError):
            return None
    if isinstance(data, (bytes, bytearray)):
        try:
            return base64.b64decode(bytes(data))
        except (ValueError, TypeError):
            return bytes(data)
    return None


def _parse_review_json(text: str) -> TryOnReviewResult:
    stripped = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.IGNORECASE | re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        candidate = match.group(0) if match else stripped
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as exc:
        return TryOnReviewResult(
            approved=False,
            issues=[f"AI Studio API review did not return valid JSON: {type(exc).__name__}"],
            retry_hint="Regenerate the image and review it again.",
            metadata={"semantic_review": True},
        )

    issues_raw = payload.get("issues", [])
    issues = [str(item) for item in issues_raw] if isinstance(issues_raw, list) else [str(issues_raw)]
    watermark_detected = bool(payload.get("watermark_detected", False))
    approved = bool(payload.get("approved", False)) and not watermark_detected
    if watermark_detected and not any("watermark" in issue.casefold() for issue in issues):
        issues.append("visible watermark detected")
    retry_hint = payload.get("retry_hint")
    return TryOnReviewResult(
        approved=approved,
        issues=issues,
        retry_hint=str(retry_hint) if retry_hint else None,
        metadata={"semantic_review": True, "watermark_detected": watermark_detected},
    )


class AIStudioAPIClient:
    def __init__(self, *, settings: Any, sdk_client: Any | None = None) -> None:
        self.settings = settings
        if sdk_client is not None:
            self.sdk_client = sdk_client
            return

        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise AIStudioAPIKeyMissing(
                "GEMINI_API_KEY is required when VIDEO_SALES_TRYON_ENGINE=ai-studio-api"
            )
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - declared runtime dependency
            raise AIStudioAPIError("google-genai is required for AI Studio API try-on") from exc
        self.sdk_client = genai.Client(api_key=api_key)

    def _generation_config(self) -> dict[str, Any]:
        return {
            "temperature": self.settings.ai_studio_api_temperature,
            "max_output_tokens": self.settings.ai_studio_api_max_output_tokens,
            "top_p": self.settings.ai_studio_api_top_p,
            "thinking_level": self.settings.ai_studio_api_thinking_level,
        }

    def _image_response_format(self) -> dict[str, str]:
        return {
            "type": "image",
            "mime_type": "image/png",
            "aspect_ratio": self.settings.ai_studio_api_aspect_ratio,
            "image_size": self.settings.ai_studio_api_image_size,
        }

    @staticmethod
    def _image_input(path: Path) -> dict[str, str]:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"AI Studio API image input not found: {resolved}")
        return {
            "type": "image",
            "mime_type": _mime_type(resolved),
            "data": base64.b64encode(resolved.read_bytes()).decode("ascii"),
        }

    @staticmethod
    def _extract_image(interaction: Any) -> bytes | None:
        output_image = getattr(interaction, "output_image", None)
        decoded = _decode_image_data(getattr(output_image, "data", None))
        if decoded:
            return decoded
        for step in getattr(interaction, "steps", []) or []:
            if getattr(step, "type", None) != "model_output":
                continue
            for part in getattr(step, "content", []) or []:
                if getattr(part, "type", None) != "image":
                    continue
                decoded = _decode_image_data(getattr(part, "data", None))
                if decoded:
                    return decoded
        return None

    def generate_tryon_image(
        self,
        *,
        model_image: Path,
        outfit_image: Path,
        prompt: str,
        output_dir: Path,
        stem: str,
    ) -> Path:
        output_dir = output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        inputs = [
            self._image_input(model_image),
            self._image_input(outfit_image),
            {"type": "text", "text": prompt},
        ]
        try:
            interaction = self.sdk_client.interactions.create(
                model=self.settings.ai_studio_api_model,
                input=inputs,
                generation_config=self._generation_config(),
                response_format=self._image_response_format(),
            )
        except Exception as exc:
            raise AIStudioAPIError(
                f"AI Studio API try-on request failed ({type(exc).__name__})"
            ) from exc

        image_bytes = self._extract_image(interaction)
        if not image_bytes:
            raise AIStudioAPIError("AI Studio API returned no image output")
        destination = output_dir / f"{_safe_stem(stem)}.png"
        destination.write_bytes(image_bytes)
        return destination.resolve()

    def review_image(self, image_path: Path) -> TryOnReviewResult:
        prompt = (
            "Review this fashion try-on image for production use. Return ONLY one JSON object with "
            'keys: {"approved": boolean, "watermark_detected": boolean, "issues": [string], '
            '"retry_hint": string|null}. Reject any visible watermark, stock-source text, unrelated '
            "overlaid text, serious face/hand/body distortion, broken garment geometry, or an outfit "
            "that is not plausibly worn by the person. Never recommend removing a watermark; require "
            "regeneration of a clean image instead."
        )
        try:
            interaction = self.sdk_client.interactions.create(
                model=self.settings.ai_studio_api_model,
                input=[self._image_input(image_path), {"type": "text", "text": prompt}],
                generation_config={
                    "temperature": 0.2,
                    "max_output_tokens": 2048,
                    "top_p": 1.0,
                    "thinking_level": self.settings.ai_studio_api_thinking_level,
                },
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "approved": {"type": "boolean"},
                            "watermark_detected": {"type": "boolean"},
                            "issues": {"type": "array", "items": {"type": "string"}},
                            "retry_hint": {"type": ["string", "null"]},
                        },
                        "required": ["approved", "watermark_detected", "issues", "retry_hint"],
                    },
                },
            )
        except Exception as exc:
            raise AIStudioAPIError(
                f"AI Studio API semantic review failed ({type(exc).__name__})"
            ) from exc
        return _parse_review_json(getattr(interaction, "output_text", "") or "")


class AIStudioAPITryOnEngine:
    name = "ai-studio-api"

    def __init__(self, *, client: AIStudioAPIClient) -> None:
        self.client = client

    def generate_tryon(
        self,
        *,
        model_image: Path,
        outfit_image: Path,
        prompt: str,
        output_dir: Path,
        stem: str,
    ) -> Path:
        return self.client.generate_tryon_image(
            model_image=model_image,
            outfit_image=outfit_image,
            prompt=prompt,
            output_dir=output_dir,
            stem=stem,
        )


class AIStudioAPITryOnReviewer:
    def __init__(self, *, local_reviewer: TryOnReviewer, client: AIStudioAPIClient) -> None:
        self.local_reviewer = local_reviewer
        self.client = client

    def review(self, image_path: Path) -> TryOnReviewResult:
        local = self.local_reviewer.review(image_path)
        if not local.approved:
            return local
        semantic = self.client.review_image(image_path)
        metadata = dict(local.metadata)
        metadata.update(semantic.metadata)
        return TryOnReviewResult(
            approved=semantic.approved,
            issues=semantic.issues,
            retry_hint=semantic.retry_hint,
            metadata=metadata,
        )
