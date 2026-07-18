---
name: reconstruct-scenes
description: Build deterministic reveal scenes from complete slide images and optional manual masks.
---

# Purpose

把每页完整位图、AI Mask 保存的精确 RLE 所有权和可选手工修正转换为 Remotion 使用的 PNG reveal 图层。生产版本固定为 `exact_rle_mask_with_manual_corrections_v5`。

# Behavior

- 无 Mask：整页静态显示，`composition_method=full_slide_static`。
- 有 Mask：从用户设置的视频背景开始合成，绝不复用完整原图作为背景。
- 每个自动 Mask 是处理边界；手工涂抹/擦除只作为其上的修正。只移除从该边界向内连通的近白色背景。
- 被内容包围的白色区域保留。
- Reveal builder 不重新判断语义归属，不做前景腐蚀或自动扩边。
- 抗锯齿边缘使用柔和透明度并去除白色污染。
- 自动 Mask 必须达到至少 99.5% 前景覆盖、零未分配组件和零跨组像素交叉。

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
- 生成资产与当前图片、Mask 或管线版本不一致。
- Mask 页面错误复用完整原图作为背景。
- `assets/` 中存在未被场景引用的旧文件。
