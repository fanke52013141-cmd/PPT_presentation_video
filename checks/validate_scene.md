# Scene 检查

检查对象：`runs/<run_id>/slides/slide_xxx/scene.json`

## 必查项

- `canvas.width = 1920`，`canvas.height = 1080`。
- `scene.json` 必须使用 `layers[]`，不得使用旧的 `elements[]`。
- 每个 layer 必须有唯一 `id`。
- 每个 layer 必须有合法 `type`、`asset`、`role`、`box`、`z_index`。
- 每个 layer 的 `type` 必须是 `png`。
- 所有 PPT 主体文字、线条、箭头、图标、图表和标注都必须已经包含在 PNG 位图素材内。
- 不允许出现 SVG、HTML、CSS、Canvas、React 绘制元素，或 `type: text`、`type: shape`、`type: line`。
- 生产默认路径应只有一个 `role: full_slide` 的整页 PNG layer。
- `full_slide` layer 的 `box` 必须是 `{"x": 0, "y": 0, "w": 1920, "h": 1080}`。
- PNG 素材必须保存到当前 slide 的 `assets/` 目录，并能被 `scripts/build_remotion_props.py` 复制到 Remotion `public/runtime/`。
- 字幕区不属于 PPT 主体内容；字幕只在视频合成阶段由 `audio_timeline.json` 叠加。

## 推荐命令

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-full-slide
```
