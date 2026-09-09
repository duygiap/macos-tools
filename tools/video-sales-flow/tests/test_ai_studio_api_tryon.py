import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_sales_flow.tryon.ai_studio_api import (
    AIStudioAPIClient,
    AIStudioAPIKeyMissing,
    AIStudioAPITryOnEngine,
)


class FakeInteractions:
    def __init__(self, interaction):
        self.interaction = interaction
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.interaction


class FakeSDKClient:
    def __init__(self, interaction):
        self.interactions = FakeInteractions(interaction)


def _settings():
    return SimpleNamespace(
        ai_studio_api_model="models/gemini-3.1-flash-lite-image",
        ai_studio_api_aspect_ratio="9:16",
        ai_studio_api_image_size="1K",
        ai_studio_api_thinking_level="high",
        ai_studio_api_temperature=1.0,
        ai_studio_api_top_p=1.0,
        ai_studio_api_max_output_tokens=65536,
    )


def _interaction_with_image(payload: bytes):
    part = SimpleNamespace(type="image", data=base64.b64encode(payload).decode("ascii"))
    step = SimpleNamespace(type="model_output", content=[part])
    return SimpleNamespace(steps=[step], output_image=None, output_text="")


def test_api_tryon_sends_model_outfit_and_current_image_response_format(tmp_path: Path):
    model = tmp_path / "model.jpg"
    outfit = tmp_path / "outfit.png"
    model.write_bytes(b"model-bytes")
    outfit.write_bytes(b"outfit-bytes")

    sdk = FakeSDKClient(_interaction_with_image(b"generated-image"))
    client = AIStudioAPIClient(settings=_settings(), sdk_client=sdk)
    engine = AIStudioAPITryOnEngine(client=client)

    output = engine.generate_tryon(
        model_image=model,
        outfit_image=outfit,
        prompt="Preserve the person and replace only the clothing.",
        output_dir=tmp_path / "out",
        stem="look-01",
    )

    assert output.read_bytes() == b"generated-image"
    call = sdk.interactions.calls[0]
    assert call["model"] == "models/gemini-3.1-flash-lite-image"
    assert call["input"][0]["type"] == "image"
    assert call["input"][0]["mime_type"] == "image/jpeg"
    assert base64.b64decode(call["input"][0]["data"]) == b"model-bytes"
    assert call["input"][1]["type"] == "image"
    assert call["input"][1]["mime_type"] == "image/png"
    assert base64.b64decode(call["input"][1]["data"]) == b"outfit-bytes"
    assert call["input"][2] == {
        "type": "text",
        "text": "Preserve the person and replace only the clothing.",
    }
    assert call["generation_config"] == {
        "temperature": 1.0,
        "max_output_tokens": 65536,
        "top_p": 1.0,
        "thinking_level": "high",
    }
    assert call["response_format"] == {
        "type": "image",
        "mime_type": "image/png",
        "aspect_ratio": "9:16",
        "image_size": "1K",
    }


def test_api_tryon_uses_output_image_shortcut_when_steps_do_not_contain_image(tmp_path: Path):
    model = tmp_path / "model.png"
    outfit = tmp_path / "outfit.png"
    model.write_bytes(b"model")
    outfit.write_bytes(b"outfit")
    interaction = SimpleNamespace(
        steps=[],
        output_image=SimpleNamespace(data=base64.b64encode(b"shortcut-image").decode("ascii")),
        output_text="done",
    )
    client = AIStudioAPIClient(settings=_settings(), sdk_client=FakeSDKClient(interaction))

    output = client.generate_tryon_image(
        model_image=model,
        outfit_image=outfit,
        prompt="try on",
        output_dir=tmp_path / "out",
        stem="shortcut",
    )

    assert output.read_bytes() == b"shortcut-image"


def test_api_client_requires_gemini_api_key_without_injected_sdk_client(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(AIStudioAPIKeyMissing, match="GEMINI_API_KEY"):
        AIStudioAPIClient(settings=_settings())
