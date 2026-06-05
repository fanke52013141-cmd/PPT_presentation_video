# 迭代经验沉淀

此文件记录端到端生成视频时发现的问题、修复方式和后续规则。出现同类问题时，应优先更新这里、相关 skill、模板或 schema。

## 2026-06-05 三轮生成：涉密文件应急处理

### 第 1 轮：端到端链路验证

- 现象：默认 MiniMax endpoint `api.minimax.io` 返回 `invalid api key`。
- 原因：当前可用 endpoint 是 `https://api.minimaxi.com/v1/t2a_v2`。
- 已沉淀：`.env.example`、`config/task.yaml`、`scripts/minimax_tts.py` 和 `generate-audio-subtitles` skill 已改为 `api.minimaxi.com`。

- 现象：Remotion 直接加载 `file:///...` 图片失败。
- 原因：Chrome 渲染环境不允许直接读取本地 file URL。
- 已沉淀：运行期图片和音频统一复制到 `scripts/remotion/public/runtime/<run_id>/`，Remotion 使用 `staticFile()` 加载。

- 现象：第 1 版视频约 125 秒，低于 AGENTS.md 规定的 3-6 分钟主版本目标。
- 优化：第 2 版补入“核实与联络”页；第 3 版扩展为 8 页，把审题拆成题型、关键词、身份三页，保证最终版进入 3-6 分钟范围。

### 长期规则

- 先跑结构版渲染，再跑完整 TTS 视频，避免音频成本浪费在路径和渲染错误上。
- 每次视频必须校验 `ffprobe`：分辨率、帧率、视频时长、音频轨。
- 若主版本低于 180 秒，不能只拉长停顿，应优先拆页或补足讲解层次。
- 字幕区不属于 scene 元素生成范围，只能在视频合成阶段由字幕文件叠加。

### 第 2 轮追加

- 现象：第 2 版增加到 6 页后，视频约 147 秒，仍低于 180 秒。
- 原因：原题解析天然包含“审题”和“示范答题”两个层级，6 页仍把审题压缩得过紧。
- 优化：第 3 版把审题拆成“定题型、抓关键词、定身份”三页，避免用延长停顿凑时长。

### 第 3 轮验收

- 结果：第 3 版扩展为 8 页，最终视频 `214.33s`，进入 3-6 分钟目标区间。
- 技术校验：视频轨 `1920x1080`、`30fps`；音频轨为 AAC，时长 `214.38s`。
- 视觉校验：抽取开头、中段、后段三帧，标题/副标题固定在顶部，正文与配图位于内容区，字幕只出现在底部字幕区。
- 已沉淀：`AGENTS.md`、`render-video` skill 和 `plan-slides` skill 补充了资源路径、结构预览、时长不足拆页规则。

### 第 4 轮：用户指出的视觉问题修复

- 现象：字幕在底部字幕框中偏上。
- 原因：Remotion 字幕容器高度只有 `58px` 且 `bottom: 30px`，没有按底图虚线字幕框中心对齐。
- 优化：字幕容器改为 `height: 82px`、`bottom: 8px`，单行和双行字幕抽帧检查均位于字幕框中心。

- 现象：每页布局几乎一致。
- 原因：`build_video_run.py` 所有页面复用相同卡片坐标和右侧视觉区。
- 优化：第 4 版加入 8 种布局：`list_left_visual_right`、`visual_left_list_right`、`keyword_grid`、`bottom_cards`、`timeline`、`report_chain`、`staggered`、`summary_board`。

- 现象：配图不是 Image Gen 生成，而是由 shape 和文字拼出。
- 原因：`build_scene()` 中用 `visual_panel`、`visual_doc`、`visual_secret`、`visual_deadline`、`visual_check` 等元素模拟配图。
- 优化：使用 Codex Image Gen 生成 8 格纸感拼贴资产表，裁切为每页独立 PNG；v4 的 `animation_role: visual` 元素全部为 `type: image`，`semantic_role: content_visual`，不再使用非图片 visual 元素。
