# 固定视觉参考图

此目录存放长期复用的视觉参考图，用于约束 AI 科普页面的整体风格，避免每次生成时风格漂移。

当前仓库实际固定参考图为：

```text
references/style_reference/PPT模板.png
references/style_reference/PPT示例.png
```

## 文件用途

- `PPT模板.png`：空白模板参考图，用于约束标题区、黄色竖线、副标题下划线、开放内容区和底部字幕安全区。
- `PPT示例.png`：完整页面示例图，用于约束内容区的信息组织方式、手写感文字、图标、分栏、标注、总结条和视觉密度；示例不使用中间大外框。

## 使用规则

- 参考图是仓库固定资源，运行期不改风格。
- 后续要更换视觉风格时，直接更新本目录中的固定参考图，并同步修改 `config/style_tokens.yaml`。
- Preflight 只检查上述两个实际文件。
- 视觉稿生成必须使用这些固定参考图。

## Remotion 约束

最终 Remotion 阶段只负责 PNG 图片层的显示、动画和音视频合成，不负责解释或绘制文本、shape、line、group 等复杂元素。

正式生产默认使用 Codex Image Gen 生成一张整页 `full_slide` PNG，模板、示例、标题、正文、图解、线条、箭头、图标和总结条都应已经包含在这张位图里。页面中间为开放内容区，不生成大圆角内容外框。

如果后续做增强拆层，`scene.json` 中的页面元素也只能是图像模型产出的 PNG 图片层：

- 整页 full_slide PNG
- 主标题 PNG
- 副标题 PNG
- 内容区主体 PNG
- 图解 PNG
- 重点标注 PNG
- 总结条 PNG

字幕由 Remotion 独立叠加，不属于 PPT 页面 PNG 层。
