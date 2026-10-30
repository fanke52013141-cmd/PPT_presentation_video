"""Complete, snapshot-checked audio export for the optional presenter stage."""

import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from artifact_fingerprint import sha256_file
from pipeline_lifecycle import project_artifact_lock, write_json_atomic
from project_storage import slide_dir
from visual_contract_service import read_contract_slide_ids


FULL_AUDIO_SOURCE_VERSION = "digital_human_full_audio_v1"


class FullAudioConflict(RuntimeError):
    pass


def audio_inputs(run_dir, ids):
    return [{"slide_id": sid, "sha256": sha256_file(slide_dir(run_dir, sid) / "voice.mp3")} for sid in ids]


def full_audio_current(run_dir):
    root = Path(run_dir)
    output = root / "planning/digital_human/audio_full.mp3"
    try:
        record = json.loads(output.with_suffix(".source.json").read_text(encoding="utf-8"))
        ids = read_contract_slide_ids(run_dir)
        return bool(ids and record.get("schema_version") == FULL_AUDIO_SOURCE_VERSION and record["inputs"] == audio_inputs(run_dir, ids)
                    and record["output_sha256"] == sha256_file(output))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def export_full_audio(run_dir, ids, audio_files, output, *, gap, ffmpeg, run_command, probe):
    if isinstance(gap, bool) or not math.isfinite(float(gap)):
        raise ValueError("页间隔必须是有限秒数")
    gap = max(0.0, min(3.0, float(gap)))
    if not ids or len(ids) != len(audio_files):
        raise ValueError("未找到完整的页面音频")
    missing = [sid for sid, path in zip(ids, audio_files) if not Path(path).is_file() or Path(path).stat().st_size <= 0]
    if missing:
        raise ValueError("以下页面缺少音频，请先完成合成：" + "、".join(missing))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    record_path = output.with_suffix(".source.json")
    with tempfile.TemporaryDirectory(prefix="audio-export-", dir=output.parent) as temporary:
        directory = Path(temporary)
        with project_artifact_lock(run_dir):
            snapshot = audio_inputs(run_dir, ids)
            if full_audio_current(run_dir):
                record = json.loads(record_path.read_text(encoding="utf-8"))
                if record.get("gap_sec") == gap:
                    return {"success": True, "slides": len(ids), "gap_sec": gap,
                        "duration_sec": record["duration_sec"], "bytes": output.stat().st_size, "reused": True}
            sources = []
            for index, path in enumerate(audio_files):
                local = directory / f"source_{index}.mp3"
                shutil.copyfile(path, local)
                sources.append(local)
        def execute(command, timeout):
            result = run_command(command, capture_output=True, text=True, timeout=timeout)
            if result.returncode:
                raise RuntimeError("音频导出失败：" + (result.stderr or "")[-400:])
        normalized = []
        for index, source in enumerate(sources):
            path = directory / f"norm_{index}.wav"
            execute([ffmpeg, "-y", "-i", str(source), "-ar", "44100", "-ac", "2", "-sample_fmt", "s16", str(path)], 120)
            normalized.append(path)
        silence = directory / "silence.wav"
        if gap > 0 and len(sources) > 1:
            execute([ffmpeg, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(gap), "-sample_fmt", "s16", str(silence)], 30)
        sequence = []
        for index, path in enumerate(normalized):
            sequence.append(path)
            if gap > 0 and index < len(normalized) - 1:
                sequence.append(silence)
        listing = directory / "concat.txt"
        listing.write_text("\n".join("file '" + str(p).replace("\\", "/").replace("'", "'\\''") + "'" for p in sequence), encoding="utf-8")
        candidate = directory / "full.mp3"
        execute([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c:a", "libmp3lame", "-b:a", "192k", str(candidate)], 900)
        duration = probe(candidate)
        if duration is None or not math.isfinite(duration) or duration <= 0:
            raise RuntimeError("导出的整段音频无法解码")
        with project_artifact_lock(run_dir):
            if read_contract_slide_ids(run_dir) != ids or audio_inputs(run_dir, ids) != snapshot:
                raise FullAudioConflict("导出期间页面或音频已变化，请重新导出整段语音")
            previous_record = record_path.read_bytes() if record_path.exists() else None
            backup = output.with_name(output.name + "." + uuid.uuid4().hex + ".rollback")
            existed = output.exists()
            if existed:
                output.replace(backup)
            try:
                os.replace(candidate, output)
                write_json_atomic(record_path, {"schema_version": FULL_AUDIO_SOURCE_VERSION, "inputs": snapshot, "gap_sec": gap,
                    "output_sha256": sha256_file(output), "duration_sec": duration})
            except Exception:
                output.unlink(missing_ok=True)
                if existed:
                    backup.replace(output)
                if previous_record is None:
                    record_path.unlink(missing_ok=True)
                else:
                    write_json_atomic(record_path, json.loads(previous_record))
                raise
            else:
                backup.unlink(missing_ok=True)
    return {"success": True, "slides": len(ids), "gap_sec": gap, "duration_sec": duration, "bytes": output.stat().st_size}
