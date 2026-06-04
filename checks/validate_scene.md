# Scene 检查

检查对象：`runs/<run_id>/slides/slide_xxx/scene.json`

- `canvas.width = 1920`，`canvas.height = 1080`。
- 每个元素有唯一 `id`。
- 每个元素有合法 `type`、`box`、`z_index`。
- 所有文本必须作为 `type: text` 存在。
- 所有 `box` 不应超出画布。
- 主要阅读元素不能互相遮挡。
- 重要元素必须有 `animation_role`。

