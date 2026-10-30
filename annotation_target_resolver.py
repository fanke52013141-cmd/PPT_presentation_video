# -*- coding: utf-8 -*-
"""勾画标注的目标短语解析器(R2,第二轮优化方案 5.1)。

职责:从被选择的真实 OCR tokens 构建可画目标;不处理 LLM 请求或文件保存。

- token 按 line_id + 阅读顺序排序,不依赖模型/用户返回顺序。
- 同行连续选择合成一个短语片段(圈整个词/日期);中间有未选字符则拆分;
  跨行拆成多个片段;不同卡片不因文字相同合并。
- 保留每个 token 的原始四边形(不退化为轴对齐外接框)。
- target.quote 取画面文字(OCR/纠正后);anchor.quote 是讲稿文字,两者分离。
- 空间质量检查:字符匹配、连续性、越界、退化框;问题进入 quality_issues。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "TARGET_RESOLVER_VERSION",
    "TargetResolutionError",
    "resolve_phrase_target",
]

TARGET_RESOLVER_VERSION = "target_resolver_v1"

# 邻词安全间距:笔迹外缘与邻词框之间至少保留的像素
NEIGHBOR_SAFETY_PX = 6.0
# 收紧后的最小留白(完全无空间时保留贴边最小圈)
MIN_SIDE_PAD_PX = 2.0


def compute_side_pads(
    layout: Dict[str, Any],
    fragment: Dict[str, Any],
    selected_token_ids: Sequence[str],
) -> Tuple[Optional[float], Optional[float]]:
    """按同行邻词距离计算 (左留白, 右留白);无邻词侧返回 None(用默认)。

    方案 4.3"邻词排除区":留白 = 与邻词框的间隙 - 安全间距,收紧但不小于
    MIN_SIDE_PAD_PX。确定性,不依赖随机。
    """
    selected = set(str(v) for v in selected_token_ids)
    line_id = str(fragment.get("line_id") or "")
    xs = [p[0] for poly in fragment["polygons"] for p in poly]
    ys = [p[1] for poly in fragment["polygons"] for p in poly]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)

    left_gap: Optional[float] = None
    right_gap: Optional[float] = None
    for token in _expand_candidates(layout):
        if str(token.get("line_id") or "") != line_id or str(token["token_id"]) in selected:
            continue
        txs = [p[0] for p in token["polygon"]]
        tys = [p[1] for p in token["polygon"]]
        t_left, t_right = min(txs), max(txs)
        t_top, t_bottom = min(tys), max(tys)
        # 仅考虑纵向重叠的同行邻词
        if t_bottom < top or t_top > bottom:
            continue
        if t_right <= left:
            gap = left - t_right
            left_gap = gap if left_gap is None else min(left_gap, gap)
        elif t_left >= right:
            gap = t_left - right
            right_gap = gap if right_gap is None else min(right_gap, gap)
    pad_left = max(MIN_SIDE_PAD_PX, left_gap - NEIGHBOR_SAFETY_PX) if left_gap is not None else None
    pad_right = max(MIN_SIDE_PAD_PX, right_gap - NEIGHBOR_SAFETY_PX) if right_gap is not None else None
    return pad_left, pad_right


class TargetResolutionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code  # unknown_token | duplicate_token | stale_layout | degenerate_box
        self.message = message


@dataclass(frozen=True)
class PhraseFragment:
    """同行连续 token 组成的短语片段。"""

    token_ids: Tuple[str, ...]
    polygons: Tuple[Tuple[Tuple[int, int], ...], ...]
    text: str
    line_id: str


def _token_entries(
    layout: Dict[str, Any],
    token_ids: Sequence[str],
    *,
    expected_layout_revision: Optional[int],
) -> List[Dict[str, Any]]:
    """按候选表把 token_id 解析回完整条目,并按行/阅读顺序排序。"""
    if expected_layout_revision is not None:
        layout_revision = layout.get("layout_revision")
        if layout_revision != expected_layout_revision:
            raise TargetResolutionError(
                "stale_layout",
                f"layout revision 已过期: 期望 {expected_layout_revision},当前 {layout_revision}",
            )
    known: Dict[str, Dict[str, Any]] = {}
    line_rank: Dict[str, int] = {}
    token_rank: Dict[str, int] = {}
    for index, token in enumerate(_expand_candidates(layout)):
        known[str(token["token_id"])] = token
        token_rank[str(token["token_id"])] = index
        line_rank.setdefault(str(token.get("line_id") or ""), len(line_rank))
    seen: set[str] = set()
    entries: List[Dict[str, Any]] = []
    for token_id in token_ids:
        key = str(token_id)
        token = known.get(key)
        if token is None:
            raise TargetResolutionError("unknown_token", f"候选 {token_id} 不存在于当前 layout")
        if key in seen:
            raise TargetResolutionError("duplicate_token", f"候选 {token_id} 重复选择")
        seen.add(key)
        polygon = token.get("polygon") or []
        if len(polygon) != 4 or any(len(p) != 2 for p in polygon):
            raise TargetResolutionError("degenerate_box", f"候选 {token_id} 的框不是 4 点四边形")
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        if max(xs) - min(xs) < 1 or max(ys) - min(ys) < 1:
            raise TargetResolutionError("degenerate_box", f"候选 {token_id} 的框退化")
        entries.append({**token, "_order": len(entries)})
    entries.sort(key=lambda t: (line_rank.get(str(t.get("line_id") or ""), 0), token_rank[t["token_id"]]))
    return entries


def _expand_candidates(layout: Dict[str, Any]) -> List[Dict[str, Any]]:
    """layout → 候选条目(与 annotation_text_layout.candidate_tokens 同口径)。"""
    from annotation_text_layout import candidate_tokens

    return candidate_tokens(layout)


def candidate_review_issues(tokens):
    """Flag uncertain OCR and tiny targets without guessing or rewriting text."""
    issues = []
    scores = [t.get("probability_average") for t in tokens if not t.get("corrected")]
    if any(isinstance(score, (int, float)) and (not math.isfinite(score) or score < .85) for score in scores):
        issues.append({"code": "ocr_low_confidence", "message": "OCR 置信度偏低，请对照原图核对文字与位置"})
    for token in tokens:
        polygon = token.get("polygon") or []
        if len(polygon) == 4 and min(math.dist(polygon[0], polygon[3]), math.dist(polygon[1], polygon[2])) < 12:
            issues.append({"code": "small_text_target", "message": "目标文字较小，请放大核对标注边界"})
            break
    return issues


def resolve_phrase_target(
    *,
    layout: Dict[str, Any],
    token_ids: Sequence[str],
    expected_layout_revision: Optional[int] = None,
) -> Dict[str, Any]:
    """解析目标短语:排序、同行连续合并、跨行拆分、质量检查。"""
    entries = _token_entries(layout, token_ids, expected_layout_revision=expected_layout_revision)
    corrections = layout.get("corrections") or {}

    fragments: List[PhraseFragment] = []
    current: List[Dict[str, Any]] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text_parts: List[str] = []
        for token in current:
            correction = corrections.get(token["token_id"])
            text_parts.append(str(correction["text"]) if correction else str(token.get("original_text") or token.get("text") or ""))
        fragments.append(
            PhraseFragment(
                token_ids=tuple(str(t["token_id"]) for t in current),
                polygons=tuple(tuple((int(p[0]), int(p[1])) for p in t["polygon"]) for t in current),
                text="".join(text_parts),
                line_id=str(current[0].get("line_id") or ""),
            )
        )
        current = []

    previous: Optional[Dict[str, Any]] = None
    for token in entries:
        line_id = str(token.get("line_id") or "")
        if previous is None:
            current = [token]
        elif line_id == str(previous.get("line_id") or "") and _adjacent_in_line(layout, previous, token):
            current.append(token)
        else:
            flush()
            current = [token]
        previous = token
    flush()

    screen_quote = "".join(fragment.text for fragment in fragments)
    issues: List[Dict[str, str]] = candidate_review_issues(entries)
    if len(fragments) > 1:
        issues.append({"code": "multi_fragment", "message": f"目标跨 {len(fragments)} 个片段(跨行或不连续)"})
    raw_granularity = str(entries[0].get("granularity") or "char") if entries else "char"
    # 同行连续多字合并成短语后,目标粒度按"词"处理;整行候选仍是 line
    granularity = raw_granularity
    if raw_granularity == "char" and sum(len(f.token_ids) for f in fragments) > 1:
        granularity = "word"
    return {
        "resolver_version": TARGET_RESOLVER_VERSION,
        "ordered_token_ids": [str(t["token_id"]) for t in entries],
        "screen_quote": screen_quote,
        "granularity": granularity,
        "fragments": [
            {
                "token_ids": list(f.token_ids),
                "polygons": [list(map(list, poly)) for poly in f.polygons],
                "text": f.text,
                "line_id": f.line_id,
            }
            for f in fragments
        ],
        "quality_issues": issues,
    }


def _adjacent_in_line(layout: Dict[str, Any], first: Dict[str, Any], second: Dict[str, Any]) -> bool:
    """同一行内两个 token 是否阅读顺序相邻(中间无未选字符)。"""
    line_id = str(first.get("line_id") or "")
    order: List[str] = []
    for token in _expand_candidates(layout):
        if str(token.get("line_id") or "") == line_id:
            order.append(str(token["token_id"]))
    try:
        i1, i2 = order.index(str(first["token_id"])), order.index(str(second["token_id"]))
    except ValueError:
        return False
    if abs(i1 - i2) != 1:
        return False
    a, b = first.get("polygon") or [], second.get("polygon") or []
    if len(a) == len(b) == 4:
        height = max(math.dist(a[0], a[3]), math.dist(b[0], b[3]), 1)
        edge_a = ((a[1][0] + a[2][0]) / 2, (a[1][1] + a[2][1]) / 2)
        edge_b = ((b[0][0] + b[3][0]) / 2, (b[0][1] + b[3][1]) / 2)
        if math.dist(edge_a, edge_b) > height * 2:
            return False  # OCR may assign two independent cards to one line.
    return True
