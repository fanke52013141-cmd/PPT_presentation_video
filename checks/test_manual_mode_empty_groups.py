#!/usr/bin/env python3
"""End-to-end test: a manual-mode contract with empty visual_groups must
flow through template -> build_reveal_scene -> static single-layer scene.

This proves the pipeline can render a slide that has only a title and
narration, without any AI-generated visualization groups.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def build_dummy_master(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1920, 1080), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Title area
    draw.rectangle((0, 0, 1920, 120), fill=(240, 244, 255))
    try:
        font = ImageFont.truetype("arial.ttf", 56)
    except OSError:
        font = ImageFont.load_default()
    draw.text((80, 40), "手动模式测试标题", fill=(20, 30, 80), font=font)
    # Body content
    draw.rectangle((140, 300, 1780, 800), outline=(180, 190, 220), width=4)
    draw.text((180, 360), "这是手动模式下生成的整页静态幻灯片。", fill=(40, 50, 100), font=font)
    draw.text((180, 460), "没有 visual_groups，不触发 Mask 标注。", fill=(40, 50, 100), font=font)
    img.save(path, format="PNG")


def write_contract(run_dir: Path) -> Path:
    contract = {
        "version": "visual_contract_v1",
        "topic": {
            "topic_id": "topic_manual_test",
            "topic_name": "手动模式端到端测试",
            "topic_summary": "手动模式端到端测试",
        },
        "presentation_policy": {
            "subtitle_policy": "no_slides_have_subtitle",
            "subtitle_decided_by": "system_no_subtitle_contract",
            "visual_narration_mapping": "manual_free_v1",
        },
        "slides": [
            {
                "slide_id": "slide_001",
                "main_title": "手动模式测试标题",
                "subtitle": "",
                "core_message": "整页静态渲染，无 Mask 揭示层。",
                "body_content": ["整页静态渲染，无 Mask 揭示层。"],
                "visual_groups": [],
                "narration_beats": [
                    {
                        "id": "slide_001_beat_001",
                        "group_id": None,
                        "visible_anchor": "",
                        "spoken_intent": "整页静态渲染，无 Mask 揭示层。",
                        "spoken_text": "这是手动模式的端到端测试，整页静态渲染，无 Mask 揭示层。",
                        "content_unit_id": "slide_001_unit_001",
                    }
                ],
            }
        ],
    }
    planning = run_dir / "planning"
    planning.mkdir(parents=True, exist_ok=True)
    path = planning / "visual_contract.json"
    path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run(cmd: list[str]) -> None:
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (exit {result.returncode}): {' '.join(cmd)}")


def main() -> None:
    tmp_root = Path(tempfile.mkdtemp(prefix="manual_mode_e2e_"))
    try:
        run_dir = tmp_root / "run_test"
        run_dir.mkdir(parents=True)

        # 1. Build dummy master image (1920x1080 with content)
        slide_dir = run_dir / "slides" / "slide_001"
        build_dummy_master(slide_dir / "visual_draft.png")

        # 2. Write contract with empty visual_groups
        write_contract(run_dir)

        # 3. Validate contract (must pass with empty visual_groups)
        run([
            sys.executable,
            str(ROOT / "scripts" / "validate_visual_contract.py"),
            "--contract",
            str(run_dir / "planning" / "visual_contract.json"),
        ])

        # 4. Generate reveal_manifest.json template (must allow empty groups)
        run([
            sys.executable,
            str(ROOT / "scripts" / "write_reveal_manifest_template.py"),
            "--run-dir",
            str(run_dir),
            "--overwrite",
        ])

        manifest_path = run_dir / "reveal_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["slides"][0]["groups"] == [], (
            f"Expected empty groups in manifest, got: {manifest['slides'][0]['groups']}"
        )
        print("[OK] reveal_manifest.json has empty groups[]")

        # 5. Build reveal scene (must produce static single-layer scene)
        run([
            sys.executable,
            str(ROOT / "scripts" / "build_reveal_scene.py"),
            "--manifest",
            str(run_dir / "reveal_manifest.json"),
            "--repo-root",
            str(ROOT),
        ])

        scene_path = slide_dir / "scene.json"
        scene = json.loads(scene_path.read_text(encoding="utf-8"))
        layers = scene.get("layers", [])
        assert len(layers) == 1, f"Expected 1 layer (full_slide), got {len(layers)}: {layers}"
        assert layers[0]["id"] == "full_slide", f"Expected full_slide layer, got: {layers[0]['id']}"
        assert layers[0]["role"] == "full_slide", f"Expected full_slide role, got: {layers[0]['role']}"
        print(f"[OK] scene.json has single full_slide layer: {layers[0]}")

        animation_path = slide_dir / "animation_timeline.json"
        animation = json.loads(animation_path.read_text(encoding="utf-8"))
        assert animation["events"] == [], (
            f"Expected empty events[] for static slide, got: {animation['events']}"
        )
        print(f"[OK] animation_timeline.json has empty events[] (static slide)")

        report_path = slide_dir / "reveal_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["fallback_full_slide"] is True, (
            f"Expected fallback_full_slide=True, got: {report.get('fallback_full_slide')}"
        )
        assert report["group_count"] == 0, f"Expected group_count=0, got: {report.get('group_count')}"
        assert report["layer_count"] == 1, f"Expected layer_count=1, got: {report.get('layer_count')}"
        print(f"[OK] reveal_report.json: fallback_full_slide=True, group_count=0, layer_count=1")

        # 6. Verify the full_slide.png asset was generated
        asset_path = slide_dir / "assets" / "full_slide.png"
        assert asset_path.exists(), f"Missing full_slide.png: {asset_path}"
        with Image.open(asset_path) as check:
            assert check.size == (1920, 1080), f"Wrong size: {check.size}"
        print(f"[OK] assets/full_slide.png exists at 1920x1080")

        print("\n=== MANUAL MODE E2E TEST PASSED ===")
        print("Empty visual_groups -> static single-layer Remotion scene is renderable.")

    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
