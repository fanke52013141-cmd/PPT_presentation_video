# Scene Reconstruction Prompt

请把通过审核的 `visual_draft.png` 重建成可编辑、可动画的 `scene.json`。

要求：

- 标题、副标题、正文、标签全部作为真实文本元素。
- 背景、主体插图、图标、线条、图形可以作为图片或形状元素。
- 每个元素必须有稳定 `id`、`type`、`box`、`z_index`、`animation_role`。
- 坐标基于 1920x1080 画布。
- 输出必须符合 `schemas/scene.schema.json`。

