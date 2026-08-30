"""Automatic multimodal AI Mask annotation routes.

The annotator detects exact foreground components, associates every component
with one narrated visual group, and writes mutually-exclusive pixel masks into
``reveal_manifest.json``. Brush strokes remain available as manual corrections
on top of the automatic base mask.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import time
from pathlib import Path
from typing import Any, Callable


from ai_mask_contracts import AI_MASK_VISION_TIMEOUT_SEC  # noqa: F401 (re-exported for ai_mask_semantic_matcher via ai_mask_engine)


SETTING_PREFIX = "ai_mask_"

DEFAULT_SETTINGS: dict[str, Any] = {
    "white_threshold": 245,
    "color_tolerance": 12,
    "closing_radius": 6,
    "add_border": 2,
    "connectivity": 8,
    "min_element_area": 120,
    "component_padding_px": 12,
    "doclayout_enabled": True,
    "doclayout_model_path": "",
    "doclayout_conf_threshold": 0.35,
    "doclayout_input_size": 1024,
    "doclayout_iou_threshold": 0.45,
    "doclayout_min_area_ratio": 0.002,
    "max_group_elements": 60,
    "llm_confidence_threshold": 0.72,
    "llm_temperature": 0.1,
    "overwrite_existing_manual_mask": False,
    "overwrite_existing_ai_mask": True,
    "skip_locked_groups": True,
}

@dataclass(frozen=True)
class AiMaskEngineDependencies:
    """Explicit capabilities required by the AI Mask algorithm layer."""

    get_setting: Callable[..., Any]
    get_openai_client: Callable[..., Any]
    read_style_tokens_data: Callable[[], dict[str, Any]]
    step2_llm_vendor_options: Callable[..., dict[str, Any]]
    clean_json_markdown: Callable[[str], str]
    is_timeout_exception: Callable[[BaseException], bool]
    write_project_log: Callable[..., None]
    logger: Any

LEGACY_DEFAULT_METHODOLOGY_V2 = """你是中文 PPT 视频的 AI Mask 语义标注专家。

## 目的
把自动检测到的语义对象绑定到当前 Slide 已有的 visual_groups 与 narration_beats，为后续生成安全、可复核的 Reveal Mask 提供匹配结果；不重写分镜或旁白。

## 系统背景
visual_group 是最小的 Mask/Reveal 原子。AI Mask 只能匹配已有语块，不能创建、拆分或改写 visual_group。若上游把多个独立视觉岛错误地塞进一个语块，你必须明确报告结构冲突，不能把“所有像素都有归属”误判为“语义分组正确”。

## 输入
- 当前 Slide 的 visual_groups、narration_beats 与 semantic_objects。
- image_full：未画框的完整原图，用于理解全局版式、阅读顺序和真实语义。
- object_XXX：语义对象切片，包含 object_id、element_ids 和 bbox。
- 所有返回 ID 必须来自输入，不得创造新 ID。

## 任务
完成“画面语义对象 → 已有语块 → 演讲稿 beat”的匹配。你不是重新生成分镜，也不是重写演讲稿。

## 匹配规则
1. `group_id` 只能使用输入 `visual_groups[].id`，不得发明新 group。
2. `narration_beat_id` 只能使用输入 `narration_beats[].id`。
3. 优先匹配 `semantic_objects[].object_id`；输出 `element_ids` 时使用所选对象的完整集合，不只挑碎片。
4. 一个标题行、标签行、卡片、配图、图标组合或流程节点通常是一个完整对象，不因字形不粘连、颜色不同或边框断开而拆散。
5. 页面上方只保留一个完整主标题，不使用页面副标题。主标题即使包含多种颜色、描边或断开的字形，也必须视为同一个语义对象：有 title narration beat 时整体绑定到唯一 title group；没有时整个标题保持静态，绝不能回退绑定到正文 group。
6. 优先匹配 `visible_text`、`visual_anchor`、`spoken_text`，再结合二维位置、role 和阅读顺序。
7. 同一语块可以绑定多个空间连续、共同服务于同一叙事时刻的对象，例如主配图与其内部标签；不能仅因主题相同就跨越明显留白合并对象。
8. 对比两侧、多个独立卡片、多个独立步骤或相距很远的视觉岛，如果表达不同子结论，必须分别绑定到不同 narration beat，不得合并为一个 Mask。
9. 匹配前执行结构审计：如果画面明显包含多个应分别 Reveal 的语义对象，但输入只提供一个正文 visual_group/narration beat，不得假装结构正确。仍按已有 ID 返回最可靠匹配，同时在 `warnings` 中加入 `type="insufficient_visual_groups_for_independent_objects"`，列出 object_ids 和原因，交由质量门阻止静默合并。
10. 不确定时降低 confidence。装饰或无口播对象放入 unmatched 列表，不得在模型输出中仅为达到覆盖率而强行匹配。
11. 只输出严格 JSON，不要 Markdown、解释或额外文字。

