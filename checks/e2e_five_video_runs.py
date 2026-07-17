#!/usr/bin/env python3
"""Run five resumable, real pipeline validations without an image-generation API.

The runner uses the same HTTP endpoints as the browser.  Topic cases exercise
article generation, import cases exercise pasted Markdown, and every slide image
is rendered locally from the resulting visual contract before being uploaded.
The remaining stages are production stages: image confirmation, AI Mask, exact
reveal assets, narration, TTS, timeline binding, Remotion render, and artifact QA.

The state file is written after every stage so an expensive run can be resumed.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_OUTPUT = ROOT / "runs" / "e2e_five_video_validation"
STAGES = [
    "created",
    "article",
    "storyboard",
    "images",
    "confirmed",
    "ai_mask",
    "mask_assets",
    "narration",
    "tts",
    "rendered",
    "qa",
]
PUNCTUATION_ONLY = re.compile(r"^[\s，。！？!?；;：:、,.…—\-]+$")


CASES: list[dict[str, str]] = [
    {
        "slug": "fridge_freshness",
        "name": "E2E-冰箱为什么能延长保质期",
        "mode": "topic",
        "source": "冰箱为什么能延长食物保质期：从微生物、温度和水分三个层面解释，约 700 字",
    },
    {
        "slug": "compound_interest",
        "name": "E2E-复利为什么需要时间",
        "mode": "import",
        "source": """# 复利为什么需要时间

## 复利不是一次性的高收益
复利的核心不是某一年赚得特别多，而是每一期的收益都留在系统里，成为下一期继续增长的本金。只要本金被频繁取走，复利链条就会中断。

## 时间承担了什么作用
增长率决定每一步走多远，时间决定这种增长重复多少次。前几年新增部分看起来很小，后期新增收益中越来越多来自过去的收益，而不只是最初本金。

## 波动为什么不能被忽略
亏损百分之五十之后，需要上涨百分之一百才能回到原点。因此复利并不等于盲目追求高回报，更重要的是控制不可逆的大幅损失，让本金能够长期留在场内。

## 普通人的可执行原则
选择自己能理解的长期策略，降低频繁交易和高费用，保留应急资金，避免在短期压力下被迫卖出。复利真正依赖的是持续、纪律与足够长的时间。""",
    },
    {
        "slug": "urban_heat_island",
        "name": "E2E-城市热岛效应",
        "mode": "topic",
        "source": "城市热岛效应如何形成，以及树木、浅色屋顶和通风廊道为什么有效，约 700 字",
    },
    {
        "slug": "sleep_memory",
        "name": "E2E-睡眠如何巩固记忆",
        "mode": "import",
        "source": """# 睡眠如何巩固记忆

## 学习结束并不等于记忆完成
白天接触的新信息首先形成较脆弱的记忆痕迹。它们容易被后续信息干扰，需要大脑在休息阶段重新整理，才更可能成为稳定的长期记忆。

## 不同睡眠阶段分工不同
深睡眠期间，大脑会重复激活白天形成的神经活动模式，帮助事实与概念逐步稳定。快速眼动睡眠更擅长把新信息与旧经验连接，促进技能、情绪和创造性联想。

## 熬夜为什么会让学习打折
缺觉不仅影响第二天的注意力，也减少了前一天信息被整理的机会。继续增加学习时长，可能只是输入更多材料，却没有给大脑留下完成保存的窗口。

