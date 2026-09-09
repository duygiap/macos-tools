from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import httpx

from .config import Settings
from .models import JobOptions, JobStatus, Tone
from .service import JobService


class TelegramAPIError(RuntimeError):
    pass


@dataclass(eq=True)
class TelegramSession:
    model_image: str | None = None
    outfit_images: list[str] = field(default_factory=list)
    last_job_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_image": self.model_image,
            "outfit_images": list(self.outfit_images),
            "last_job_id": self.last_job_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TelegramSession":
        return cls(
            model_image=value.get("model_image"),
            outfit_images=[str(item) for item in value.get("outfit_images", [])],
            last_job_id=value.get("last_job_id"),
        )


class TelegramSessionStore:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, chat_id: int) -> Path:
        return self.root / f"{int(chat_id)}.json"

    def media_dir(self, chat_id: int) -> Path:
        path = self.root.parent / "media" / str(int(chat_id))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get(self, chat_id: int) -> TelegramSession:
        with self._lock:
            path = self._path(chat_id)
            if not path.exists():
                return TelegramSession()
            return TelegramSession.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def _save(self, chat_id: int, session: TelegramSession) -> None:
        path = self._path(chat_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def add_image(self, chat_id: int, image_path: Path) -> str:
        with self._lock:
            session = self.get(chat_id)
            if session.model_image is None:
                session.model_image = str(image_path)
                role = "model"
            else:
                session.outfit_images.append(str(image_path))
                role = "outfit"
            self._save(chat_id, session)
            return role

    def set_last_job(self, chat_id: int, job_id: str) -> None:
        with self._lock:
            session = self.get(chat_id)
            session.last_job_id = job_id
            self._save(chat_id, session)

    def reset_inputs(self, chat_id: int) -> None:
        with self._lock:
            session = self.get(chat_id)
            session.model_image = None
            session.outfit_images = []
            self._save(chat_id, session)


def parse_make_command(text: str) -> JobOptions:
    parts = text.strip().split()
    if not parts or parts[0].split("@", 1)[0].lower() != "/make":
        raise ValueError("expected /make [count] [tone]")

    count = 3
    tone = Tone.ENERGETIC
    count_seen = False
    tone_seen = False
    valid_tones = {item.value: item for item in Tone}

    for token in parts[1:]:
        normalized = token.strip().lower()
        if normalized.isdigit():
            if count_seen:
                raise ValueError("video count may be specified only once")
            count = int(normalized)
            count_seen = True
            continue
        if normalized in valid_tones:
            if tone_seen:
                raise ValueError("tone may be specified only once")
            tone = valid_tones[normalized]
            tone_seen = True
            continue
        raise ValueError(
            "usage: /make [count] [energetic|elegant|youthful|premium|minimal]"
        )

    return JobOptions(video_count=count, tone=tone)


def parse_allowed_chat_ids(value: str | None) -> set[int] | None:
    if value is None or not value.strip():
        return None
    result: set[int] = set()
    for item in value.split(","):
        token = item.strip()
        if not token:
            continue
        try:
            result.add(int(token))
        except ValueError as exc:
            raise ValueError(f"invalid TELEGRAM_ALLOWED_CHAT_IDS value: {token}") from exc
    return result or None


class TelegramHTTPClient:
    MAX_HOSTED_VIDEO_BYTES = 50 * 1024 * 1024

    def __init__(self, token: str, timeout_seconds: float = 70.0):
        token = token.strip()
        if not token:
            raise ValueError("Telegram bot token must not be empty")
        self._api_base = f"https://api.telegram.org/bot{token}"
        self._file_base = f"https://api.telegram.org/file/bot{token}"
        self._http = httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=15.0))

    def close(self) -> None:
        self._http.close()

    @staticmethod
    def _transport_error(operation: str, exc: httpx.HTTPError) -> TelegramAPIError:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        suffix = f" (HTTP {status_code})" if status_code is not None else ""
        return TelegramAPIError(f"Telegram {operation} request failed{suffix}")

    def _request(self, method: str, *, json_payload: dict[str, Any] | None = None) -> Any:
        try:
            response = self._http.post(f"{self._api_base}/{method}", json=json_payload or {})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise self._transport_error(method, exc) from exc
        payload = response.json()
        if not payload.get("ok"):
            raise TelegramAPIError(payload.get("description", f"Telegram {method} failed"))
        return payload.get("result")

    def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._request("getUpdates", json_payload=payload)
        return list(result or [])

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to_message_id is not None:
            payload["reply_parameters"] = {"message_id": reply_to_message_id}
        return self._request("sendMessage", json_payload=payload)

    def send_video(
        self,
        chat_id: int,
        video_path: Path,
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> Any:
        video_path = video_path.expanduser().resolve()
        if not video_path.is_file():
            raise FileNotFoundError(f"video not found: {video_path}")
        if video_path.stat().st_size > self.MAX_HOSTED_VIDEO_BYTES:
            raise ValueError("video exceeds Telegram hosted Bot API 50 MB sendVideo limit")
        data: dict[str, str] = {"chat_id": str(chat_id), "caption": caption}
        if reply_to_message_id is not None:
            data["reply_parameters"] = json.dumps({"message_id": reply_to_message_id})
        try:
            with video_path.open("rb") as stream:
                response = self._http.post(
                    f"{self._api_base}/sendVideo",
                    data=data,
                    files={"video": (video_path.name, stream, "video/mp4")},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise self._transport_error("sendVideo", exc) from exc
        payload = response.json()
        if not payload.get("ok"):
            raise TelegramAPIError(payload.get("description", "Telegram sendVideo failed"))
        return payload.get("result")

    def download_file(self, file_id: str, destination_dir: Path) -> Path:
        result = self._request("getFile", json_payload={"file_id": file_id})
        file_path = str((result or {}).get("file_path", ""))
        if not file_path:
            raise TelegramAPIError("Telegram getFile returned no file_path")

        try:
            response = self._http.get(f"{self._file_base}/{file_path}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise self._transport_error("file download", exc) from exc
        destination_dir.mkdir(parents=True, exist_ok=True)
        original_name = Path(file_path).name or f"telegram-{file_id}.jpg"
        destination = destination_dir / f"{time.time_ns()}-{original_name}"
        destination.write_bytes(response.content)
        return destination


_HELP = """Gửi ảnh theo thứ tự:
1. Ảnh đầu tiên = model
2. Các ảnh tiếp theo = outfit

Sau đó dùng:
/make [số_video] [tone]
Ví dụ: /make 3 premium

Lệnh khác:
/status - trạng thái job gần nhất
/reset - xoá ảnh đang chờ
/resend [job_id] - gửi lại video đã tạo
"""


class TelegramBot:
    def __init__(
        self,
        client: Any,
        service: JobService,
        session_store: TelegramSessionStore,
        executor: Any | None = None,
        allowed_chat_ids: set[int] | None = None,
        poll_timeout: int = 25,
    ) -> None:
        self.client = client
        self.service = service
        self.session_store = session_store
        self.allowed_chat_ids = allowed_chat_ids
        self.poll_timeout = poll_timeout
        self._owns_executor = executor is None
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="telegram-video")

    def _is_allowed(self, chat_id: int) -> bool:
        return self.allowed_chat_ids is None or chat_id in self.allowed_chat_ids

    @staticmethod
    def _command(text: str) -> str:
        if not text.startswith("/"):
            return ""
        return text.split()[0].split("@", 1)[0].lower()

    @staticmethod
    def _image_file_id(message: Mapping[str, Any]) -> str | None:
        photos = message.get("photo") or []
        if photos:
            return str(photos[-1]["file_id"])
        document = message.get("document") or {}
        mime_type = str(document.get("mime_type", ""))
        if mime_type.startswith("image/") and document.get("file_id"):
            return str(document["file_id"])
        return None

    def handle_message(self, message: Mapping[str, Any]) -> None:
        chat = message.get("chat") or {}
        if "id" not in chat:
            return
        chat_id = int(chat["id"])
        message_id = int(message.get("message_id", 0)) or None

        if not self._is_allowed(chat_id):
            self.client.send_message(chat_id, "Chat này chưa được cấp quyền sử dụng bot.", message_id)
            return

        file_id = self._image_file_id(message)
        if file_id is not None:
            path = self.client.download_file(file_id, self.session_store.media_dir(chat_id))
            role = self.session_store.add_image(chat_id, path)
            session = self.session_store.get(chat_id)
            if role == "model":
                text = "✅ Đã nhận ảnh model. Gửi tiếp ít nhất 1 ảnh outfit."
            else:
                text = f"✅ Đã nhận outfit #{len(session.outfit_images)}. Dùng /make khi đã đủ ảnh."
            self.client.send_message(chat_id, text, message_id)
            return

        text = str(message.get("text", "")).strip()
        command = self._command(text)
        if command in {"/start", "/help"}:
            self.client.send_message(chat_id, _HELP, message_id)
            return
        if command == "/reset":
            self.session_store.reset_inputs(chat_id)
            self.client.send_message(chat_id, "🧹 Đã xoá ảnh đang chờ. Gửi ảnh model mới để bắt đầu.", message_id)
            return
        if command == "/status":
            self._handle_status(chat_id, message_id)
            return
        if command == "/resend":
            self._handle_resend(chat_id, message_id, text)
            return
        if command == "/make":
            self._handle_make(chat_id, message_id, text)
            return
        if text:
            self.client.send_message(chat_id, "Dùng /help để xem hướng dẫn.", message_id)

    def _handle_make(self, chat_id: int, message_id: int | None, text: str) -> None:
        try:
            options = parse_make_command(text)
            session = self.session_store.get(chat_id)
            if session.model_image is None:
                raise ValueError("chưa có ảnh model")
            if not session.outfit_images:
                raise ValueError("chưa có ảnh outfit")

            manifest = self.service.create_job(
                model_image=Path(session.model_image),
                outfit_images=[Path(item) for item in session.outfit_images],
                options=options,
            )
            self.session_store.set_last_job(chat_id, manifest.job_id)
            self.session_store.reset_inputs(chat_id)
            self.client.send_message(
                chat_id,
                f"⏳ Đã tạo job {manifest.job_id}. Đang tạo {options.video_count} video...",
                message_id,
            )
            self.executor.submit(self._execute_and_deliver, manifest.job_id, chat_id, message_id)
        except (ValueError, FileNotFoundError) as exc:
            self.client.send_message(chat_id, f"❌ Không thể tạo job: {exc}", message_id)

    def _execute_and_deliver(self, job_id: str, chat_id: int, reply_to_message_id: int | None) -> None:
        try:
            manifest = self.service.execute(job_id)
            if manifest.status is not JobStatus.COMPLETED:
                self.client.send_message(
                    chat_id,
                    f"❌ Job {job_id} thất bại: {manifest.error or 'unknown error'}",
                    reply_to_message_id,
                )
                return
            self._deliver_videos(manifest, chat_id, reply_to_message_id)
        except Exception as exc:
            self.client.send_message(
                chat_id,
                f"❌ Job {job_id} gặp lỗi khi xử lý/gửi Telegram: {type(exc).__name__}: {exc}",
                reply_to_message_id,
            )

    def _deliver_videos(self, manifest: Any, chat_id: int, reply_to_message_id: int | None) -> None:
        videos = [Path(asset.path) for asset in manifest.assets if asset.asset_type == "video"]
        if not videos:
            self.client.send_message(
                chat_id,
                f"⚠️ Job {manifest.job_id} hoàn thành nhưng không có video asset.",
                reply_to_message_id,
            )
            return
        for index, path in enumerate(videos, start=1):
            self.client.send_video(
                chat_id,
                path,
                caption=f"Video {index}/{len(videos)} · {manifest.job_id}",
                reply_to_message_id=reply_to_message_id,
            )
        self.client.send_message(
            chat_id,
            f"🎉 Hoàn thành {len(videos)} video · {manifest.job_id}",
            reply_to_message_id,
        )

    def _handle_status(self, chat_id: int, message_id: int | None) -> None:
        session = self.session_store.get(chat_id)
        if not session.last_job_id:
            self.client.send_message(chat_id, "Chưa có job nào trong chat này.", message_id)
            return
        try:
            manifest = self.service.load_manifest(session.last_job_id)
            status = manifest.status.value if hasattr(manifest.status, "value") else str(manifest.status)
            text = f"Job {manifest.job_id}: {status}"
            if getattr(manifest, "error", None):
                text += f"\nError: {manifest.error}"
            self.client.send_message(chat_id, text, message_id)
        except FileNotFoundError as exc:
            self.client.send_message(chat_id, f"❌ {exc}", message_id)

    def _handle_resend(self, chat_id: int, message_id: int | None, text: str) -> None:
        parts = text.split(maxsplit=1)
        session = self.session_store.get(chat_id)
        job_id = parts[1].strip() if len(parts) == 2 else session.last_job_id
        if not job_id:
            self.client.send_message(chat_id, "Usage: /resend <job_id>", message_id)
            return
        try:
            manifest = self.service.load_manifest(job_id)
            if manifest.status is not JobStatus.COMPLETED:
                self.client.send_message(
                    chat_id,
                    f"Job {job_id} chưa completed nên chưa thể gửi lại.",
                    message_id,
                )
                return
            self._deliver_videos(manifest, chat_id, message_id)
        except (FileNotFoundError, ValueError) as exc:
            self.client.send_message(chat_id, f"❌ {exc}", message_id)

    def run_forever(self) -> None:
        offset: int | None = None
        while True:
            try:
                updates = self.client.get_updates(offset=offset, timeout=self.poll_timeout)
                for update in updates:
                    update_id = int(update.get("update_id", 0))
                    offset = max(offset or 0, update_id + 1)
                    message = update.get("message")
                    if message:
                        self.handle_message(message)
            except KeyboardInterrupt:
                return
            except Exception as exc:
                print(f"Telegram polling error: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(2)

    def close(self) -> None:
        if self._owns_executor:
            self.executor.shutdown(wait=False, cancel_futures=False)
        close = getattr(self.client, "close", None)
        if callable(close):
            close()


def build_telegram_bot(
    settings: Settings,
    env: Mapping[str, str] | None = None,
    poll_timeout: int = 25,
) -> TelegramBot:
    source = os.environ if env is None else env
    token = source.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    allowed = parse_allowed_chat_ids(source.get("TELEGRAM_ALLOWED_CHAT_IDS"))
    if settings.engine == "google-flow" and allowed is None:
        raise ValueError(
            "TELEGRAM_ALLOWED_CHAT_IDS is required when VIDEO_SALES_ENGINE=google-flow"
        )

    from .engines import build_engine

    engine = build_engine(settings.engine, settings)
    service = JobService(
        output_root=settings.output_root,
        engine=engine,
        max_videos=settings.max_videos,
        max_outfits=settings.max_outfits,
    )
    session_store = TelegramSessionStore(settings.output_root / "_telegram" / "sessions")
    return TelegramBot(
        client=TelegramHTTPClient(token),
        service=service,
        session_store=session_store,
        allowed_chat_ids=allowed,
        poll_timeout=poll_timeout,
    )
