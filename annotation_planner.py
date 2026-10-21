# -*- coding: utf-8 -*-
"""勾画标注 AI 规划器(W3):最小载荷、输出校验、与人工修改合并。

- 窄 LLM 依赖:``llm_generate(system, user) -> dict`` 由装配注入(生产为
  ``json_llm_service.generate_json_with_configured_llm`` 的受控包装);
  本模块不导入 server、不持有客户端。
- 格式损坏最多一次修复/重试(LLM 服务内建);解析失败保留现有草稿并报告。
- 重规划不覆盖 locked/modified 条目;AI 初始建议作为可恢复快照保存
  (页级 ai_suggestion_snapshot)。
- 校验:beat 存在、码点切片与 quote 一致、token 存在、样式合法、
  密度上限(默认每页最多 3 条,emphasis=weak 1 条)、重复建议剔除。
"""
from __future__ import annotations
from annotation_contracts import EMPHASIS_LIMITS

import logging
from runtime_support import is_timeout_exception
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Tuple

from annotation_contracts import (
    AnnotationItem,
    AnnotationPage,
    Issue,
    RECOMMENDATION_CATEGORIES,
    anchor_quote_matches,
)
from annotation_prompt_templates import AnnotationPromptStore, compose_plan_prompts

logger = logging.getLogger("PPTStudio.AnnotationPlanner")

VALID_STYLES = ("ellipse", "underline", "highlighter")
MAX_SUGGESTIONS = EMPHASIS_LIMITS
MAX_RANGE_CODEPOINTS = 40


@dataclass(frozen=True)
class AnnotationPlannerDependencies:
    prompt_store: AnnotationPromptStore
    llm_generate: Callable[..., Dict[str, Any]]  # (system_prompt=, user_prompt=, ...) -> dict


