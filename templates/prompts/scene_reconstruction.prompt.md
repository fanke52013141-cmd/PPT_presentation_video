# Scene Reconstruction Prompt

请把通过审核的 `visual_draft.png` 重建成可编辑、可动画的 `scene.json`。

## 基本要求

- 标题、副标题、正文、标签全部作为真实文本元素。
- 背景、主体插图、图标、线条、图形可以作为图片、形状或线条元素。
- 每个元素必须有稳定 `id`、`type`、`box`、`z_index`、`animation_role`、`region`、`semantic_role`。
- 坐标基于 1920x1080 画布。
- 默认使用 `config/layout_templates.yaml` 中的 `warm_handdrawn_framed_content` 版式。
- 标题区、内容区、字幕区必须保持独立，不互相侵入。
- 底部 `Y=930` 到 `Y=1080` 是字幕安全区，不输出任何 scene 元素；字幕只在视频合成阶段由字幕文件叠加。
- 输出必须符合 `schemas/scene.schema.json`。

## 固定结构

- 背景固定为 `#FFFDF7`。
- 必须输出 `title_marker`，作为左侧黄色竖线，`semantic_role: brand_marker`。
- 必须输出 `subtitle_underline`，作为副标题下方黄色横线，`semantic_role: subtitle_underline`。
- 必须输出 `content_frame`，作为中间大圆角黑色内容框，`semantic_role: content_frame`。
- 内容框位置固定为 `X=60, Y=250, W=1800, H=650`。
- 主标题固定使用 `main_title` token，字号 72px。
- 副标题固定使用 `subtitle` token，字号 38px。

## 内容区规则

- 内容元素只允许属于 `content`。
- 如果内容区有多条要点，每条要点必须拆成独立 `text` 元素，使用 `semantic_role: content_point` 和递增的 `content_index`。
- 正文短句使用 `semantic_role: content_text`。
- 手绘箭头使用 `semantic_role: content_arrow`。
- Token 小方块使用 `semantic_role: content_token_block`。
- 图标使用 `semantic_role: content_icon` 或 `summary_icon`。
- 小标题胶囊底使用 `semantic_role: capsule_label`。
- 总结条使用 `semantic_role: summary_bar`。

## 强调规则

- 关键词下划线使用 `semantic_role: keyword_underline`，颜色为 `#F9D65C`。
- 一页最多使用一个 `semantic_role: keyword_circle`。
- 小标题可用浅黄、浅绿或浅蓝胶囊底。
- 总结句优先放在内容框底部，左侧可加星星、灯泡或便签图标。
- 不要整句全部加粗，只强调关键词。

## 风格禁止项

- 不使用科技蓝黑风、赛博朋克、复杂 3D 背景。
- 不使用大面积渐变、金属质感、强阴影。
- 不使用儿童卡通大插画。
- 不生成不可编辑的正文、标题或图表文字。
