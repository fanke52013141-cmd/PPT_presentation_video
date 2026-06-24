#!/usr/bin/env python3
"""Generate a first-pass visual_contract.json from article.md.

The contract is the minimal semantic mapping source for the pipeline: slide content
units, visual groups, narration beats, and mask targets live in one file. It is a
runnable scaffold and still benefits from model or editorial refinement.

This deterministic scaffold supports the same project-level subtitle policy used
by the AI planner: all slides have subtitles, or no slides have subtitles.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


class ContractBuildError(RuntimeError):
    pass


SUBTITLE_POLICY_WITH_SUBTITLE = "all_slides_have_subtitle"
SUBTITLE_POLICY_NO_SUBTITLE = "no_slides_have_subtitle"
ALLOWED_SUBTITLE_POLICIES = {SUBTITLE_POLICY_WITH_SUBTITLE, SUBTITLE_POLICY_NO_SUBTITLE}

PUNCT_RE = re.compile(r"[\s\u3000，。！？；：、,.!?;:（）()《》<>\[\]【】\"'`]+")
SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])\s*")
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^)]*\)", lambda m: m.group(0).split("]", 1)[0].lstrip("["), text)
    text = re.sub(r"[*_`>#-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    plain = strip_markdown(text)
    parts = [clean_line(part) for part in SENTENCE_RE.split(plain) if clean_line(part)]
    if not parts and plain:
        return [plain]
    return parts


def short_label(text: str, max_chars: int = 9) -> str:
    text = PUNCT_RE.sub("", text)
    if not text:
        return "关键点"
    return text[:max_chars]


def compact_summary(sentences: list[str], max_chars: int = 46) -> str:
    joined = "".join(sentences[:2]).strip()
    if not joined:
        return "本页解释一个关键观点。"
    return joined[:max_chars]


def numbered_body_label(index: int) -> str:
    return f"第{index}点"


def detailed_spoken_text(label: str, point: str, index: int, max_chars: int = 180) -> str:
    point = clean_line(point)
    if not point:
        return f"{numbered_body_label(index)}是“{label}”。这里需要结合画面中的这一块来理解。"
    return (
        f"{numbered_body_label(index)}是“{label}”。"
        f"这里的意思是，{point}"
        f"请对应看画面中标注为“{label}”的这一块，它就是这句话的视觉说明。"
    )[:max_chars]


def semantic_group(
    *,
    group_id: str,
    content_unit_id: str,
    role: str,
    visible_text: str,
    source_text: str,
    visual_anchor: str,
    narration_function: str,
    mask_target: str,
    must_include: list[str],
    must_not_include: list[str],
    reveal_order: int,
) -> dict[str, Any]:
    return {
        "id": group_id,
        "content_unit_id": content_unit_id,
        "role": role,
        "visible_text": visible_text,
        "source_text": source_text,
        "visual_anchor": visual_anchor,
        "narration_function": narration_function,
        "mask_target": mask_target,
        "must_include": must_include,
        "must_not_include": must_not_include,
        "reveal_order": reveal_order,
    }


def narration_beat(
    *,
    beat_id: str,
    content_unit_id: str,
    group_id: str,
    visible_anchor: str,
    spoken_intent: str,
    spoken_text: str,
) -> dict[str, Any]:
    return {
        "id": beat_id,
        "content_unit_id": content_unit_id,
        "group_id": group_id,
        "visible_anchor": visible_anchor,
        "spoken_intent": spoken_intent,
        "spoken_text": spoken_text,
    }


def parse_article(path: Path) -> tuple[str, list[dict[str, Any]]]:
    if not path.exists():
        raise ContractBuildError(f"Missing article: {path}")
    raw = path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        raise ContractBuildError(f"Article is empty: {path}")
    title = path.stem
    sections: list[dict[str, Any]] = []
    current_title = ""
    current_lines: list[str] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        match = HEADING_RE.match(line)
        if match:
            if not title or title == path.stem:
                title = clean_line(match.group(2))
            if current_lines:
                sections.append({"title": current_title or title, "text": "\n".join(current_lines)})
                current_lines = []
            current_title = clean_line(match.group(2))
            continue
        if line:
            current_lines.append(line)
    if current_lines:
        sections.append({"title": current_title or title, "text": "\n".join(current_lines)})
    if not sections:
        sections = [{"title": title, "text": raw}]
    return title, sections


def chunk_sections(sections: list[dict[str, Any]], min_slides: int, max_slides: int) -> list[dict[str, Any]]:
    if len(sections) >= min_slides:
        return sections[:max_slides]
    all_sentences: list[str] = []
    for section in sections:
        all_sentences.extend(split_sentences(str(section.get("text", ""))))
    target = min(max(min_slides, len(sections)), max_slides)
    if len(all_sentences) < target:
        return sections
    chunks: list[dict[str, Any]] = []
    size = max(1, round(len(all_sentences) / target))
    for index in range(0, len(all_sentences), size):
        if len(chunks) >= max_slides:
            break
        part = all_sentences[index : index + size]
        chunks.append({"title": short_label(part[0], 14), "text": "".join(part)})
    return chunks


def key_points(text: str, count: int = 3) -> list[str]:
    sentences = split_sentences(text)
    points = [sentence for sentence in sentences if len(PUNCT_RE.sub("", sentence)) >= 6]
    if not points:
        points = sentences or [text]
    return points[:count]


def default_layout_type(points: list[str]) -> str:
    if len(points) >= 3:
        return "cause_effect_chain"
    if len(points) == 2:
        return "left_right_comparison"
    return "hero_diagram"


def build_slide(slide_index: int, section: dict[str, Any], subtitle_policy: str) -> dict[str, Any]:
    slide_id = f"slide_{slide_index:03d}"
    title_text = clean_line(str(section.get("title") or f"第{slide_index}页"))[:24]
    section_text = str(section.get("text", ""))
    sentences = split_sentences(section_text)
    points = key_points(section_text, count=3)
    core = compact_summary(sentences)
    subtitle_text = short_label(core, 16) if subtitle_policy == SUBTITLE_POLICY_WITH_SUBTITLE else ""
    layout_type = default_layout_type(points)

    visual_groups: list[dict[str, Any]] = [
        semantic_group(
            group_id="title_group",
            content_unit_id="title_main",
            role="title",
            visible_text=title_text,
            source_text=title_text,
            visual_anchor="顶部主标题",
            narration_function="引出本页主题。",
            mask_target="覆盖完整主标题和标题附近的强调装饰。",
            must_include=["主标题文字", "标题强调装饰"],
            must_not_include=["body_group_01", "summary_group"],
            reveal_order=1,
        )
    ]

    if subtitle_policy == SUBTITLE_POLICY_WITH_SUBTITLE:
        visual_groups.append(
            semantic_group(
                group_id="subtitle_group",
                content_unit_id="title_sub",
                role="subtitle",
                visible_text=subtitle_text,
                source_text=core,
                visual_anchor="标题下方副标题",
                narration_function="辅助展示本页理解角度；是否讲解由 narration_beats 决定。",
                mask_target="覆盖完整副标题和副标题下方装饰线。",
                must_include=["副标题文字", "副标题装饰线"],
                must_not_include=["title_group", "body_group_01"],
                reveal_order=2,
            )
        )

    narration_beats: list[dict[str, Any]] = [
        narration_beat(
            beat_id="beat_title",
            content_unit_id="title_main",
            group_id="title_group",
            visible_anchor=title_text,
            spoken_intent="引出本页主题",
            spoken_text=f"这一页我们看“{title_text}”。接下来我会按画面中的几个内容块，把这个主题拆开讲清楚。",
        )
    ]

    body_group_ids: list[str] = []
    body_order_offset = 3 if subtitle_policy == SUBTITLE_POLICY_WITH_SUBTITLE else 2
    for point_index, point in enumerate(points, start=1):
        group_id = f"body_group_{point_index:02d}"
        content_unit_id = f"body_{point_index:02d}"
        label = short_label(point)
        body_group_ids.append(group_id)
        role = "content_body" if point_index != 2 else "diagram"
        visual_groups.append(
            semantic_group(
                group_id=group_id,
                content_unit_id=content_unit_id,
                role=role,
                visible_text=label,
                source_text=point,
                visual_anchor=f"第{point_index}个内容区：{label}",
                narration_function=point[:100],
                mask_target=f"覆盖第{point_index}个内容区的完整视觉表达，包括标签、卡片/图标、局部箭头和说明文字。",
                must_include=["内容区边界或视觉主体", "可见标签", "相关图标", "局部箭头或连接符", "局部说明文字"],
                must_not_include=[
                    gid
                    for gid in ["title_group", "subtitle_group", "summary_group", *body_group_ids]
                    if gid != group_id and not (subtitle_policy == SUBTITLE_POLICY_NO_SUBTITLE and gid == "subtitle_group")
                ],
                reveal_order=point_index + body_order_offset,
            )
        )
        narration_beats.append(
            narration_beat(
                beat_id=f"beat_{point_index:02d}",
                content_unit_id=content_unit_id,
                group_id=group_id,
                visible_anchor=label,
                spoken_intent=point[:110],
                spoken_text=detailed_spoken_text(label, point, point_index),
            )
        )

    summary_label = short_label(core, 12)
    visual_groups.append(
        semantic_group(
            group_id="summary_group",
            content_unit_id="summary",
            role="summary",
            visible_text=summary_label,
            source_text=core,
            visual_anchor="主体内容区内的总结区",
            narration_function="收束本页观点",
            mask_target="覆盖主体内容区内的完整总结标签、强调符号和总结卡片，不进入底部字幕安全区。",
            must_include=["总结标签", "总结卡片或强调区", "总结强调符号"],
            must_not_include=["title_group", *body_group_ids],
            reveal_order=len(visual_groups) + 1,
        )
    )
    narration_beats.append(
        narration_beat(
            beat_id="beat_summary",
            content_unit_id="summary",
            group_id="summary_group",
            visible_anchor=summary_label,
            spoken_intent="总结本页核心观点",
            spoken_text=f"最后回到“{summary_label}”。这一页的核心结论是：{core}",
        )
    )

    return {
        "slide_id": slide_id,
        "slide_purpose": core,
        "main_title": title_text,
        "subtitle": subtitle_text,
        "core_message": core,
        "layout_type": layout_type,
        "visual_metaphor": "选择一个能直接解释本页核心观点的强主视觉。",
        "composition": {
            "primary_focus": "hero_visual",
            "reading_order": "left_to_right",
            "hierarchy": ["main_title", "hero_visual", "supporting_groups", "summary"],
            "group_count": len(visual_groups),
        },
        "visual_groups": visual_groups,
        "narration_beats": narration_beats,
    }


def build_contract(article_path: Path, min_slides: int, max_slides: int, topic_name: str | None, subtitle_policy: str) -> dict[str, Any]:
    if subtitle_policy not in ALLOWED_SUBTITLE_POLICIES:
        raise ContractBuildError(f"Unsupported subtitle policy: {subtitle_policy}")
    inferred_title, sections = parse_article(article_path)
    title = topic_name or inferred_title
    chunks = chunk_sections(sections, min_slides=min_slides, max_slides=max_slides)
    slides = [build_slide(index, section, subtitle_policy=subtitle_policy) for index, section in enumerate(chunks, start=1)]
    return {
        "version": "visual_contract_v1",
        "presentation_policy": {
            "subtitle_policy": subtitle_policy,
            "subtitle_decided_by": "deterministic_scaffold",
            "subtitle_rationale": (
                "Scaffold default; AI storyboard generation should replace this with a project-level content decision."
                if subtitle_policy == SUBTITLE_POLICY_NO_SUBTITLE
                else "Scaffold was configured to include subtitles on every slide."
            ),
            "default_visual_group_count": "3-5",
            "layout_diversity": "high",
        },
        "mapping_policy": {
            "semantic_unit": "visual_group",
            "id_chain": "narration_beat.id -> content_unit_id -> visual_group.id -> reveal_manifest.group.id -> box/mask",
            "narration_policy": "narration_beats exclusively determine which visual groups are spoken",
        },
        "topic": {
            "topic_id": re.sub(r"[^A-Za-z0-9_\-]+", "_", article_path.stem).strip("_") or "topic",
            "topic_name": title,
            "topic_summary": compact_summary(split_sentences("\n".join(str(s.get("text", "")) for s in chunks)), 80),
        },
        "slides": slides,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate visual_contract.json from article.md.")
    parser.add_argument("--article", type=Path, help="Article markdown path. Defaults to <run-dir>/inputs/article.md")
    parser.add_argument("--run-dir", type=Path, help="Run directory. Used for default input/output paths.")
    parser.add_argument("--out", type=Path, help="Output contract path. Defaults to <run-dir>/planning/visual_contract.json")
    parser.add_argument("--topic-name")
    parser.add_argument("--min-slides", type=int, default=8)
    parser.add_argument("--max-slides", type=int, default=14)
    parser.add_argument(
        "--subtitle-policy",
        choices=sorted(ALLOWED_SUBTITLE_POLICIES),
        default=SUBTITLE_POLICY_NO_SUBTITLE,
        help="Project-level subtitle policy for deterministic scaffold output.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.article and not args.run_dir:
        print("Error: provide --article or --run-dir", file=sys.stderr)
        return 2
    article = args.article or args.run_dir / "inputs" / "article.md"
    out = args.out or args.run_dir / "planning" / "visual_contract.json"
    if out.exists() and not args.overwrite:
        print(f"Error: output exists, use --overwrite: {out}", file=sys.stderr)
        return 2
    try:
        contract = build_contract(
            article.resolve(),
            min_slides=args.min_slides,
            max_slides=args.max_slides,
            topic_name=args.topic_name,
            subtitle_policy=args.subtitle_policy,
        )
        write_json(out.resolve(), contract)
    except ContractBuildError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
