from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_sales_flow.config import Settings
from video_sales_flow.models import GeneratedAsset, JobOptions, JobStatus, Tone
from video_sales_flow.telegram_bot import (
    TelegramBot,
    TelegramSessionStore,
    build_telegram_bot,
    parse_make_command,
)
from video_sales_flow.tryon.mock import MockTryOnEngine


class InlineExecutor:
    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - surfaced by production callback
            future.set_exception(exc)
        return future


class FakeTelegramClient:
    def __init__(self, downloads: dict[str, Path]):
        self.downloads = downloads
        self.messages: list[tuple[int, str, int | None]] = []
        self.videos: list[tuple[int, Path, str, int | None]] = []
        self.downloaded_file_ids: list[str] = []

    def download_file(self, file_id: str, destination_dir: Path) -> Path:
        self.downloaded_file_ids.append(file_id)
        source = self.downloads[file_id]
        destination_dir.mkdir(parents=True, exist_ok=True)
        target = destination_dir / source.name
        target.write_bytes(source.read_bytes())
        return target

    def send_message(self, chat_id: int, text: str, reply_to_message_id: int | None = None):
        self.messages.append((chat_id, text, reply_to_message_id))
        return {"ok": True}

    def send_video(
        self,
        chat_id: int,
        video_path: Path,
        caption: str = "",
        reply_to_message_id: int | None = None,
    ):
        self.videos.append((chat_id, video_path, caption, reply_to_message_id))
        return {"ok": True}


class FakeJobService:
    def __init__(self, output_root: Path, video_path: Path):
        self.output_root = output_root
        self.video_path = video_path
        self.created: list[tuple[Path, list[Path], JobOptions]] = []
        self.manifests: dict[str, SimpleNamespace] = {}

    def create_job(self, model_image: Path, outfit_images: list[Path], options: JobOptions):
        self.created.append((model_image, outfit_images, options))
        manifest = SimpleNamespace(job_id="job-telegram-1", status=JobStatus.PENDING, assets=[])
        self.manifests[manifest.job_id] = manifest
        return manifest

    def execute(self, job_id: str):
        manifest = SimpleNamespace(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            assets=[
                GeneratedAsset(
                    asset_type="video",
                    path=str(self.video_path),
                    prompt_title="sales_video_1",
                )
            ],
            error=None,
        )
        self.manifests[job_id] = manifest
        return manifest

    def load_manifest(self, job_id: str):
        return self.manifests[job_id]


def test_parse_make_command_supports_count_and_tone():
    options = parse_make_command("/make 4 premium")
    assert options.video_count == 4
    assert options.tone is Tone.PREMIUM


def test_session_store_assigns_first_image_as_model_and_rest_as_outfits(tmp_path: Path):
    store = TelegramSessionStore(tmp_path / "sessions")

    assert store.add_image(101, tmp_path / "model.jpg") == "model"
    assert store.add_image(101, tmp_path / "shirt.jpg") == "outfit"
    assert store.add_image(101, tmp_path / "jacket.jpg") == "outfit"

    session = store.get(101)
    assert session.model_image == str(tmp_path / "model.jpg")
    assert session.outfit_images == [str(tmp_path / "shirt.jpg"), str(tmp_path / "jacket.jpg")]

    reloaded = TelegramSessionStore(tmp_path / "sessions").get(101)
    assert reloaded == session


def test_bot_receives_images_then_returns_generated_video_to_same_chat(tmp_path: Path):
    source_model = tmp_path / "source-model.jpg"
    source_outfit = tmp_path / "source-shirt.jpg"
    source_model.write_bytes(b"model")
    source_outfit.write_bytes(b"outfit")
    video = tmp_path / "result.mp4"
    video.write_bytes(b"video")

    client = FakeTelegramClient({"model-file": source_model, "outfit-file": source_outfit})
    service = FakeJobService(tmp_path / "jobs", video)
    bot = TelegramBot(
        client=client,
        service=service,
        session_store=TelegramSessionStore(tmp_path / "telegram-sessions"),
        executor=InlineExecutor(),
    )

    bot.handle_message(
        {"message_id": 1, "chat": {"id": 777}, "photo": [{"file_id": "model-file"}]}
    )
    bot.handle_message(
        {"message_id": 2, "chat": {"id": 777}, "photo": [{"file_id": "outfit-file"}]}
    )
    bot.handle_message(
        {"message_id": 3, "chat": {"id": 777}, "text": "/make 1 premium"}
    )

    assert client.downloaded_file_ids == ["model-file", "outfit-file"]
    assert len(service.created) == 1
    _, outfits, options = service.created[0]
    assert len(outfits) == 1
    assert options.video_count == 1
    assert options.tone is Tone.PREMIUM
    assert client.videos == [(777, video, "Video 1/1 · job-telegram-1", 3)]
    assert any(chat_id == 777 and "Hoàn thành 1 video" in text for chat_id, text, _ in client.messages)


def test_reset_clears_pending_images_but_keeps_last_job_for_resend(tmp_path: Path):
    store = TelegramSessionStore(tmp_path / "sessions")
    store.add_image(9, tmp_path / "model.jpg")
    store.add_image(9, tmp_path / "outfit.jpg")
    store.set_last_job(9, "job-123")

    store.reset_inputs(9)

    session = store.get(9)
    assert session.model_image is None
    assert session.outfit_images == []
    assert session.last_job_id == "job-123"


def test_google_flow_telegram_bot_requires_chat_allowlist(tmp_path: Path):
    settings = Settings(
        output_root=tmp_path / "outputs",
        profile_dir=tmp_path / "profile",
        engine="google-flow",
    )

    with pytest.raises(ValueError, match="TELEGRAM_ALLOWED_CHAT_IDS"):
        build_telegram_bot(settings, env={"TELEGRAM_BOT_TOKEN": "123:test-token"})


def test_telegram_builder_injects_configured_tryon_pipeline(tmp_path: Path):
    settings = Settings(
        output_root=tmp_path / "outputs",
        profile_dir=tmp_path / "profile",
        engine="mock",
        tryon_engine="mock",
        tryon_min_width=1,
        tryon_min_height=1,
    )

    bot = build_telegram_bot(settings, env={"TELEGRAM_BOT_TOKEN": "123:test-token"})
    try:
        assert bot.service.tryon_pipeline is not None
        assert isinstance(bot.service.tryon_pipeline.engine, MockTryOnEngine)
    finally:
        bot.close()
