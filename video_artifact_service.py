"""MP4 paths, freshness metadata, variants, and artifact lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable

from sqlalchemy.orm import Session

from runtime_support import kill_process_tree

from artifact_fingerprint import render_input_fingerprint
from artifact_registry import record_artifact, remove_artifact_record
from database import Project
from pipeline_lifecycle import write_json_atomic
from project_storage import (
    UnsafeProjectPath,
    legacy_video_file,
    project_run_dir,
    video_file,
    video_sidecar,
    videos_dir,
)
from video_contracts import VideoRenderError


logger = logging.getLogger("PPTStudio.VideoArtifacts")


@dataclass(frozen=True)
class VideoArtifactDependencies:
    runs_root: Path
    pipeline_version: str
    render_timeout_sec: float
    read_visual_settings: Callable[[Project], dict[str, Any]]
    normalize_color: Callable[..., str]
    normalize_subtitle_style: Callable[[Any], dict[str, Any]]
    resolve_media_tool: Callable[[str], str | None]


class VideoArtifactService:
    """Owns every filesystem and registry operation for rendered MP4 files."""

    def __init__(self, dependencies: VideoArtifactDependencies) -> None:
        self.dependencies = dependencies

    def get_project(self, db: Session, project_id: str) -> Project:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise VideoRenderError(404, "项目不存在")
        return project

    def validated_run_dir(self, project: Project) -> Path:
        try:
            return project_run_dir(
                self.dependencies.runs_root,
                project.run_dir,
                project.id,
            )
        except UnsafeProjectPath as exc:
            logger.error(
                "Unsafe project run directory for %s: %s",
                project.id,
                exc,
            )
            raise VideoRenderError(
                500,
                "项目运行目录安全校验失败",
            ) from exc

    def project_video_dir(self, project: Project) -> Path:
        target = videos_dir(self.validated_run_dir(project))
        target.mkdir(parents=True, exist_ok=True)
        return target

    def project_video_file(
        self,
        project: Project,
        filename: str,
    ) -> Path:
        try:
            return video_file(
                self.validated_run_dir(project),
                filename,
            )
        except UnsafeProjectPath as exc:
            raise VideoRenderError(400, "视频文件名无效") from exc

    def project_legacy_video_file(self, project: Project) -> Path:
        return legacy_video_file(self.validated_run_dir(project))

    @staticmethod
    def video_metadata_path(path: str | Path) -> Path:
        return video_sidecar(path)

    def read_video_metadata(
        self,
        path: str | Path,
    ) -> dict[str, Any]:
        metadata_path = self.video_metadata_path(path)
        if not metadata_path.exists():
            return {}
        try:
            value = json.loads(metadata_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception as exc:
            logger.warning(
                "Failed to read video metadata %s: %s",
                metadata_path,
                exc,
            )
            return {}

    def current_render_input_fingerprint(
        self,
        project: Project,
    ) -> dict[str, Any]:
        return render_input_fingerprint(
            project.run_dir,
            visual_settings=self.visual_settings(project),
            pipeline_version=self.dependencies.pipeline_version,
        )

    def visual_settings(self, project: Project) -> dict[str, Any]:
        return self.dependencies.read_visual_settings(project)

    def video_item(
        self,
        project: Project,
        path: str | Path,
        label: str | None = None,
        current_fingerprint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = Path(path)
        stat = target.stat()
        filename = target.name
        metadata_path = self.video_metadata_path(target)
        metadata_exists = metadata_path.exists()
        metadata = self.read_video_metadata(target)
        pipeline_version = str(
            metadata.get("reveal_pipeline_version") or ""
        )
        video_background = self.dependencies.normalize_color(
            metadata.get("video_background"),
            fallback="",
        )
        current_visual_settings = self.visual_settings(project)
        current_background = current_visual_settings["video_background"]
        has_subtitle_style_metadata = isinstance(
            metadata.get("subtitle_style"),
            dict,
        )
        subtitle_style = self.dependencies.normalize_subtitle_style(
            metadata.get("subtitle_style")
        )
        current_subtitle_style = current_visual_settings["subtitle_style"]
        playback_rate = float(
            metadata.get("playback_rate", 1.0) or 1.0
        )
        stored_fingerprint = metadata.get("input_fingerprint")
        current_fingerprint = (
            current_fingerprint
            or self.current_render_input_fingerprint(project)
        )
        if metadata_exists and not metadata:
            artifact_state = "invalid"
        elif (
            not metadata_exists
            or pipeline_version != self.dependencies.pipeline_version
            or not isinstance(stored_fingerprint, dict)
        ):
            artifact_state = "legacy"
        elif (
            stored_fingerprint.get("digest")
            != current_fingerprint.get("digest")
            or video_background != current_background
            or not has_subtitle_style_metadata
            or subtitle_style != current_subtitle_style
        ):
            artifact_state = "stale"
        else:
            artifact_state = "current"
        return {
            "filename": filename,
            "label": label or filename,
            "size": stat.st_size,
            "created_at": datetime.fromtimestamp(
                stat.st_mtime
            ).isoformat(timespec="seconds"),
            "url": f"/api/projects/{project.id}/videos/{filename}",
            "reveal_pipeline_version": pipeline_version or None,
            "video_background": video_background or None,
            "subtitle_style": subtitle_style,
            "playback_rate": playback_rate,
            "source_filename": (
                str(metadata.get("source_filename") or "") or None
            ),
            "is_speed_variant": abs(playback_rate - 1.0) > 0.001,
            "artifact_state": artifact_state,
            "is_current": artifact_state == "current",
            "is_stale": artifact_state == "stale",
            "is_legacy": artifact_state == "legacy",
            "is_invalid": artifact_state == "invalid",
        }

    def list_video_items(
        self,
        project: Project,
    ) -> list[dict[str, Any]]:
        run_dir = self.validated_run_dir(project)
        managed_dir = videos_dir(run_dir)
        items: list[dict[str, Any]] = []
        current_fingerprint: dict[str, Any] | None = None
        if managed_dir.is_dir():
            for path in managed_dir.iterdir():
                if path.is_file() and path.suffix.lower() == ".mp4":
                    current_fingerprint = (
                        current_fingerprint
                        or self.current_render_input_fingerprint(project)
                    )
                    items.append(
                        self.video_item(
                            project,
                            path,
                            current_fingerprint=current_fingerprint,
                        )
                    )
        legacy_path = legacy_video_file(run_dir)
        if legacy_path.exists() and not items:
            current_fingerprint = (
                current_fingerprint
                or self.current_render_input_fingerprint(project)
            )
            legacy = self.video_item(
                project,
                legacy_path,
                "out.mp4",
                current_fingerprint=current_fingerprint,
            )
            legacy["url"] = f"/api/projects/{project.id}/video"
            items.append(legacy)
        items.sort(
            key=lambda item: item["created_at"],
            reverse=True,
        )
        return items

    def write_render_metadata(
        self,
        output_path: str | Path,
        metadata: dict[str, Any],
    ) -> None:
        write_json_atomic(
            self.video_metadata_path(output_path),
            metadata,
        )

    def record_rendered_video(
        self,
        db: Session,
        project: Project,
        output_path: Path,
        output_filename: str,
        *,
        render_metadata: dict[str, Any],
        render_fingerprint: dict[str, Any],
    ) -> Any:
        self.write_render_metadata(output_path, render_metadata)
        artifact = record_artifact(
            db,
            project_id=project.id,
            artifact_type="video",
            path=output_path,
            relative_path=f"videos/{output_filename}",
            mime_type="video/mp4",
            source_fingerprint=render_fingerprint,
            metadata=render_metadata,
        )
        shutil.copy2(
            output_path,
            self.project_legacy_video_file(project),
        )
        return artifact

    def list_videos(
        self,
        db: Session,
        project_id: str,
    ) -> dict[str, Any]:
        project = self.get_project(db, project_id)
        return {
            "success": True,
            "videos": self.list_video_items(project),
        }

    def video_download(
        self,
        db: Session,
        project_id: str,
        filename: str,
    ) -> Path:
        project = self.get_project(db, project_id)
        path = self.project_video_file(project, filename)
        if not path.exists():
            raise VideoRenderError(404, "视频文件不存在")
        return path

    def create_speed_adjusted_video(
        self,
        db: Session,
        project_id: str,
        filename: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        project = self.get_project(db, project_id)
        requested_path = self.project_video_file(project, filename)
        try:
            speed = round(float(payload.get("speed", 1.0)), 2)
        except (TypeError, ValueError) as exc:
            raise VideoRenderError(400, "视频语速必须是数字") from exc
        if speed < 0.5 or speed > 2.0:
            raise VideoRenderError(400, "视频语速范围为 0.5× 到 2.0×")
        if not requested_path.exists():
            raise VideoRenderError(404, "视频文件不存在")

        requested_metadata = self.read_video_metadata(requested_path)
        source_name = Path(
            str(requested_metadata.get("source_filename") or filename)
        ).name
        try:
            source_path = self.project_video_file(project, source_name)
        except VideoRenderError:
            source_name = filename
            source_path = requested_path
        if not source_path.exists():
            source_name = filename
            source_path = requested_path
        if abs(speed - 1.0) <= 0.001:
            return {
                "success": True,
                "video": self.video_item(project, source_path),
                "videos": self.list_video_items(project),
            }

        ffmpeg = self.dependencies.resolve_media_tool("ffmpeg")
        if not ffmpeg:
            raise VideoRenderError(
                500,
                "未找到 FFmpeg，无法生成调速视频",
            )
        speed_tag = (
            f"{speed:.2f}".rstrip("0").rstrip(".").replace(".", "_")
        )
        output_name = f"{source_path.stem}_speed_{speed_tag}x.mp4"
        output_path = self.project_video_file(project, output_name)
        temporary = Path(f"{output_path}.tmp.mp4")
        if temporary.exists():
            temporary.unlink()
        command = [
            ffmpeg,
            "-y",
            "-i",
            str(source_path),
            "-filter:v",
            f"setpts=PTS/{speed}",
            "-filter:a",
            f"atempo={speed}",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.dependencies.render_timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            kill_process_tree(getattr(exc, "process", None))
            if temporary.exists():
                temporary.unlink()
            raise VideoRenderError(504, "生成调速视频超时") from exc
        if result.returncode != 0 or not temporary.exists():
            if temporary.exists():
                temporary.unlink()
            raise VideoRenderError(
                500,
                "生成调速视频失败："
                + str(result.stderr or "")[-800:],
            )
        os.replace(temporary, output_path)
        source_metadata = self.read_video_metadata(source_path)
        source_metadata.update(
            {
                "rendered_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
                "playback_rate": speed,
                "source_filename": source_name,
                "speed_adjustment": "ffmpeg_setpts_atempo",
            }
        )
        self.write_render_metadata(output_path, source_metadata)
        record_artifact(
            db,
            project_id=project.id,
            artifact_type="video",
            path=output_path,
            relative_path=f"videos/{output_name}",
            mime_type="video/mp4",
            source_fingerprint=(
                source_metadata.get("input_fingerprint")
                if isinstance(
                    source_metadata.get("input_fingerprint"),
                    dict,
                )
                else {}
            ),
            metadata=source_metadata,
        )
        db.commit()
        item = self.video_item(project, output_path)
        return {
            "success": True,
            "video": item,
            "videos": self.list_video_items(project),
        }

    def delete_video(
        self,
        db: Session,
        project_id: str,
        filename: str,
    ) -> dict[str, Any]:
        project = self.get_project(db, project_id)
        path = (
            self.project_legacy_video_file(project)
            if filename == "out.mp4"
            else self.project_video_file(project, filename)
        )
        if not path.exists():
            raise VideoRenderError(404, "视频文件不存在")
        path.unlink()
        metadata_path = self.video_metadata_path(path)
        if metadata_path.exists():
            metadata_path.unlink()
        remove_artifact_record(
            db,
            project_id=project.id,
            artifact_type="video",
            filename=path.name,
        )
        db.commit()

        remaining = self.list_video_items(project)
        legacy_path = self.project_legacy_video_file(project)
        regular_remaining = [
            item
            for item in remaining
            if item.get("filename") != "out.mp4"
            and self.project_video_file(
                project,
                item["filename"],
            ).exists()
        ]
        if regular_remaining:
            newest_path = self.project_video_file(
                project,
                regular_remaining[0]["filename"],
            )
            shutil.copy2(newest_path, legacy_path)
        elif legacy_path.exists():
            legacy_path.unlink()
        return {
            "success": True,
            "videos": self.list_video_items(project),
        }

    def final_video_status(
        self,
        db: Session,
        project_id: str,
    ) -> dict[str, Any]:
        project = self.get_project(db, project_id)
        run_dir = self.validated_run_dir(project)
        video_path = legacy_video_file(run_dir)
        exists = video_path.exists()
        video_mtime = video_path.stat().st_mtime if exists else 0.0
        latest_input_mtime = 0.0
        latest_input_path: Path | None = None
        input_candidates = [
            run_dir / "reveal_manifest.json",
            run_dir / "planning" / "visual_contract.json",
        ]
        slides_dir = run_dir / "slides"
        if slides_dir.is_dir():
            for path in slides_dir.rglob("*"):
                if (
                    path.is_file()
                    and path.suffix.lower()
                    in {
                        ".json",
                        ".mp3",
                        ".srt",
                        ".png",
                        ".jpg",
                        ".jpeg",
                    }
                ):
                    input_candidates.append(path)
        for path in input_candidates:
            if not path.exists():
                continue
            mtime = path.stat().st_mtime
            if mtime > latest_input_mtime:
                latest_input_mtime = mtime
                latest_input_path = path
        stale = bool(
            exists and latest_input_mtime > video_mtime + 1
        )
        return {
            "exists": exists,
            "video_url": (
                f"/api/projects/{project_id}/video"
                if exists
                else None
            ),
            "size": video_path.stat().st_size if exists else 0,
            "updated_at": (
                datetime.fromtimestamp(video_mtime).isoformat(
                    timespec="seconds"
                )
                if exists
                else None
            ),
            "stale": stale,
            "latest_input_updated_at": (
                datetime.fromtimestamp(
                    latest_input_mtime
                ).isoformat(timespec="seconds")
                if latest_input_mtime
                else None
            ),
            "latest_input_path": (
                str(latest_input_path)
                if latest_input_path
                else None
            ),
        }

    def final_video_download(
        self,
        db: Session,
        project_id: str,
    ) -> Path:
        project = self.get_project(db, project_id)
        path = self.project_legacy_video_file(project)
        if not path.exists():
            items = self.list_video_items(project)
            if items:
                path = self.project_video_file(
                    project,
                    items[0]["filename"],
                )
        if not path.exists():
            raise VideoRenderError(404, "最终视频尚未渲染生成")
        return path
