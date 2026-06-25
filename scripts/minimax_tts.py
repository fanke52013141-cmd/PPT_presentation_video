#!/usr/bin/env python3
"""
MiniMax TTS helper for the article-to-video workflow.

The script supports synchronous T2A HTTP and asynchronous T2A endpoints, and writes:
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
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import httpx


DEFAULT_ENDPOINT = "https://api.minimaxi.com/v1/t2a_async_v2"
DEFAULT_MODEL = "speech-2.8-hd"
DEFAULT_VOICE_ID = "Chinese (Mandarin)_Soft_Girl"
DEFAULT_MAX_SUBTITLE_CHARS = 26
ALLOWED_EXPRESSION_TAGS = {
    "(applause)",
    "(breath)",
    "(burps)",
    "(chuckle)",
    "(clear-throat)",
    "(coughs)",
    "(crying)",
    "(emm)",
    "(exhale)",
    "(gasps)",
    "(groans)",
    "(hissing)",
    "(humming)",
    "(inhale)",
    "(laughs)",
    "(lip-smacking)",
    "(pant)",
    "(sighs)",
    "(sneezes)",
    "(sniffs)",
    "(snorts)",
    "(whistles)",
}
PAUSE_RE = re.compile(r"<#\d+(?:\.\d{1,2})?#>")
EXPRESSION_RE = re.compile(r"\([A-Za-z-]+\)")
SENTENCE_END_RE = re.compile(r"(?<=[\u3002\uff01\uff1f!?；;])\s*")
HARD_SUBTITLE_MARKS = ["\u3002", "\uff01", "\uff1f", "!", "?", "\uff1b", ";"]
SOFT_SUBTITLE_MARKS = ["\uff0c", "\u3001", "\uff1a", ",", ":"]
SUBTITLE_EDGE_PUNCTUATION = "\uff0c\u3002\uff01\uff1f\uff1b\uff1a\u3001,.!?;: \t\r\n"
DEFAULT_HTTP_RETRIES = 3
RETRIABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def retry_delay_sec(attempt: int) -> float:
    return min(2.0 * attempt, 8.0)


def retry_notice(purpose: str, attempt: int, attempts: int, error: Any) -> None:
    print(
        f"Warning: MiniMax {purpose} attempt {attempt}/{attempts} failed: {error}; retrying...",
        file=sys.stderr,
    )


def request_bytes_with_retry(
    request: urllib.request.Request,
    *,
    timeout: int,
    purpose: str,
    attempts: int = DEFAULT_HTTP_RETRIES,
) -> bytes:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = f"MiniMax {purpose} HTTP {exc.code}: {body[:800]}"
            if exc.code in RETRIABLE_HTTP_STATUS and attempt < attempts:
                retry_notice(purpose, attempt, attempts, message)
                time.sleep(retry_delay_sec(attempt))
                continue
            raise RuntimeError(message) from exc
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            if attempt < attempts:
                retry_notice(purpose, attempt, attempts, exc)
                time.sleep(retry_delay_sec(attempt))
                continue
            raise RuntimeError(f"MiniMax {purpose} failed after {attempts} attempts: {exc}") from exc
    raise RuntimeError(f"MiniMax {purpose} failed after {attempts} attempts")


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
    body = request_bytes_with_retry(request, timeout=timeout, purpose="request").decode("utf-8")
    return json.loads(body)


def is_async_endpoint(endpoint: str) -> bool:
    return "t2a_async_v2" in urllib.parse.urlparse(endpoint).path


def upload_minimax_text_file(text: str, endpoint: str, api_key: str, timeout: int) -> str:
    parsed = urllib.parse.urlparse(endpoint)
    upload_url = urllib.parse.urlunparse(parsed._replace(path="/v1/files/upload", query=""))
    response = None
    for attempt in range(1, DEFAULT_HTTP_RETRIES + 1):
        try:
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                response = client.post(
                    upload_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    data={"purpose": "t2a_async_input"},
                    files={"file": ("tts_input.txt", text.encode("utf-8"), "text/plain")},
                )
            if response.status_code == 200:
                break
            message = f"MiniMax text upload HTTP {response.status_code}: {response.text[:800]}"
            if response.status_code in RETRIABLE_HTTP_STATUS and attempt < DEFAULT_HTTP_RETRIES:
                retry_notice("text upload", attempt, DEFAULT_HTTP_RETRIES, message)
                time.sleep(retry_delay_sec(attempt))
                continue
            raise RuntimeError(message)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt < DEFAULT_HTTP_RETRIES:
                retry_notice("text upload", attempt, DEFAULT_HTTP_RETRIES, exc)
                time.sleep(retry_delay_sec(attempt))
                continue
            raise RuntimeError(f"MiniMax text upload failed after {DEFAULT_HTTP_RETRIES} attempts: {exc}") from exc
    if response is None or response.status_code != 200:
        raise RuntimeError("MiniMax text upload failed without a response")
    payload = response.json()
    check_base_resp(payload, "text upload")
    file_id = str(get_nested(payload, "file", "file_id") or "").strip()
    if not file_id:
        raise RuntimeError(f"MiniMax text upload did not return file_id: {json.dumps(payload, ensure_ascii=False)[:800]}")
    return file_id


def check_base_resp(response_json: dict[str, Any], context: str) -> None:
    base_resp = response_json.get("base_resp") or response_json.get("baseResponse") or {}
    status_code = base_resp.get("status_code", base_resp.get("statusCode", 0))
    if status_code not in (0, "0", None):
        raise RuntimeError(f"MiniMax {context} error: {json.dumps(base_resp, ensure_ascii=False)}")


def append_query(url: str, params: dict[str, Any]) -> str:
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is not None and value != "":
            query[key] = str(value)
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def async_query_endpoint(endpoint: str, task_id: str) -> str:
    parsed = urllib.parse.urlparse(endpoint)
    path = parsed.path.replace("/v1/t2a_async_v2", "/v1/query/t2a_async_query_v2")
    if path == parsed.path:
        path = "/v1/query/t2a_async_query_v2"
    return append_query(urllib.parse.urlunparse(parsed._replace(path=path)), {"task_id": task_id})


def file_retrieve_endpoint(endpoint: str, file_id: str) -> str:
    parsed = urllib.parse.urlparse(endpoint)
    base = urllib.parse.urlunparse(parsed._replace(path="/v1/files/retrieve_content", query=""))
    return append_query(base, {"file_id": file_id})


def get_nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def response_task_id(response_json: dict[str, Any]) -> str:
    return str(
        response_json.get("task_id")
        or get_nested(response_json, "data", "task_id")
        or get_nested(response_json, "data", "taskId")
        or ""
    ).strip()


def response_file_id(response_json: dict[str, Any]) -> str:
    return str(
        response_json.get("file_id")
        or get_nested(response_json, "data", "file_id")
        or get_nested(response_json, "data", "fileId")
        or get_nested(response_json, "file", "file_id")
        or ""
    ).strip()


def response_status(response_json: dict[str, Any]) -> str:
    return str(
        response_json.get("status")
        or get_nested(response_json, "data", "status")
        or get_nested(response_json, "task", "status")
        or ""
    ).strip()


def download_url(url: str, api_key: str | None = None, timeout: int = 120) -> bytes:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    request = urllib.request.Request(url, headers=headers, method="GET")
    return request_bytes_with_retry(request, timeout=timeout, purpose="download")


def audio_bytes_from_string(value: str, api_key: str, timeout: int) -> bytes:
    text = value.strip()
    if text.startswith(("http://", "https://")):
        return download_url(text, api_key=None, timeout=timeout)
    try:
        return binascii.unhexlify(text)
    except (binascii.Error, ValueError):
        import base64

        return base64.b64decode(text)


def download_minimax_file(endpoint: str, file_id: str, api_key: str, out_audio: Path, timeout: int) -> None:
    url = file_retrieve_endpoint(endpoint, file_id)
    body = download_url(url, api_key=api_key, timeout=timeout)
    content = body.lstrip()
    if content.startswith(b"{"):
        data = json.loads(body.decode("utf-8"))
        for key in ("download_url", "url", "file_url", "audio", "content"):
            value = data.get(key) or get_nested(data, "data", key)
            if isinstance(value, str) and value.strip():
                body = audio_bytes_from_string(value, api_key, timeout)
                break
        else:
            raise RuntimeError(f"MiniMax file response did not include audio content: {json.dumps(data, ensure_ascii=False)[:800]}")
    out_audio.parent.mkdir(parents=True, exist_ok=True)
    out_audio.write_bytes(body)


def call_minimax_async_tts(payload: dict[str, Any], endpoint: str, api_key: str, timeout: int, out_audio: Path) -> dict[str, Any]:
    async_payload = dict(payload)
    async_payload.pop("stream", None)
    response_json = call_minimax_tts(async_payload, endpoint, api_key, timeout)
    check_base_resp(response_json, "async submit")
    task_id = response_task_id(response_json)
    file_id = response_file_id(response_json)
    deadline = time.monotonic() + max(30, timeout)
    poll_response = response_json
    completed = not task_id

    if task_id:
        while time.monotonic() < deadline:
            query_url = async_query_endpoint(endpoint, task_id)
            request = urllib.request.Request(
                query_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="GET",
            )
            body = request_bytes_with_retry(
                request,
                timeout=min(30, timeout),
                purpose="async query",
            )
            poll_response = json.loads(body.decode("utf-8"))
            check_base_resp(poll_response, "async query")

            file_id = response_file_id(poll_response) or file_id
            status = response_status(poll_response).lower()
            if status in {"success", "completed", "done"}:
                completed = True
                break
            if status in {"failed", "fail", "error", "expired"}:
                raise RuntimeError(f"MiniMax async task failed: {json.dumps(poll_response, ensure_ascii=False)[:800]}")
            time.sleep(2)

    if task_id and not completed:
        raise RuntimeError(f"MiniMax async task timed out: {json.dumps(poll_response, ensure_ascii=False)[:800]}")
    if not file_id:
        raise RuntimeError(f"MiniMax async response did not include file_id: {json.dumps(poll_response, ensure_ascii=False)[:800]}")
    download_minimax_file(endpoint, file_id, api_key, out_audio, timeout)
    poll_response.setdefault("async_submit", response_json)
    poll_response.setdefault("file_id", file_id)
    return poll_response


def write_audio(response_json: dict[str, Any], out_audio: Path) -> None:
    data = response_json.get("data") or {}
    audio = data.get("audio")
    if not audio:
        raise RuntimeError(f"MiniMax response did not include data.audio: {json.dumps(response_json, ensure_ascii=False)[:800]}")

    out_audio.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(audio, str) and audio.startswith(("http://", "https://")):
        request = urllib.request.Request(audio, method="GET")
        out_audio.write_bytes(request_bytes_with_retry(request, timeout=120, purpose="audio url download"))
        return

    try:
        out_audio.write_bytes(binascii.unhexlify(audio))
    except (binascii.Error, TypeError) as exc:
        raise RuntimeError("MiniMax audio field is neither URL nor valid hex.") from exc


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", strip_tts_markup(text)).strip()
    parts = SENTENCE_END_RE.split(normalized)
    sentences = [part.strip() for part in parts if part.strip()]
    if sentences:
        return sentences
    return [normalized] if normalized else []


def split_subtitle_chunks(sentence: str, max_chars: int = DEFAULT_MAX_SUBTITLE_CHARS) -> list[str]:
    sentence = sentence.strip()
    if not sentence:
        return []

    chunks: list[str] = []
    remaining = sentence
    while remaining:
        if len(remaining) <= max_chars:
            chunk = remaining
            remaining = ""
        else:
            window = remaining[: max_chars + 1]
            hard_cut = max([window.rfind(mark) for mark in HARD_SUBTITLE_MARKS] + [-1])
            soft_cut = max([window.rfind(mark) for mark in SOFT_SUBTITLE_MARKS] + [-1])
            cut_index = hard_cut if hard_cut >= max(8, max_chars // 2) else soft_cut
            if cut_index < max(8, max_chars // 2) or cut_index >= max_chars:
                cut_index = max_chars - 1
            chunk = remaining[: cut_index + 1]
            remaining = remaining[cut_index + 1 :].strip()
        chunk = chunk.strip(SUBTITLE_EDGE_PUNCTUATION)
        if chunk:
            chunks.append(chunk)

    return [chunk for chunk in chunks if chunk]


def split_subtitles(text: str, max_chars: int) -> list[str]:
    chunks: list[str] = []
    for sentence in split_sentences(text):
        chunks.extend(split_subtitle_chunks(sentence, max_chars=max_chars))
    return chunks


def duration_from_response(response_json: dict[str, Any]) -> float | None:
    extra = response_json.get("extra_info") or {}
    raw = extra.get("audio_length")
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw) / 1000.0 if raw > 1000 else float(raw)
    return None


def estimate_duration_sec(text: str) -> float:
    clean = strip_tts_markup(text)
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", clean))
    latin_words = len(re.findall(r"[A-Za-z0-9]+", clean))
    return max(1.0, chinese_chars / 4.2 + latin_words / 2.8)


def probe_audio_duration_sec(audio_path: Path) -> float | None:
    if not audio_path.exists() or audio_path.stat().st_size <= 0:
        return None
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(audio_path),
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def choose_audio_duration(response_json: dict[str, Any], subtitle_text: str, audio_path: Path) -> tuple[float, str, float | None]:
    local_duration = probe_audio_duration_sec(audio_path)
    provider_duration = duration_from_response(response_json)
    if local_duration:
        return local_duration, "local_audio_ffprobe", provider_duration
    if provider_duration:
        return provider_duration, "provider_response", provider_duration
    return estimate_duration_sec(subtitle_text), "text_estimate", None


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

    payload = {
        "model": args.model,
        "text": text,
        "language_boost": args.language_boost,
        "voice_setting": voice_setting,
        "audio_setting": {
            "bitrate": args.bitrate,
            "format": args.audio_format,
            "channel": args.channel,
        },
    }
    if is_async_endpoint(args.endpoint):
        payload["audio_setting"]["audio_sample_rate"] = args.sample_rate
    else:
        payload["stream"] = False
        payload["output_format"] = "hex"
        payload["subtitle_enable"] = args.subtitle_enable
        payload["subtitle_type"] = args.subtitle_type
        payload["audio_setting"]["sample_rate"] = args.sample_rate
    return payload


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
    parser.add_argument("--timeout", type=int, default=300)
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
    max_chars = 50000 if is_async_endpoint(args.endpoint) else 10000
    if len(tts_text) >= max_chars:
        print(f"Input text must be less than {max_chars:,} characters for the configured MiniMax TTS endpoint.", file=sys.stderr)
        return 2

    if args.out_tts_text:
        Path(args.out_tts_text).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_tts_text).write_text(tts_text + "\n", encoding="utf-8")

    payload = build_payload(args, tts_text)
    out_audio = Path(args.out_audio)
    if is_async_endpoint(args.endpoint):
        text_file_id = upload_minimax_text_file(tts_text, args.endpoint, args.api_key, args.timeout)
        payload.pop("text", None)
        payload["text_file_id"] = int(text_file_id) if text_file_id.isdigit() else text_file_id
        response_json = call_minimax_async_tts(payload, args.endpoint, args.api_key, args.timeout, out_audio)
    else:
        response_json = call_minimax_tts(payload, args.endpoint, args.api_key, args.timeout)
        check_base_resp(response_json, "sync")
        write_audio(response_json, out_audio)

    duration_sec, duration_source, provider_duration_sec = choose_audio_duration(response_json, subtitle_text, out_audio)
    timing_source = f"estimated_{duration_source}"
    segments = build_segments(subtitle_text, duration_sec, args.slide_id, timing_source, args.max_subtitle_chars)
    timeline = {
        "slide_id": args.slide_id,
        "audio_file": str(out_audio).replace("\\", "/"),
        "duration_sec": round(duration_sec, 3),
        "audio_content_duration_sec": round(duration_sec, 3),
        "duration_source": duration_source,
        "provider_duration_sec": round(provider_duration_sec, 3) if provider_duration_sec else None,
        "timing_source": timing_source,
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
            "duration": {
                "source": duration_source,
                "sec": round(duration_sec, 3),
                "provider_sec": round(provider_duration_sec, 3) if provider_duration_sec else None,
            },
        }
        write_json(Path(args.out_meta), meta)

    if args.out_srt:
        write_srt(segments, Path(args.out_srt))

    if args.out_timeline:
        write_json(Path(args.out_timeline), timeline)

    print(json.dumps({"audio": str(out_audio), "duration_sec": round(duration_sec, 3), "duration_source": duration_source}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
