# Visual Draft Prompt Template

为 `slide_plan.json` 中指定的 slide 生成一张 16:9、1920x1080 的整页静态视觉稿。

正式生产必须使用 Codex Image Gen 生成整页位图。标题、副标题、内容区、图标、线条、箭头、标注、总结条和所有 PPT 主体视觉内容都必须进入生成图片本身；后续 Remotion 只允许展示这张 PNG、叠加字幕和播放音频，不得用 SVG、HTML、CSS、Canvas 或 React 代码补画页面主体内容。

本阶段不重新定义风格。风格固定来自：

- `config/style_tokens.yaml`
- `references/style_reference/PPT模板.png`
- `references/style_reference/PPT示例.png`

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

- `PPT模板.png`：用于锁定标题区、黄色竖线、副标题下划线、开放内容区和底部字幕安全区。
- `PPT示例.png`：用于锁定内容区的信息组织方式、手写感文字、图标、分栏、标注、总结条和视觉密度；注意示例没有中间大外框。

## 固定风格

使用仓库固定参考图和 `style_tokens.yaml` 中定义的风格。不要使用运行期其它风格图。

画面必须符合：

- 画布为 16:9，1920x1080。
- 主标题、副标题和底部字幕区必须稳定。
- 中间为无外框开放内容区，不生成大圆角内容框。
- 内容区只表达当前 slide 的一个核心信息。
- 底部保留干净字幕区，不放 PPT 内容。
- 画面应作为完整整页 PNG 直接进入 Remotion。只有当拆出的素材本身也是图像模型生成的 PNG 时，才允许作为可选增强拆层。

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
- 不要生成中间大圆角外框、黑色 enclosing content frame 或任何把内容圈起来的整页边框。
- 不要让内容进入底部字幕区。
- 不要生成乱码、假文字、假 UI、假数据标签。
- 不要塞满页面，一页只表达一个核心点。
- 后续 Remotion 只负责 PNG 图片层显示、轻量动画、音频和字幕；不得绘制 PPT 主体文字、线条、形状或图表。