class AnnotationPlanningError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AnnotationPlanner:
    def __init__(self, dependencies: AnnotationPlannerDependencies):
        self._deps = dependencies

    # ------------------------------------------------------------ 主流程

    def plan_slide(
        self,
        run_dir: str,
        slide_id: str,
        beats: List[Dict[str, Any]],
        candidates: List[Dict[str, Any]],
        page: Optional[AnnotationPage],
        *,
        emphasis: str,
        image_hash: Optional[str],
        narration_hash: Optional[str],
        now_iso: str,
    ) -> Tuple[List[AnnotationItem], Dict[str, Any], List[Issue]]:
        """对本页执行一次 AI 规划,返回 (新增条目, 建议快照, 校验问题)。

        - 不覆盖 locked/modified 条目;本函数只产出新增条目，删除由用户显式操作。
        - LLM 输出非法字段一律拒绝并记录 issue;不猜测 ID。
        """
        system_prompt, source = self._deps.prompt_store.effective_system_prompt(run_dir)
        protected = self._protected_summaries(page)
        prompts = compose_plan_prompts(
            system_prompt=system_prompt,
            beats=beats,
            candidates=candidates,
            protected_items=protected,
            emphasis=emphasis,
        )
        for attempt in range(2):
            try:
                raw = self._deps.llm_generate(
                    system_prompt=prompts["system"],
                    user_prompt=prompts["user"],
                    run_dir=run_dir,
                    artifact_prefix=f"annotation_plan_{slide_id}",
                    schema_hint='{"schema_version":"annotation_plan_v2","suggestions":[{"beat_id":"...","range":[0,1],"quote":"...","target_candidate_ids":["..."],"category":"conclusion|contrast|condition|action|evidence|concept","priority":1,"style":"ellipse|underline|highlighter","reason":"...","ambiguous":false}]}',
                )
                break
            except Exception as exc:
                if is_timeout_exception(exc) and attempt == 0:
                    logger.warning("Annotation recommendation timed out for %s; retrying once", slide_id)
                    continue
                if is_timeout_exception(exc):
                    raise AnnotationPlanningError("llm_timeout", "AI 重点推荐两次请求均超时，请稍后重试；已有标注已保留。") from exc
                raise AnnotationPlanningError("llm_failed", str(exc)) from exc

        snapshot = {
            "version": 1,
            "schema_version": "annotation_plan_v2",
            "prompt_source": source,
            "emphasis": emphasis,
            "created_at": now_iso,
            "suggestions": raw.get("suggestions") if isinstance(raw, dict) else None,
        }
        issues: List[Issue] = []
        suggestions = self._normalize_suggestions(
            raw,
            beats,
            candidates,
            issues,
            max_suggestions=MAX_SUGGESTIONS.get(emphasis, MAX_SUGGESTIONS["moderate"]),
            protected_items=protected,
            existing_targets=[
                tuple(item.target.token_ids)
                for item in (page.items if page else ())
                if item.target.token_ids
            ],
        )
        suggestions = [replace(item, inputs=replace(item.inputs, image_hash=image_hash, narration_hash=narration_hash)) for item in suggestions]
        snapshot.update(image_hash=image_hash, narration_hash=narration_hash)
        return suggestions, snapshot, issues

    # ------------------------------------------------------------ 校验

    def _protected_summaries(self, page: Optional[AnnotationPage]) -> List[Dict[str, Any]]:
        protected: List[Dict[str, Any]] = []
        for item in page.items if page else ():
            if item.protection.source != "manual" and not item.protection.locked and not item.protection.modified_fields:
                continue
            protected.append(
                {
                    "quote": item.anchor.quote if item.anchor else (item.target.quote or ""),
                    "beat_id": item.anchor.beat_id if item.anchor else None,
                    "style": item.style.type,
                    "locked": item.protection.locked,
                    "source": item.protection.source,
                    "target_kind": item.target.kind,
                    "target_candidate_ids": list(item.target.token_ids),
                }
            )
        return protected

    def _normalize_suggestions(
        self,
        raw: Any,
        beats: List[Dict[str, Any]],
        candidates: List[Dict[str, Any]],
        issues: List[Issue],
        *,
        max_suggestions: int,
        protected_items: List[Dict[str, Any]],
        existing_targets: List[Tuple[str, ...]],
    ) -> List[AnnotationItem]:
        from annotation_contracts import (
            AnnotationAnchor,
            AnnotationInputs,
            AnnotationProtection,
            AnnotationStatus,
            AnnotationStyle,
            AnnotationTarget,
            AnnotationTiming,
        )

        if not isinstance(raw, dict) or not isinstance(raw.get("suggestions"), list):
            issues.append(Issue("suggestions", "bad_structure", "模型输出缺少 suggestions 数组"))
            return []
        if raw.get("schema_version") != "annotation_plan_v2":
            issues.append(Issue("schema_version", "bad_version", "模型输出 schema_version 必须为 annotation_plan_v2"))
            return []
        unexpected = set(raw) - {"schema_version", "suggestions"}
        if unexpected:
            issues.append(Issue("output", "unexpected_fields", f"模型输出包含未定义字段: {', '.join(sorted(unexpected))}"))
            return []
        beat_map = {str(b.get("beat_id")): str(b.get("spoken_text") or "") for b in beats}
        candidate_map = {str(c.get("token_id")): c for c in candidates}
        token_order = {str(c.get("token_id")): index for index, c in enumerate(candidates)}
        existing_target_sets = {frozenset(ids) for ids in existing_targets if ids}
        protected_beat_quotes = {
            (str(p.get("beat_id")), str(p.get("quote") or ""))
            for p in protected_items
            if p.get("beat_id") and p.get("quote")
        }

        items: List[AnnotationItem] = []
        seen_quotes: set[tuple[str, str]] = set()
        seen_targets: set[tuple[str, tuple[str, ...]]] = set()
        for index, suggestion in enumerate(raw["suggestions"]):
            path = f"suggestions[{index}]"
            if not isinstance(suggestion, dict):
                issues.append(Issue(path, "bad_structure", "建议必须是对象"))
                continue
            required_fields = {
                "beat_id", "range", "quote", "target_candidate_ids", "category", "priority",
                "style", "reason", "ambiguous",
            }
            missing_fields = required_fields - set(suggestion)
            if missing_fields:
                issues.append(Issue(path, "missing_fields", f"建议缺少必需字段: {', '.join(sorted(missing_fields))}"))
                continue
            beat_id = suggestion.get("beat_id")
            spoken = beat_map.get(str(beat_id))
            if spoken is None:
                issues.append(Issue(f"{path}.beat_id", "unknown_beat", f"语块 {beat_id} 不存在"))
                continue
            style_type = suggestion.get("style")
            if style_type not in VALID_STYLES:
                issues.append(Issue(f"{path}.style", "bad_enum", f"style 必须是 {VALID_STYLES} 之一"))
            category = suggestion.get("category")
            if category not in RECOMMENDATION_CATEGORIES:
                issues.append(Issue(f"{path}.category", "bad_enum", "category 必须是定义的重点类型之一"))
                continue
            priority = suggestion.get("priority")
            if isinstance(priority, bool) or not isinstance(priority, int) or priority not in (1, 2, 3):
                issues.append(Issue(f"{path}.priority", "bad_range", "priority 必须是 1、2 或 3"))
                continue
            ambiguous = suggestion.get("ambiguous")
            reason = suggestion.get("reason")
            if not isinstance(ambiguous, bool):
                issues.append(Issue(f"{path}.ambiguous", "bad_type", "ambiguous 必须是布尔值"))
                continue
            if not isinstance(reason, str) or len(reason) > 40:
                issues.append(Issue(f"{path}.reason", "bad_string", "reason 必须是 40 字以内的字符串"))
                continue
            if ambiguous and not reason.strip():
                issues.append(Issue(f"{path}.reason", "required", "ambiguous=true 时必须说明分歧点"))
                continue
            unexpected = set(suggestion) - {
                "beat_id", "range", "quote", "target_candidate_ids", "category", "priority",
                "style", "reason", "ambiguous",
            }
            if unexpected:
                issues.append(Issue(path, "unexpected_fields", f"建议包含未定义字段: {', '.join(sorted(unexpected))}"))
                continue
            range_value = suggestion.get("range")
            quote = suggestion.get("quote")
            if (
                not isinstance(range_value, list)
                or len(range_value) != 2
                or not all(isinstance(v, int) and not isinstance(v, bool) for v in range_value)
            ):
                issues.append(Issue(f"{path}.range", "bad_range", "range 必须是 [start, end] 整数"))
                continue
            start, end = range_value
            if not isinstance(quote, str) or not quote:
                issues.append(Issue(f"{path}.quote", "bad_quote", "quote 必须是非空字符串"))
                continue
            if end - start > MAX_RANGE_CODEPOINTS:
                issues.append(Issue(f"{path}.range", "too_long", f"锚点范围超过 {MAX_RANGE_CODEPOINTS} 个码点"))
                continue
            if start < 0 or end > len(spoken) or not anchor_quote_matches(spoken, AnnotationAnchor(
                beat_id=str(beat_id), range_start=start, range_end=end, quote=quote,
                occurrence=1, context_before="", context_after="",
            )):
                issues.append(Issue(f"{path}.quote", "quote_mismatch", "quote 与讲稿码点切片不一致"))
                continue

            token_ids_raw = suggestion.get("target_candidate_ids")
            if not isinstance(token_ids_raw, list) or not token_ids_raw or not all(isinstance(token_id, str) and token_id for token_id in token_ids_raw):
                issues.append(Issue(f"{path}.target_candidate_ids", "required", "必须给出画面候选"))
                continue
            token_ids: List[str] = []
            unknown_tokens = False
            for token_id in token_ids_raw:
                candidate = candidate_map.get(str(token_id))
                if candidate is None:
                    issues.append(Issue(f"{path}.target_candidate_ids", "unknown_token", f"候选 {token_id} 不存在"))
                    unknown_tokens = True
                    break
                token_ids.append(str(token_id))
            if unknown_tokens:
                continue
            token_ids = sorted(set(token_ids), key=lambda token_id: token_order[token_id])
            # Candidates retain OCR reading order, including line wraps. A target
            # may span lines, but must not jump over visible intervening text.
            # Reject rather than filling gaps: skipped characters may change the
            # meaning, and their boxes were never selected by the model.
            selected_ids = set(token_ids)
            first, last = token_order[token_ids[0]], token_order[token_ids[-1]]
            if any(
                str(candidate.get("token_id")) not in selected_ids
                and str(candidate.get("text") or "").strip()
                for candidate in candidates[first:last + 1]
            ):
                issues.append(Issue(
                    f"{path}.target_candidate_ids", "discontinuous_target",
                    "画面目标跳过了中间文字，已剔除零散字符建议；请选择连续完整的目标",
                ))
                continue
            polygons = [candidate_map[token_id].get("polygon") or [] for token_id in token_ids]
            canonical_target = frozenset(token_ids)
            if canonical_target in existing_target_sets or (str(beat_id), quote) in protected_beat_quotes:
                continue
            if style_type not in VALID_STYLES:
                continue
            granularity = "line" if any(candidate_map[t].get("granularity") == "line" for t in token_ids) else "char"
            quote_key = (str(beat_id), quote)
            target_key = (str(beat_id), tuple(token_ids))
            if quote_key in seen_quotes or target_key in seen_targets:
                continue  # 重复建议静默剔除(同语块同短语只保留一条)
            seen_quotes.add(quote_key)
            seen_targets.add(target_key)
            items.append(
                AnnotationItem(
                    annotation_id="",  # 由调用方分配
                    target=AnnotationTarget(
                        kind="text",
                        layout_revision=None,
                        token_ids=tuple(token_ids),
                        polygons=tuple(tuple((p[0], p[1]) for p in poly) for poly in polygons if len(poly) == 4),
                        quote=quote,
                        granularity=granularity,
                        mask_group_ids=(),
                    ),
                    anchor=AnnotationAnchor(
                        beat_id=str(beat_id),
                        range_start=start,
                        range_end=end,
                        quote=quote,
                        occurrence=1,
                        context_before="",
                        context_after="",
                    ),
                    style=AnnotationStyle(type="highlighter", color="#F6CE46", opacity=0.28, width=5, padding=4, seed=0),
                    timing=AnnotationTiming(
                        trigger_mode="anchor_start", offset_sec=0.0, draw_duration_sec=0.6,
                        hold_mode="beat_end", hold_duration_sec=None, exit_duration_sec=0.15,
                    ),
                    status=AnnotationStatus(
                        content="draft",
                        spatial="needs_review" if ambiguous or granularity == "line" else "valid",
                        temporal="awaiting_audio",
                    ),
                    protection=AnnotationProtection(source="ai", modified_fields=(), locked=False),
                    inputs=AnnotationInputs(image_hash=None, narration_hash=None, audio_hash=None),
                    review_issues=({"code": "ambiguous", "message": reason},) if ambiguous else (),
                    recommendation={
                        "category": category,
                        "priority": priority,
                        "reason": reason,
                    },
                )
            )
        items.sort(key=lambda item: item.recommendation["priority"] if item.recommendation else 3)
        if len(items) > max_suggestions:
            issues.append(Issue("suggestions", "limit_exceeded", f"建议超过当前密度上限 {max_suggestions} 条，已截取优先项"))
            items = items[:max_suggestions]
        return items
