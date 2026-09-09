from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


class MockTryOnEngine:
    name = "mock"

    def __init__(self, width: int = 768, height: int = 1024) -> None:
        if width < 1 or height < 1:
            raise ValueError("mock try-on dimensions must be positive")
        self.width = width
        self.height = height

    def generate_tryon(
        self,
        *,
        model_image: Path,
        outfit_image: Path,
        prompt: str,
        output_dir: Path,
        stem: str,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{stem}.png"
        image = Image.new("RGB", (self.width, self.height), "white")
        draw = ImageDraw.Draw(image)
        draw.text((24, 24), "video-sales-flow mock try-on", fill="black")
        draw.text((24, 56), f"model: {model_image.name}", fill="black")
        draw.text((24, 88), f"outfit: {outfit_image.name}", fill="black")
        image.save(path, format="PNG")
        return path.resolve()