## 输出
严格遵循系统另行提供的“OUTPUT STRUCTURE / 输出结构”，只返回一个 JSON object。
"""

LEGACY_STORED_METHODOLOGY_V2 = LEGACY_DEFAULT_METHODOLOGY_V2.replace(
    "5. 页面上方只保留一个完整主标题，不使用页面副标题。主标题即使包含多种颜色、描边或断开的字形，也必须视为同一个语义对象：有 title narration beat 时整体绑定到唯一 title group；没有时整个标题保持静态，绝不能回退绑定到正文 group。",
    "5. 页面上方主标题/副标题保持固定布局；只有存在对应 narration beat 时才参与逐语块 Reveal。",
).replace(
    "\n\n## 输出\n严格遵循系统另行提供的“OUTPUT STRUCTURE / 输出结构”，只返回一个 JSON object。",
    "",
)

LEGACY_DEFAULT_OUTPUT_STRUCTURE_V2 = """必须输出一个 JSON object：
{
  "slide_id": "slide_001",
  "matches": [
    {
      "group_id": "body_group_01",
      "narration_beat_id": "beat_01",
      "object_ids": ["obj_010"],
      "element_ids": ["el_auto_010", "el_auto_011"],
      "confidence": 0.95,
      "reason": "obj_010 是完整语义对象，包含主配图与紧邻标签，并共同对应 beat_01"
    }
  ],
  "unmatched_objects": [],
  "unmatched_elements": [],
  "unmatched_groups": [],
  "warnings": [
    {
      "type": "insufficient_visual_groups_for_independent_objects",
      "object_ids": ["obj_010", "obj_020"],
      "reason": "两个对象空间分离且表达不同子结论，但输入只有一个正文语块"
    }
  ]
}

约束：group_id 必须来自 visual_groups[].id；narration_beat_id 必须来自 narration_beats[].id；object_ids 必须来自 semantic_objects[].object_id；element_ids 必须来自 semantic_objects[].element_ids 或 auto_elements[].element_id；confidence 是 0 到 1 的数字。没有结构冲突时 warnings 输出空数组。
"""

DEFAULT_METHODOLOGY = """<PromptVersion>ai_mask_semantic_mapping_v3</PromptVersion>

## 角色与目标
你是中文 PPT 视频的 AI Mask 语义归属专家。你的唯一任务是把画面中已检测的语义对象，准确绑定到当前 Slide 已存在的 `visual_groups` 与 `narration_beats`，供后续生成 Reveal Mask。

你不生成或修改图片，不重写分镜、标题、正文或演讲稿，不创建、拆分、合并 `visual_group`，也不直接处理像素或 RLE Mask。

## 生产背景
- `visual_group` 是上游定义的最小 Mask/Reveal 语块；`narration_beat` 是该语块对应的演讲片段。
- 系统先从纯白背景幻灯片中检测前景组件，再合并成 `semantic_objects`。一个对象可能是一行标题、一张卡片、一幅插图、一个流程节点，或一个容器及其内部文字和图标。
- `image_full` 用于理解整页结构、阅读顺序与对象之间的关系；随后按顺序提供的 `object_XXX` 切片与 `semantic_objects[].object_id` 一一对应。
- 你的输出只决定“语义锚点属于哪个语块”。下游会把对象展开为底层 `element_ids`，并用确定性规则补齐装饰与残余碎片，以满足前景覆盖要求。因此语义正确优先于为了覆盖率强行匹配。
- 如果上游语块数量不足，AI Mask 无权修改上游结构；必须明确告警，不能把像素全有归属误判为语义分组正确。

