#!/usr/bin/env python3
"""Generate a first-pass visual_contract.json from article.md.

This is a deterministic scaffold generator. It does not replace editorial review,
but it makes the pipeline runnable before a model or human refines each visual
anchor and narration beat.
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


def build_slide(slide_index: int, section: dict[str, Any]) -> dict[str, Any]:
    slide_id = f"slide_{slide_index:03d}"
    title_text = clean_line(str(section.get("title") or f"第{slide_index}页"))[:24]
    sentences = split_sentences(str(section.get("text", "")))
    points = key_points(str(section.get("text", "")), count=3)
    core = compact_summary(sentences)
    subtitle_text = short_label(core, 16)

    visual_groups: list[dict[str, Any]] = [
        {
            "id": "title_group",
            "role": "title",
            "visible_text": title_text,
            "visual_anchor": "顶部主标题",
            "narration_function": "引出本页主题",
            "reveal_order": 1,
        },
        {
            "id": "subtitle_group",
            "role": "subtitle",
            "visible_text": subtitle_text,
            "visual_anchor": "标题下方副标题",
            "narration_function": "给出本页理解角度",
            "reveal_order": 2,
        },
    ]

    narration_beats: list[dict[str, Any]] = []
    for point_index, point in enumerate(points, start=1):
        group_id = f"body_group_{point_index:02d}"
        label = short_label(point)
        visual_groups.append(
            {
                "id": group_id,
                "role": "content_body" if point_index != 2 else "diagram",
                "visible_text": label,
                "visual_anchor": f"第{point_index}个内容区：{label}",
                "narration_function": point[:80],
                "reveal_order": point_index + 2,
            }
        )
        narration_beats.append(
            {
                "id": f"beat_{point_index:02d}",
                "group_id": group_id,
                "visible_anchor": label,
                "spoken_intent": point[:90],
                "spoken_text": f"看这一块“{label}”：{point[:90]}",
            }
        )

    summary_label = short_label(core, 12)
    visual_groups.append(
        {
            "id": "summary_group",
            "role": "summary",
            "visible_text": summary_label,
            "visual_anchor": "底部总结区",
            "narration_function": "收束本页观点",
            "reveal_order": len(visual_groups) + 1,
        }
    )
    narration_beats.append(
        {
            "id": f"beat_{len(narration_beats) + 1:02d}",
            "group_id": "summary_group",
            "visible_anchor": summary_label,
            "spoken_intent": "总结本页核心观点",
            "spoken_text": f"最后记住“{summary_label}”：{core}",
        }
    )

    return {
        "slide_id": slide_id,
        "slide_purpose": core,
        "main_title": title_text,
        "subtitle": subtitle_text,
        "core_message": core,
        "visual_groups": visual_groups,
        "narration_beats": narration_beats,
    }


def build_contract(article_path: Path, min_slides: int, max_slides: int, topic_name: str | None) -> dict[str, Any]:
    inferred_title, sections = parse_article(article_path)
    title = topic_name or inferred_title
    chunks = chunk_sections(sections, min_slides=min_slides, max_slides=max_slides)
    slides = [build_slide(index, section) for index, section in enumerate(chunks, start=1)]
    return {
        "version": "visual_contract_v1",
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
        contract = build_contract(article.resolve(), min_slides=args.min_slides, max_slides=args.max_slides, topic_name=args.topic_name)
        write_json(out.resolve(), contract)
    except ContractBuildError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
