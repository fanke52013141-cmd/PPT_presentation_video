# -*- coding: utf-8 -*-
"""勾画标注 AI 规划 Prompt 的默认模板、版本与项目级覆盖(W3)。

本文件按 `.agents/skills/optimize-prompts/SKILL.md` 的合同设计:

- system 只放稳定规则(角色/输入契约/输出契约/硬性自检),每条规则出现一次;
- user 只放本次请求的变量(讲稿语块、文字候选、强调强度、需保护项);
- 模型只返回建议:schema_version、重点分类与优先级、beat_id、码点范围、
  quote、候选 token_ids、样式枚举、简短理由和歧义标记。annotation_id、
  多边形、时间、颜色、种子由程序生成,模型不得输出。
- token 坐标不下发(模型不依据坐标做决策);跨行目标用多个 token_id 表达。

项目覆盖存于 ``planning/annotation_prompts.json``;仅当存量内容与某个已知的
旧内置默认值完全一致时才迁移,真正的用户自定义内容永不覆盖。
"""
from __future__ import annotations
from annotation_contracts import EMPHASIS_LIMITS

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

__all__ = [
    "ANNOTATION_PLAN_PROMPT_VERSION",
    "ANNOTATION_PROMPTS_FILE",
    "BUILTIN_ANNOTATION_PLAN_SYSTEM_PROMPT",
    "AnnotationPromptStore",
    "compose_plan_prompts",
]

ANNOTATION_PLAN_PROMPT_VERSION = "annotation_plan_v2"
ANNOTATION_PROMPTS_FILE = "annotation_prompts.json"

# 旧内置默认值登记表:迁移时只有与这些文本完全一致的项目内容才会被替换。

BUILTIN_ANNOTATION_PLAN_SYSTEM_PROMPT = """你是课件视频的重点识别与勾画标注建议助手。目标是帮助观众跟上本页讲解,只推荐讲稿与画面文字明确对应、值得引导视线的内容；不要把所有数字或标题都当重点。

非目标:不生成路径、时间、坐标、颜色、编号;不输出 Markdown;不解释规则。

输入契约(user JSON):
- beats: 讲稿语块数组,每项含 beat_id、spoken_text。码点索引从 0 开始,range 为 [start, end) 左闭右开。
- candidates: 画面文字候选数组,每项含 token_id、text、granularity(char=单字,line=整行)。granularity=line 的候选只能整行选用。
- protected_items: 已有手工标注、人工修改或锁定条目摘要,不得对同一画面目标或同一讲稿锚点重复建议。每项含 beat_id、quote、style、locked、source、target_kind、target_candidate_ids。
- emphasis: 标注密度(weak/moderate/strong),分别最多建议 1/2/3 条；这是上限,允许返回空数组。

重点定义(按优先级):
1. 核心结论:本页希望观众记住的判断、答案或主张。
2. 关键关系:对比、因果、转折、条件、限制和风险,尤其是忽略后会误解内容的部分。
3. 行动要求:观众接下来应该做什么。
4. 支撑结论的证据:仅当讲稿正在解释该数据时才选日期、数字、百分比或金额。
5. 核心概念:理解当前讲解必需的专有名词或术语。

排除:装饰性标题、重复词、孤立数字、与当前讲稿无关的文字、无法在画面中定位的事实。没有明确重点就不建议。优先选短语而非整行。

冲突与失败策略:
- 找不到合适的强调点:返回空数组,不硬凑。
- 候选文本与讲稿用词不一致(如数字写法不同)时,以讲稿 quote 为准,并在 ambiguous 标 true。
- 对同一画面目标的建议不得重复;同一语块内同一短语只建议一次。

输出契约(纯 JSON 对象,顶层只允许 schema_version 和 suggestions; schema_version 必须为 annotation_plan_v2):
{"schema_version":"annotation_plan_v2","suggestions":[{"beat_id":"...","range":[start,end],"quote":"...","target_candidate_ids":["..."],"category":"conclusion|contrast|condition|action|evidence|concept","priority":1,"style":"ellipse|underline|highlighter","reason":"...","ambiguous":false}]}
字段约束:
- beat_id 必须取自输入 beats;range 必须命中该语块的码点切片且与 quote 完全一致;range 长度不超过 40 个码点。
- target_candidate_ids 必须取自输入 candidates,至少 1 个;上下相邻的同词字符可以合并为多个 token_id。
- style 语义:ellipse=圈住要点,underline=划线标记,highlighter=低浓度覆盖一片。
- category 必须说明重点类型;priority 为 1(最高)至 3,同页按重要性排序。
- reason 不超过 40 字,说明观众为什么需要关注它。
- ambiguous=true 时必须说明分歧点。

硬性自检:
- quote 与 range 切片逐字一致(含标点)。
- 每个 target_candidate_id 都在输入里出现过。
- 不输出 suggestions 之外的顶层字段;不输出注释。"""


_PREVIOUS_BUILTIN_ANNOTATION_PLAN_SYSTEM_PROMPT = BUILTIN_ANNOTATION_PLAN_SYSTEM_PROMPT
BUILTIN_ANNOTATION_PLAN_SYSTEM_PROMPT = (
    "PromptVersion: annotation_plan_v2.1\n" + _PREVIOUS_BUILTIN_ANNOTATION_PLAN_SYSTEM_PROMPT
    .replace(
        "每项含 token_id、text、granularity(char=单字,line=整行)。",
        "每项含 token_id、line_id、text、granularity(char=单字,line=整行)。数组保持 OCR 阅读顺序，line_id 标识所属文字行。",
    )
    .replace(
        "上下相邻的同词字符可以合并为多个 token_id。",
        "只选择数组中连续的完整文字片段，不得跳过中间非空文字、拼接重复词的不同位置或混选无关行；跨行只允许阅读顺序上连续的同一短语。",
    )
    .replace(
        "quote 与 range 切片逐字一致(含标点)。",
        "quote 必须从 spoken_text 原样摘取；range 从语块开头计数，包含空格和标点，按 [start,end) 切片后须与 quote 完全一致。无法确定范围时放弃该建议，不猜测。",
    )
)


