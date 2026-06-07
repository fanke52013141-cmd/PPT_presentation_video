# 固定视觉参考图

此目录存放长期复用的视觉参考图，用于约束 AI 科普页面的整体风格，避免每次生成时风格漂移。

当前仓库实际固定参考图为：

```text
references/style_reference/fixed_title_free_content_reference.png
references/style_reference/paper_subtitle_background.png
```

## 文件用途

- `fixed_title_free_content_reference.png`：主参考图，用于约束固定标题区、内容区自由排版、整体页面密度和知识类页面气质。
- `paper_subtitle_background.png`：字幕背景和底部区域参考图，用于约束视频字幕背景、留白和底部视觉处理。

## 使用规则

- 参考图是仓库固定资源，运行期不改风格。
- 后续要更换视觉风格时，直接更新本目录中的固定参考图，并同步修改 `config/style_tokens.yaml`。
- Preflight 只检查上述两个实际文件，不再检查 `PPT_template.png` 或 `PPT_example.png`。
- 视觉稿生成必须使用这些固定参考图。

## Remotion 约束

最终 Remotion 阶段只负责 PNG 图片层的显示、动画和音视频合成，不负责解释或绘制文本、shape、line、group 等复杂元素。

因此，后续 `scene.json` 中的页面元素应尽量是 PNG 图片层：

- 整页背景 PNG
- 主标题 PNG
- 副标题 PNG
- 内容区主体 PNG
- 图解 PNG
- 重点标注 PNG
- 总结条 PNG

字幕由 Remotion 独立叠加，不属于 PPT 页面 PNG 层。
