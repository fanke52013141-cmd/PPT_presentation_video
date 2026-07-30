"""Remotion subprocess pipeline for producing one validated MP4 file."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from typing import Any, Callable

from database import Project
from video_contracts import VideoRenderConfig


@dataclass(frozen=True)
class RemotionRunnerDependencies:
    config: VideoRenderConfig
    build_reveal_assets: Callable[[Project], None]
    write_project_log: Callable[..., None]
    run_subprocess_bounded: Callable[..., subprocess.CompletedProcess]
    resolve_media_tool: Callable[[str], str | None]


@dataclass(frozen=True)
class RemotionRenderResult:
    output_path: Path
    output_filename: str
    color_validation: dict[str, Any]


class RemotionRunner:
    """Runs reveal building, timeline binding, Remotion, and color QA."""

    def __init__(self, dependencies: RemotionRunnerDependencies) -> None:
        self.dependencies = dependencies

    @property
    def config(self) -> VideoRenderConfig:
        return self.dependencies.config

    def run(
        self,
        project: Project,
        *,
        output_dir: Path,
        set_stage: Callable[[str], None],
    ) -> RemotionRenderResult:
        set_stage("building_reveal")
        self.dependencies.build_reveal_assets(project)
        self._bind_timeline(project, set_stage)
        props, public_dir = self._build_remotion_props(
            project,
            set_stage,
        )
        self._ensure_remotion_dependencies(project)
        output_path, output_filename = self._render_video(
            project,
            props,
            public_dir,
            output_dir,
            set_stage,
        )
        color_validation = self._validate_render_color(
            project,
            output_path,
            set_stage,
        )
        return RemotionRenderResult(
            output_path=output_path,
            output_filename=output_filename,
            color_validation=color_validation,
        )

    @staticmethod
    def validate_public_assets(
        props: dict[str, Any],
        public_dir: str | Path,
    ) -> list[str]:
        missing: list[str] = []
        public_root = Path(public_dir).resolve()

        def check_asset(value: Any) -> None:
            if (
                not isinstance(value, str)
                or not value
                or re.match(r"^https?://", value)
            ):
                return
            asset_path = (
                public_root / value.replace("/", os.sep)
            ).resolve()
            try:
                asset_path.relative_to(public_root)
            except ValueError:
                missing.append(value)
                return
            if not asset_path.exists():
                missing.append(value)

        slides = (
            props.get("slides", [])
            if isinstance(props.get("slides"), list)
            else []
        )
        for slide in slides:
            scene = (
                slide.get("scene")
                if isinstance(slide, dict)
                else None
            )
            layers = (
                scene.get("layers")
                if isinstance(scene, dict)
                else None
            )
            if isinstance(layers, list):
                for layer in layers:
                    if isinstance(layer, dict):
                        check_asset(layer.get("asset"))
                        check_asset(layer.get("cutout_asset"))
            if (
                isinstance(scene, dict)
                and isinstance(scene.get("canvas"), dict)
            ):
                check_asset(scene["canvas"].get("background_asset"))
            check_asset(
                slide.get("audio_file")
                if isinstance(slide, dict)
                else None
            )
        return sorted(set(missing))

    def _bind_timeline(
        self,
        project: Project,
        set_stage: Callable[[str], None],
    ) -> None:
        set_stage("binding_timeline")
        script = (
            self.config.repo_root
            / "scripts"
            / "bind_reveal_timeline.py"
        )
        result = self.dependencies.run_subprocess_bounded(
            [
                sys.executable,
                str(script),
                "--run-dir",
                project.run_dir,
                "--lead-sec",
                str(self.config.reveal_visual_lead_sec),
            ],
            timeout_sec=self.config.bind_timeout_sec,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError(
                "渲染前绑定语音时间轴失败："
                + str(result.stderr or "")
            )

    def _build_remotion_props(
        self,
        project: Project,
        set_stage: Callable[[str], None],
    ) -> tuple[dict[str, Any], Path]:
        set_stage("building_props")
        script = (
            self.config.repo_root
            / "scripts"
            / "build_remotion_props.py"
        )
        public_dir = (
            self.config.repo_root
            / "scripts"
            / "remotion"
            / "public"
        )
        started = time.time()
        result = self.dependencies.run_subprocess_bounded(
            [
                sys.executable,
                str(script),
                "--run-dir",
                project.run_dir,
                "--repo-root",
                str(self.config.repo_root),
                "--remotion-public-dir",
                str(public_dir),
            ],
            timeout_sec=self.config.build_props_timeout_sec,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            self.dependencies.write_project_log(
                project,
                "step8_build_props_error",
                returncode=result.returncode,
                stderr=result.stderr or "",
            )
            raise RuntimeError(
                "构建 Remotion 配置失败："
                + str(result.stderr or "")
            )
        self.dependencies.write_project_log(
            project,
            "step8_build_props_success",
            elapsed_sec=round(time.time() - started, 3),
            stdout=(result.stdout or "").strip(),
        )
        props_path = Path(project.run_dir) / "remotion_props.json"
        props = json.loads(props_path.read_text(encoding="utf-8"))
        return props, public_dir

    def _ensure_remotion_dependencies(
        self,
        project: Project,
    ) -> None:
        remotion_dir = (
            self.config.repo_root / "scripts" / "remotion"
        )
        node_modules = remotion_dir / "node_modules"
        if node_modules.exists():
            self.dependencies.write_project_log(
                project,
                "step8_npm_install_skipped",
                node_modules_dir=str(node_modules),
            )
            return
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        started = time.time()
        self.dependencies.write_project_log(
            project,
            "step8_npm_install_start",
            cwd=str(remotion_dir),
        )
        result = self.dependencies.run_subprocess_bounded(
            [npm_cmd, "install"],
            timeout_sec=self.config.npm_install_timeout_sec,
            cwd=str(remotion_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            self.dependencies.write_project_log(
                project,
                "step8_npm_install_error",
                returncode=result.returncode,
                stderr=result.stderr or "",
            )
            raise RuntimeError(
                "初始化 Remotion Node 依赖失败："
                + str(result.stderr or "")
            )
        self.dependencies.write_project_log(
            project,
            "step8_npm_install_success",
            elapsed_sec=round(time.time() - started, 3),
            stdout=(result.stdout or "").strip(),
        )

    def _render_video(
        self,
        project: Project,
        props: dict[str, Any],
        public_dir: Path,
        output_dir: Path,
        set_stage: Callable[[str], None],
    ) -> tuple[Path, str]:
        missing_assets = self.validate_public_assets(
            props,
            public_dir,
        )
        if missing_assets:
            self.dependencies.write_project_log(
                project,
                "step8_public_asset_validation_error",
                missing_assets=missing_assets[:50],
                missing_count=len(missing_assets),
                public_dir=str(public_dir),
            )
            raise RuntimeError(
                f"Remotion 渲染素材缺失：{missing_assets[:8]}"
            )
        remotion_dir = (
            self.config.repo_root / "scripts" / "remotion"
        )
        output_filename = (
            "render_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + f"_{uuid.uuid4().hex[:6]}.mp4"
        )
        output_path = output_dir / output_filename
        props_path = Path(project.run_dir) / "remotion_props.json"
        npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
        args = [
            npx_cmd,
            "remotion",
            "render",
            "src/index.tsx",
            "ArticleVideo",
            str(output_path),
            f"--props={props_path}",
            "--codec=h264",
            "--image-format=png",
            "--pixel-format=yuv420p",
            "--color-space=bt709",
        ]
        set_stage("rendering")
        started = time.time()
        self.dependencies.write_project_log(
            project,
            "step8_remotion_render_start",
            output=str(output_path),
            timeout_sec=self.config.render_timeout_sec,
            total_duration_sec=props.get("total_duration_sec"),
        )
        try:
            result = subprocess.run(
                args,
                cwd=str(remotion_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.render_timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            self.dependencies.write_project_log(
                project,
                "step8_remotion_render_timeout",
                timeout_sec=self.config.render_timeout_sec,
            )
            raise RuntimeError("视频渲染超时") from exc
        if result.returncode != 0:
            self.dependencies.write_project_log(
                project,
                "step8_remotion_render_error",
                returncode=result.returncode,
                stdout=(result.stdout or "")[-4000:],
                stderr=(result.stderr or "")[-4000:],
            )
            raise RuntimeError(
                "视频渲染失败：" + str(result.stderr or "")
            )
        self.dependencies.write_project_log(
            project,
            "step8_remotion_render_success",
            elapsed_sec=round(time.time() - started, 3),
            stdout=(result.stdout or "")[-4000:],
        )
        return output_path, output_filename

    def _normalize_video_color_metadata(
        self,
        video_path: str | Path,
        project: Project,
    ) -> bool:
        ffmpeg = self.dependencies.resolve_media_tool("ffmpeg")
        if not ffmpeg:
            self.dependencies.write_project_log(
                project,
                "step8_color_metadata_normalize_skipped",
                reason="ffmpeg_not_found",
            )
            return False
        target = Path(video_path)
        temporary = Path(f"{target}.bt709.tmp.mp4")
        if temporary.exists():
            temporary.unlink()
        result = self.dependencies.run_subprocess_bounded(
            [
                ffmpeg,
                "-y",
                "-i",
                str(target),
                "-c",
                "copy",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-colorspace",
                "bt709",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            timeout_sec=self.config.color_process_timeout_sec,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0 or not temporary.exists():
            self.dependencies.write_project_log(
                project,
                "step8_color_metadata_normalize_error",
                returncode=result.returncode,
                stderr=(result.stderr or "")[-4000:],
            )
            if temporary.exists():
                temporary.unlink()
            return False
        os.replace(temporary, target)
        self.dependencies.write_project_log(
            project,
            "step8_color_metadata_normalize_success",
            stdout=(result.stdout or "")[-4000:],
        )
        return True

    def _validate_render_color(
        self,
        project: Project,
        output_path: Path,
        set_stage: Callable[[str], None],
    ) -> dict[str, Any]:
        set_stage("validating_color")
        self._normalize_video_color_metadata(output_path, project)
        validator = (
            self.config.repo_root
            / "scripts"
            / "validate_render_color.py"
        )
        result = self.dependencies.run_subprocess_bounded(
            [
                sys.executable,
                str(validator),
                "--video",
                str(output_path),
                "--run-dir",
                project.run_dir,
            ],
            timeout_sec=self.config.color_process_timeout_sec,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            if output_path.exists():
                output_path.unlink()
            raise RuntimeError(
                "视频颜色校验失败，已阻止输出："
                + str(result.stderr or "")
            )
        return self._parse_json_stdout(result)

    @staticmethod
    def _parse_json_stdout(
        result: subprocess.CompletedProcess,
    ) -> dict[str, Any]:
        try:
            payload = json.loads(result.stdout or "{}")
        except (TypeError, json.JSONDecodeError):
            return {
                "parse_warning": (
                    "validator stdout was not valid JSON"
                ),
                "raw_stdout": str(result.stdout or ""),
            }
        return (
            payload
            if isinstance(payload, dict)
            else {"result": payload}
        )
