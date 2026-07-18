---
name: plan-slides
description: Convert a complete article into speech-driven slides and atomic narration-bound visual elements.
---

# Purpose

直接读取完整文章，用两个清晰阶段完成分镜规划：先形成认知旅程与逐页演讲稿，再把演讲稿逐字切分为可生成、可 Mask、可 Reveal 的原子视觉元素。流程不依赖文章摘要，不生成页面副标题。

# Inputs

```json
{
  "article_path": "runs/<run_id>/inputs/article.md",
  "generation_requirement": "可选：页数、受众、重点、用途和语气"
}
```

# Outputs

```json
{
  "script_plan_path": "runs/<run_id>/planning/slide_script_plan.json",
  "visual_plan_path": "runs/<run_id>/planning/slide_visual_plan.json",
  "visual_contract_path": "runs/<run_id>/planning/visual_contract.json"
}
```

# Stage A: Speech-driven script planning

读取 `article.md` 全文，输出：

```json
{
  "title": "项目或视频标题",
  "slides": [
    {
      "slide_id": "slide_001",
      "slide_title": "本页标题",
      "narration": "本页完整、可直接朗读的演讲稿"
    }
  ]
}
```

规则：

- 根据用户要求或文章内容判断领域与受众，不把非 AI 内容强行改写成 AI 科普。
- 先设计认知旅程，再分页；每页只推进一个主要认知动作。
- 默认页数自适应，用户明确页数时将其作为目标，但不能牺牲事实和关键逻辑。
- 演讲稿开头用可独立切分的自然片段引出标题，正文承担主要信息。
- 不输出副标题、正文要点数组、视觉元素、Mask 或动画。

# Stage B: Atomic visual planning

只读取 Stage A 的 `title`、`slide_id`、`slide_title` 和完整 `narration`，输出：

```json
{
  "slides": [
    {
      "slide_id": "slide_001",
      "visual_elements": [
        {
          "element_id": "el_001",
          "role": "title",
          "visual_type": "text",
          "visual_description": "画面实际文字或可画的元素描述",
          "narration": "原演讲稿中的连续非空片段"
        }
      ]
    }
  ]
}
```

规则：

- 每页恰好一个标题元素且至少一个正文元素。
- 不预设正文数量；由语义、Reveal 时机和空间边界自然决定。
- 一个元素是一项最小 Mask/Reveal 原子，不包含需要分别出现的独立视觉岛。
- 标题无论多色、描边或字形分离，始终是一个标题元素和一个组级 Mask。
- 每个元素绑定且只绑定一个非空旁白片段。
- 所有片段按顺序直接拼接后必须逐字还原 Stage A 演讲稿，标点不丢失、不重复、不改写。
- 每页 `element_id` 从 `el_001` 连续编号。

# Compose

把两个规划合并为 `visual_contract.json`，保持一项视觉元素对应一项 narration beat。文章短摘要仅可从 `article.md` 现场计算后写入合同元数据，不能成为演讲稿知识来源。

# Validation

- `article.md` 是唯一文章输入且非空。
- Stage A 每页只有 `slide_id`、`slide_title`、`narration`。
- Stage B 不改变 Slide 数量、顺序或标题。
- 每页标题唯一、正文非空，视觉元素和旁白严格一对一。
- 一个正文元素是合法结果；超过密度参考值只提示，不因数量直接拒绝。
- 原子性、Mask 可分离性和旁白完整性通过质量门。

# Failure Handling

- 内容简单时允许一页或一个正文视觉元素，不为凑数拆分。
- 内容复杂时自然增加页面或视觉元素，不把多个独立语义硬塞进一个组。
- 旁白无法自然切分时设计统一视觉结构，不改写旁白、不创建空旁白元素。
- 事实不足时保留边界，不补造数字、案例、引文或结论。

# Bad Case Tags

- `missing-input`
- `narration-weak`
- `source-divergence`
- `mapping-incomplete`
- `visual-not-atomic`
- `mask-boundary-unclear`
