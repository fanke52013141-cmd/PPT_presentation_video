"""Per-project video background and subtitle style settings."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import Project
import invalidation_service


logger = logging.getLogger("PPTStudio.VisualSettings")

IMAGE_GENERATION_BACKGROUND = "#FFFFFF"
DEFAULT_VIDEO_BACKGROUND = "#FEFDF9"
PROJECT_VISUAL_SETTINGS_FILE = "visual_settings.json"
DEFAULT_SUBTITLE_STYLE = {
    "font_key": "lxgw_marker_gothic",
    "font_family": "LXGW Marker Gothic",
    "font_size": 40,
    "font_weight": 400,
    "bottom": 0,
    "horizontal_margin": 110,
    "color": "#000000",
    "highlight_color": "#000000",
    "paging_window_ms": 1300,
    "token_highlight": True,
    "max_lines": 1,
    "line_height": 1.4,
}
OPEN_SOURCE_CHINESE_FONTS = [
    {
        "key": "noto_sans_sc",
        "label": "Noto Sans SC（现代黑体）",
        "family": "Noto Sans SC",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "noto_serif_sc",
        "label": "Noto Serif SC（现代宋体）",
        "family": "Noto Serif SC",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "ma_shan_zheng",
        "label": "马善政毛笔体（书写感）",
        "family": "Ma Shan Zheng",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "zcool_xiaowei",
        "label": "站酷小薇体（标题宋体）",
        "family": "ZCOOL XiaoWei",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "zcool_qingke",
        "label": "站酷庆科黄油体（醒目展示）",
        "family": "ZCOOL QingKe HuangYou",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "zcool_kuaile",
        "label": "站酷快乐体（活泼手写）",
        "family": "ZCOOL KuaiLe",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "long_cang",
        "label": "龙藏体（粗犷手写）",
        "family": "Long Cang",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "liu_jian_mao_cao",
        "label": "刘建毛草（奔放草书）",
        "family": "Liu Jian Mao Cao",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "zhi_mang_xing",
        "label": "志莽行书（自然行书）",
        "family": "Zhi Mang Xing",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "lxgw_marker_gothic",
        "label": "霞鹜标楷黑（马克笔展示）",
        "family": "LXGW Marker Gothic",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "lxgw_wenkai_tc",
        "label": "霞鹜文楷 TC（清晰楷体）",
        "family": "LXGW WenKai TC",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "noto_sans_tc",
        "label": "Noto Sans TC（繁简兼容黑体）",
        "family": "Noto Sans TC",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "noto_serif_tc",
        "label": "Noto Serif TC（繁简兼容宋体）",
        "family": "Noto Serif TC",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "lxgw_wenkai",
        "label": "霞鹜文楷（本机字体优先）",
        "family": "LXGW WenKai",
        "license": "SIL OFL 1.1",
        "source": "LXGW WenKai",
    },
]


@dataclass(frozen=True)
class VisualSettingsDependencies:
    read_contract_slide_ids: Callable[[str], list[str]]
    reveal_lock_for: Callable[[Project], Any]
    write_json_atomic: Callable[[str, Any], Any]
    style_reference_dir: Path
    style_reference_template: str


def normalize_hex_color(
    value: Any,
    fallback: str = DEFAULT_VIDEO_BACKGROUND,
) -> str:
    text = str(value or "").strip().upper()
    if re.fullmatch(r"#[0-9A-F]{6}", text):
        return text
    return fallback


def normalize_subtitle_style(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}

    def clamp_int(
        raw: Any,
        fallback: int,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            parsed = int(float(raw))
        except (TypeError, ValueError):
            parsed = fallback
        return max(minimum, min(maximum, parsed))

    def clamp_float(
        raw: Any,
        fallback: float,
        minimum: float,
        maximum: float,
    ) -> float:
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            parsed = fallback
        return max(minimum, min(maximum, parsed))

    def parse_bool(raw: Any, fallback: bool) -> bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        if isinstance(raw, (int, float)):
            return bool(raw)
        return fallback

    font_by_key = {
        font["key"]: font for font in OPEN_SOURCE_CHINESE_FONTS
    }
    font_key = str(
        payload.get("font_key")
        or DEFAULT_SUBTITLE_STYLE["font_key"]
    ).strip()
    if font_key not in font_by_key:
        font_key = DEFAULT_SUBTITLE_STYLE["font_key"]
    font = font_by_key[font_key]
    return {
        "font_key": font_key,
        "font_family": font["family"],
        "font_size": clamp_int(
            payload.get("font_size"),
            DEFAULT_SUBTITLE_STYLE["font_size"],
            22,
            72,
        ),
        "font_weight": clamp_int(
            payload.get("font_weight"),
            DEFAULT_SUBTITLE_STYLE["font_weight"],
            300,
            800,
        ),
        "bottom": clamp_int(
            payload.get("bottom"),
            DEFAULT_SUBTITLE_STYLE["bottom"],
            0,
            220,
        ),
        "horizontal_margin": clamp_int(
            payload.get("horizontal_margin"),
            DEFAULT_SUBTITLE_STYLE["horizontal_margin"],
            40,
            420,
        ),
        "color": normalize_hex_color(
            payload.get("color"),
            DEFAULT_SUBTITLE_STYLE["color"],
        ),
        "highlight_color": normalize_hex_color(
            payload.get("highlight_color"),
            DEFAULT_SUBTITLE_STYLE["highlight_color"],
        ),
        "paging_window_ms": clamp_int(
            payload.get("paging_window_ms"),
            DEFAULT_SUBTITLE_STYLE["paging_window_ms"],
            600,
            2500,
        ),
        "token_highlight": parse_bool(
            payload.get("token_highlight"),
            DEFAULT_SUBTITLE_STYLE["token_highlight"],
        ),
        "max_lines": clamp_int(
            payload.get("max_lines"),
            DEFAULT_SUBTITLE_STYLE["max_lines"],
            1,
            3,
        ),
        "line_height": clamp_float(
            payload.get("line_height"),
            DEFAULT_SUBTITLE_STYLE["line_height"],
            1.0,
            2.0,
        ),
    }


def project_visual_settings_path(project: Project) -> str:
    return os.path.join(
        project.run_dir,
        PROJECT_VISUAL_SETTINGS_FILE,
    )


class VisualSettingsService:
    def __init__(self, dependencies: VisualSettingsDependencies) -> None:
        self.dependencies = dependencies

    def get(
        self,
        project_id: str,
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db)
        return {
            "success": True,
            **self.read_settings(project),
        }

    def read_settings(self, project: Project) -> dict[str, Any]:
        path = project_visual_settings_path(project)
        payload: dict[str, Any] = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as file:
                    value = json.load(file)
                if isinstance(value, dict):
                    payload = value
            except Exception as exc:
                logger.warning(
                    "Failed to read project visual settings: %s",
                    exc,
                )
        return {
            "generation_background": IMAGE_GENERATION_BACKGROUND,
            "video_background": normalize_hex_color(
                payload.get("video_background")
            ),
            "subtitle_style": normalize_subtitle_style(
                payload.get("subtitle_style")
            ),
        }

    def write_settings(
        self,
        project: Project,
        video_background: str | None = None,
        subtitle_style: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.read_settings(project)
        settings = {
            "generation_background": IMAGE_GENERATION_BACKGROUND,
            "video_background": normalize_hex_color(
                video_background,
                current["video_background"],
            ),
            "subtitle_style": normalize_subtitle_style(
                subtitle_style or current["subtitle_style"]
            ),
        }
        self.dependencies.write_json_atomic(
            project_visual_settings_path(project),
            settings,
        )
        return settings

    def update_background(
        self,
        project_id: str,
        payload: dict[str, Any],
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db)
        raw_color = str(
            payload.get("video_background") or ""
        ).strip().upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", raw_color):
            raise HTTPException(
                status_code=400,
                detail="视频背景色必须是 #RRGGBB 格式",
            )
        previous = self.read_settings(project)
        settings = self.write_settings(
            project,
            raw_color,
        )
        self.sync_background(project)
        if (
            previous["video_background"]
            != settings["video_background"]
        ):
            invalidation_service.video_background_changed(
                project,
                self.dependencies.read_contract_slide_ids(
                    project.run_dir
                ),
            )
            db.commit()
        return {"success": True, **settings}

    def get_subtitles(
        self,
        project_id: str,
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db)
        settings = self.read_settings(project)
        return {
            "success": True,
            "subtitle_style": settings["subtitle_style"],
            "fonts": OPEN_SOURCE_CHINESE_FONTS,
            "preview_url": self.preview_background_url(project),
        }

    def update_subtitles(
        self,
        project_id: str,
        payload: dict[str, Any],
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db)
        previous = self.read_settings(project)
        subtitle_style = (
            payload.get("subtitle_style")
            if isinstance(payload, dict)
            else None
        )
        settings = self.write_settings(
            project,
            subtitle_style=subtitle_style,
        )
        if previous["subtitle_style"] != settings["subtitle_style"]:
            invalidation_service.subtitle_style_changed(project)
            db.commit()
        return {
            "success": True,
            "subtitle_style": settings["subtitle_style"],
            "fonts": OPEN_SOURCE_CHINESE_FONTS,
            "preview_url": self.preview_background_url(project),
        }

    def preview_background_url(self, project: Project) -> str:
        for slide_id in self.dependencies.read_contract_slide_ids(
            project.run_dir
        ):
            path = os.path.join(
                project.run_dir,
                "slides",
                slide_id,
                "visual_draft.png",
            )
            if os.path.exists(path):
                return (
                    f"/api/projects/{project.id}/slides/{slide_id}"
                    f"/image?t={int(os.path.getmtime(path))}"
                )
        template_path = (
            self.dependencies.style_reference_dir
            / self.dependencies.style_reference_template
        )
        if template_path.exists():
            return (
                "/api/image-style/reference/template"
                f"?t={int(template_path.stat().st_mtime)}"
            )
        return ""

    def sync_background(self, project: Project) -> str | None:
        manifest_path = os.path.join(
            project.run_dir,
            "reveal_manifest.json",
        )
        if not os.path.exists(manifest_path):
            return None
        background_hex = self.read_settings(project)[
            "video_background"
        ]
        with self.dependencies.reveal_lock_for(project):
            with open(
                manifest_path,
                "r",
                encoding="utf-8",
            ) as file:
                manifest = json.load(file)
            canvas = manifest.setdefault("canvas", {})
            canvas["background"] = background_hex
            manifest.pop("background_detection", None)
            manifest["background_settings"] = {
                "generation_background": IMAGE_GENERATION_BACKGROUND,
                "video_background": background_hex,
                "outer_background_removal": (
                    "outer_connected_near_white_only"
                ),
            }
            self.dependencies.write_json_atomic(
                manifest_path,
                manifest,
            )
        return background_hex

    @staticmethod
    def _project(project_id: str, db: Session) -> Project:
        project = (
            db.query(Project)
            .filter(Project.id == project_id)
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        return project


_SERVICE: VisualSettingsService | None = None


def configure_visual_settings_service(
    dependencies: VisualSettingsDependencies,
) -> VisualSettingsService:
    global _SERVICE
    _SERVICE = VisualSettingsService(dependencies)
    return _SERVICE


def get_visual_settings_service() -> VisualSettingsService:
    if _SERVICE is None:
        raise RuntimeError(
            "Visual settings service has not been configured"
        )
    return _SERVICE


def read_project_visual_settings(
    project: Project,
) -> dict[str, Any]:
    return get_visual_settings_service().read_settings(project)


def write_project_visual_settings(
    project: Project,
    video_background: str | None = None,
    subtitle_style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return get_visual_settings_service().write_settings(
        project,
        video_background,
        subtitle_style,
    )


def subtitle_preview_background_url(project: Project) -> str:
    return get_visual_settings_service().preview_background_url(
        project
    )


def sync_project_background_color(
    project: Project,
) -> str | None:
    return get_visual_settings_service().sync_background(project)
