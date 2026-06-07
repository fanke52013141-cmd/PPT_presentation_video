# 固定视觉参考图

此目录存放长期复用的视觉参考图，用于约束 AI 科普页面整体风格，避免每次生成时风格漂移。

当前固定参考图：

```text
references/style_reference/PPT模板.png
references/style_reference/PPT示例.png
```

## 文件用途

- `PPT模板.png`：空白模板参考图，用于约束标题区、黄色竖线、副标题下划线、开放内容区和底部字幕安全区。
- `PPT示例.png`：完整页面示例图，用于约束内容组织方式、手写感文字、图标、分栏、标注、总结条和视觉密度；示例不使用中间大外框。

## 使用规则

- 参考图是仓库固定资源，运行期不换风格。
- 后续要更换视觉风格时，直接更新本目录中的固定参考图，并同步修改 `config/style_tokens.yaml`。
- Preflight 只检查上述两个实际文件。
- 视觉稿生成必须使用这些固定参考图。

## Remotion 约束

Remotion 只负责 PNG 图片层显示、PNG 图片层动画和音视频合成，不负责解释或绘制文本、shape、line、group 等复杂元素。

正式生产路径：

1. Codex Image Gen 生成整页 `visual_draft.png`。
2. `scripts/decompose_slide_layers.py` 保留 `assets/full_slide.png` 作为源图备份。
3. 从源图裁切 `background`、`title`、`subtitle`、`content_body`、`diagram`、`annotation`、`summary` 等 PNG 图层。
4. `scene.json` 使用 `visual_source: codex_image_gen_png_layers` 和 `layers[]`。
5. `animation_timeline.json` 绑定到 `scene.layers[].id`。

字幕由 Remotion 独立叠加，不属于 PPT 页面 PNG 层。
