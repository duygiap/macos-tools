from video_sales_flow.config import Settings


def test_settings_accept_ai_studio_api_engine_and_review_mode(tmp_path):
    settings = Settings.from_env(
        {
            "VIDEO_SALES_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "VIDEO_SALES_PROFILE_DIR": str(tmp_path / "profile"),
            "VIDEO_SALES_TRYON_ENGINE": "ai-studio-api",
            "VIDEO_SALES_TRYON_REVIEW_MODE": "ai-studio-api",
        }
    )

    assert settings.tryon_engine == "ai-studio-api"
    assert settings.tryon_review_mode == "ai-studio-api"
    assert settings.ai_studio_api_model == "models/gemini-3.1-flash-lite-image"
    assert settings.ai_studio_api_aspect_ratio == "9:16"
    assert settings.ai_studio_api_image_size == "1K"
    assert settings.ai_studio_api_thinking_level == "high"
    assert settings.ai_studio_api_temperature == 1.0
    assert settings.ai_studio_api_top_p == 1.0
    assert settings.ai_studio_api_max_output_tokens == 65536


def test_settings_allow_ai_studio_api_generation_overrides(tmp_path):
    settings = Settings.from_env(
        {
            "VIDEO_SALES_OUTPUT_ROOT": str(tmp_path / "outputs"),
            "VIDEO_SALES_PROFILE_DIR": str(tmp_path / "profile"),
            "VIDEO_SALES_AI_STUDIO_API_MODEL": "models/custom-image",
            "VIDEO_SALES_AI_STUDIO_API_ASPECT_RATIO": "3:4",
            "VIDEO_SALES_AI_STUDIO_API_IMAGE_SIZE": "2K",
            "VIDEO_SALES_AI_STUDIO_API_THINKING_LEVEL": "minimal",
            "VIDEO_SALES_AI_STUDIO_API_TEMPERATURE": "0.7",
            "VIDEO_SALES_AI_STUDIO_API_TOP_P": "0.9",
            "VIDEO_SALES_AI_STUDIO_API_MAX_OUTPUT_TOKENS": "4096",
        }
    )

    assert settings.ai_studio_api_model == "models/custom-image"
    assert settings.ai_studio_api_aspect_ratio == "3:4"
    assert settings.ai_studio_api_image_size == "2K"
    assert settings.ai_studio_api_thinking_level == "minimal"
    assert settings.ai_studio_api_temperature == 0.7
    assert settings.ai_studio_api_top_p == 0.9
    assert settings.ai_studio_api_max_output_tokens == 4096
