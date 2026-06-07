# Visual Draft Prompt Template

为 `slide_plan.json` 中指定的 slide 生成一张 16:9、1920x1080 的整页静态视觉稿。

本阶段不重新定义风格。风格固定来自：

- `config/style_tokens.yaml`
- `references/style_reference/fixed_title_free_content_reference.png`
- `references/style_reference/paper_subtitle_background.png`

## Slide 信息

- Slide ID：`{{slide_id}}`
- 页面作用：`{{slide_purpose}}`
- 主标题：`{{main_title}}`
- 副标题：`{{subtitle}}`
- 核心信息：`{{core_message}}`
- 内容结构类型：`{{content_type}}`
- 内容版式意图：`{{layout_intent}}`
- 页面内容项：`{{content_items}}`
- 本页演讲稿：`{{narration}}`

## 固定参考图

生成时必须参考：

- `fixed_title_free_content_reference.png`：用于锁定固定标题区、内容区自由编排、整体页面密度和知识类页面气质。
- `paper_subtitle_background.png`：用于锁定底部字幕区域、字幕背景视觉和页面底部留白。

## 固定风格

使用仓库固定参考图和 `style_tokens.yaml` 中定义的风格。不要使用运行期其它风格图。

画面必须符合：

- 画布为 16:9，1920x1080。
- 标题区、内容区和底部字幕区必须稳定。
- 内容区只表达当前 slide 的一个核心信息。
- 底部保留干净字幕区，不放 PPT 内容。
- 画面应适合后续拆成若干 PNG 图片层并在 Remotion 中做轻量动画。

## 内容结构处理

根据 `content_type` 选择表达方式：

- `concept_explanation`：左侧短句解释，右侧示意图，底部总结条。
- `bullet_list`：3 到 5 个要点卡片或项目符号。
- `process_flow`：横向或分段流程，用箭头连接步骤。
- `comparison`：左右对比，左侧容易误解，右侧更准确说法。
- `timeline`：横向时间轴，展示先后顺序。
- `cycle`：循环箭头，展示反复优化或闭环过程。
- `cards`：多张卡片展示并列概念。
- `example_breakdown`：上方原句，下方拆成小方块或片段。
- `misconception_correction`：温和展示误区和修正。
- `cause_effect`：用箭头串联原因、影响和结果。
- `framework_map`：中心概念 + 周边分支。
- `hierarchy`：上下层级或从大到小关系。
- `matrix`：二维矩阵或四象限。
- `checklist`：操作清单，适合建议页。
- `summary_takeaway`：核心结论 + 底部总结条。
- `custom`：保持固定模板风格，并让结构尽量简单清楚。

## 强约束

- 不要偏离固定参考图。
- 不要让内容进入底部字幕区。
- 不要生成乱码、假文字、假 UI、假数据标签。
- 不要塞满页面，一页只表达一个核心点。
- 后续 Remotion 只负责 PNG 图片层动画，因此视觉稿应适合拆分为独立 PNG 图层。
