from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .base import TryOnReviewResult


_WATERMARK_TOKENS = (
    "watermark",
    "freepik",
    "shutterstock",
    "getty",
    "adobe-stock",
    "adobe_stock",
    "dreamstime",
    "depositphotos",
)


class TryOnReviewer:
    def __init__(self, min_width: int = 512, min_height: int = 512) -> None:
        if min_width < 1 or min_height < 1:
            raise ValueError("minimum image dimensions must be positive")
        self.min_width = min_width
        self.min_height = min_height

    def review(self, image_path: Path) -> TryOnReviewResult:
        path = image_path.expanduser().resolve()
        issues: list[str] = []
        metadata: dict[str, str | int | float | bool | None] = {}

        if not path.is_file():
            return TryOnReviewResult(
                approved=False,
                issues=[f"generated image does not exist: {path}"],
                retry_hint="Regenerate the try-on image and ensure an image file is returned.",
            )
        if path.stat().st_size == 0:
            return TryOnReviewResult(
                approved=False,
                issues=["generated image file is empty"],
                retry_hint="Regenerate the try-on image and wait for the image download to finish.",
            )

        lowered_name = path.name.casefold()
        if any(token in lowered_name for token in _WATERMARK_TOKENS):
            issues.append("suspected watermark or stock-source marker in generated image filename")

        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
                metadata["width"] = width
                metadata["height"] = height
                metadata["format"] = image.format or "unknown"
                info_text = " ".join(str(value) for value in image.info.values()).casefold()
                if any(token.replace("-", " ") in info_text for token in _WATERMARK_TOKENS):
                    issues.append("suspected watermark or stock-source marker in image metadata")
                if width < self.min_width or height < self.min_height:
                    issues.append(
                        f"image dimensions {width}x{height} are below minimum "
                        f"{self.min_width}x{self.min_height}"
                    )
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            return TryOnReviewResult(
                approved=False,
                issues=[f"generated asset is not a valid supported image: {type(exc).__name__}"],
                retry_hint="Regenerate and download a valid PNG, JPEG, or WebP image.",
            )

        if issues:
            return TryOnReviewResult(
                approved=False,
                issues=issues,
                retry_hint=(
                    "Regenerate a clean, high-resolution try-on image without watermark, "
                    "stock text, or unrelated overlaid text."
                ),
                metadata=metadata,
            )
        return TryOnReviewResult(approved=True, metadata=metadata)
