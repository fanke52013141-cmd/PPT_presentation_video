# Slide Plan Prompt

请基于输入文章 `runs/<run_id>/inputs/article.md`，直接生成 AI 科普 PPT 视频的 `slide_plan.json`。

不要先生成 `article_brief.json`。不要输出估算时长、语言字段或每页 duration。

## 输出目标

把整篇文章切分成一组可制作 PPT 视频的 slide。每页 slide 必须能直接进入后续视觉稿、scene 重建、TTS 和动画阶段。

## 输出结构

输出 JSON 必须符合 `schemas/slide_plan.schema.json`。

顶层字段：

- `topic.topic_id`
- `topic.topic_name`
- `topic.topic_summary`
- `slides[]`

每页 slide 必须包含：

- `slide_id`
- `slide_purpose`
- `main_title`
- `subtitle`
- `core_message`
- `content.content_type`
- `content.layout_intent`
- `content.items[]`
- `narration`

## 内容结构类型

`content.content_type` 必须优先使用以下值：

- `concept_explanation`：概念解释
- `bullet_list`：分点说明
- `process_flow`：流程结构
- `comparison`：对比结构
- `timeline`：时间轴
- `cycle`：循环结构
- `cards`：卡片组
- `example_breakdown`：示例拆解
- `misconception_correction`：误区纠正
- `cause_effect`：因果链
- `framework_map`：框架图
- `hierarchy`：层级结构
- `matrix`：矩阵结构
- `checklist`：操作清单
- `summary_takeaway`：总结页
- `custom`：仅在以上结构都不能表达时使用

## 生成规则

- 不限制 slide 数量，以讲清楚整篇文章为准。
- 每页只讲一个核心观点、问题或解释单元。
- 不要把多个复杂概念塞进同一页。
- `content.items[]` 要表达页面主要内容，不要只写一整段大文本。
- `layout_intent` 描述内容层面的排版意图，例如左右解释、横向流程、左右对比、时间轴、循环、卡片组等。
- `narration` 是这一页的演讲稿，必须可直接给 MiniMax TTS 朗读。
- 旁白使用中文短句，避免术语堆叠。
- 不写舞台说明、镜头说明、括号情绪说明。
- 如果文章结构混乱，按“问题、概念、过程、例子、误区、建议、总结”的教学顺序重组。

## 输出示例

```json
{
  "topic": {
    "topic_id": "token_basics",
    "topic_name": "什么是 Token？",
    "topic_summary": "Token 是 AI 处理文字时使用的基本单位，它会影响理解范围、速度和费用。"
  },
  "slides": [
    {
      "slide_id": "slide_001",
      "slide_purpose": "concept_explanation",
      "main_title": "什么是 Token？",
      "subtitle": "AI 处理文字时使用的最小单位",
      "core_message": "Token 不是简单的字数，而是 AI 读取和处理信息时使用的小单位。",
      "content": {
        "content_type": "concept_explanation",
        "layout_intent": "左侧短句解释概念，右侧用手绘小方块示意文字被拆分。",
        "items": [
          {"type": "text", "text": "Token 是模型读取和处理信息时使用的小单位。"},
          {"type": "text", "text": "它不一定等于一个字，也不一定等于一个词。"},
          {"type": "summary", "text": "一句话：Token 像 AI 理解文字时使用的小积木。"}
        ]
      },
      "narration": "我们先从一个基础问题开始，什么是 Token？你可以把它理解成 AI 读文字时用的小单位。它不一定等于一个字，也不一定等于一个词，更像是 AI 用来理解信息的小积木。"
    }
  ]
}
```
