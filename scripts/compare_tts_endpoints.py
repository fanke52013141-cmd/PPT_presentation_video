"""对比 MiniMax 异步 / 同步端点的字幕时间戳质量与请求成本。

背景
----
MiniMax 默认走**异步**端点 ``/v1/t2a_async_v2``，一页语音至少消耗 4 次上游请求
（上传文本 → 提交任务 → 轮询 → 取回音频）。网关额度是全局的且通常很低
（默认 10 请求/分钟），所以异步端点的实际页吞吐只有约 1-2 页/分钟。

切换到**同步**端点 ``/v1/t2a_v2`` 后一页只消耗 1 次请求，页吞吐可提升约 4 倍。
代价是同步端点可能不返回 provider 级字幕时间戳
（``scripts/minimax_tts.py:452-453`` 的 ``subtitle_timestamps``），
那样字幕时间轴会退化为 ``estimated_*`` 估算值，属于业务质量回退。

因此**不能默认切换**：先用本脚本对同一段旁白跑两次，比较字幕质量，再决定。

用法
----
    python scripts/compare_tts_endpoints.py --run-dir runs/<run_id> --slide-id slide_001
    python scripts/compare_tts_endpoints.py --text "第一句。第二句，稍微长一点的第三句。"

脚本只读取配音文本，不会修改任何项目产物；两次合成都写到临时目录。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MINIMAX_HELPER = REPO_ROOT / "scripts" / "minimax_tts.py"
ASYNC_ENDPOINT = "https://api.minimaxi.com/v1/t2a_async_v2"
SYNC_ENDPOINT = "https://api.minimaxi.com/v1/t2a_v2"


def _load_text(args: argparse.Namespace) -> str:
    if args.text:
        return args.text
    if not (args.run_dir and args.slide_id):
        raise SystemExit("必须提供 --text，或同时提供 --run-dir 与 --slide-id")
    text_path = Path(args.run_dir) / "slides" / args.slide_id / "tts_text.txt"
    if not text_path.exists():
        raise SystemExit(f"未找到配音文本：{text_path}")
    return text_path.read_text(encoding="utf-8").strip()


def _api_key() -> str:
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if key:
        return key
    try:
        from config_store import get_setting

        return str(get_setting("tts_api_key", "") or "").strip()
    except Exception:
        return ""


def _synthesize(
    *,
    endpoint: str,
    api_key: str,
    text: str,
    out_dir: Path,
    slide_id: str,
    model: str,
    voice_id: str,
    speed: str,
    volume: str,
    pitch: str,
) -> dict:
    out_audio = out_dir / "voice.mp3"
    out_timeline = out_dir / "audio_timeline.json"
    command = [
        sys.executable,
        str(MINIMAX_HELPER),
        "--text",
        text,
        "--out-audio",
        str(out_audio),
        "--out-timeline",
        str(out_timeline),
        "--out-tts-text",
        str(out_dir / "tts_text.txt"),
        "--slide-id",
        slide_id,
        "--endpoint",
        endpoint,
        "--api-key",
        api_key,
        "--model",
        model,
        "--voice-id",
        voice_id,
        "--speed",
        str(speed),
        "--volume",
        str(volume),
        "--pitch",
        str(pitch),
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    elapsed = round(time.monotonic() - started, 2)
    result = {
        "endpoint": endpoint,
        "ok": completed.returncode == 0,
        "elapsed_sec": elapsed,
        "returncode": completed.returncode,
        "stderr_tail": (completed.stderr or "").strip()[-600:],
    }
    if out_timeline.exists():
        try:
            timeline = json.loads(out_timeline.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            timeline = {}
        segments = timeline.get("segments") if isinstance(timeline, dict) else []
        segments = segments if isinstance(segments, list) else []
        result.update(
            {
                "timing_source": timeline.get("timing_source"),
                "duration_sec": timeline.get("duration_sec"),
                "duration_source": timeline.get("duration_source"),
                "segment_count": len(segments),
                "first_segment_start": (
                    segments[0].get("start") if segments else None
                ),
                "last_segment_end": (
                    segments[-1].get("end") if segments else None
                ),
                "segment_timing_sources": sorted(
                    {
                        str(segment.get("timing_source") or "")
                        for segment in segments
                    }
                ),
                "audio_bytes": out_audio.stat().st_size if out_audio.exists() else 0,
            }
        )
    return result


def _verdict(async_result: dict, sync_result: dict) -> tuple[str, list[str]]:
    notes: list[str] = []
    if not async_result.get("ok"):
        return "无法判定", ["异步端点合成失败，请先修复基础配置"]
    if not sync_result.get("ok"):
        return "不要切换", ["同步端点合成失败；继续使用异步端点"]

    async_source = str(async_result.get("timing_source") or "")
    sync_source = str(sync_result.get("timing_source") or "")
    notes.append(f"timing_source：异步={async_source} 同步={sync_source}")

    if async_source.startswith("provider") and not sync_source.startswith("provider"):
        notes.append(
            "同步端点丢失了 provider 级时间戳，字幕会退化为估算时间轴 —— 存在质量回退"
        )
        return "不要切换", notes

    async_count = int(async_result.get("segment_count") or 0)
    sync_count = int(sync_result.get("segment_count") or 0)
    notes.append(f"字幕分段数：异步={async_count} 同步={sync_count}")
    if async_count and abs(async_count - sync_count) > max(1, async_count // 3):
        notes.append("分段数量差异超过 1/3，字幕切分会明显不同")
        return "不要切换", notes

    async_duration = float(async_result.get("duration_sec") or 0.0)
    sync_duration = float(sync_result.get("duration_sec") or 0.0)
    if async_duration > 0:
        drift = abs(async_duration - sync_duration) / async_duration
        notes.append(f"音频时长：异步={async_duration:.2f}s 同步={sync_duration:.2f}s（偏差 {drift:.1%}）")
        if drift > 0.05:
            notes.append("时长偏差超过 5%，语速/停顿可能与已确认的音频不一致")
            return "不要切换", notes

    notes.append(
        "每页请求数：异步 ≥4（上传+提交+轮询+取回），同步 =1 → 页吞吐约提升 4 倍"
    )
    return "可以切换", notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", help="包含 slides/<slide_id>/tts_text.txt 的项目运行目录")
    parser.add_argument("--slide-id", default="", help="要对比的页面 ID")
    parser.add_argument("--text", default="", help="直接指定要合成的文本（优先于 --run-dir）")
    parser.add_argument("--model", default=os.environ.get("MINIMAX_TTS_MODEL", "speech-2.8-hd"))
    parser.add_argument("--voice-id", default=os.environ.get("MINIMAX_TTS_VOICE_ID", "Chinese (Mandarin)_Soft_Girl"))
    parser.add_argument("--speed", default=os.environ.get("MINIMAX_TTS_SPEED", "1.2"))
    parser.add_argument("--volume", default=os.environ.get("MINIMAX_TTS_VOLUME", "1.0"))
    parser.add_argument("--pitch", default=os.environ.get("MINIMAX_TTS_PITCH", "0"))
    parser.add_argument("--json", action="store_true", help="只输出 JSON 结果")
    parser.add_argument(
        "--out-dir",
        default="",
        help="保留两次合成的音频/时间轴到该目录（便于试听与人工比对）；默认用临时目录并在结束后删除",
    )
    args = parser.parse_args()

    api_key = _api_key()
    if not api_key:
        raise SystemExit("未找到 MiniMax API Key（设置中的 tts_api_key 或环境变量 MINIMAX_API_KEY）")

    text = _load_text(args)
    slide_id = args.slide_id or "slide_001"

    def _compare(root: Path) -> tuple[dict, dict]:
        async_dir = root / "async"
        sync_dir = root / "sync"
        async_dir.mkdir(parents=True, exist_ok=True)
        sync_dir.mkdir(parents=True, exist_ok=True)
        async_result = _synthesize(
            endpoint=ASYNC_ENDPOINT, api_key=api_key, text=text,
            out_dir=async_dir, slide_id=slide_id, model=args.model,
            voice_id=args.voice_id, speed=args.speed, volume=args.volume, pitch=args.pitch,
        )
        sync_result = _synthesize(
            endpoint=SYNC_ENDPOINT, api_key=api_key, text=text,
            out_dir=sync_dir, slide_id=slide_id, model=args.model,
            voice_id=args.voice_id, speed=args.speed, volume=args.volume, pitch=args.pitch,
        )
        return async_result, sync_result

    if args.out_dir:
        root = Path(args.out_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        async_result, sync_result = _compare(root)
    else:
        with tempfile.TemporaryDirectory() as temp_dir:
            async_result, sync_result = _compare(Path(temp_dir))

    verdict, notes = _verdict(async_result, sync_result)
    payload = {
        "success": async_result.get("ok") and sync_result.get("ok"),
        "verdict": verdict,
        "notes": notes,
        "async": async_result,
        "sync": sync_result,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("=" * 68)
        print(f"结论：{verdict}")
        print("=" * 68)
        for note in notes:
            print(f"  - {note}")
        print()
        print(json.dumps({"async": async_result, "sync": sync_result}, ensure_ascii=False, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
