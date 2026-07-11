"""Apply project image backgrounds to built reveal scene assets.

This is a runtime post-build bridge. It keeps visual_draft.png pure white for Mask
processing, then replaces the rendered base/background assets after
scripts/build_reveal_scene.py finishes successfully.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

try:
    from scripts.background_color import connected_background_mask
except Exception:  # pragma: no cover
    connected_background_mask = None

CONFIG_NAME = "storyboard_background.json"
IMAGE_NAME = "storyboard_background.png"




def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fit_image(path: Path, size: tuple[int, int], fit: str) -> Image.Image:
    source = Image.open(path).convert("RGB")
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


def _resolve_slide_dir(raw: Any, manifest_dir: Path, run_dir: Path) -> Path:
    path = Path(str(raw or ""))
    if path.is_absolute():
        return path
    for base in (manifest_dir, run_dir):
        candidate = base / path
        if candidate.exists():
            return candidate
    return manifest_dir / path


def _apply_to_static_full_slide(full_path: Path, background: Image.Image) -> bool:
    if connected_background_mask is None or not full_path.exists():
        return False
    original = Image.open(full_path).convert("RGB")
    bg = background if background.size == original.size else background.resize(original.size, Image.Resampling.LANCZOS)
    mask = connected_background_mask(original)
    Image.composite(bg, original, mask).save(full_path, format="PNG")
    return True


def apply_storyboard_background(manifest_path: Path) -> int:
    manifest = _read_json(manifest_path)
    run_dir = manifest_path.parent
    config = _read_json(run_dir / "planning" / CONFIG_NAME)
    if config.get("mode") != "image":
        return 0
    image_path = run_dir / "planning" / IMAGE_NAME
    if not image_path.exists():
        return 0
    fit = str(config.get("image_fit") or "cover")
    changed = 0
    for slide in manifest.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        slide_dir = _resolve_slide_dir(slide.get("slide_dir"), manifest_path.parent, run_dir)
        scene_path = slide_dir / "scene.json"
        if not scene_path.exists():
            continue
        scene = _read_json(scene_path)
        canvas = scene.get("canvas") if isinstance(scene.get("canvas"), dict) else {}
        width = int(canvas.get("width") or 1920)
        height = int(canvas.get("height") or 1080)
        background = _fit_image(image_path, (width, height), fit)
        base_path = slide_dir / "assets" / "base_slide.png"
        full_path = slide_dir / "assets" / "full_slide.png"
        did_change = False
        if base_path.exists():
            background.save(base_path, format="PNG")
            did_change = True
        elif _apply_to_static_full_slide(full_path, background):
            did_change = True
        if did_change:
            scene.setdefault("canvas", {})["background_mode"] = "image"
            scene["canvas"]["background_image"] = str(image_path)
            scene["composition"] = scene.get("composition") if isinstance(scene.get("composition"), dict) else {}
            scene["composition"]["background_source"] = "planning/storyboard_background.png"
            _write_json(scene_path, scene)
            changed += 1
    return changed
