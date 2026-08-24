"""Production-accurate single-slide Mask preview builds and lookup."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Dict

from runtime_support import run_subprocess_killable


logger = logging.getLogger("PPTStudio.MaskPreview")


class MaskPreviewError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class MaskPreviewDependencies:
    reveal_lock_for: Callable[..., Any]
    sync_project_background_color: Callable[..., Any]
    current_slide_file_or_404: Callable[..., str]
    project_run_dir_or_500: Callable[..., str]
    read_json_file: Callable[..., Dict[str, Any]]
    apply_storyboard_background: Callable[..., Any]
    compose_preview_image: Callable[..., Any]
    repo_root: Path
    python_executable: str
    build_timeout_sec: float


_dependencies: MaskPreviewDependencies | None = None


def configure_mask_preview_dependencies(
    dependencies: MaskPreviewDependencies,
) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> MaskPreviewDependencies:
    if _dependencies is None:
        raise RuntimeError("Mask preview dependencies have not been configured")
    return _dependencies


def build_step5_mask_preview(
    project: Any,
    slide_id: str,
) -> Dict[str, Any]:
    dependencies = _deps()
    preview_path = Path(
        dependencies.current_slide_file_or_404(
            project,
            slide_id,
            "mask_preview.png",
        )
    )
    manifest_path = (
        Path(dependencies.project_run_dir_or_500(project))
        / "reveal_manifest.json"
    )
    if not manifest_path.exists():
        raise MaskPreviewError(400, "Mask 配置文件不存在")

    with dependencies.reveal_lock_for(project):
        dependencies.sync_project_background_color(project)
        build_scene_script = (
            dependencies.repo_root / "scripts" / "build_reveal_scene.py"
        )
        command = [
            dependencies.python_executable,
            str(build_scene_script),
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(dependencies.repo_root),
            "--slide-id",
            slide_id,
            "--preview-output",
            str(preview_path),
        ]
        result = run_subprocess_killable(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout_sec=dependencies.build_timeout_sec,
        )
        if result.returncode == 124:
            raise MaskPreviewError(
                504,
                "精确 Mask 预览构建超时，请重试",
            )
        if result.returncode != 0 or not preview_path.exists():
            logger.error(
                "Build exact Mask preview failed: %s",
                result.stderr,
            )
            raise MaskPreviewError(
                500,
                f"精确 Mask 预览构建失败: {result.stderr or ''}",
            )

        dependencies.apply_storyboard_background(manifest_path.resolve())
        dependencies.compose_preview_image(
            preview_path.parent,
            preview_path,
        )
        report_path = dependencies.current_slide_file_or_404(
            project,
            slide_id,
            "reveal_report.json",
        )
        report = dependencies.read_json_file(report_path, {})
        manifest_fingerprint = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        groups = [
            *(
                report.get("groups")
                if isinstance(report.get("groups"), list)
                else []
            ),
            *(
                report.get("static_groups")
                if isinstance(report.get("static_groups"), list)
                else []
            ),
        ]
        cutout_stats = {
            key: sum(
                int((group.get("cutout") or {}).get(key, 0) or 0)
                for group in groups
                if isinstance(group, dict)
            )
            for key in (
                "manual_mask_pixel_count",
                "removed_outer_white_pixel_count",
                "soft_edge_pixel_count",
                "retained_pixel_count",
            )
        }

    version = int(os.path.getmtime(preview_path) * 1000)
    return {
        "success": True,
        "slide_id": slide_id,
        "manifest_fingerprint": manifest_fingerprint,
        "preview_url": (
            f"/api/projects/{project.id}/slides/{slide_id}/"
            f"mask-preview?t={version}"
        ),
        "fallback_full_slide": bool(
            report.get("fallback_full_slide")
        ),
        "warnings": report.get("warnings", []),
        "cutout_stats": cutout_stats,
    }


def get_step5_mask_preview_path(
    project: Any,
    slide_id: str,
) -> str:
    preview_path = _deps().current_slide_file_or_404(
        project,
        slide_id,
        "mask_preview.png",
    )
    if not os.path.exists(preview_path):
        raise MaskPreviewError(
            404,
            "精确 Mask 预览尚未生成",
        )
    return preview_path