## 更有效的安排
把高强度学习放在清醒时段，睡前做简短回顾，保持规律睡眠。与其用熬夜换取表面上的学习时间，不如让学习和睡眠组成一个完整循环。""",
    },
    {
        "slug": "bullwhip_effect",
        "name": "E2E-供应链牛鞭效应",
        "mode": "topic",
        "source": "供应链中的牛鞭效应：为什么消费者需求只变化一点，上游库存却剧烈波动，约 700 字",
    },
]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stage_done(case_state: dict[str, Any], stage: str) -> bool:
    current = str(case_state.get("stage") or "")
    return current in STAGES and STAGES.index(current) >= STAGES.index(stage)


class Api:
    def __init__(self, base_url: str, in_process: bool = False) -> None:
        if in_process:
            from fastapi.testclient import TestClient
            import server

            # A fresh Python process imports the current worktree, avoiding a
            # stale long-running dev server during iterative E2E validation.
            self.client = TestClient(server.app)
            return
        # Local validation must not inherit corporate/system HTTP proxies.  A
        # proxy can accept the localhost socket and then leave the request
        # hanging before the first stage is recorded.
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(1200.0, connect=15.0),
            trust_env=False,
        )

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _payload(response: httpx.Response, label: str) -> Any:
        try:
            payload = response.json()
        except Exception:
            payload = {"detail": response.text[:1000]}
        if response.status_code >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            raise RuntimeError(f"{label} failed ({response.status_code}): {detail or payload}")
        return payload

    def get(self, path: str, label: str) -> Any:
        return self._payload(self.client.get(path), label)

    def post(self, path: str, label: str, **kwargs: Any) -> Any:
        return self._payload(self.client.post(path, **kwargs), label)

    def put(self, path: str, label: str, **kwargs: Any) -> Any:
        return self._payload(self.client.put(path, **kwargs), label)


def find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        ROOT / "assets" / "fonts" / "NotoSansSC-Regular.otf",
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def compact_text(value: Any, limit: int = 44) -> str:
    text = re.sub(r"\s+", "", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def body_groups(slide: dict[str, Any]) -> list[dict[str, Any]]:
    groups = []
    for group in slide.get("visual_groups", []) or []:
        if not isinstance(group, dict):
            continue
        role = str(group.get("role") or "").strip().lower()
        if role in {"title", "subtitle", "decoration"}:
            continue
        groups.append(group)
    return groups


def group_label(group: dict[str, Any], index: int) -> str:
    for key in ("display_text", "visible_text", "visual_anchor", "mask_target"):
        value = compact_text(group.get(key), 46)
        if value:
            return value
    return f"可视化语块 {index + 1}"


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    fill: str,
    max_lines: int = 3,
) -> None:
    x1, y1, x2, y2 = box
    max_width = x2 - x1
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and sum(len(line) for line in lines) < len(text):
        lines[-1] = lines[-1][:-1] + "…"
    line_height = max(1, int((y2 - y1) / max_lines))
    for line_index, line in enumerate(lines):
        draw.text((x1, y1 + line_index * line_height), line, font=font, fill=fill)


def render_local_slide(slide: dict[str, Any], out_path: Path, case_index: int) -> dict[str, Any]:
    width, height = 1920, 1080
    image = Image.new("RGB", (width, height), "#FEFDF9")
    draw = ImageDraw.Draw(image)
    title_font = find_font(58, bold=True)
    subtitle_font = find_font(31)
    body_font = find_font(25, bold=True)
    meta_font = find_font(20)
    colors = [
        ("#FFF3D6", "#F0A51A", "#8B5B00"),
        ("#EAF7E4", "#62A844", "#2F6D22"),
        ("#E6F1FF", "#4B83D1", "#235391"),
        ("#F4EAFF", "#8C65C7", "#59358F"),
        ("#FFE9EC", "#D95D70", "#9E3143"),
        ("#E4F8F6", "#2B9A91", "#17665F"),
    ]

    title = compact_text(slide.get("main_title") or slide.get("title") or slide.get("slide_id"), 34)
    subtitle = compact_text(slide.get("subtitle"), 52)
    draw.text((76, 58), title, font=title_font, fill="#1F2937")
    if subtitle:
        draw.text((80, 142), subtitle, font=subtitle_font, fill="#667085")
    draw.line((76, 218, 1844, 218), fill="#E7E9F2", width=3)

    groups = body_groups(slide)
    count = max(1, len(groups))
    columns = 1 if count == 1 else 2 if count <= 4 else 3
    rows = math.ceil(count / columns)
    left, right, top, bottom = 76, 1844, 274, 900
    gap_x, gap_y = 64, 56
    card_width = int((right - left - gap_x * (columns - 1)) / columns)
    card_height = int((bottom - top - gap_y * (rows - 1)) / rows)

    boxes: list[dict[str, Any]] = []
    for index, group in enumerate(groups or [{"id": f"{slide.get('slide_id')}_body"}]):
        row, column = divmod(index, columns)
        x1 = left + column * (card_width + gap_x)
        y1 = top + row * (card_height + gap_y)
        x2, y2 = x1 + card_width, y1 + card_height
        bg, border, ink = colors[(index + case_index) % len(colors)]
        draw.rounded_rectangle((x1, y1, x2, y2), radius=30, fill=bg, outline=border, width=7)

        icon_center = (x1 + 82, y1 + 82)
        draw.ellipse(
            (icon_center[0] - 43, icon_center[1] - 43, icon_center[0] + 43, icon_center[1] + 43),
            fill="#FFFFFF",
            outline=border,
            width=6,
        )
        draw.line(
            (icon_center[0] - 20, icon_center[1], icon_center[0] - 5, icon_center[1] + 17, icon_center[0] + 25, icon_center[1] - 22),
            fill=border,
            width=9,
            joint="curve",
        )
        label = group_label(group, index)
        draw_wrapped_text(draw, label, (x1 + 150, y1 + 42, x2 - 35, y2 - 42), body_font, ink, max_lines=4)
        draw.text((x1 + 42, y2 - 42), f"语块 {index + 1} · 独立视觉岛", font=meta_font, fill=ink)
        boxes.append({"group_id": str(group.get("id") or ""), "box": {"x": x1, "y": y1, "w": card_width, "h": card_height}})

    draw.text((78, 970), "本地图像上传 · 16:9 · 标题静态 · 视觉岛间距 ≥ 56px", font=meta_font, fill="#98A2B3")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, format="PNG", optimize=True)
    return {"slide_id": slide.get("slide_id"), "path": str(out_path), "visual_islands": boxes}


def set_stage(state_path: Path, state: dict[str, Any], case_state: dict[str, Any], stage: str, **extra: Any) -> None:
    case_state["stage"] = stage
    case_state["updated_at"] = now()
    case_state.update(extra)
    write_json(state_path, state)


def require_success(payload: dict[str, Any], label: str) -> dict[str, Any]:
    if payload.get("success") is False:
        raise RuntimeError(f"{label} returned success=false: {payload}")
    return payload


def run_case(api: Api, case: dict[str, str], case_index: int, state: dict[str, Any], state_path: Path, output_dir: Path) -> None:
    case_state = state.setdefault("cases", {}).setdefault(case["slug"], {"case": case, "stage": ""})
    case_state.pop("error", None)
    print(f"\n[{case_index + 1}/{len(CASES)}] {case['name']} (resume={case_state.get('stage') or 'new'})", flush=True)

    if not stage_done(case_state, "created"):
        created = api.post("/api/projects", "create project", json={"name": case["name"], "description": "Codex 完整视频流程验收"})
        project = created.get("project") or {}
        project_id = str(project.get("id") or "")
        if not project_id:
            raise RuntimeError("create project did not return project.id")
        detail = api.get(f"/api/projects/{project_id}", "get project")
        set_stage(state_path, state, case_state, "created", project_id=project_id, run_dir=detail.get("run_dir"))

    project_id = str(case_state["project_id"])
    run_dir = Path(str(case_state["run_dir"]))

    if not stage_done(case_state, "article"):
        if case["mode"] == "topic":
            generated = api.post(
                f"/api/projects/{project_id}/steps/1/generate-article",
                "generate article",
                json={"topic": case["source"]},
            )
            article = str(generated.get("content") or "").strip()
            if not article:
                raise RuntimeError("topic generation returned empty article")
        else:
            article = case["source"]
        api.post(f"/api/projects/{project_id}/steps/1/import", "import article", data={"content": article})
        set_stage(state_path, state, case_state, "article", article_characters=len(article), article_mode=case["mode"])

    if not stage_done(case_state, "storyboard"):
        api.post(f"/api/projects/{project_id}/steps/2/script/execute", "article to slides", json={})
        api.post(f"/api/projects/{project_id}/steps/2/visual/execute", "slides to visual", json={})
        composed = api.post(f"/api/projects/{project_id}/steps/2/compose", "compose visual contract", json={})
        contract = composed.get("contract") or composed.get("result") or read_json(run_dir / "planning" / "visual_contract.json")
        slides = contract.get("slides") or []
        if not slides:
            raise RuntimeError("storyboard produced no slides")
        set_stage(state_path, state, case_state, "storyboard", slide_count=len(slides))

    contract = read_json(run_dir / "planning" / "visual_contract.json")
    slides = [slide for slide in contract.get("slides", []) if isinstance(slide, dict)]
    if not stage_done(case_state, "images"):
        rendered_images = []
        local_dir = output_dir / "local_images" / case["slug"]
        for slide in slides:
            slide_id = str(slide.get("slide_id") or "").strip()
            if not slide_id:
                continue
            image_path = local_dir / f"{slide_id}.png"
            rendered_images.append(render_local_slide(slide, image_path, case_index))
            with image_path.open("rb") as image_file:
                api.post(
                    f"/api/projects/{project_id}/steps/3/upload",
                    f"upload {slide_id}",
                    data={"slide_id": slide_id},
                    files={"file": (image_path.name, image_file, "image/png")},
                )
        set_stage(
            state_path,
            state,
            case_state,
            "images",
            image_source="local_pillow_upload_no_image_api",
            rendered_images=rendered_images,
        )

    if not stage_done(case_state, "confirmed"):
        api.post(f"/api/projects/{project_id}/steps/3/confirm", "confirm images")
        set_stage(state_path, state, case_state, "confirmed")

    if not stage_done(case_state, "ai_mask"):
        mask_payload = {"settings": {"overwrite_existing_manual_mask": True, "skip_locked_groups": False}}
        result = api.post(f"/api/projects/{project_id}/steps/5/ai-mask/annotate", "AI Mask", json=mask_payload)
        if result.get("complete") is False:
            result = api.post(f"/api/projects/{project_id}/steps/5/ai-mask/annotate", "AI Mask retry", json=mask_payload)
        mask_result_path = output_dir / "mask_results" / f"{case['slug']}.json"
        write_json(mask_result_path, result)
        set_stage(
            state_path,
            state,
            case_state,
            "ai_mask",
            mask_result=str(mask_result_path),
            mask_complete=bool(result.get("complete", True)),
            mask_updated_groups=int(result.get("updated_group_count") or 0),
        )

    if not stage_done(case_state, "mask_assets"):
        manifest_payload = api.get(f"/api/projects/{project_id}/steps/5/result", "get Mask manifest")
        manifest = manifest_payload.get("manifest")
        if not isinstance(manifest, dict):
            raise RuntimeError("Mask manifest is missing")
        api.put(f"/api/projects/{project_id}/steps/5/result", "build exact Mask assets", json=manifest)
        set_stage(state_path, state, case_state, "mask_assets")

    if not stage_done(case_state, "narration"):
        initialized = api.post(f"/api/projects/{project_id}/steps/6/init", "initialize narration")
        beats = initialized.get("beats") or {}
        annotated = api.post(f"/api/projects/{project_id}/steps/6/annotate", "annotate narration", json=beats)
        narration = annotated.get("beats") or beats
        api.put(f"/api/projects/{project_id}/steps/6/result", "confirm narration", json=narration)
        set_stage(state_path, state, case_state, "narration")

    if not stage_done(case_state, "tts"):
        api.post(f"/api/projects/{project_id}/steps/7/synthesize", "synthesize TTS")
        api.post(f"/api/projects/{project_id}/steps/7/confirm", "confirm TTS")
        set_stage(state_path, state, case_state, "tts")

    if not stage_done(case_state, "rendered"):
        rendered = api.post(f"/api/projects/{project_id}/steps/8/render", "render video")
        video = rendered.get("video") or rendered.get("item") or rendered
        filename = str(video.get("filename") or video.get("name") or "") if isinstance(video, dict) else ""
        if not filename:
            videos = sorted((run_dir / "videos").glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
            if not videos:
                raise RuntimeError("render endpoint returned no filename and videos directory is empty")
            filename = videos[0].name
        set_stage(state_path, state, case_state, "rendered", video_filename=filename)

    if not stage_done(case_state, "qa"):
        qa = validate_case(case, case_state, run_dir, slides, output_dir)
        qa_path = output_dir / "qa" / f"{case['slug']}.json"
        write_json(qa_path, qa)
        if not qa["passed"]:
            raise RuntimeError("QA failed: " + "; ".join(qa["errors"][:8]))
        set_stage(state_path, state, case_state, "qa", qa_result=str(qa_path), qa_passed=True)


def resolve_media_tool(name: str) -> str:
    from scripts.media_tools import resolve_media_tool as resolve

    value = resolve(name, repo_root=ROOT)
    if not value:
        raise RuntimeError(f"{name} is unavailable")
    return value


def probe_video(video_path: Path) -> dict[str, Any]:
    ffprobe = resolve_media_tool("ffprobe")
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,width,height,pix_fmt,color_range,color_space,color_transfer,color_primaries",
        "-of",
        "json",
        str(video_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return json.loads(result.stdout)


def extract_contact_sheet(video_path: Path, out_dir: Path, duration: float) -> Path:
    ffmpeg = resolve_media_tool("ffmpeg")
    out_dir.mkdir(parents=True, exist_ok=True)
    times = sorted({0.0, min(0.12, duration / 10), min(0.3, duration / 8), duration * 0.5, max(0.0, duration - 0.2)})
    frames: list[Path] = []
    for index, second in enumerate(times):
        path = out_dir / f"t_{second:07.2f}_{index}.png"
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{second:.3f}", "-i", str(video_path), "-frames:v", "1", "-y", str(path)]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=90)
        if result.returncode != 0:
            raise RuntimeError(f"frame extraction failed: {result.stderr}")
        frames.append(path)
    sheet_path = out_dir / "contact_sheet.png"
    subprocess.run(
        [sys.executable, str(ROOT / "checks" / "make_contact_sheet.py"), "--out", str(sheet_path), "--columns", "3", *map(str, frames)],
        check=True,
        timeout=120,
    )
    return sheet_path


def validate_case(
    case: dict[str, str],
    case_state: dict[str, Any],
    run_dir: Path,
    slides: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {
        "slide_count": len(slides),
        "duplicate_spoken_text": 0,
        "punctuation_only_subtitles": 0,
        "short_blank_subtitle_gaps": 0,
        "late_visual_events": 0,
        "static_header_missing": 0,
        "title_animation_missing": 0,
    }

    spoken_seen: dict[str, str] = {}
    for slide in slides:
        slide_id = str(slide.get("slide_id") or "")
        for beat in slide.get("narration_beats", []) or []:
            if not isinstance(beat, dict):
                continue
            spoken = re.sub(r"\s+", "", str(beat.get("spoken_text") or ""))
            if spoken and spoken in spoken_seen:
                metrics["duplicate_spoken_text"] += 1
                errors.append(f"duplicate spoken_text: {spoken_seen[spoken]} and {slide_id}/{beat.get('id')}")
            elif spoken:
                spoken_seen[spoken] = f"{slide_id}/{beat.get('id')}"

        slide_dir = run_dir / "slides" / slide_id
        audio_path = slide_dir / "audio_timeline.json"
        animation_path = slide_dir / "animation_timeline.json"
        scene_path = slide_dir / "scene.json"
        for required in (audio_path, animation_path, scene_path, slide_dir / "voice.mp3"):
            if not required.exists():
                errors.append(f"missing artifact: {required}")
        if not audio_path.exists() or not animation_path.exists() or not scene_path.exists():
            continue

        audio = read_json(audio_path)
        animation = read_json(animation_path)
        scene = read_json(scene_path)
        title_group_ids = {
            str(group.get("id") or "")
            for group in slide.get("visual_groups", []) or []
            if isinstance(group, dict)
            and str(group.get("role") or "").strip().lower() in {"title", "subtitle"}
        }
        title_beat_ids = {
            str(beat.get("id") or "")
            for beat in slide.get("narration_beats", []) or []
            if isinstance(beat, dict) and str(beat.get("group_id") or "") in title_group_ids
        }
        segments = [segment for segment in audio.get("segments", []) if isinstance(segment, dict)]
        previous_end: float | None = None
        for segment in segments:
            text = str(segment.get("text") or "").strip()
            start = float(segment.get("start") or 0.0)
            end = float(segment.get("end") or 0.0)
            if text and PUNCTUATION_ONLY.fullmatch(text):
                metrics["punctuation_only_subtitles"] += 1
                errors.append(f"{slide_id}: punctuation-only subtitle {text!r}")
            if end <= start:
                errors.append(f"{slide_id}: invalid subtitle interval {start}-{end}")
            if previous_end is not None:
                gap = start - previous_end
                if 0.001 < gap <= 0.35:
                    metrics["short_blank_subtitle_gaps"] += 1
                    errors.append(f"{slide_id}: short blank subtitle gap {gap:.3f}s")
            previous_end = end

        for event in animation.get("events", []) or []:
            if not isinstance(event, dict) or event.get("link_to_narration") is False:
                continue
            at = float(event.get("at") or 0.0)
            narration_at = float(event.get("narration_start_at") or 0.0)
            duration = float(event.get("duration") or 0.0)
            if at > narration_at - 0.2 + 0.015 or at + duration > narration_at + 0.015:
                metrics["late_visual_events"] += 1
                errors.append(f"{slide_id}: visual is not established before narration ({at:.3f}+{duration:.3f} vs {narration_at:.3f})")

        composition = scene.get("composition") if isinstance(scene.get("composition"), dict) else {}
        event_beat_ids = {
            str(event.get("narration_beat_id") or "")
            for event in animation.get("events", []) or []
            if isinstance(event, dict) and event.get("link_to_narration") is not False
        }
        if title_beat_ids and not title_beat_ids.issubset(event_beat_ids):
            metrics["title_animation_missing"] += 1
            errors.append(f"{slide_id}: narrated title/subtitle is missing a Reveal event")
        elif not title_beat_ids and not composition.get("static_header_in_base"):
            metrics["static_header_missing"] += 1
            errors.append(f"{slide_id}: non-narrated title header is not composited into base")

    mask_result_path = Path(str(case_state.get("mask_result") or ""))
    mask_result = read_json(mask_result_path) if mask_result_path.exists() else {}
    metrics["mask_complete"] = bool(mask_result.get("complete", True))
    metrics["mask_updated_groups"] = int(mask_result.get("updated_group_count") or 0)
    metrics["mask_slides"] = len(mask_result.get("slides", []) or [])
    if not metrics["mask_complete"]:
        errors.append("AI Mask did not report complete=true")
    for item in mask_result.get("slides", []) or []:
        if not isinstance(item, dict):
            continue
        quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
        if quality and not quality.get("passed"):
            errors.append(f"{item.get('slide_id')}: AI Mask pixel quality failed")
        if int(quality.get("overlap_pixel_count") or 0) != 0:
            errors.append(f"{item.get('slide_id')}: overlapping Mask pixels")
        if int(quality.get("unassigned_component_count") or 0) != 0:
            errors.append(f"{item.get('slide_id')}: unassigned visual components")
        if float(quality.get("foreground_coverage_ratio") or 0.0) < 0.995:
            errors.append(f"{item.get('slide_id')}: foreground coverage below 99.5%")

    video_path = run_dir / "videos" / str(case_state.get("video_filename") or "")
    if not video_path.exists() or video_path.stat().st_size <= 0:
        errors.append(f"video is missing or empty: {video_path}")
    else:
        probe = probe_video(video_path)
        duration = float((probe.get("format") or {}).get("duration") or 0.0)
        streams = probe.get("streams") or []
        video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
        metrics.update(
            {
                "video_bytes": video_path.stat().st_size,
                "video_duration_sec": round(duration, 3),
                "video_width": video_stream.get("width"),
                "video_height": video_stream.get("height"),
                "video_pix_fmt": video_stream.get("pix_fmt"),
                "video_color_space": video_stream.get("color_space"),
                "has_audio_stream": bool(audio_stream),
            }
        )
        if duration <= 0 or not audio_stream:
            errors.append("rendered MP4 has no duration or audio stream")
        if (video_stream.get("width"), video_stream.get("height")) != (1920, 1080):
            errors.append("rendered MP4 is not 1920x1080")
        if video_stream.get("pix_fmt") != "yuv420p" or video_stream.get("color_space") != "bt709":
            errors.append("rendered MP4 is not yuv420p/bt709")
        contact_dir = output_dir / "contact_sheets" / case["slug"]
        metrics["contact_sheet"] = str(extract_contact_sheet(video_path, contact_dir, duration))

    if metrics["mask_updated_groups"] <= 0:
        warnings.append("AI Mask reused existing groups or returned zero updated groups")
    return {
        "case": case,
        "project_id": case_state.get("project_id"),
        "run_dir": str(run_dir),
        "video": str(video_path),
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "checked_at": now(),
    }


def write_summary(output_dir: Path, state: dict[str, Any], cases: list[dict[str, str]]) -> None:
    rows = []
    qa_results = []
    for case in cases:
        case_state = state.get("cases", {}).get(case["slug"], {})
        qa_value = str(case_state.get("qa_result") or "").strip()
        qa_path = Path(qa_value) if qa_value else None
        qa = read_json(qa_path) if qa_path is not None and qa_path.is_file() else {}
        if qa:
            qa_results.append(qa)
        metrics = qa.get("metrics") or {}
        rows.append(
            "| {name} | {mode} | {stage} | {slides} | {masks} | {duration} | {result} |".format(
                name=case["name"],
                mode=case["mode"],
                stage=case_state.get("stage") or "未开始",
                slides=metrics.get("slide_count", "-"),
                masks=metrics.get("mask_updated_groups", "-"),
                duration=metrics.get("video_duration_sec", "-"),
                result="通过" if qa.get("passed") else "未通过",
            )
        )
    all_passed = len(qa_results) == len(cases) and all(result.get("passed") for result in qa_results)
    content = "\n".join(
        [
            "# 完整视频流程验收报告",
            "",
            f"- 生成时间：{now()}",
            f"- 总体结果：{'通过' if all_passed else '未完成或有失败'}",
            "- 图片来源：全部由本地 Pillow 依据实际 visual_contract 绘制并上传；未调用图片生成 API。",
            "- 覆盖流程：主题生成/文章导入 → 文章到 Slides → Slides 到可视化 → 本地图上传 → AI Mask → Reveal 资产 → 旁白 → TTS → 视频渲染 → MP4/字幕/时间轴/Mask 质检。",
            "",
            "| 项目 | 输入模式 | 当前阶段 | Slides | Mask 语块 | 视频秒数 | 结果 |",
            "|---|---|---:|---:|---:|---:|---|",
            *rows,
            "",
            "## 本轮固定质量门",
            "",
            "- spoken_text 不允许跨语块完全重复。",
            "- 字幕不允许标点独占，也不允许 0.35 秒以内的短暂空白闪烁。",
            "- 动态画面必须在对应语音前至少 0.2 秒完整出现。",
            "- 主标题必须作为一个完整标题组进入静态底图，不能拆成动态残片；不生成页面副标题。",
            "- AI Mask 前景覆盖率至少 99.5%，无重叠像素、无未分配组件。",
            "- MP4 必须为 1920×1080、yuv420p、BT.709 且包含音轨。",
            "",
            "## 产物位置",
            "",
            f"- 状态：`{output_dir / 'state.json'}`",
            f"- 单轮 QA：`{output_dir / 'qa'}`",
            f"- Mask 结果：`{output_dir / 'mask_results'}`",
            f"- 视频抽帧：`{output_dir / 'contact_sheets'}`",
        ]
    )
    (output_dir / "report.md").write_text(content + "\n", encoding="utf-8")
    write_json(output_dir / "report.json", {"passed": all_passed, "cases": qa_results, "generated_at": now()})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--in-process", action="store_true", help="Load the current FastAPI app directly instead of using a running server.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case", choices=[case["slug"] for case in CASES])
    parser.add_argument(
        "--restart-from",
        choices=STAGES[1:],
        help="Re-run this stage and every later stage for the selected case(s).",
    )
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "state.json"
    state = read_json(state_path) if state_path.exists() else {"version": "e2e_five_video_v1", "created_at": now(), "cases": {}}
    selected = [case for case in CASES if not args.case or case["slug"] == args.case]
    api = Api(args.base_url, in_process=args.in_process)
    failed = False
    try:
        api.get("/api/projects", "server preflight")
        for case in selected:
            case_index = CASES.index(case)
            if args.restart_from:
                case_state = state.setdefault("cases", {}).get(case["slug"])
                if isinstance(case_state, dict) and case_state.get("project_id"):
                    restart_index = STAGES.index(args.restart_from)
                    case_state["stage"] = STAGES[restart_index - 1]
                    case_state.pop("error", None)
                    case_state["restart_from"] = args.restart_from
                    case_state["updated_at"] = now()
                    write_json(state_path, state)
            try:
                run_case(api, case, case_index, state, state_path, output_dir)
            except Exception as exc:
                failed = True
                case_state = state.setdefault("cases", {}).setdefault(case["slug"], {"case": case})
                case_state["error"] = str(exc)
                case_state["failed_at"] = now()
                write_json(state_path, state)
                print(f"FAILED {case['name']}: {exc}", file=sys.stderr, flush=True)
                if not args.continue_on_error:
                    break
    finally:
        api.close()
        write_summary(output_dir, state, selected)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