## 实际输入
1. `slide.visual_groups[]`：重点使用 `id`、`role`、`visible_text`、`visual_anchor`。
2. `slide.narration_beats[]`：重点使用 `id`、`group_id`、`spoken_text`；只有这里引用的 group 才是本次需要动态 Reveal 的目标。
3. `semantic_objects[]`：包含 `object_id`、`type`、`bbox`、`center`、`element_count`、`cluster_member_count`；对象切片提供真实视觉内容。
4. 极少数兼容路径可能只提供 `auto_elements[]` 和带框整图，此时改用 `element_id` 匹配。

字段可能为空。只能使用输入中真实存在的 ID，不得补写、改写或猜测 ID。

## 判断优先级
按以下顺序判断；高优先级证据冲突时，不得仅靠低优先级证据覆盖：
1. 语义证据：对象可见文字/图意，与 `visible_text`、`visual_anchor`、`spoken_text` 的含义是否一致。
2. 视觉边界：对象是否属于同一卡片、容器、插图或流程节点，是否存在明显留白、分栏或独立边框。
3. 空间证据：二维位置、包含关系、相邻关系与阅读顺序。
4. 辅助证据：`role`、编号、颜色。颜色或顺序不能单独决定归属。

### 兼容路径（auto_elements）
当输入没有 `semantic_objects`、只有 `auto_elements[]` 与带框整图时，按与对象路径完全相同的优先级（语义 > 视觉边界 > 空间 > 辅助）把 element 绑定到目标 group。每个 `element_id` 只能归属一个 group；一个 group 可绑定多个共同构成同一叙事时刻的 element，但同一 element 不得跨 group 重复。其余规则（标题区、完整性、置信度）与对象路径一致。

## 执行流程
### A. 建立目标清单
- 先根据 `narration_beats[].group_id` 列出需要匹配的动态 group。
- 每个动态 group 最多输出一条 match；同一 `object_id` 最多只能归属一个 group。

### B. 处理标题区
- 新版页面只有一个完整主标题，不使用页面副标题。
- 主标题即使有多色、描边、断笔或分离字形，仍是一个完整对象。
- 只有存在 `role=title` 且被 narration beat 引用的 group 时，才把完整标题绑定给该 title group；否则标题保持静态，绝不能绑定到正文 group。
- 对兼容旧项目出现的 subtitle，只在存在独立、被旁白引用的 subtitle group 时匹配；否则保持静态。

### C. 匹配正文语义对象
- 优先做一对一匹配：一个动态 group 对应一个最完整、语义最明确的对象。
- 只有同时满足以下三项时，一个 group 才能绑定多个对象：它们共同表达同一叙事时刻；空间连续、相互包含或明显属于同一容器；拆开后任一对象都不能独立表达新的子结论。
- 同一标题行、同一卡片内部文字与图标、同一流程节点的编号与说明，不因颜色不同、字形断开或检测框碎片化而拆开。

### D. 防止错误合并
- 对比左右两侧、并列卡片、独立步骤、独立方案、相距较远的视觉岛，只要表达不同子结论，就必须分别对应不同 group/beat。
- “主题相同”“颜色相同”“都属于正文”均不足以跨越明显留白、分栏或独立边框进行合并。
- 如果画面存在多个应独立 Reveal 的对象，但输入只有一个可用正文 group/beat：只把语义最吻合的对象匹配给该 group，其余对象放入 `unmatched_objects`；同时输出 `insufficient_visual_groups_for_independent_objects` 告警。不要把多个独立对象硬塞进同一个 Mask。

### E. 完整性与置信度复核
- 检查每个 match 的 group、beat、object 是否都来自输入；检查 group 不重复、object 不跨组重复。
- 没有可靠对象的动态 group 放入 `unmatched_groups`，不要用标题、装饰或无关对象补位。
- 独立装饰、分隔线、角标或无口播对象放入 `unmatched_objects`；下游会处理像素覆盖，不能把装饰当作语义锚点。
- 置信度标准：`0.90-1.00` 为语义与视觉边界均明确；`0.80-0.89` 为证据充分但存在轻微歧义；`0.72-0.79` 为可匹配但需要人工复核；低于 `0.72` 时不要输出 match，改放 unmatched。
- 任何低于系统置信度阈值（默认 0.72）的候选匹配都不得写入 `matches`，一律放入 `unmatched_objects` 或 `unmatched_elements`，由下游按确定性规则处理。

