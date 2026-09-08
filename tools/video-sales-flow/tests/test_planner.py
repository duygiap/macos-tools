from pathlib import Path

from video_sales_flow.models import JobOptions, Motion, Tone
from video_sales_flow.planner import PromptPlanner


def test_tryon_prompt_preserves_identity_and_exact_garment_details() -> None:
    options = JobOptions(video_count=1, tone=Tone.PREMIUM)

    prompt = PromptPlanner().plan_tryon(
        Path("model.jpg"), Path("shirt.png"), options
    )

    lowered = prompt.prompt.lower()
    assert "preserve the model's identity" in lowered
    assert "face" in lowered
    assert "body proportions" in lowered
    assert "garment reference" in lowered
    assert "do not invent logos" in lowered
    assert prompt.reference_paths == ["model.jpg", "shirt.png"]


def test_auto_motion_plan_is_diverse_and_matches_requested_count() -> None:
    options = JobOptions(video_count=7, motions=[Motion.AUTO])

    prompts = PromptPlanner().plan_videos(
        [Path("look-1.png"), Path("look-2.png")], options
    )

    assert len(prompts) == 7
    assert [p.motion for p in prompts[:5]] == [
        Motion.POSE,
        Motion.CATWALK,
        Motion.TURN,
        Motion.MIXED,
        Motion.JUMP,
    ]
    assert len({p.prompt for p in prompts[:5]}) == 5
    assert prompts[0].reference_paths == ["look-1.png"]
    assert prompts[1].reference_paths == ["look-2.png"]


def test_explicit_motions_cycle_without_auto_expansion() -> None:
    options = JobOptions(
        video_count=5,
        motions=[Motion.CATWALK, Motion.POSE],
        tone=Tone.ENERGETIC,
    )

    prompts = PromptPlanner().plan_videos([Path("look.png")], options)

    assert [p.motion for p in prompts] == [
        Motion.CATWALK,
        Motion.POSE,
        Motion.CATWALK,
        Motion.POSE,
        Motion.CATWALK,
    ]


def test_video_prompt_keeps_outfit_visible_and_avoids_generated_cta_text() -> None:
    options = JobOptions(
        video_count=1,
        motions=[Motion.JUMP],
        brand_name="A8 Fashion",
        product_name="Áo sơ mi nữ",
        cta_text="Mua ngay",
        aspect_ratio="9:16",
        duration_seconds=8,
    )

    prompt = PromptPlanner().plan_videos([Path("look.png")], options)[0]

    lowered = prompt.prompt.lower()
    assert "keep the garment clearly visible" in lowered
    assert "preserve" in lowered and "garment" in lowered
    assert "do not render text" in lowered
    assert "a8 fashion" in lowered
    assert "áo sơ mi nữ" in lowered
    assert "9:16" in prompt.prompt
    assert "8-second" in prompt.prompt
