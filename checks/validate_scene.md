# Scene 检查

检查对象：`runs/<run_id>/slides/slide_xxx/scene.json`

- `canvas.width = 1920`，`canvas.height = 1080`。
- 每个元素有唯一 `id`。
- 每个元素有合法 `type`、`box`、`z_index`。
- 所有文本必须作为 `type: text` 存在。
- 所有 `box` 不应超出画布。
- 元素只允许属于 `title_block` 或 `content`，不得属于字幕区。
- 必须只有一个 `semantic_role: main_title` 和一个 `semantic_role: subtitle`。
- 多条正文要点必须拆成多个 `semantic_role: content_point` 的独立文本元素。
- 字幕区不允许出现任何 scene 元素；字幕只在视频合成阶段由字幕文件叠加。
- 主要阅读元素不能互相遮挡。
- 重要元素必须有 `animation_role`。
