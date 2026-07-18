# Visual Draft Prompt Contract

## 目的

生成一张完整、可直接使用，并适合后续元素抠除与 AI 语义匹配的 1920×1080 PPT 位图。

## 输入

每页只接收必要且最小的内容：

- `slide_id`：任务标识，不得画进页面。
- `main_title`：唯一主标题。
- `body_elements[]`：Step 2B 已确认的正文视觉元素；每项只包含 `type` 与 `content`。
- 当前生效的图片风格与可选参考图。

不重复发送完整文章、完整旁白、核心信息、正文摘要、旁白节奏或完整 `visual_groups` 元数据。运行时可编辑的完整规则来源是 `templates/prompts/step3_image_system.md`，项目自定义值保存在 `planning/step3_image_prompts.json`。

## 输出

只输出一张完整的 1920×1080、16:9 PPT 静态位图，不输出说明、JSON、备选拼图、Mockup、透明图层、Mask、边界框或动画说明。

## 不可覆盖的生产铁律

- 外围画布为连续纯白 `#FFFFFF`。
- 只有一个主标题，不生成页面副标题。
- 所有可见内容止于 `y<930`，`y=930..1080` 完全留空。
- 独立语义元素之间保留清晰纯白间隙，不重叠、穿插、压住或粘连。
- 图片本身包含全部 PPT 主体；Remotion 不重绘标题、正文、图标、箭头、图表或标签。
