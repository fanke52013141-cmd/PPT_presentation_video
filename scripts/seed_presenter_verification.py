"""Seed isolated presenter UI/API fixtures from real generated narration.

This verifies the presenter feature, not upstream article/storyboard generation.
It never imports server or opens the user's database. Run before launching the
single application instance with the environment recorded in acceptance_env.json.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root", type=Path, required=True)
    args = parser.parse_args()
    media = args.media_root.resolve()
    from scripts.media_tools import probe_video_metadata, probe_media_duration_sec, resolve_media_tool
    for name in ("reference.mp4", "transferred_b.mp4"):
        metadata = probe_video_metadata(media / name)
        if not metadata or metadata["duration_sec"] < 20:
            raise ValueError("Actual 20-second generated videos are required before fixture setup")
    if not (media / "narration.wav").is_file():
        raise ValueError("Real generated narration is missing")
    workspace = media / "acceptance_runtime"
    environment = {
        "PPT_STUDIO_DB_PATH": str(workspace / "projects.db"),
        "PPT_STUDIO_DATA_DIR": str(workspace / "data"),
        "PPT_STUDIO_RUNS_DIR": str(workspace / "runs"),
        "PPT_DIGITAL_HUMAN_DATA_DIR": str(workspace / "data/digital_human"),
    }
    os.environ.update(environment)
    workspace.mkdir(parents=True, exist_ok=True)
    (media / "acceptance_env.json").write_text(json.dumps(environment, indent=2), encoding="utf-8")
    # All imports that initialize persistence follow the side-effect-free media preflight.
    import database
    from database import Project, SessionLocal
    from digital_human_audio_service import export_full_audio
    from scripts.generic_tts import write_common_outputs
    from tts_artifacts import artifact_paths, build_confirmation_payload, confirmation_path
    database.init_db()
    ffmpeg = resolve_media_tool("ffmpeg")
    text = (media.parent / "two_mode_20261105/narration.txt").read_text(encoding="utf-8")
    summary = []
    with SessionLocal() as db:
        for suffix, name in [("upload", "数字人验证 · 直接上传"), ("motion", "数字人验证 · 照片动作迁移")]:
            project_id = "presenter_acceptance_" + suffix
            run = workspace / "runs" / project_id
            existing = db.get(Project, project_id)
            if existing:
                summary.append({"id": project_id, "run_dir": str(run)})
                continue
            planning = run / "planning"
            planning.mkdir(parents=True, exist_ok=True)
            (planning / "visual_contract.json").write_text(json.dumps({"version": "visual_contract_v1", "slides": [{
                "slide_id": "slide_001", "title": "数字人验证", "narration": text,
            }]}, ensure_ascii=False), encoding="utf-8")
            paths = artifact_paths(run, "slide_001")
            paths["slide_dir"].mkdir(parents=True, exist_ok=True)
            subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(media / "narration.wav"),
                            "-c:a", "libmp3lame", "-b:a", "192k", str(paths["audio"])], check=True)
            paths["text"].write_text(text, encoding="utf-8")
            common = SimpleNamespace(
                out_audio=str(paths["audio"]), out_meta=str(paths["metadata"]),
                out_srt=str(paths["srt"]), out_timeline=str(paths["timeline"]),
                slide_id="slide_001", max_subtitle_chars=18, endpoint="local-comfyui",
                region="", model="IndexTTS2.5", voice_id="verification", clone_voice_id="",
                audio_format="mp3", sample_rate=22050, speed=1, volume=1, pitch=1,
                provider_extra="", _tts_text=text,
            )
            write_common_outputs(args=common, provider="comfyui", response_json={"verification_fixture": True},
                audio_bytes=paths["audio"].read_bytes(), subtitle_text=text,
                duration_sec=probe_media_duration_sec(paths["audio"]))
            confirmation_path(run).write_text(json.dumps(build_confirmation_payload(
                run, ["slide_001"], confirmation_mode="automated_verification_fixture")), encoding="utf-8")
            export_full_audio(run, ["slide_001"], [paths["audio"]],
                planning / "digital_human/audio_full.mp3", gap=0.6, ffmpeg=ffmpeg,
                run_command=subprocess.run, probe=probe_media_duration_sec)
            project = Project(id=project_id, name=name, run_dir=str(run), account_id="default", current_step=9,
                              description="隔离验证项目；上游阶段使用真实旁白产物夹具，仅验证数字人功能。")
            project.set_step_status({str(step): "completed" for step in range(1, 11)})
            db.add(project)
            db.commit()
            summary.append({"id": project_id, "run_dir": str(run)})
    (media / "acceptance_projects.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
