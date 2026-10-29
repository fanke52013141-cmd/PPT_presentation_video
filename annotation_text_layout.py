# -*- coding: utf-8 -*-
"""勾画标注模块的统一文字布局层(W3)。

对应交接文档 6.2/5.1:

- 输入受控:图像字节、画布尺寸、引擎配置快照、可选 ROI;引擎实现通过
  ``recognize`` 回调注入(生产为 ``annotation_ocr_baidu``,测试为 stub)。
- 输出规范:候选携带**同一 layout revision 内稳定**的 token/line ID;
  重识别产生新 revision,ID 允许变化,上层按 revision 重绑定。
- 缓存键 = 图像哈希 + 引擎/配置快照 + ROI;命中时零模型请求。
- 粒度诚实:无字级结果时粒度标 ``line``,整行框绝不均分成"字框"。
- 文本纠正:保留原识别文本,纠正值单独存储;字符数变化记录重定位需求。
- 纯模块:不导入 server/FastAPI/数据库;文件写出经 ``write_json_atomic``
  注入,坐标不做换算(引擎坐标即提交图像坐标,画布=1920×1080 时直通)。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from annotation_contracts import ANNOTATION_SCHEMA_VERSION
from annotation_ocr_baidu import BaiduOcrEngineConfig, BaiduOcrResult, build_ocr_cache_key

__all__ = [
    "TEXT_LAYOUT_SCHEMA_VERSION",
    "TEXT_LAYOUT_FILE",
    "TextLayoutDependencies",
    "TextLayoutBuilder",
    "build_layout_payload_from_ocr",
    "load_text_layout",
    "candidate_tokens",
]

TEXT_LAYOUT_SCHEMA_VERSION = 1
TEXT_LAYOUT_FILE = "text_layout.json"


@dataclass(frozen=True)
class TextLayoutDependencies:
    """窄依赖:原子写出 + OCR 引擎配置提供者 + 时钟。"""

    write_json_atomic: Callable[[Any, Any], None]
    read_json_file: Callable[[Any], Any]
    ocr_config_provider: Callable[[], BaiduOcrEngineConfig]
    now_iso: Callable[[], str] = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_layout_payload_from_ocr(
    slide_id: str,
    image_hash: str,
    image_size: Tuple[int, int],
    ocr_result: BaiduOcrResult,
    *,
    layout_revision: int,
    cache_key: str,
    roi: Optional[Sequence[int]] = None,
    created_at: str = "",
) -> Dict[str, Any]:
    """把引擎结果规范化为 text_layout.json 载荷(纯函数)。

    token/line ID 在本 revision 内稳定:行序与字序完全来自引擎返回顺序。
    """
    lines: List[Dict[str, Any]] = []
    token_count = 0
    for line_index, line in enumerate(ocr_result.lines):
        line_id = f"line_{layout_revision:03d}_{line_index:03d}"
        tokens: List[Dict[str, Any]] = []
        for char_index, char in enumerate(line.chars):
            token_id = f"tok_{layout_revision:03d}_{token_count:04d}"
            token_count += 1
            tokens.append(
                {
                    "token_id": token_id,
                    "char": char.char,
                    "polygon": char.polygon,
                }
            )
        lines.append(
            {
                "line_id": line_id,
                "text": line.text,
                "polygon": line.polygon,
                "probability_average": line.probability_average,
                "tokens": tokens,
            }
        )
    return {
        "schema_version": TEXT_LAYOUT_SCHEMA_VERSION,
        "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
        "slide_id": slide_id,
        "layout_revision": layout_revision,
        "image_hash": image_hash,
        "image_size": [image_size[0], image_size[1]],
        "engine": {
            "engine_version": ocr_result.engine_version,
            "granularity": ocr_result.granularity,
            "direction": ocr_result.direction,
            "log_id": ocr_result.log_id,
            "request_elapsed_sec": ocr_result.request_elapsed_sec,
        },
        "cache_key": cache_key,
        "roi": list(roi) if roi else None,
        "reading_order": [line["line_id"] for line in lines],
        "lines": lines,
        # 纠正:token_id -> {"text": str, "chars_changed": bool, "updated_at": str}
        "corrections": {},
        "created_at": created_at,
    }


def candidate_tokens(layout: Dict[str, Any]) -> List[Dict[str, Any]]:
    """展开候选文字 token(供前端点选与规划器使用)。

    有纠正时 quote 取纠正文本;chars_changed 标记边界可能变化。
    """
    corrections = layout.get("corrections") or {}
    tokens: List[Dict[str, Any]] = []
    for line in layout.get("lines", []):
        line_text = str(line.get("text") or "")
        line_tokens = line.get("tokens") or []
        if line_tokens:
            for token in line_tokens:
                correction = corrections.get(token["token_id"])
                tokens.append(
                    {
                        "token_id": token["token_id"],
                        "line_id": line["line_id"],
                        "text": str(correction["text"]) if correction else str(token.get("char") or ""),
                        "original_text": str(token.get("char") or ""),
                        "corrected": correction is not None,
                        "chars_changed": bool(correction and correction.get("chars_changed")),
                        "polygon": token["polygon"],
                        "granularity": "char",
                    }
                )
        else:
            # 行级候选:粒度诚实标 line,不均分字符
            tokens.append(
                {
                    "token_id": line["line_id"],
                    "line_id": line["line_id"],
                    "text": line_text,
                    "original_text": line_text,
                    "corrected": False,
                    "chars_changed": False,
                    "polygon": line["polygon"],
                    "granularity": "line",
                }
            )
    return tokens


class TextLayoutBuilder:
    """页面文字布局的构建与缓存读取。"""

    def __init__(self, dependencies: TextLayoutDependencies):
        self._deps = dependencies

    def layout_path(self, run_dir: str, slide_id: str) -> Any:
        from project_storage import slide_file

        return slide_file(run_dir, slide_id, TEXT_LAYOUT_FILE)

    def load(self, run_dir: str, slide_id: str) -> Optional[Dict[str, Any]]:
        path = self.layout_path(run_dir, slide_id)
        payload = self._deps.read_json_file(path)
        if payload is None:
            return None
        if not isinstance(payload, dict) or payload.get("schema_version") != TEXT_LAYOUT_SCHEMA_VERSION:
            raise ValueError(f"text_layout.json 结构非法: {path}")
        return payload

    def get_or_detect(
        self,
        run_dir: str,
        slide_id: str,
        image_bytes: bytes,
        image_hash: str,
        image_size: Tuple[int, int],
        *,
        recognize: Callable[[bytes, BaiduOcrEngineConfig], BaiduOcrResult],
        roi: Optional[Sequence[int]] = None,
        force: bool = False,
        publish: Optional[Callable[[Dict[str, Any], Optional[Dict[str, Any]]], None]] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """返回 (布局载荷, 是否新识别)。

        缓存命中(相同图像哈希+配置+ROI 且未强制)时零模型请求;强制或
        换图后以 revision+1 重识别,保证 ID 变化可被上层感知。
        """
        existing = None
        try:
            existing = self.load(run_dir, slide_id)
        except ValueError:
            existing = None
        config = self._deps.ocr_config_provider()
        cache_key = build_ocr_cache_key(image_bytes, config, roi=roi)
        if (
            not force
            and existing is not None
            and existing.get("cache_key") == cache_key
            and existing.get("image_hash") == image_hash
        ):
            return existing, False

        result = recognize(image_bytes, config)
        previous_revision = int(existing.get("layout_revision") or 0) if existing else 0
        payload = build_layout_payload_from_ocr(
            slide_id,
            image_hash,
            image_size,
            result,
            layout_revision=previous_revision + 1,
            cache_key=cache_key,
            roi=roi,
            created_at=self._deps.now_iso(),
        )
        # 重识别不继承纠正(原文可能整体变化);纠正随 revision 失效并
        # 由上层对引用旧 token 的目标标记 needs_review。
        if publish is not None:
            publish(payload, existing)
        else:
            self._deps.write_json_atomic(self.layout_path(run_dir, slide_id), payload)
        return payload, True

    def save(self, run_dir: str, slide_id: str, layout: Dict[str, Any]) -> None:
        self._deps.write_json_atomic(self.layout_path(run_dir, slide_id), layout)

    def apply_correction(
        self,
        layout: Dict[str, Any],
        token_id: str,
        corrected_text: str,
    ) -> Tuple[Dict[str, Any], bool]:
        """应用单条候选纠正:保留原识别文本;字符数变化记录重定位需求。

        返回 (新载荷, 是否发生了变化)。未知 token 抛 KeyError。
        """
        known = {token["token_id"] for token in candidate_tokens(layout)}
        if token_id not in known:
            raise KeyError(token_id)
        corrections = dict(layout.get("corrections") or {})
        if corrected_text and isinstance(corrections.get(token_id), dict) and corrections[token_id].get("text") == corrected_text:
            return layout, False
        if not corrected_text:
            if token_id not in corrections:
                return layout, False
            corrections.pop(token_id)
        else:
            original = next(
                (token["original_text"] for token in candidate_tokens(layout) if token["token_id"] == token_id),
                "",
            )
            corrections[token_id] = {
                "text": corrected_text,
                "chars_changed": len(corrected_text) != len(original),
                "updated_at": self._deps.now_iso(),
            }
        updated = dict(layout)
        updated["corrections"] = corrections
        return updated, True
