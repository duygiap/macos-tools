from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .models import JobOptions, Motion, PlannedPrompt, PromptKind


_AUTO_MOTIONS: tuple[Motion, ...] = (
    Motion.POSE,
    Motion.CATWALK,
    Motion.TURN,
    Motion.MIXED,
    Motion.JUMP,
)

_MOTION_DIRECTIONS: dict[Motion, str] = {
    Motion.POSE: (
        "Perform two or three confident editorial pose transitions with natural hand "
        "placement, keeping the garment front and silhouette easy to inspect."
    ),
    Motion.CATWALK: (
        "Take a short confident runway walk toward camera, then settle into a clean "
        "fashion pose with natural arm swing and realistic fabric movement."
    ),
    Motion.TURN: (
        "Start front-facing, make a controlled half-turn and a slow full-body turn so "
        "the side and back construction of the garment are visible."
    ),
    Motion.JUMP: (
        "Make one light playful fashion jump with a soft landing; keep anatomy realistic "
        "and use the fabric movement to show drape without covering the garment."
    ),
    Motion.MIXED: (
        "Combine a confident pose, two short runway steps, and a gentle turn; keep the "
        "sequence smooth and commercially focused rather than choreographically complex."
    ),
    Motion.AUTO: "",
}

_TONE_DIRECTIONS = {
    "energetic": "upbeat, current, lively, commercial",
    "elegant": "graceful, polished, refined",
    "youthful": "fresh, social-first, playful, stylish",
    "premium": "cinematic, restrained, high-end fashion advertising",
    "minimal": "clean, simple, product-focused, modern",
}


class PromptPlanner:
    def plan_tryon(
        self,
        model_image: Path,
        outfit_image: Path,
        options: JobOptions,
    ) -> PlannedPrompt:
        prompt = f"""
Use Reference Image A as the model and Reference Image B as the garment reference.

Replace only the model's current clothing with the garment from Reference Image B.
Preserve the model's identity, face, facial features, skin tone, hair, body proportions,
and overall pose unless a tiny pose adjustment is required for realistic garment fit.
Preserve the garment reference faithfully: color, cut, silhouette, seams, collar, sleeves,
visible graphics, logo placement, material cues, and proportions. Do not invent logos,
words, accessories, pockets, patterns, or construction details that are not visible in the
garment reference.

Make the clothing fit naturally on the model with realistic folds, drape, contact shadows,
and anatomy. Keep hands and limbs anatomically plausible. Produce a polished commercial
fashion still suitable as the visual reference for a short apparel sales video.
Background direction: {options.background_style}.
""".strip()
        return PlannedPrompt(
            kind=PromptKind.TRYON,
            title=f"tryon-{outfit_image.stem}",
            prompt=prompt,
            reference_paths=[str(model_image), str(outfit_image)],
        )

    def plan_videos(
        self,
        edited_images: Sequence[Path],
        options: JobOptions,
    ) -> list[PlannedPrompt]:
        if not edited_images:
            raise ValueError("at least one edited model image is required")

        motions = self._expanded_motions(options)
        prompts: list[PlannedPrompt] = []
        for index in range(options.video_count):
            motion = motions[index % len(motions)]
            reference = edited_images[index % len(edited_images)]
            prompts.append(
                PlannedPrompt(
                    kind=PromptKind.VIDEO,
                    title=f"sales-video-{index + 1:02d}-{motion.value}",
                    prompt=self._video_prompt(motion, options, index),
                    reference_paths=[str(reference)],
                    motion=motion,
                )
            )
        return prompts

    @staticmethod
    def _expanded_motions(options: JobOptions) -> tuple[Motion, ...]:
        if options.motions == [Motion.AUTO]:
            return _AUTO_MOTIONS
        return tuple(options.motions)

    @staticmethod
    def _video_prompt(motion: Motion, options: JobOptions, index: int) -> str:
        commercial_bits: list[str] = []
        if options.brand_name:
            commercial_bits.append(f"Brand context: {options.brand_name}.")
        if options.product_name:
            commercial_bits.append(f"Product context: {options.product_name}.")
        if options.target_audience:
            commercial_bits.append(f"Audience context: {options.target_audience}.")
        if options.cta_text:
            commercial_bits.append(
                f"Desired downstream CTA metadata: {options.cta_text}. Do not render text in the generated video."
            )

        commercial = "\n".join(commercial_bits) or "No on-screen sales text is required."
        tone = _TONE_DIRECTIONS[options.tone.value]
        camera_variants = (
            "Start with a medium-full shot and use a subtle forward camera drift.",
            "Use a full-body composition with a gentle lateral camera move.",
            "Begin slightly wider, then ease into a medium-full product-focused framing.",
            "Keep the camera mostly stable with one smooth fashion-commercial push-in.",
            "Use a clean full-body framing with a subtle arc that never hides the outfit.",
        )
        camera = camera_variants[index % len(camera_variants)]

        return f"""
Create a {options.duration_seconds}-second apparel sales video in {options.aspect_ratio} using
Reference Image A as the authoritative identity and outfit reference.

Preserve the same person, face, hair, body proportions, garment design, garment color,
visible graphics, material character, and styling from Reference Image A. Do not redesign,
replace, recolor, or add details to the garment. Keep the garment clearly visible during all
key selling moments and maintain realistic fabric physics, hands, face, and body anatomy.

Motion direction: {_MOTION_DIRECTIONS[motion]}
Camera direction: {camera}
Visual tone: {tone}.
Background: {options.background_style}.
Lighting should be clean and flattering with product-readable texture and silhouette.
Avoid abrupt cuts, extreme lens distortion, occlusion of the product, extra people, or
unrelated props. End on a strong, stable fashion pose suitable for a product showcase.

{commercial}
""".strip()
