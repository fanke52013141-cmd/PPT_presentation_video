#!/usr/bin/env python3
"""Provider-neutral TTS helper for slide audio generation.

The script keeps the project's downstream contract stable:

- out audio file
- metadata JSON
- optional SRT
- audio_timeline.json

MiniMax is delegated to the mature `minimax_tts.py` implementation. Additional
providers are implemented here behind the same CLI contract.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import httpx

try:
    from scripts.minimax_tts import (
        build_segments,
        format_srt_time,
        normalize_tts_markup,
        strip_tts_markup,
    )
except ModuleNotFoundError:
    from minimax_tts import build_segments, format_srt_time, normalize_tts_markup, strip_tts_markup


DEFAULT_MAX_SUBTITLE_CHARS = 26


class TtsError(RuntimeError):
    pass


def read_text(args: argparse.Namespace) -> str:
    if args.text:
        return args.text.strip()
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8").strip()
    raise TtsError("Either --text or --text-file is required.")


def read_subtitle_text(args: argparse.Namespace, tts_text: str) -> str:
    if args.subtitle_text_file:
        return Path(args.subtitle_text_file).read_text(encoding="utf-8").strip()
    if args.subtitle_text:
        return args.subtitle_text.strip()
    return strip_tts_markup(tts_text)


def read_provider_extra(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise TtsError(f"--provider-extra must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TtsError("--provider-extra must be a JSON object")
    return parsed


def endpoint_url(endpoint: str, provider: str) -> str:
    endpoint = str(endpoint or "").strip()
    if provider == "aliyun_cosyvoice":
        if not endpoint or endpoint.rstrip("/") == "https://dashscope.aliyuncs.com/api/v1":
            return "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
        if endpoint.rstrip("/").endswith("/services/audio/tts/SpeechSynthesizer"):
            return endpoint
        return endpoint.rstrip("/") + "/services/audio/tts/SpeechSynthesizer"
    return endpoint


def download_url(url: str, headers: dict[str, str] | None = None, timeout: int = 300) -> bytes:
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
        response = client.get(url, headers=headers or {})
        response.raise_for_status()
        return response.content


def decode_audio_value(value: Any, headers: dict[str, str] | None = None, timeout: int = 300) -> bytes:
    if isinstance(value, bytes):
        return value
    if not isinstance(value, str) or not value.strip():
        raise TtsError("Provider response did not include audio content")
    text = value.strip()
    if text.startswith(("http://", "https://")):
        return download_url(text, headers=headers, timeout=timeout)
    try:
        return base64.b64decode(text)
    except Exception as base64_error:
        try:
            return bytes.fromhex(text)
        except ValueError as hex_error:
            error = TtsError("Audio field is neither URL, base64 nor hex")
            error.__context__ = base64_error
            raise error from hex_error


def estimate_duration_sec(text: str) -> float:
    clean = strip_tts_markup(text)
    chinese_chars = len([ch for ch in clean if "\u4e00" <= ch <= "\u9fff"])
    latin_words = len([part for part in clean.split() if part])
    return max(1.0, chinese_chars / 4.2 + latin_words / 2.8)


def write_json(path: Path | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_srt(segments: list[dict[str, Any]], out_srt: Path | None) -> None:
    if not out_srt:
        return
    out_srt.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_time(float(segment['start']))} --> {format_srt_time(float(segment['end']))}",
                    str(segment["text"]),
                ]
            )
        )
    out_srt.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_common_outputs(
    *,
    args: argparse.Namespace,
    provider: str,
    response_json: dict[str, Any],
    audio_bytes: bytes,
    subtitle_text: str,
    duration_sec: float | None = None,
) -> None:
    out_audio = Path(args.out_audio)
    out_audio.parent.mkdir(parents=True, exist_ok=True)
    out_audio.write_bytes(audio_bytes)

    duration = float(duration_sec or 0) if duration_sec else estimate_duration_sec(subtitle_text)
    segments = build_segments(
        subtitle_text,
        duration,
        args.slide_id,
        "estimated",
        args.max_subtitle_chars,
    )
    timeline = {
        "slide_id": args.slide_id,
        "audio_file": str(out_audio).replace("\\", "/"),
        "duration_sec": round(duration, 3),
        "timing_source": "estimated",
        "subtitle_display": {"max_lines": 1, "max_cjk_chars": args.max_subtitle_chars},
        "segments": segments,
    }
    write_json(Path(args.out_timeline) if args.out_timeline else None, timeline)
    write_srt(segments, Path(args.out_srt) if args.out_srt else None)
    write_json(
        Path(args.out_meta) if args.out_meta else None,
        {
            "provider": provider,
            "request": {
                "endpoint": args.endpoint,
                "model": args.model,
                "voice_id": args.voice_id,
                "clone_voice_id": args.clone_voice_id,
                "audio_format": args.audio_format,
                "sample_rate": args.sample_rate,
                "speed": args.speed,
                "volume": args.volume,
                "pitch": args.pitch,
            },
            "response": response_json,
            "tts_text_has_markup": args._tts_text != subtitle_text,
        },
    )
    print(json.dumps({"audio": str(out_audio), "duration_sec": round(duration, 3), "provider": provider}, ensure_ascii=False))


def run_minimax(args: argparse.Namespace) -> int:
    script = Path(__file__).resolve().with_name("minimax_tts.py")
    cmd = [
        sys.executable,
        str(script),
        "--out-audio",
        args.out_audio,
        "--slide-id",
        args.slide_id,
        "--endpoint",
        args.endpoint,
        "--model",
        args.model,
        "--voice-id",
        args.clone_voice_id or args.voice_id,
        "--speed",
        str(args.speed),
        "--volume",
        str(args.volume),
        "--pitch",
        str(int(float(args.pitch))),
        "--audio-format",
        args.audio_format,
        "--sample-rate",
        str(args.sample_rate),
        "--bitrate",
        str(args.bitrate),
        "--channel",
        str(args.channel),
        "--max-subtitle-chars",
        str(args.max_subtitle_chars),
        "--timeout",
        str(args.timeout),
    ]
    if args.text_file:
        cmd.extend(["--text-file", args.text_file])
    else:
        cmd.extend(["--text", args.text or ""])
    if args.subtitle_text_file:
        cmd.extend(["--subtitle-text-file", args.subtitle_text_file])
    elif args.subtitle_text:
        cmd.extend(["--subtitle-text", args.subtitle_text])
    if args.out_meta:
        cmd.extend(["--out-meta", args.out_meta])
    if args.out_srt:
        cmd.extend(["--out-srt", args.out_srt])
    if args.out_timeline:
        cmd.extend(["--out-timeline", args.out_timeline])
    if args.out_tts_text:
        cmd.extend(["--out-tts-text", args.out_tts_text])
    if args.emotion:
        cmd.extend(["--emotion", args.emotion])
    if args.language_boost:
        cmd.extend(["--language-boost", args.language_boost])
    if args.api_key:
        cmd.extend(["--api-key", args.api_key])
    result = subprocess.run(cmd, text=True)
    return result.returncode


def synthesize_aliyun(args: argparse.Namespace, tts_text: str, subtitle_text: str) -> None:
    if not args.api_key:
        raise TtsError("DASHSCOPE API key is required for aliyun_cosyvoice")
    url = endpoint_url(args.endpoint, "aliyun_cosyvoice")
    input_payload: dict[str, Any] = {
        "text": strip_tts_markup(tts_text),
        "voice": args.clone_voice_id or args.voice_id,
        "format": args.audio_format,
        "sample_rate": args.sample_rate,
        "volume": max(0, min(100, int(round(float(args.volume) * 50)))),
        "rate": float(args.speed),
    }
    if args.pitch:
        try:
            pitch_value = float(args.pitch)
            input_payload["pitch"] = pitch_value if pitch_value > 0 else 1.0
        except ValueError:
            pass
    if args.instruction:
        input_payload["instruction"] = args.instruction
    if args.language_boost:
        input_payload["language_hints"] = [args.language_boost]
    extra = read_provider_extra(args.provider_extra)
    input_payload.update(extra.get("input", {}) if isinstance(extra.get("input"), dict) else {})
    payload = {"model": args.model, "input": input_payload}
    payload.update(extra.get("request", {}) if isinstance(extra.get("request"), dict) else {})
    with httpx.Client(timeout=args.timeout, trust_env=False) as client:
        response = client.post(
            url,
            headers={"Authorization": f"Bearer {args.api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 400:
        raise TtsError(f"Aliyun CosyVoice HTTP {response.status_code}: {response.text[:800]}")
    data = response.json()
    audio = (((data.get("output") or {}).get("audio") or {}) if isinstance(data, dict) else {})
    audio_bytes = decode_audio_value(audio.get("url") or audio.get("data"), timeout=args.timeout)
    write_common_outputs(
        args=args,
        provider="aliyun_cosyvoice",
        response_json=data,
        audio_bytes=audio_bytes,
        subtitle_text=subtitle_text,
    )


def sign_tencent(secret_key: str, date: str, service: str, canonical_request: str, timestamp: int) -> tuple[str, str]:
    algorithm = "TC3-HMAC-SHA256"
    hashed_request_payload = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join([algorithm, str(timestamp), credential_scope, hashed_request_payload])
    secret_date = hmac.new(("TC3" + secret_key).encode("utf-8"), date.encode("utf-8"), hashlib.sha256).digest()
    secret_service = hmac.new(secret_date, service.encode("utf-8"), hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return credential_scope, signature


def synthesize_tencent(args: argparse.Namespace, tts_text: str, subtitle_text: str) -> None:
    secret_id = args.api_key or os.getenv("TENCENTCLOUD_SECRET_ID", "")
    secret_key = args.secret_key or os.getenv("TENCENTCLOUD_SECRET_KEY", "")
    if not secret_id or not secret_key:
        raise TtsError("Tencent Cloud SecretId and SecretKey are required")
    endpoint = args.endpoint or "https://tts.tencentcloudapi.com"
    host = urllib.parse.urlparse(endpoint).netloc or "tts.tencentcloudapi.com"
    service = "tts"
    timestamp = int(time.time())
    date = dt.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
    voice_id = str(args.voice_id or "101001").strip()
    payload: dict[str, Any] = {
        "Text": strip_tts_markup(tts_text),
        "SessionId": args.slide_id + "-" + uuid.uuid4().hex[:10],
        "Volume": max(-10.0, min(10.0, (float(args.volume) - 1.0) * 10.0)),
        "Speed": float(args.speed),
        "ProjectId": 0,
        "ModelType": int(float(args.model or 1)),
        "PrimaryLanguage": 1,
        "SampleRate": int(args.sample_rate),
        "Codec": args.audio_format,
        "EnableSubtitle": False,
    }
    if args.clone_voice_id:
        payload["VoiceType"] = 200000000
        payload["FastVoiceType"] = args.clone_voice_id
    elif voice_id:
        try:
            payload["VoiceType"] = int(voice_id)
        except ValueError:
            payload["VoiceType"] = 200000000
            payload["FastVoiceType"] = voice_id
    extra = read_provider_extra(args.provider_extra)
    payload.update(extra.get("request", {}) if isinstance(extra.get("request"), dict) else {})
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{host}\n"
    signed_headers = "content-type;host"
    hashed_payload = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    canonical_request = "\n".join(["POST", "/", "", canonical_headers, signed_headers, hashed_payload])
    credential_scope, signature = sign_tencent(secret_key, date, service, canonical_request, timestamp)
    authorization = (
        "TC3-HMAC-SHA256 "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-TC-Action": "TextToVoice",
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": "2019-08-23",
    }
    if args.region:
        headers["X-TC-Region"] = args.region
    with httpx.Client(timeout=args.timeout, trust_env=False) as client:
        response = client.post(endpoint, headers=headers, content=payload_json.encode("utf-8"))
    if response.status_code >= 400:
        raise TtsError(f"Tencent TTS HTTP {response.status_code}: {response.text[:800]}")
    data = response.json()
    response_data = data.get("Response") if isinstance(data, dict) else {}
    if isinstance(response_data, dict) and response_data.get("Error"):
        raise TtsError(f"Tencent TTS error: {json.dumps(response_data['Error'], ensure_ascii=False)}")
    audio_bytes = decode_audio_value((response_data or {}).get("Audio"), timeout=args.timeout)
    write_common_outputs(
        args=args,
        provider="tencent_tts",
        response_json=data,
        audio_bytes=audio_bytes,
        subtitle_text=subtitle_text,
    )


def synthesize_volcengine(args: argparse.Namespace, tts_text: str, subtitle_text: str) -> None:
    token = args.api_key or os.getenv("VOLCENGINE_TTS_TOKEN", "")
    if not token:
        raise TtsError("Volcengine TTS token is required")
    extra = read_provider_extra(args.provider_extra)
    appid = str(extra.get("appid") or os.getenv("VOLCENGINE_TTS_APPID", "")).strip()
    cluster = str(extra.get("cluster") or os.getenv("VOLCENGINE_TTS_CLUSTER", "volcano_tts")).strip()
    if not appid:
        raise TtsError("Volcengine provider_extra.appid or VOLCENGINE_TTS_APPID is required")
    endpoint = args.endpoint or "https://openspeech.bytedance.com/api/v1/tts"
    payload = {
        "app": {"appid": appid, "token": token, "cluster": cluster},
        "user": {"uid": str(extra.get("uid") or "ppt-presentation-video")},
        "audio": {
            "voice_type": args.clone_voice_id or args.voice_id,
            "encoding": args.audio_format,
            "speed_ratio": float(args.speed),
            "volume_ratio": float(args.volume),
            "pitch_ratio": float(args.pitch) if str(args.pitch).strip() else 1.0,
            "rate": int(args.sample_rate),
        },
        "request": {
            "reqid": uuid.uuid4().hex,
            "text": strip_tts_markup(tts_text),
            "text_type": "plain",
            "operation": "query",
        },
    }
    payload.update(extra.get("payload", {}) if isinstance(extra.get("payload"), dict) else {})
    headers = {"Authorization": f"Bearer;{token}", "Content-Type": "application/json"}
    resource_id = str(extra.get("resource_id") or "").strip()
    if resource_id:
        headers["X-Api-Resource-Id"] = resource_id
    with httpx.Client(timeout=args.timeout, trust_env=False) as client:
        response = client.post(endpoint, headers=headers, json=payload)
    if response.status_code >= 400:
        raise TtsError(f"Volcengine TTS HTTP {response.status_code}: {response.text[:800]}")
    data = response.json()
    audio_value = data.get("data") or data.get("audio") or ((data.get("result") or {}).get("audio") if isinstance(data.get("result"), dict) else None)
    audio_bytes = decode_audio_value(audio_value, timeout=args.timeout)
    write_common_outputs(
        args=args,
        provider="volcengine_seed",
        response_json=data,
        audio_bytes=audio_bytes,
        subtitle_text=subtitle_text,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate TTS audio with a configurable provider.")
    parser.add_argument("--provider", default=os.getenv("TTS_PROVIDER", "minimax"))
    parser.add_argument("--text")
    parser.add_argument("--text-file")
    parser.add_argument("--subtitle-text")
    parser.add_argument("--subtitle-text-file")
    parser.add_argument("--out-tts-text")
    parser.add_argument("--out-audio", required=True)
    parser.add_argument("--out-meta")
    parser.add_argument("--out-srt")
    parser.add_argument("--out-timeline")
    parser.add_argument("--slide-id", default="slide_001")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--secret-key", default="")
    parser.add_argument("--region", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--voice-id", default="")
    parser.add_argument("--clone-voice-id", default="")
    parser.add_argument("--provider-extra", default="")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--emotion", default="calm")
    parser.add_argument("--language-boost", default="zh")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--volume", type=float, default=1.0)
    parser.add_argument("--pitch", default="1.0")
    parser.add_argument("--audio-format", default="mp3", choices=["mp3", "wav", "pcm", "opus", "flac"])
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--bitrate", type=int, default=128000)
    parser.add_argument("--channel", type=int, default=1)
    parser.add_argument("--max-subtitle-chars", type=int, default=DEFAULT_MAX_SUBTITLE_CHARS)
    parser.add_argument("--timeout", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    provider = str(args.provider or "minimax").strip().lower()
    if provider == "doubao":
        provider = "volcengine_seed"
    if provider in {"aliyun", "dashscope", "cosyvoice"}:
        provider = "aliyun_cosyvoice"
    if provider in {"tencent"}:
        provider = "tencent_tts"

    if provider == "minimax":
        return run_minimax(args)

    tts_text = normalize_tts_markup(read_text(args))
    subtitle_text = strip_tts_markup(read_subtitle_text(args, tts_text))
    if not tts_text:
        raise TtsError("Input text is empty")
    args._tts_text = tts_text
    if args.out_tts_text:
        Path(args.out_tts_text).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_tts_text).write_text(tts_text + "\n", encoding="utf-8")

    if provider == "aliyun_cosyvoice":
        synthesize_aliyun(args, tts_text, subtitle_text)
    elif provider == "tencent_tts":
        synthesize_tencent(args, tts_text, subtitle_text)
    elif provider == "volcengine_seed":
        synthesize_volcengine(args, tts_text, subtitle_text)
    else:
        raise TtsError(f"Unsupported TTS provider: {args.provider}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TtsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
