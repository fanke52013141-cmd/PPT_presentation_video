---
name: render-element-previews
description: Review the exact v3 mask composition before final video rendering.
---

# Purpose

检查视频实际会使用的抠除结果，不再预览旧的自动分层或宏观裁切结果。

# Inputs

- `slides/<slide_id>/visual_draft.png`
- `slides/<slide_id>/scene.json`
- `slides/<slide_id>/reveal_report.json`
- `slides/<slide_id>/assets/`

# Review Rules

- 无 Mask 页面必须完整显示原图。
- 有 Mask 页面必须显示用户设置的视频背景色。
- 内容内部白色不得被挖空。
- Mask 外前景以红色诊断图显示，覆盖率达到生产阈值后才能确认。
- Reveal 图层不得截断文字、线条、图标或色块。
- PPT 主体不进入底部字幕安全区。

# Validation

运行：

```powershell
python scripts/validate_reveal_scene.py `
  --run-dir runs/<run_id> `
  --repo-root .
```

同时在 Web 页面打开“最终抠除预览”，逐页确认最终合成图。
