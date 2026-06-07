#!/usr/bin/env python3
"""
MiniMax TTS helper for the article-to-video workflow.

The script uses the synchronous T2A HTTP endpoint and writes:
- audio file
- response metadata
- SRT subtitles
- audio_timeline.json

The TTS input may contain MiniMax pause/expression markup. Subtitle output is
built from clean text so control markup never appears on screen.
"""

from __future__ import annotations

import argparse
import binascii
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_ENDPOINT = "https://api.minimaxi.com/v1/t2a_v2"
DEFAULT_MODEL = "speech-2.8-hd"
DEFAULT_VOICE_ID = "Chinese (Mandarin)_Soft_Girl"
DEFAULT_MAX_SUBTITLE_CHARS = 28
ALLOWED_EXPRESSION_TAGS = {"(breath)", "(emm)", "(chuckle)", "(laughs)", "(sighs)"}
PAUSE_RE = re.compile(r"<#\d+(?:\.\d{1,2})?#>")
EXPRESSION_RE = re.compile(r"\([A-Za-z-]+\)")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def read_text(args: argparse.Namespace) -> str:
    if args.text:
        return args.text.strip()
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8").strip()
    raise SystemExit("Either --text or --text-file is required.")


def read_subtitle_text(args: argparse.Namespace, tts_text: str) -> str:
    if args.subtitle_text_file:
        return Path(args.subtitle_text_file).read_text(encoding="utf-8").strip()
    if args.subtitle_text:
        return args.subtitle_text.strip()
    return strip_tts_markup(tts_text)


def strip_tts_markup(text: str) -> str:
    text = PAUSE_RE.sub(" ", text)
    text = EXPRESSION_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_tts_markup(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(<#\d+(?:\.\d{1,2})?#>\s*){2,}", lambda m: PAUSE_RE.search(m.group(0)).group(0) + " ", text)

    # Remove boundary pause/expression tags. They sound unnatural in this workflow.
    text = re.sub(r"^(?:\s*(?:<#\d+(?:\.\d{1,2})?#>|\([A-Za-z-]+\))\s*)+", "", text).strip()
    text = re.sub(r"(?:\s*(?:<#\d+(?:\.\d{1,2})?#>|\([A-Za-z-]+\))\s*)+$", "", text).strip()

    # Keep only expression tags allowed by this project; remove other supported-but-unsuitable tags.
    def keep_or_remove(match: re.Match[str]) -> str:
        tag = match.group(0)
        return tag if tag in ALLOWED_EXPRESSION_TAGS else " "

    text = EXPRESSION_RE.sub(keep_or_remove, text)
    return re.sub(r"\s+", " ", text).strip()


def call_minimax_tts(payload: dict[str, Any], endpoint: str, api_key: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MiniMax HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MiniMax request failed: {exc}") from exc


def write_audio(response_json: dict[str, Any], out_audio: Path) -> None:
    data = response_json.get("data") or {}
    audio = data.get("audio")
    if not audio:
        raise RuntimeError(f"MiniMax response did not include data.audio: {json.dumps(response_json, ensure_ascii=False)[:800]}")

    out_audio.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(audio, str) and audio.startswith(("http://", "https://")):
        with urllib.request.urlopen(audio, timeout=120) as response:
            out_audio.write_bytes(response.read())
        return

    try:
        out_audio.write_bytes(binascii.unhexlify(audio))
    except (binascii.Error, TypeError) as exc:
        raise RuntimeError("MiniMax audio field is neither URL nor valid hex.") from exc


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", strip_tts_markup(text)).strip()
    parts = re.split(r"(?<=[。！？!?；;])\s*", normalized)
    sentences = [part.strip() for part in parts if part.strip()]
    if sentences:
        return sentences
    return [normalized] if normalized else []


def split_subtitle_chunks(sentence: str, max_chars: int = DEFAULT_MAX_SUBTITLE_CHARS) -> list[str]:
    sentence = sentence.strip()
    if not sentence:
        return []
    if len(sentence) <= max_chars:
        return [sentence]

    soft_marks = ["，", "、", "：", "；", ",", ":"]
    chunks: list[str] = []
    current = ""

    for char in sentence:
        current += char
        if len(current) >= max_chars:
            cut_index = max([current.rfind(mark) for mark in soft_marks] + [-1])
            if cut_index > 8:
                chunks.append(current[: cut_index + 1].strip())
                current = current[cut_index + 1 :].strip()
            else:
                chunks.append(current.strip())
                current = ""

    if current:
        chunks.append(current.strip())

    return [chunk for chunk in chunks if chunk]


def split_subtitles(text: str, max_chars: int) -> list[str]:
    chunks: list[str] = []
    for sentence in split_sentences(text):
        chunks.extend(split_subtitle_chunks(sentence, max_chars=max_chars))
    return chunks


def duration_from_response(response_json: dict[str, Any], text: str) -> float:
    extra = response_json.get("extra_info") or {}
    raw = extra.get("audio_length")
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw) / 1000.0 if raw > 1000 else float(raw)
    clean = strip_tts_markup(text)
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", clean))
    latin_words = len(re.findall(r"[A-Za-z0-9]+", clean))
    return max(1.0, chinese_chars / 4.2 + latin_words / 2.8)


def build_segments(text: str, duration_sec: float, slide_id: str, timing_source: str, max_subtitle_chars: int) -> list[dict[str, Any]]:
    chunks = split_subtitles(text, max_subtitle_chars)
    if not chunks:
        return []
    weights = [max(1, len(chunk)) for chunk in chunks]
    total_weight = sum(weights)
    cursor = 0.0
    segments: list[dict[str, Any]] = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights), start=1):
        segment_duration = duration_sec * weight / total_weight
        end = duration_sec if index == len(chunks) else cursor + segment_duration
        segments.append(
            {
                "id": f"{slide_id}_seg_{index:03d}",
                "start": round(cursor, 3),
                "end": round(end, 3),
                "text": chunk,
                "timing_source": timing_source,
                "max_cjk_chars": max_subtitle_chars,
                "max_lines": 1,
            }
        )
        cursor = end
    return segments


