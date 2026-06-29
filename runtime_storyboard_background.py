"""Storyboard background settings bridge.

Background settings are stored per project and applied to prompt files and
reveal_manifest canvas metadata. The generated visual_draft remains pure white
for Mask stability; image backgrounds are stored as separate project assets.
"""

from __future__ import annotations

import json
import io
import os
import re
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from PIL import Image

PATCH_MARKER = "__ppt_storyboard_background_runtime_patch__"
CONFIG_NAME = "storyboard_background.json"
IMAGE_NAME = "storyboard_background.png"
ORIGINAL_IMAGE_NAME = "storyboard_background_original.png"
PROMPT_START = "<!-- STORYBOARD_BACKGROUND_POLICY_START -->"
PROMPT_END = "<!-- STORYBOARD_BACKGROUND_POLICY_END -->"
DEFAULT_COLOR = "#FFFFFF"
MAX_BACKGROUND_BYTES = 12 * 1024 * 1024


def _read_json(path: Path, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(fallback or {})
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return dict(fallback or {})
    return value if isinstance(value, dict) else dict(fallback or {})


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_color(value: Any, fallback: str = DEFAULT_COLOR) -> str:
    text = str(value or "").strip().upper()
    return text if re.fullmatch(r"#[0-9A-F]{6}", text) else fallback


def _normalize_mode(value: Any) -> str:
    return "image" if str(value or "solid").strip().lower() == "image" else "solid"


def _run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def _config_path(run_dir: Path) -> Path:
    return run_dir / "planning" / CONFIG_NAME


def _image_path(run_dir: Path) -> Path:
    return run_dir / "planning" / IMAGE_NAME


def _original_image_path(run_dir: Path) -> Path:
    return run_dir / "planning" / ORIGINAL_IMAGE_NAME


def _image_url(project_id: Any) -> str:
    return f"/api/projects/{project_id}/storyboard-background/image?t={int(time.time())}"


def _read_config(run_dir: Path, project_id: Any | None = None) -> dict[str, Any]:
    payload = _read_json(_config_path(run_dir), {})
    exists = _image_path(run_dir).exists() or _original_image_path(run_dir).exists()
    mode = _normalize_mode(payload.get("mode"))
    if mode == "image" and not exists:
        mode = "solid"
    return {
        "mode": mode,
        "solid_color": _normalize_color(payload.get("solid_color"), DEFAULT_COLOR),
        "image_fit": str(payload.get("image_fit") or "cover"),
        "image_exists": exists,
        "image_url": _image_url(project_id) if exists and project_id is not None else "",
        "generation_policy": "keep_visual_draft_white_for_mask",
    }


def _fit_image(data: bytes, size: tuple[int, int] = (1920, 1080), fit: str = "cover") -> Image.Image:
    import io
    source = Image.open(io.BytesIO(data)).convert("RGB")
    tw, th = size
    sw, sh = source.size
    if fit == "contain":
        scale = min(tw / sw, th / sh)
        nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
        out = Image.new("RGB", size, (255, 255, 255))
        resized = source.resize((nw, nh), Image.Resampling.LANCZOS)
        out.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
        return out
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = source.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    return resized.crop((left, top, left + tw, top + th))


def _render_background_image(run_dir: Path, fit: str) -> None:
    original = _original_image_path(run_dir)
    rendered = _image_path(run_dir)
    if not original.exists():
        if rendered.exists():
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(rendered.read_bytes())
        else:
            return
    image = _fit_image(original.read_bytes(), (1920, 1080), fit)
    rendered.parent.mkdir(parents=True, exist_ok=True)
    image.save(rendered, format="PNG")


def _prompt_block(config: dict[str, Any]) -> str:
    if config.get("mode") == "image":
        body = """Storyboard background mode: image background.
- Keep visual_draft.png generation on a clean pure-white #FFFFFF outer canvas so AI Mask and manual Mask cutout remain reliable.
- Do not bake the uploaded background image into the generated visual elements.
- The project stores planning/storyboard_background.png as the final background asset for downstream composition.
- Keep all icons, text, arrows, labels, and cards visually separated; do not let elements stick together."""
    else:
        color = _normalize_color(config.get("solid_color"), DEFAULT_COLOR)
        body = f"""Storyboard background mode: solid color {color}.
- Keep visual_draft.png generation on a clean pure-white #FFFFFF outer canvas so AI Mask and manual Mask cutout remain reliable.
- Downstream Reveal/video composition should replace the connected white outer background with solid color {color}.
- Do not draw texture, gradient, shadow, or off-white noise in the outer canvas.
- Keep all icons, text, arrows, labels, and cards visually separated; do not let elements stick together."""
    return f"\n{PROMPT_START}\n{body}\n{PROMPT_END}\n"


def _patch_prompts(run_dir: Path, config: dict[str, Any]) -> int:
    pattern = re.compile(re.escape(PROMPT_START) + r".*?" + re.escape(PROMPT_END), re.S)
    block = _prompt_block(config).strip()
    count = 0
    for path in sorted((run_dir / "slides").glob("*/visual_prompt.md")):
        try:
            text = path.read_text(encoding="utf-8-sig")
            patched = pattern.sub(block, text) if pattern.search(text) else text.rstrip() + "\n\n" + block + "\n"
            if patched != text:
                path.write_text(patched, encoding="utf-8")
                count += 1
        except Exception:
            continue
    return count


def _relative(path: Path, run_dir: Path) -> str:
    try:
        return str(path.relative_to(run_dir)).replace("\\", "/")
    except Exception:
        return str(path)


def _patch_manifest(run_dir: Path, config: dict[str, Any]) -> bool:
    path = run_dir / "reveal_manifest.json"
    if not path.exists():
        return False
    manifest = _read_json(path, {})
    before = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    canvas = manifest.setdefault("canvas", {})
    if config.get("mode") == "image":
        canvas["background_mode"] = "image"
        canvas["background"] = _normalize_color(config.get("solid_color"), DEFAULT_COLOR)
        canvas["background_image"] = _relative(_image_path(run_dir), run_dir)
        canvas["background_image_fit"] = str(config.get("image_fit") or "cover")
    else:
        canvas["background_mode"] = "solid"
        canvas["background"] = _normalize_color(config.get("solid_color"), DEFAULT_COLOR)
        canvas.pop("background_image", None)
        canvas.pop("background_image_fit", None)
    for slide in manifest.get("slides", []) or []:
        if isinstance(slide, dict):
            slide.setdefault("canvas", {}).update(canvas)
    if json.dumps(manifest, ensure_ascii=False, sort_keys=True) == before:
        return False
    _write_json(path, manifest)
    return True


def _apply(project: Any, payload: dict[str, Any]) -> dict[str, Any]:
    run_dir = _run_dir(project)
    current = _read_config(run_dir, getattr(project, "id", None))
    mode = _normalize_mode(payload.get("mode", current.get("mode")))
    if mode == "image" and not (_image_path(run_dir).exists() or _original_image_path(run_dir).exists()):
        mode = "solid"
    config = {
        "mode": mode,
        "solid_color": _normalize_color(payload.get("solid_color", current.get("solid_color", DEFAULT_COLOR))),
        "image_fit": str(payload.get("image_fit") or current.get("image_fit") or "cover"),
        "generation_policy": "keep_visual_draft_white_for_mask",
    }
    if mode == "image":
        _render_background_image(run_dir, config["image_fit"])
    _write_json(_config_path(run_dir), config)
    config = _read_config(run_dir, getattr(project, "id", None))
    config["patched_prompt_count"] = _patch_prompts(run_dir, config)
    config["manifest_updated"] = _patch_manifest(run_dir, config)
    return config


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db", "File", "FileResponse")
    if not all(hasattr(server_module, item) for item in required):
        return False
    app = server_module.app

    def get_background(project_id: str, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        return {"success": True, "background": _read_config(_run_dir(project), project.id)}

    def put_background(project_id: str, payload: dict[str, Any], db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        return {"success": True, "background": _apply(project, payload if isinstance(payload, dict) else {})}

    async def upload_background(project_id: str, file: Any = server_module.File(...), db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        content_type = str(getattr(file, "content_type", "") or "").lower()
        if content_type and not content_type.startswith("image/"):
            raise server_module.HTTPException(status_code=400, detail="背景文件必须是图片")
        data = await file.read()
        if not data:
            raise server_module.HTTPException(status_code=400, detail="背景图片为空")
        if len(data) > MAX_BACKGROUND_BYTES:
            raise server_module.HTTPException(status_code=400, detail="背景图片超过 12MB，请压缩后再上传")
        run_dir = _run_dir(project)
        current = _read_config(run_dir, project.id)
        try:
            original = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as exc:
            raise server_module.HTTPException(status_code=400, detail=f"无法读取背景图片: {exc}") from exc
        _original_image_path(run_dir).parent.mkdir(parents=True, exist_ok=True)
        original.save(_original_image_path(run_dir), format="PNG")
        return {"success": True, "background": _apply(project, {**current, "mode": "image"})}

    def get_background_image(project_id: str, db: Any = server_module.Depends(server_module.get_db)) -> Any:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        path = _image_path(_run_dir(project))
        if not path.exists():
            raise server_module.HTTPException(status_code=404, detail="背景图片不存在")
        return server_module.FileResponse(str(path), media_type="image/png")

    app.add_api_route("/api/projects/{project_id}/storyboard-background", get_background, methods=["GET"])
    app.add_api_route("/api/projects/{project_id}/storyboard-background", put_background, methods=["PUT"])
    app.add_api_route("/api/projects/{project_id}/storyboard-background/image", upload_background, methods=["POST"])
    app.add_api_route("/api/projects/{project_id}/storyboard-background/image", get_background_image, methods=["GET"])
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [m for m in list(sys.modules.values()) if isinstance(m, ModuleType) and hasattr(m, "app") and hasattr(m, "Project")]


def _install_when_ready() -> None:
    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_STORYBOARD_BACKGROUND") and time.monotonic() - started_at < 120:
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(target=worker, name="ppt-storyboard-background-runtime", daemon=True).start()


_install_when_ready()
