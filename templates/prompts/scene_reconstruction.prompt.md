# Scene Reconstruction Prompt

请把通过审核的 `visual_draft.png` 重建成可编辑、可动画的 `scene.json`。

要求：

- 标题、副标题、正文、标签全部作为真实文本元素。
- 背景、主体插图、图标、线条、图形可以作为图片或形状元素。
- 每个元素必须有稳定 `id`、`type`、`box`、`z_index`、`animation_role`。
- 坐标基于 1920x1080 画布。
- 默认使用 `config/layout_templates.yaml` 中的 `fixed_title_free_content` 版式。
- 主标题和副标题必须放在同一个固定 `title_block` 内，分别作为真实文本元素输出。
- 主标题固定使用 `main_title` token，副标题固定使用 `subtitle` token，不要自行改变字号、颜色和位置。
- 中部统一作为 `content` 内容区，正文、配图、图表和重点块可在内容区内自由编排。
- 输出元素只允许属于 `title_block` 或 `content`。
- 如果内容区有多条要点，每条要点必须拆成独立 `text` 元素，使用 `semantic_role: content_point` 和递增的 `content_index`。
- 配图、图解、线条、重点块必须属于内容区，分别使用 `content_visual`、`content_diagram`、`content_line` 或 `content_highlight` 等语义角色。
- 标题区、内容区、字幕区必须保持独立，不互相侵入。
- 底部 120px 为字幕安全区，不输出任何 scene 元素；字幕只在视频合成阶段由字幕文件叠加。
- 输出必须符合 `schemas/scene.schema.json`。