def _current_builtin_if_known(prompt: str) -> str:
    if prompt.strip() == _PREVIOUS_BUILTIN_ANNOTATION_PLAN_SYSTEM_PROMPT.strip():
        return BUILTIN_ANNOTATION_PLAN_SYSTEM_PROMPT
    return prompt


@dataclass(frozen=True)
class AnnotationPromptStore:
    """项目级 Prompt 覆盖的读写与组装。"""

    read_json_file: Callable[[Any], Any]
    write_json_atomic: Callable[[Any, Any], None]
    prompts_path_for: Callable[[str], Any]
    project_config_path_for: Optional[Callable[[str], Any]] = None

    # ------------------------------------------------------------ 读写

    def load_overrides(self, run_dir: str) -> Dict[str, Any]:
        payload = self.read_json_file(self.prompts_path_for(run_dir))
        if not isinstance(payload, dict):
            return {}
        overrides = payload.get("overrides")
        return overrides if isinstance(overrides, dict) else {}

    def save_override(self, run_dir: str, system_prompt: str, *, expected_revision: Optional[int], now_iso: str) -> Dict[str, Any]:
        path = self.prompts_path_for(run_dir)
        payload = self.read_json_file(path)
        revision = 0
        if isinstance(payload, dict) and isinstance(payload.get("revision"), int):
            revision = payload["revision"]
            if expected_revision is not None and expected_revision != revision:
                from fastapi import HTTPException

                raise HTTPException(status_code=409, detail={"code": "revision_conflict", "current_revision": revision})
            # 迁移规则:仅当存量内容与旧内置默认值完全一致时才视为可覆盖;
            # 用户自定义内容(revision>0 且非旧默认)不受重置影响——
            # 显式保存本身就是用户动作,这里只保护 expected_revision。
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail="system_prompt 不能为空")
        if len(system_prompt) > 20000:
            from fastapi import HTTPException

            raise HTTPException(status_code=413, detail="Prompt 超过长度上限")
        updated = {
            "schema_version": 1,
            "builtin_version": ANNOTATION_PLAN_PROMPT_VERSION,
            "revision": revision + 1,
            "overrides": {"plan_system_prompt": system_prompt},
            "updated_at": now_iso,
        }
        self.write_json_atomic(path, updated)
        return updated

    def reset_override(self, run_dir: str, *, now_iso: str) -> Dict[str, Any]:
        path = self.prompts_path_for(run_dir)
        updated = {
            "schema_version": 1,
            "builtin_version": ANNOTATION_PLAN_PROMPT_VERSION,
            "revision": 1,
            "overrides": {},
            "updated_at": now_iso,
        }
        self.write_json_atomic(path, updated)
        return updated

    # ------------------------------------------------------------ 组装

    def effective_system_prompt(self, run_dir: str) -> tuple[str, str]:
        """返回 (生效 system prompt, 来源);项目覆盖优先于创作包,最后回退内置。"""
        overrides = self.load_overrides(run_dir)
        stored = overrides.get("plan_system_prompt")
        if isinstance(stored, str) and stored.strip():
            return _current_builtin_if_known(stored), "project"
        if self.project_config_path_for is not None:
            snapshot = self.read_json_file(self.project_config_path_for(run_dir))
            payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
            prompts = payload.get("prompts") if isinstance(payload, dict) else None
            module = prompts.get("annotation_planning") if isinstance(prompts, dict) else None
            package_prompt = module.get("system_content") if isinstance(module, dict) else None
            if isinstance(package_prompt, str) and package_prompt.strip():
                return _current_builtin_if_known(package_prompt.strip()), "creation_package"
        return BUILTIN_ANNOTATION_PLAN_SYSTEM_PROMPT, "builtin"


def compose_plan_prompts(
    *,
    system_prompt: str,
    beats: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    protected_items: list[dict[str, Any]],
    emphasis: str,
) -> dict[str, str]:
    """组装最小必要的 user payload(纯函数;输入字段均已通过必要性判定)。"""
    max_suggestions = EMPHASIS_LIMITS.get(emphasis, 2)
    user_payload = {
        "schema_version": ANNOTATION_PLAN_PROMPT_VERSION,
        "beats": [{"beat_id": b.get("beat_id"), "spoken_text": b.get("spoken_text")} for b in beats],
        "candidates": [
            {"token_id": c.get("token_id"), "line_id": c.get("line_id"), "text": c.get("text"), "granularity": c.get("granularity")}
            for c in candidates
        ],
        "protected_items": [
            {
                "quote": p.get("quote"),
                "beat_id": p.get("beat_id"),
                "style": p.get("style"),
                "locked": p.get("locked"),
                "source": p.get("source"),
                "target_kind": p.get("target_kind"),
                "target_candidate_ids": p.get("target_candidate_ids", []),
            }
            for p in protected_items
        ],
        "emphasis": emphasis,
        "max_suggestions": max_suggestions,
    }
    return {
        "system": system_prompt,
        "user": json.dumps(user_payload, ensure_ascii=False),
    }