def format_srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, remainder = divmod(millis, 3600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def write_srt(segments: list[dict[str, Any]], out_srt: Path) -> None:
    out_srt.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_time(segment['start'])} --> {format_srt_time(segment['end'])}",
                    segment["text"],
                ]
            )
        )
    out_srt.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_payload(args: argparse.Namespace, text: str) -> dict[str, Any]:
    voice_setting: dict[str, Any] = {
        "voice_id": args.voice_id,
        "speed": args.speed,
        "vol": args.volume,
        "pitch": args.pitch,
    }
    if args.emotion:
        voice_setting["emotion"] = args.emotion

    return {
        "model": args.model,
        "text": text,
        "stream": False,
        "language_boost": args.language_boost,
        "output_format": "hex",
        "subtitle_enable": args.subtitle_enable,
        "subtitle_type": args.subtitle_type,
        "voice_setting": voice_setting,
        "audio_setting": {
            "sample_rate": args.sample_rate,
            "bitrate": args.bitrate,
            "format": args.audio_format,
            "channel": args.channel,
        },
    }


def parse_args() -> argparse.Namespace:
    load_dotenv(Path(".env"))
    parser = argparse.ArgumentParser(description="Generate TTS audio with MiniMax.")
    parser.add_argument("--text", help="Narration text, optionally with MiniMax markup.")
    parser.add_argument("--text-file", help="Path to TTS text file, optionally with MiniMax markup.")
    parser.add_argument("--subtitle-text", help="Clean narration text for subtitles.")
    parser.add_argument("--subtitle-text-file", help="Path to clean narration text for subtitles.")
    parser.add_argument("--out-tts-text", help="Output normalized TTS input text path.")
    parser.add_argument("--out-audio", required=True, help="Output audio path, usually voice.mp3.")
    parser.add_argument("--out-meta", help="Output MiniMax response metadata JSON path.")
    parser.add_argument("--out-srt", help="Output SRT subtitle path.")
    parser.add_argument("--out-timeline", help="Output audio_timeline.json path.")
    parser.add_argument("--slide-id", default="slide_001", help="Slide id for timeline segment ids.")
    parser.add_argument("--max-subtitle-chars", type=int, default=DEFAULT_MAX_SUBTITLE_CHARS, help="Maximum CJK characters per subtitle segment.")
    parser.add_argument("--endpoint", default=os.getenv("MINIMAX_TTS_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--api-key", default=os.getenv("MINIMAX_API_KEY"))
    parser.add_argument("--model", default=os.getenv("MINIMAX_TTS_MODEL", DEFAULT_MODEL))
    parser.add_argument("--voice-id", default=os.getenv("MINIMAX_TTS_VOICE_ID", DEFAULT_VOICE_ID))
    parser.add_argument("--emotion", default=os.getenv("MINIMAX_TTS_EMOTION", "calm"))
    parser.add_argument("--language-boost", default=os.getenv("MINIMAX_TTS_LANGUAGE_BOOST", "Chinese"))
    parser.add_argument("--speed", type=float, default=env_float("MINIMAX_TTS_SPEED", 1.0))
    parser.add_argument("--volume", type=float, default=env_float("MINIMAX_TTS_VOLUME", 1.0))
    parser.add_argument("--pitch", type=int, default=env_int("MINIMAX_TTS_PITCH", 0))
    parser.add_argument("--audio-format", default="mp3", choices=["mp3", "wav", "flac"])
    parser.add_argument("--sample-rate", type=int, default=32000)
    parser.add_argument("--bitrate", type=int, default=128000)
    parser.add_argument("--channel", type=int, default=1)
    parser.add_argument("--subtitle-enable", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--subtitle-type", default="sentence", choices=["sentence", "word"])
    parser.add_argument("--timeout", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.api_key:
        print("MINIMAX_API_KEY is required. Set it in .env or environment variables.", file=sys.stderr)
        return 2

    tts_text = normalize_tts_markup(read_text(args))
    subtitle_text = strip_tts_markup(read_subtitle_text(args, tts_text))
    if not tts_text:
        print("Input text is empty.", file=sys.stderr)
        return 2
    if len(tts_text) >= 10000:
        print("Input text must be less than 10,000 characters for MiniMax HTTP T2A.", file=sys.stderr)
        return 2

    if args.out_tts_text:
        Path(args.out_tts_text).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_tts_text).write_text(tts_text + "\n", encoding="utf-8")

    payload = build_payload(args, tts_text)
    response_json = call_minimax_tts(payload, args.endpoint, args.api_key, args.timeout)

    base_resp = response_json.get("base_resp") or {}
    if base_resp.get("status_code", 0) not in (0, "0", None):
        raise RuntimeError(f"MiniMax error: {json.dumps(base_resp, ensure_ascii=False)}")

    out_audio = Path(args.out_audio)
    write_audio(response_json, out_audio)

    duration_sec = duration_from_response(response_json, subtitle_text)
    segments = build_segments(subtitle_text, duration_sec, args.slide_id, "estimated", args.max_subtitle_chars)
    timeline = {
        "slide_id": args.slide_id,
        "audio_file": str(out_audio).replace("\\", "/"),
        "duration_sec": round(duration_sec, 3),
        "timing_source": "estimated",
        "subtitle_display": {"max_lines": 1, "max_cjk_chars": args.max_subtitle_chars},
        "segments": segments,
    }

    if args.out_meta:
        meta = {
            "trace_id": response_json.get("trace_id"),
            "base_resp": response_json.get("base_resp"),
            "extra_info": response_json.get("extra_info"),
            "request": {
                "endpoint": args.endpoint,
                "model": args.model,
                "voice_id": args.voice_id,
                "emotion": args.emotion,
                "language_boost": args.language_boost,
                "audio_format": args.audio_format,
                "sample_rate": args.sample_rate,
                "bitrate": args.bitrate,
                "channel": args.channel,
                "max_subtitle_chars": args.max_subtitle_chars,
            },
            "tts_text_has_markup": tts_text != subtitle_text,
        }
        write_json(Path(args.out_meta), meta)

    if args.out_srt:
        write_srt(segments, Path(args.out_srt))

    if args.out_timeline:
        write_json(Path(args.out_timeline), timeline)

    print(json.dumps({"audio": str(out_audio), "duration_sec": round(duration_sec, 3)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
