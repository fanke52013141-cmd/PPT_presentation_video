"""Process-local serialized publication of voice references with rollback on metadata failure."""

from pathlib import Path
import math
import threading
import uuid

import model_connection_service as connections
from model_connection_models import ModelConnectionUpdate


_PUBLISH_LOCK = threading.Lock()
_AUDIO_SUFFIXES = {".wav", ".mp3", ".pcm", ".ogg"}


def validate_reference_connection(connection):
    revision = connection.get("revision") or {}
    if connection.get("kind") != "tts" or revision.get("provider") not in {"volcengine_seed_audio", "comfyui_tts"}:
        raise ValueError("仅豆包音频生成 1.0 或 ComfyUI / IndexTTS 模型可以上传参考音频")
    return revision


def publish_reference_audio(connection_id, filename, content, root, *, probe):
    """Bounded HTTP reading stays in the adapter; this service owns file publication.

    A failed metadata write restores old audio byte-for-byte. The shared lock
    prevents two uploads from overwriting each other's pending files or backup.
    """
    suffix = Path(filename).suffix.lower()
    if not connection_id or "/" in connection_id or "\\" in connection_id or connection_id in {".", ".."}:
        raise ValueError("模型连接 ID 无效")
    if suffix not in _AUDIO_SUFFIXES:
        raise ValueError("参考音频仅支持 wav、mp3、pcm 或 ogg 格式")
    # Validate identity before deriving any path.
    validate_reference_connection(connections.get_model_connection(connection_id))
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{connection_id}{suffix}"
    pending = root / f"{connection_id}.{uuid.uuid4().hex}.upload{suffix}"
    try:
        pending.write_bytes(content)
        duration = probe(pending)
        if duration is None or not math.isfinite(duration) or duration <= 0:
            raise ValueError("参考音频无法解码，请重新上传有效音频")
        if duration > 30:
            raise ValueError("参考音频不能超过 30 秒")
        with _PUBLISH_LOCK:
            revision = validate_reference_connection(connections.get_model_connection(connection_id))
            previous = []
            published = False
            try:
                for existing in root.glob(f"{connection_id}.*"):
                    if existing.suffix.lower() not in _AUDIO_SUFFIXES or existing.stem != connection_id:
                        continue
                    backup = root / (existing.name + "." + uuid.uuid4().hex + ".rollback")
                    existing.replace(backup)
                    previous.append((existing, backup))
                pending.replace(target)
                published = True
                config = dict(revision.get("public_config") or {})
                config["clone_voice_id"] = f"data/model_voice_references/{target.name}"
                updated = connections.update_model_connection(connection_id, ModelConnectionUpdate(public_config=config))
            except Exception:
                if published:
                    target.unlink(missing_ok=True)
                for original, backup in previous:
                    backup.replace(original)
                raise
            for _original, backup in previous:
                backup.unlink(missing_ok=True)
        return {"connection": updated, "reference_audio": {
            "name": filename, "size": len(content), "duration_sec": round(duration, 3)}}
    finally:
        pending.unlink(missing_ok=True)
