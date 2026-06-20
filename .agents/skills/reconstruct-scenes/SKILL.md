---
name: reconstruct-scenes
description: Build deterministic reveal scenes from complete slide images and optional manual masks.
---

# Purpose

把每页完整位图和可选手工 Mask 转换为 Remotion 使用的 PNG reveal 图层。生产版本固定为 `manual_mask_outer_white_v3`。

# Behavior

- 无 Mask：整页静态显示，`composition_method=full_slide_static`。
- 有 Mask：使用用户设置的视频背景色，`composition_method=solid_background_outer_white_manual_mask`。
- 只移除与图片外边缘连通的近白色背景。
- 被内容包围的白色区域保留。
- 手工 Mask 是保留范围；不做前景腐蚀、膨胀、自动扩边或语义分割。
- 未使用橡皮时填平完全封闭的 Mask 内部空洞；使用橡皮时保留擦除结果。

# Command

```powershell
python scripts/build_reveal_scene.py `
  --manifest runs/<run_id>/reveal_manifest.json `
  --repo-root .

python scripts/validate_reveal_scene.py `
  --run-dir runs/<run_id> `
  --repo-root .
```

# Outputs

- `slides/<slide_id>/scene.json`
- `slides/<slide_id>/animation_timeline.json`
- `slides/<slide_id>/reveal_report.json`
- `slides/<slide_id>/assets/*.png`

# Blocking Conditions

- 当前页图片或 Mask 文件缺失。
- Mask 外仍有超过允许阈值的前景内容。
- 生成资产与当前图片、Mask 或管线版本不一致。
- Mask 页面错误复用完整原图作为背景。
