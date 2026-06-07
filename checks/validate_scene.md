# Scene 检查

检查对象：`runs/<run_id>/slides/slide_xxx/scene.json`

## 必查项

- `canvas.width = 1920`，`canvas.height = 1080`。
- `scene.json` 必须使用 `layers[]`，不得使用旧的 `elements[]`。
- `visual_source` 必须是 `codex_image_gen_png_layers`。
- 生产场景必须是多 PNG layer，不得只有一个 `full_slide` layer。
- 每个 layer 必须有唯一 `id`。
- 每个 layer 必须有合法 `type`、`asset`、`role`、`box`、`z_index`。
- 每个 layer 的 `type` 必须是 `png`。
- 每个 layer 的 PNG 文件尺寸必须等于 `box.w`、`box.h`。
- 每个 layer 的 `box` 必须位于 1920x1080 画布内。
- 所有 PPT 主体文字、线条、箭头、图标、图表和标注都必须来自 PNG 位图裁切。
- 不允许出现 SVG、HTML、CSS、Canvas、React 绘制元素，或 `type: text`、`type: shape`、`type: line`。
- 字幕区 `Y=930` 到 `Y=1080` 不属于 PPT 主体内容，只能由视频合成阶段叠加字幕。
- 如果 `decomposition_report.json` 有 warning，需要判断是否阻塞：重叠、单主体 group、无法检测内容通常应回到视觉稿生成。

## 推荐命令

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered
```

严格模式：

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered `
  --fail-on-decomposition-warnings
```
