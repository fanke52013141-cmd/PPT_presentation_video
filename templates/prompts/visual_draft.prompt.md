# Visual Draft Prompt Template

为 `slide_plan.json` 中指定的 slide 生成一张 16:9、1920x1080 的整页静态视觉稿。

本阶段不重新定义风格。风格固定来自：

- `config/style_tokens.yaml`
- `references/style_reference/PPT_template.png`
- `references/style_reference/PPT_example.png`

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

- `PPT_template.png`：用于锁定空白母版、标题位置、黄色竖线、副标题横线、大圆角内容框、底部字幕留白。
- `PPT_example.png`：用于锁定内容密度、手绘图解风格、浅色胶囊标签、Token 小方块、手绘箭头、总结条样式。

## 固定风格

使用“温暖极简手绘线稿风”。

画面必须符合：

- 背景固定为暖白色 `#FFFDF7`。
- 左上角是主标题和副标题，黑色手写感字体。
- 标题左侧有一条短黄色竖线。
- 副标题下方有一条黄色手绘横线。
- 中间是一个大圆角黑色手绘内容框。
- 内容框内使用黑色手绘线稿、箭头、图标、浅色胶囊块、Token 小方块。
- 强调色只使用暖黄、浅绿、浅蓝。
- 底部保留干净字幕区，不放任何内容。

## 默认版式

- 主标题位置：`X=110, Y=55`，字号约 72px。
- 副标题位置：`X=110, Y=150`，字号约 38px。
- 黄色竖线位置：`X=60, Y=65, W=10, H=75`。
- 内容框位置：`X=60, Y=250, W=1800, H=650`。
- 字幕区范围：`Y=930` 到 `Y=1080`，必须留空。

## 内容结构处理

根据 `content_type` 选择表达方式：

- `concept_explanation`：左侧短句解释，右侧手绘示意图，底部总结条。
- `bullet_list`：3 到 5 个手绘要点卡片或项目符号。
- `process_flow`：横向或分段流程，用手绘箭头连接步骤。
- `comparison`：左右对比，左侧容易误解，右侧更准确说法。
- `timeline`：横向时间轴，展示先后顺序。
- `cycle`：循环箭头，展示反复优化或闭环过程。
- `cards`：多张卡片展示并列概念。
- `example_breakdown`：上方原句，下方拆成小方块或片段。
- `misconception_correction`：温和展示误区和修正，不使用强烈红叉。
- `cause_effect`：用箭头串联原因、影响和结果。
- `framework_map`：中心概念 + 周边分支。
- `hierarchy`：上下层级或从大到小关系。
- `matrix`：二维矩阵或四象限。
- `checklist`：操作清单，适合建议页。
- `summary_takeaway`：核心结论 + 底部总结条。
- `custom`：保持模板风格，并让结构尽量简单清楚。

## 强约束

- 不要科技蓝黑风。
- 不要赛博朋克。
- 不要复杂 3D 背景。
- 不要大面积渐变。
- 不要金属质感。
- 不要儿童卡通风。
- 不要让内容进入底部字幕区。
- 不要生成乱码、假文字、假 UI、假数据标签。
- 不要塞满页面，一页只表达一个核心点。
- 真实标题、正文、标签和图表文字后续必须由渲染器排版；视觉稿中不要依赖不可编辑文字。
