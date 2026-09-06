"""Hardware video-encoder capability detection and selection.

The helpers in this module deliberately only inspect ffmpeg's advertised
encoders.  They do not assume that a GPU reported by the operating system is
usable by the ffmpeg binary bundled with the application.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


ACCELERATION_MODES = frozenset({"auto", "gpu", "cpu"})


@dataclass(frozen=True)
class VideoEncoderSelection:
    """The encoder selected for an optional ffmpeg re-encode stage."""

    encoder: str
    mode: str
    hardware: bool
    fallback_reason: str | None = None


_HARDWARE_ENCODERS = (
    ("h264_nvenc", "nvidia"),
    ("h264_qsv", "intel"),
    ("h264_amf", "amd"),
)


def normalize_render_acceleration(value: object) -> str:
    """Return a stable acceleration mode for persisted or environment config."""

    mode = str(value or "auto").strip().lower()
    return mode if mode in ACCELERATION_MODES else "auto"


def parse_ffmpeg_video_encoders(output: object) -> frozenset[str]:
    """Extract the supported H.264 encoder names from ``ffmpeg -encoders``.

    ffmpeg formats this output in columns whose flag prefix differs slightly
    among releases, so matching the encoder token itself is more robust than
    parsing column offsets.
    """

    text = str(output or "")
    advertised = set(re.findall(r"\bh264_(?:nvenc|qsv|amf)\b", text))
    if re.search(r"\blibx264\b", text):
        advertised.add("libx264")
    return frozenset(advertised)


def select_video_encoder(
    acceleration: object,
    available_encoders: Iterable[str],
) -> VideoEncoderSelection:
    """Choose a video encoder without touching the host's hardware.

    ``gpu`` is intentionally strict during capability selection: callers get a
    clear error before beginning an expensive render if ffmpeg exposes no
    supported hardware H.264 encoder.  Runtime encoding failures can still be
    retried with CPU by the renderer to preserve a usable output.
    """

    mode = normalize_render_acceleration(acceleration)
    available = {str(item).strip().lower() for item in available_encoders}
    if mode == "cpu":
        return VideoEncoderSelection("libx264", mode, False)
    for encoder, _vendor in _HARDWARE_ENCODERS:
        if encoder in available:
            return VideoEncoderSelection(encoder, mode, True)
    if mode == "gpu":
        raise RuntimeError(
            "GPU 编码不可用：当前 FFmpeg 未提供 h264_nvenc、"
            "h264_qsv 或 h264_amf 编码器。"
        )
    return VideoEncoderSelection(
        "libx264",
        mode,
        False,
        fallback_reason="hardware_h264_encoder_not_advertised",
    )


def encoder_reencode_arguments(encoder: str) -> list[str]:
    """Return conservative quality settings for a selected H.264 encoder."""

    if encoder == "h264_nvenc":
        return ["-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    if encoder == "h264_qsv":
        return ["-global_quality", "18"]
    if encoder == "h264_amf":
        return ["-quality", "balanced", "-rc", "cqp", "-qp_i", "18", "-qp_p", "20"]
    return ["-preset", "veryfast", "-crf", "18"]
