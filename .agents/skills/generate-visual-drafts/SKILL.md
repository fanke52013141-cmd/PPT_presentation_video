---
name: generate-visual-drafts
description: Generate one complete pure-white-background 1920x1080 slide image per storyboard page.
---

# Purpose

根据分镜规划生成完整的 `visual_draft.png`。图片本身包含标题、正文、图标、箭头、图表和标注；后续代码不得重绘 PPT 主体。

# Inputs

- `runs/<run_id>/planning/visual_contract.json`
- `runs/<run_id>/slides/<slide_id>/visual_prompt.md`
- `config/style_tokens.yaml`
- `references/style_reference/PPT模板.png`
- `references/style_reference/PPT示例.png`

# Outputs

- `runs/<run_id>/slides/<slide_id>/visual_draft.png`

# Required Rules

- 16:9，1920×1080。
- 画布外围背景必须是纯白色 `#FFFFFF`，不得使用米白、渐变、纹理、阴影或噪点作为外底。
- 内容内部可以使用白色；系统只会移除与画布边缘连通的近白色区域。
- 每页表达一个核心概念，独立内容组之间保留清晰留白。
- PPT 主体内容保持在 `y < 930`，底部字幕安全区不放内容或装饰。
- 标题、文字、图标、箭头和总结条必须全部生成在位图中。
- 不生成假 UI、乱码、无法解释的数据或复杂图表。

# Procedure

1. 读取当前页分镜和固定风格资源。
2. 运行 `python scripts/write_visual_prompts.py --run-dir runs/<run_id> --overwrite`。
3. 检查提示词包含“纯白色外围背景”和字幕安全区约束。
4. 生成或上传完整页面图片。
5. 目视检查图片尺寸、文字可读性、外围白底和底部安全区。

# Failure Handling

- 外围不是纯白色：重新生成。
- 文字乱码、对象重叠或内容过密：重新生成或拆页。
- 内容进入字幕区：调整提示词后重新生成。
