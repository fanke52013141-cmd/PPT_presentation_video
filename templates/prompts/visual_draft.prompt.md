# Visual Draft Prompt Template

## Production Override: Macro Layer Package

Use this template to request both:

- a complete full-slide reference image for visual approval;
- separate Image Gen/Web Image Gen macro-layer PNGs plus a layer split plan for
  `layer_manifest.json`.

Do not rely on code to semantically crop `visual_draft.png` into production
layers. The split must be requested at image-generation time as large coherent
groups: `title_group`, `subtitle_group`, 1-4 `content_group` / `diagram_group`
assets, and optional `summary_group`.

Flat backgrounds should be represented by a manifest color or a generated solid
PNG, not by decomposing a full-slide bitmap.

Keep macro groups separated by 40-60px clean background and keep the subtitle
safe zone empty. For 1920x1080, PPT body layers should end at or above `y=930`.

For each macro layer, provide `text_summary` and `narration_cue` values for the
future `layer_manifest.json`. The narration must describe or expand the actual
visible content in those layers. The animation timeline should reveal layers
when the voice reaches their cue; do not reveal all content at the beginning.

为 `slide_plan.json` 中指定的 slide 生成一张 16:9、1920x1080 的整页静态视觉稿。

正式生产必须使用 Codex Image Gen 生成整页位图。标题、副标题、内容区、图标、线条、箭头、标注、总结条和所有 PPT 主体视觉内容都必须进入生成图片本身；后续 Remotion 只允许显示从这张 PNG 裁切出来的 PNG 图层、叠加字幕和播放音频，不得用 SVG、HTML、CSS、Canvas 或 React 代码补画页面主体内容。

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

- `references/style_reference/PPT模板.png`：锁定标题区、黄色竖线、副标题下划线、开放内容区和底部字幕安全区。
- `references/style_reference/PPT示例.png`：锁定内容区信息组织方式、手写感文字、图标、分栏、标注、总结条和视觉密度；注意示例没有中间大外框。

## 固定风格

- 画布为 16:9、1920x1080。
- 背景为暖白纸感。
- 主标题、副标题和底部字幕区位置必须稳定。
- 中间为无外框开放内容区，不生成大圆角内容框或 enclosing content frame。
- 内容区只表达当前 slide 的一个核心信息。
- 底部 `Y=930` 到 `Y=1080` 保留为干净字幕区，不放 PPT 主体内容。

## 内容结构处理

根据 `content_type` 选择表达方式：

- `concept_explanation`：左侧短句解释，右侧示意图，底部总结条。
- `bullet_list`：3 到 5 个要点卡片或项目符号。
- `process_flow`：横向或分段流程，用箭头连接步骤。
- `comparison`：左右对比，左侧常见误解，右侧准确说法。
- `timeline`：横向时间轴，展示先后顺序。
- `cycle`：循环箭头，展示反复优化或闭环过程。
- `cards`：多张卡片并列展示概念。
- `example_breakdown`：上方原句，下方拆成小方块或片段。
- `misconception_correction`：温和展示误区和修正。
- `cause_effect`：用箭头串联原因、影响和结果。
- `framework_map`：中心概念加周边分支。
- `hierarchy`：上下层级或从大到小关系。
- `matrix`：二维矩阵或四象限。
- `checklist`：操作清单。
- `summary_takeaway`：核心结论加底部总结条。
- `custom`：保持固定模板风格，结构尽量简单清楚。

## 可拆解要求

后续生产会从这张 `visual_draft.png` 中裁切 PNG 图层，并按图层做动画。生成时必须让主要视觉对象具备清晰分离边界：

- 主标题、副标题、每个内容块、图解、箭头、标签、总结条都应有可识别的独立区域。
- 独立可动画对象之间至少保留 24-40px 干净背景，不要互相压边。
- 箭头可以表达关系，但箭头端点不要贴住或压住文字、图标、边框、标签。
- 文字不要盖在图标、箭头或其他装饰上，除非它和背景色块属于同一个标签组。
- 优先生成 3-7 个大的可裁切内容组，不要生成大量细碎且彼此粘连的小元素。
- 如果画面需要连接关系，用留白和对齐表达层级，避免用长线穿过多个对象。

## 强约束

- 不要偏离固定参考图。
- 不要生成中间大圆角外框、黑色 enclosing content frame 或任何把内容圈起来的整页边框。
- 不要让内容进入底部字幕区。
- 不要生成乱码、假文字、假 UI、假数据标签。
- 不要塞满页面，一页只表达一个核心点。
- 后续 Remotion 只负责 PNG 图片层显示、轻量动画、音频和字幕；不得绘制 PPT 主体文字、线条、形状或图表。