## 输出要求
严格遵循另行提供的“OUTPUT STRUCTURE / 输出结构”。只返回一个合法 JSON object，不要 Markdown、代码围栏、分析过程或额外文字。
"""

DEFAULT_OUTPUT_STRUCTURE = """只输出以下结构的一个合法 JSON object：
{
  "slide_id": "slide_001",
  "matches": [
    {
      "group_id": "body_group_01",
      "narration_beat_id": "beat_01",
      "object_ids": ["obj_010"],
      "element_ids": [],
      "confidence": 0.95,
      "reason": "语义=卡片文字与 beat_01 一致；边界=对象位于独立卡片内"
    }
  ],
  "unmatched_objects": ["obj_020"],
  "unmatched_elements": [],
  "unmatched_groups": [],
  "warnings": [
    {
      "type": "insufficient_visual_groups_for_independent_objects",
      "group_id": "body_group_01",
      "object_ids": ["obj_010", "obj_020"],
      "reason": "两个对象位于独立卡片并表达不同子结论，但输入只有一个正文语块"
    }
  ]
}

硬性约束：
1. `group_id` 必须来自 `visual_groups[].id`，且在 `matches` 中最多出现一次。
2. `narration_beat_id` 必须来自 `narration_beats[].id`，并且该 beat 的 `group_id` 必须等于本条 match 的 `group_id`。
3. 正常生产输入存在 `semantic_objects`：此时 `object_ids` 必须来自 `semantic_objects[].object_id`，同一 object 不得跨 match 重复；`element_ids` 输出空数组，系统会按 object 自动展开。
4. 仅当输入没有 `semantic_objects`、只有 `auto_elements` 时：`object_ids` 输出空数组，`element_ids` 使用 `auto_elements[].element_id`。
5. `confidence` 是 0 到 1 的数字；`reason` 使用“语义=…；边界=…”格式，简短说明关键证据。
6. `unmatched_objects`、`unmatched_elements`、`unmatched_groups` 只填写输入中真实存在且未匹配的 ID。
7. 只有发现“独立视觉对象数量多于可用语块”时才输出示例中的告警；否则 `warnings` 必须是空数组。
8. 任何 `confidence` 低于系统阈值（默认 0.72）的候选不得进入 `matches`，必须放入对应的 unmatched 数组。
"""

PROMPT_METHOD_KEY = SETTING_PREFIX + "match_methodology_system_content"
PROMPT_OUTPUT_KEY = SETTING_PREFIX + "match_output_structure_system_content"
LEGACY_TITLE_RULE = "6. 主标题与副标题是否属于同一个 Mask，以 narration_beats 的讲解关系为准，不按字体颜色、断笔或字间距拆分。"
STATIC_TITLE_RULE = "6. 页面上方固定主标题/副标题区域属于静态上下文，不分配给任何 narration group，不参与逐语块 Reveal；元素匹配必须同时考虑横向与纵向距离；大面积主配图应吸收其内部、边界上和紧邻的图标、对号、标签与说明，除非它们明确对应独立 narration beat；不允许因为颜色相似就跨卡片、跨栏或跨配图分配。"
PREVIOUS_TITLE_AND_ISLAND_RULES = """6. 页面上方主标题/副标题保持固定布局，但有 narration 绑定时必须参与逐语块 Reveal；副标题优先绑定独立 subtitle group，没有独立组时与主标题共同绑定到首个标题 narration group；元素匹配必须同时考虑横向与纵向距离；大面积主配图应吸收其内部、边界上和紧邻的图标、对号、标签与说明，除非它们明确对应独立 narration beat；不允许因为颜色相似就跨卡片、跨栏或跨配图分配。"""
CURRENT_TITLE_AND_ISLAND_RULES = """6. 页面上方只保留一个完整主标题，不使用页面副标题。无论主标题包含多少颜色、描边、断笔或分离字形，都必须整体绑定到唯一的 title group，不能拆给多个正文 group；如果不存在 title narration beat，则整个标题保持静态。元素匹配必须同时考虑横向与纵向距离；大面积主配图应吸收其内部、边界上和紧邻的图标、对号、标签与说明，除非它们明确对应独立 narration beat；不允许因为颜色相似就跨卡片、跨栏或跨配图分配。"""


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except Exception:
        parsed = default
    return max(lo, min(hi, parsed))


def _float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        parsed = float(str(value).strip())
    except Exception:
        parsed = default
    return max(lo, min(hi, parsed))


def normalize_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = {**DEFAULT_SETTINGS, **(raw or {})}
    return {
        "white_threshold": _int(raw.get("white_threshold"), 245, 220, 255),
        "color_tolerance": _int(raw.get("color_tolerance"), 12, 0, 40),
        "closing_radius": _int(raw.get("closing_radius"), 6, 0, 20),
        "add_border": _int(raw.get("add_border"), 2, 0, 8),
        "connectivity": 4 if str(raw.get("connectivity")) == "4" else 8,
        "min_element_area": _int(raw.get("min_element_area"), 120, 10, 10000),
        "component_padding_px": _int(raw.get("component_padding_px"), 12, 0, 80),
        "max_group_elements": max(20, _int(raw.get("max_group_elements"), 60, 1, 120)),
        "doclayout_enabled": _bool(raw.get("doclayout_enabled"), False),
        "doclayout_model_path": str(raw.get("doclayout_model_path") or "").strip(),
        "doclayout_conf_threshold": _float(raw.get("doclayout_conf_threshold"), 0.35, 0, 1),
        "doclayout_input_size": _int(raw.get("doclayout_input_size"), 1024, 256, 2048),
        "doclayout_iou_threshold": _float(raw.get("doclayout_iou_threshold"), 0.45, 0, 1),
        "doclayout_min_area_ratio": _float(raw.get("doclayout_min_area_ratio"), 0.002, 0, 0.5),
        "llm_confidence_threshold": _float(raw.get("llm_confidence_threshold"), 0.72, 0, 1),
        "llm_temperature": _float(raw.get("llm_temperature"), 0.1, 0, 1),
        "overwrite_existing_manual_mask": _bool(raw.get("overwrite_existing_manual_mask"), False),
        "overwrite_existing_ai_mask": _bool(raw.get("overwrite_existing_ai_mask"), True),
        "skip_locked_groups": _bool(raw.get("skip_locked_groups"), True),
    }


from ai_mask_component_detection import (
    _read_json,
    _write_json,
    detect_elements,
)


from ai_mask_assignment import (
    _clean_match,
    _complete_component_coverage,
    _configured_title_regions,
    _consolidate_title_regions,
    _ensure_narrated_group_anchors,
    _fallback_match,
    _merge_match_results,
)


def _resolved_vision_model(capabilities: Any) -> tuple[str, str]:
    provider = str(capabilities.get_setting("llm_provider") or "").strip().lower()
    configured = str(capabilities.get_setting("vision_model") or "").strip()
    # A model name from another provider cannot be sent to the active endpoint.
    # Preserve the configured value for diagnostics and use the provider's
    # working LLM model as the multimodal fallback.
    if provider not in {"", "openai", "newapi", "openrouter", "litellm", "custom"} and configured.startswith("gpt-"):
        return str(capabilities.get_setting("llm_model") or "").strip(), configured
    return configured or str(capabilities.get_setting("llm_model") or "").strip(), configured


def _is_timeout(capabilities: Any, exc: BaseException) -> bool:
    helper = getattr(capabilities, "is_timeout_exception", None)
    if callable(helper):
        try:
            return bool(helper(exc))
        except Exception:
            pass
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower() or "timed out" in str(exc).lower()


from ai_mask_manifest_apply import (
    _apply,
    _review_issues,
    _replaceable_ai_mask,
)


def _select_contract_slides(
    contract: dict[str, Any],
    slide_ids: list[str] | None,
) -> list[dict[str, Any]]:
    contract_slides = [slide for slide in contract.get("slides", []) or [] if isinstance(slide, dict)]
    if slide_ids is None:
        return contract_slides
    requested_ids = list(dict.fromkeys(str(value).strip() for value in slide_ids if str(value).strip()))
    contract_ids = {str(slide.get("slide_id") or "") for slide in contract_slides}
    unknown_ids = [slide_id for slide_id in requested_ids if slide_id not in contract_ids]
    if unknown_ids:
        raise ValueError(f"AI Mask slide_ids 不属于当前 Contract: {', '.join(unknown_ids)}")
    requested_set = set(requested_ids)
    selected = [slide for slide in contract_slides if str(slide.get("slide_id") or "") in requested_set]
    if not selected:
        raise ValueError("AI Mask slide_ids 不能为空")
    return selected


def _annotate_project(
    capabilities: AiMaskEngineDependencies,
    project: Any,
    settings: dict[str, Any],
    methodology: str,
    output_structure: str,
    vision_matcher: Callable[..., dict[str, Any] | None],
    slide_ids: list[str] | None = None,
) -> dict[str, Any]:
    run_dir = Path(project.run_dir)
    contract = _read_json(run_dir / "planning" / "visual_contract.json")
    manifest = _read_json(run_dir / "reveal_manifest.json")
    contract_slides = _select_contract_slides(contract, slide_ids)
    prepared: list[dict[str, Any]] = []
    for slide in contract_slides:
        slide_id = str(slide.get("slide_id") or "")
        slide_dir = run_dir / "slides" / slide_id
        image_path = slide_dir / "visual_draft.png"
        # ---- DocLayout-YOLO layout detection (optional) ----
        layout_boxes = None
        if settings.get("doclayout_enabled"):
            try:
                from ai_mask_doclayout import DocLayoutDetector
                from PIL import Image
                detector = DocLayoutDetector(
                    model_path=str(settings.get("doclayout_model_path") or ""),
                    conf_threshold=float(settings.get("doclayout_conf_threshold", 0.35)),
                    input_size=int(settings.get("doclayout_input_size", 1024)),
                    iou_threshold=float(settings.get("doclayout_iou_threshold", 0.45)),
                    min_area_ratio=float(settings.get("doclayout_min_area_ratio", 0.002)),
                )
                if detector.available():
                    layout_boxes = detector.detect(Image.open(image_path))
                    if layout_boxes and capabilities.logger is not None:
                        capabilities.logger.info(
                            "DocLayout-YOLO: %d layout boxes detected for %s", len(layout_boxes), slide_id
                        )
            except Exception as exc:
                if capabilities.logger is not None:
                    capabilities.logger.warning(
                        "DocLayout-YOLO layout detection failed for %s: %s", slide_id, exc
                    )
                layout_boxes = None
        elements = detect_elements(image_path, slide_dir, settings, layout_boxes)
        canvas = elements.get("canvas", {}) if isinstance(elements.get("canvas"), dict) else {}
        title_regions = _configured_title_regions(
            capabilities,
            max(1, int(canvas.get("width", 1920))),
            max(1, int(canvas.get("height", 1080))),
        )
        element_list = elements.get("elements", []) + elements.get("residual_elements", [])
        manifest_slide = next(
            (
                item for item in manifest.get("slides", []) or []
                if isinstance(item, dict) and str(item.get("slide_id") or "") == slide_id
            ),
            {},
        )
        fallback = _fallback_match(slide, element_list, manifest_slide)
        prepared.append({
            "slide": slide,
            "slide_id": slide_id,
            "slide_dir": slide_dir,
            "image_path": image_path,
            "elements": elements,
            "element_list": element_list,
            "fallback": fallback,
            "title_regions": title_regions,
        })

    def match_slide(item: dict[str, Any]) -> dict[str, Any]:
        vision_started = time.monotonic()
        resolved_model, configured_model = _resolved_vision_model(capabilities)
        try:
            raw_vision = vision_matcher(
                capabilities,
                project,
                item["slide"],
                item["element_list"],
                item["image_path"],
                item["slide_dir"] / "auto_mask" / "candidate_overlay.png",
                methodology,
                output_structure,
                settings,
            )
            raw = _merge_match_results(raw_vision, item["fallback"])
        except Exception as exc:
            logger = capabilities.logger
            if logger is not None:
                logger.warning("AI Mask multimodal match failed for %s; using deterministic prior: %s", item["slide_id"], exc)
            try:
                capabilities.write_project_log(
                    project,
                    "ai_mask_vision_failed",
                    slide_id=item["slide_id"],
                    elapsed_sec=round(time.monotonic() - vision_started, 2),
                    timeout=_is_timeout(capabilities, exc),
                    error_type=type(exc).__name__,
                    error=str(exc)[:500],
                    configured_vision_model=configured_model,
                    resolved_vision_model=resolved_model,
                    thinking_disabled=bool(
                        capabilities.step2_llm_vendor_options(
                            resolved_model,
                            capabilities.get_setting("llm_base_url"),
                        )
                    ),
                )
            except Exception:
                pass
            raw = item["fallback"]
        cleaned = _clean_match(raw, item["slide"], item["element_list"], settings, item["fallback"])
        cleaned = _consolidate_title_regions(cleaned, item["elements"], item["slide"], item["title_regions"])
        cleaned = _ensure_narrated_group_anchors(cleaned, item["elements"], item["slide"])
        try:
            _write_json(item["slide_dir"] / "auto_mask" / "auto_match_before_completion.json", cleaned)
        except Exception:
            pass
        completed = _complete_component_coverage(cleaned, item["elements"], item["slide"])
        try:
            _write_json(item["slide_dir"] / "auto_mask" / "auto_match_after_completion.json", completed)
        except Exception:
            pass
        return completed

    matches: dict[str, dict[str, Any]] = {}
    if prepared:
        with ThreadPoolExecutor(max_workers=min(3, len(prepared)), thread_name_prefix="ai-mask-match") as executor:
            futures = {executor.submit(match_slide, item): item["slide_id"] for item in prepared}
            for future in as_completed(futures):
                matches[futures[future]] = future.result()

    slides_out = []
    total_updated = 0
    total_unmatched_groups = 0
    total_skipped = 0
    quality_passed = True
    review_issues: list[dict[str, Any]] = []
    for item in prepared:
        slide_id = item["slide_id"]
        match = matches[slide_id]
        _write_json(item["slide_dir"] / "auto_mask" / "auto_match.json", match)
        _write_json(item["slide_dir"] / "auto_mask" / "semantic_quality_report.json", {
            "slide_id": slide_id,
            "quality": match.get("quality", {}),
            "semantic_quality": match.get("semantic_quality", {}),
            "residual_assignment_report": match.get("residual_assignment_report", []),
        })
        applied = _apply(manifest, item["slide"], item["elements"], match, settings)
        total_updated += applied["updated"]
        total_skipped += applied["skipped"]
        unmatched_group_count = len(match.get("unmatched_groups", []))
        total_unmatched_groups += unmatched_group_count
        slide_quality = match.get("quality", {}) if isinstance(match.get("quality"), dict) else {}
        quality_passed = quality_passed and bool(slide_quality.get("passed"))
        semantic_quality = match.get("semantic_quality", {}) if isinstance(match.get("semantic_quality"), dict) else {}
        slide_review_issues = [{"slide_id": slide_id, **issue} for issue in _review_issues(match)]
        review_issues.extend(slide_review_issues)
        slides_out.append({"slide_id": slide_id, "detected_element_count": len(item["element_list"]), "residual_component_count": len(item["elements"].get("residual_elements", [])), "matched_group_count": len(match.get("matches", [])), "updated_group_count": applied["updated"], "skipped_group_count": applied["skipped"], "unmatched_element_count": len(match.get("unmatched_elements", [])), "unmatched_group_count": unmatched_group_count, "matching_method": match.get("matching_method"), "quality": slide_quality, "semantic_quality": semantic_quality, "warnings": match.get("warnings", []), "review_required": bool(slide_review_issues), "review_issues": slide_review_issues})
    # ``complete`` remains a backward-compatible processing signal.  Consumers
    # must use ``quality_status`` to distinguish a clean result from a usable
    # result that still needs human review.
    complete = total_updated > 0 and len(slides_out) > 0
    if not complete:
        quality_status = "failed"
    elif quality_passed and not review_issues:
        quality_status = "passed"
    else:
        quality_status = "needs_review"
    annotation_status = {
        "passed": "completed",
        "needs_review": "completed_needs_review",
        "failed": "incomplete",
    }[quality_status]
    manifest["ai_mask_annotation"] = {
        "version": "ai_mask_annotation_v3_exact_rle",
        "status": annotation_status,
        "quality_status": quality_status,
        "settings": settings,
        "processed_slide_count": len(slides_out),
        "updated_group_count": total_updated,
        "unmatched_group_count": total_unmatched_groups,
        "skipped_group_count": total_skipped,
        "quality_passed": quality_passed,
        "review_required": bool(review_issues),
        "review_issue_count": len(review_issues),
        "review_issues": review_issues,
        "scope_slide_ids": [item["slide_id"] for item in prepared],
    }
    _write_json(run_dir / "reveal_manifest.json", manifest)
    return {
        "success": True,
        "complete": complete,
        "quality_status": quality_status,
        "quality_passed": quality_passed,
        "processed_slide_count": len(slides_out),
        "updated_group_count": total_updated,
        "unmatched_group_count": total_unmatched_groups,
        "review_required": bool(review_issues),
        "review_issue_count": len(review_issues),
        "review_issues": review_issues,
        "slides": slides_out,
        "manifest_path": str(run_dir / "reveal_manifest.json"),
    }


