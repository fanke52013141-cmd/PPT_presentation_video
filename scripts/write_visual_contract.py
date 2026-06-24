#!/usr/bin/env python3
"""Generate a first-pass visual_contract.json from article.md.

This deterministic scaffold is intentionally simple and narration-first. It
creates titles, optional project-level subtitles, body content, narration, and a
small set of post-design visual anchors. The anchors support Mask/Reveal review;
they are not a rigid page layout template.
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
CLAUSE_RE = re.compile(r"[，,]\s*")
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
NUMBERED_HEADING_RE = re.compile(
    r"^(?:第?[一二三四五六七八九十百千万\d]+[章节部分、.．]\s*)(.+?)\s*$"
)
TERMINAL_PUNCT_RE = re.compile(r"[。！？!?；;，,、：:]$")
PLAIN_HEADING_KEYWORDS = (
    "定义",
    "对比",
    "流程",
    "组件",
    "总结",
    "价值",
    "方法",
    "步骤",
    "规则",
    "触发器",
    "生成器",
    "评估器",
    "反馈",
    "修正",
    "终止",
    "升级",
    "Trigger",
    "Generator",
    "Evaluator",
    "Repair",
    "Stop",
)


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


def looks_like_document_title(line: str) -> bool:
    line = clean_line(strip_markdown(line))
    if not line:
        return False
    if len(line) > 90:
        return False
    if any(token in line for token in ("完整解读", "指南", "教程", "解析", "科普", "方案")):
        return True
    return not TERMINAL_PUNCT_RE.search(line) and len(PUNCT_RE.sub("", line)) <= 42


def extract_heading_text(line: str) -> str | None:
    line = clean_line(line)
    if not line:
        return None
    match = HEADING_RE.match(line)
    if match:
        return clean_line(match.group(2))
    match = NUMBERED_HEADING_RE.match(line)
    if match:
        return clean_line(match.group(1))
    if TERMINAL_PUNCT_RE.search(line):
        return None
    plain = clean_line(strip_markdown(line))
    if not plain or len(PUNCT_RE.sub("", plain)) > 34:
        return None
    if any(keyword in plain for keyword in PLAIN_HEADING_KEYWORDS):
        return plain
    if re.search(r"[A-Za-z]{2,}", plain) and len(plain) <= 28:
        return plain
    return None


def split_sentences(text: str) -> list[str]:
    plain = strip_markdown(text)
    parts = [clean_line(part) for part in SENTENCE_RE.split(plain) if clean_line(part)]
    if not parts and plain:
        return [plain]
    return parts


def short_label(text: str, max_chars: int = 9) -> str:
    text = clean_line(strip_markdown(text))
    text = re.split(r"[。！？!?；;：:\n]", text, maxsplit=1)[0]
    text = re.sub(r"^[\-—•·\d一二三四五六七八九十、.．\s]+", "", text).strip()
    text = re.sub(r"^(是|为|核心是|核心在于)\s*", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return "关键点"
    return text[:max_chars]


def compact_summary(sentences: list[str], max_chars: int = 46) -> str:
    joined = "".join(sentences[:2]).strip()
    if not joined:
        return "本页解释一个关键观点。"
    return joined[:max_chars]


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

    lines = [line.rstrip() for line in raw.splitlines()]
    start_index = 0
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        match = HEADING_RE.match(line)
        if match:
            title = clean_line(match.group(2))
            start_index = index + 1
            break
        if looks_like_document_title(line):
            title = clean_line(strip_markdown(line))
            start_index = index + 1
            break
        break

    for raw_line in lines[start_index:]:
        line = raw_line.strip()
        heading = extract_heading_text(line)
        if heading:
            if current_lines:
                sections.append({"title": current_title or title, "text": "\n".join(current_lines)})
                current_lines = []
            current_title = heading
            continue
        if line:
            current_lines.append(line)
    if current_lines:
        sections.append({"title": current_title or title, "text": "\n".join(current_lines)})
    if not sections:
        sections = [{"title": title, "text": raw}]
    return title, sections


def split_long_section(section: dict[str, Any], sentences_per_slide: int = 2) -> list[dict[str, Any]]:
    section_text = str(section.get("text", ""))
    sentences = split_sentences(section_text)
    if len(sentences) <= sentences_per_slide:
        return [section]
    chunks: list[dict[str, Any]] = []
    for index in range(0, len(sentences), sentences_per_slide):
        part = sentences[index : index + sentences_per_slide]
        if not part:
            continue
        title = str(section.get("title") or "").strip()
        if index:
            title = short_label(part[0], 18)
        chunks.append({"title": title or short_label(part[0], 18), "text": " ".join(part)})
    return chunks or [section]


def merge_section_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    titles = [clean_line(str(item.get("title") or "")) for item in group if clean_line(str(item.get("title") or ""))]
    body_parts: list[str] = []
    for item in group:
        title = clean_line(str(item.get("title") or ""))
        text = clean_line(str(item.get("text") or ""))
        if not text:
            continue
        if title and title not in text:
            body_parts.append(f"{title}：{text}")
        else:
            body_parts.append(text)
    merged_title = " / ".join(titles[:2]) if titles else "关键内容"
    return {"title": merged_title[:30].rstrip(" /-—：:，,、"), "text": "\n".join(body_parts)}


def merge_overflow_sections(sections: list[dict[str, Any]], max_slides: int) -> list[dict[str, Any]]:
    if len(sections) <= max_slides:
        return sections
    preserve_count = 2 if max_slides >= 4 else 1
    result = sections[:preserve_count]
    remaining = sections[preserve_count:]
    slots = max(1, max_slides - len(result))
    group_size = max(1, -(-len(remaining) // slots))
    for index in range(0, len(remaining), group_size):
        result.append(merge_section_group(remaining[index : index + group_size]))
    return result[:max_slides]


def chunk_sections(sections: list[dict[str, Any]], min_slides: int, max_slides: int) -> list[dict[str, Any]]:
    if len(sections) > max_slides:
        return merge_overflow_sections(sections, max_slides)
    if len(sections) >= min_slides:
        return sections[:max_slides]
    expanded: list[dict[str, Any]] = []
    for section in sections:
        expanded.extend(split_long_section(section))
    if len(expanded) >= min_slides:
        return expanded[:max_slides]
    all_sentences: list[str] = []
    for section in expanded or sections:
        all_sentences.extend(split_sentences(str(section.get("text", ""))))
    target = min(max(min_slides, len(sections)), max_slides)
    if len(all_sentences) < target:
        return (expanded or sections)[:max_slides]
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
    if len(points) < count:
        clauses = [
            clean_line(part)
            for sentence in sentences or [strip_markdown(text)]
            for part in CLAUSE_RE.split(sentence)
            if len(PUNCT_RE.sub("", clean_line(part))) >= 8
        ]
        if len(points) == 1 and len(points[0]) > 100 and clauses:
            points = clauses[:count]
        else:
            for clause in clauses:
                if clause not in points:
                    points.append(clause)
                if len(points) >= count:
                    break
    if not points:
        points = sentences or [text]
    return points[:count]


def visual_anchor(
    *,
    group_id: str,
    role: str,
    visible_text: str,
    source_text: str,
    order: int,
) -> dict[str, Any]:
    """Return a lightweight post-design anchor compatible with existing validators."""

    return {
        "id": group_id,
        "content_unit_id": group_id,
        "role": role,
        "visible_text": visible_text,
        "source_text": source_text,
        "visual_anchor": f"由生图完成后，在画面中匹配“{visible_text}”对应的区域。",
        "narration_function": source_text[:100] or visible_text,
        "mask_target": f"生图完成后，覆盖与“{visible_text}”对应的完整可见区域。",
        "must_include": ["对应可见区域"],
        "must_not_include": ["无关内容", "底部字幕安全区"],
        "reveal_order": order,
    }


def narration_beat(beat_id: str, group_id: str, visible_anchor: str, spoken_intent: str, spoken_text: str) -> dict[str, Any]:
    return {
        "id": beat_id,
        "content_unit_id": group_id,
        "group_id": group_id,
        "visible_anchor": visible_anchor,
        "spoken_intent": spoken_intent,
        "spoken_text": spoken_text,
    }


def readable_slide_title(raw_title: str, slide_index: int) -> str:
    title = clean_line(strip_markdown(raw_title))
    if "Loop Engineering" in title and "循环工程" in title:
        return "Loop Engineering：循环工程"
    if not title:
        return f"第{slide_index}页"
    return title[:24].rstrip(" /-—：:，,、")


def infer_role(point: str, point_index: int) -> str:
    text = clean_line(point)
    if any(token in text for token in ("原话", "引用", "金句", "我不再")):
        return "quote"
    if any(token in text for token in ("Trigger", "Generator", "Evaluator", "Repair", "Stop", "触发器", "生成器", "评估器", "反馈修正", "终止")):
        return "process_step"
    if any(token in text for token in ("对比", "流程", "闭环", "链路", "→", "->")):
        return "diagram"
    if re.search(r"\d", text):
        return "data_point" if point_index != 1 else "content_body"
    return "content_body"


def build_slide(slide_index: int, section: dict[str, Any], subtitle_policy: str) -> dict[str, Any]:
    slide_id = f"slide_{slide_index:03d}"
    title_text = readable_slide_title(str(section.get("title") or f"第{slide_index}页"), slide_index)
    section_text = str(section.get("text", ""))
    sentences = split_sentences(section_text)
    points = key_points(section_text, count=3)
    core = compact_summary(sentences)
    subtitle_text = short_label(core, 16) if subtitle_policy == SUBTITLE_POLICY_WITH_SUBTITLE else ""

    body_content = points or [core]
    narration = f"这一页我们看“{title_text}”。" + "".join(body_content)

    visual_groups: list[dict[str, Any]] = [
        visual_anchor(
            group_id="title_group",
            role="title",
            visible_text=title_text,
            source_text="页面主标题",
            order=1,
        )
    ]
    next_order = 2
    if subtitle_policy == SUBTITLE_POLICY_WITH_SUBTITLE:
        visual_groups.append(
            visual_anchor(
                group_id="subtitle_group",
                role="subtitle",
                visible_text=subtitle_text,
                source_text="页面副标题",
                order=next_order,
            )
        )
        next_order += 1

    narration_beats: list[dict[str, Any]] = [
        narration_beat(
            "beat_title",
            "title_group",
            title_text,
            "引出本页主题",
            f"这一页我们看“{title_text}”。",
        )
    ]

    for point_index, point in enumerate(body_content, start=1):
        label = short_label(point)
        group_id = f"body_anchor_{point_index:02d}"
        visual_groups.append(
            visual_anchor(
                group_id=group_id,
                role="body_content",
                visible_text=label,
                source_text=point,
                order=next_order,
            )
        )
        next_order += 1
        narration_beats.append(
            narration_beat(
                f"beat_{point_index:02d}",
                group_id,
                label,
                point[:110],
                point,
            )
        )

    return {
        "slide_id": slide_id,
        "slide_purpose": core,
        "main_title": title_text,
        "subtitle": subtitle_text,
        "core_message": core,
        "body_content": body_content,
        "visual_intent": "根据演讲稿自由绘制完整页面；视觉锚点只用于后续 Mask/Reveal 匹配，不作为版式模板。",
        "narration": narration,
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
            "default_visual_anchor_count": "2-5",
            "layout_freedom": "high",
        },
        "mapping_policy": {
            "semantic_unit": "post_design_visual_anchor",
            "id_chain": "narration_beat.id -> visual_anchor.id -> reveal_manifest.group.id -> box/mask",
            "narration_policy": "narration is the source of truth; visual anchors are reviewed after the page is drawn",
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
