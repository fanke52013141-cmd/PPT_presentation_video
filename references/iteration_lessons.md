# 迭代经验沉淀

本文档记录端到端生成视频时发现的问题、修复方式和后续规则。出现同类问题时，应优先更新这里、相关 skill、模板或 schema。

## 长期规则

- 先跑结构和视觉预览，再跑完整 TTS 视频，避免音频成本浪费在路径和渲染错误上。
- 每次视频必须校验 `ffprobe`：分辨率、帧率、视频时长、音频轨。
- 主版本低于目标时长时，优先拆页或补足讲解层次，不用延长停顿硬凑。
- 字幕区不属于 scene 元素生成范围，只能在视频合成阶段由字幕文件叠加。
- 页面主体必须来自 Codex Image Gen 位图，不得用前端代码补画。
- 当前生产默认路径是 `codex_image_gen_png_layers`：整页位图生成后必须拆成 PNG layers，再按 layer 动画。

## 2026-06-07 Token 经济学端到端运行

### 已解决的问题

- 固定 PPT 模板和 PPT 示例未被稳定使用。
  - 原因：参考图路径分散在配置、prompt、skill 和检查文档里。
  - 修复：统一为 `references/style_reference/PPT模板.png` 和 `references/style_reference/PPT示例.png`，并新增 `scripts/write_visual_prompts.py` 固化每页 Image Gen prompt。

- 视觉主体可能被 SVG、前端代码或本地绘图脚本拼出来。
  - 原因：旧流程没有明确禁止 code-native text/shape/line，也没有校验 production scene 是否仍带旧 `elements[]`。
  - 修复：`scripts/build_remotion_props.py` 拒绝 `elements[]`；Remotion 只接受 PNG layers；主体内容必须来自 Image Gen 位图裁切。

- PowerShell 默认编码导致中文 JSON 显示乱码甚至被误判。
  - 原因：Windows PowerShell 默认编码和 UTF-8 运行产物不一致。
  - 修复：核心 JSON 读写交给 Python 脚本，使用 `encoding="utf-8-sig"`。

## 2026-06-08 图层拆解修复

### 发现的问题

- 项目规定“每张 slide 图片生成后需要拆解成元素，并依据元素做动画”，但当前流程实际只生成一个 `full_slide_layer`。
- 单图层动画只能整页淡入，无法按标题、图解、标注、总结条逐步讲解。
- 视觉稿如果对象重叠、箭头压字、标签粘连，后处理很难拆出干净图层。

### 原因

- Stage 3 被收敛成单图层兜底路径，`prepare_full_slide_scenes.py` 会直接生成一个整页 PNG scene。
- 生成提示词只强调“整页位图”，没有强调后续要裁切成可动画对象。
- 校验器只检查 PNG 能不能渲染，没有生产级阻断“只有 full_slide”。

### 修复

- 新增 `scripts/decompose_slide_layers.py`：
  - 标准化 `visual_draft.png` 为 `assets/full_slide.png`。
  - 估计背景色，生成 `assets/background.png`。
  - 从整页图中裁切 `title`、`subtitle`、`content_*` 等透明 PNG 图层。
  - 生成 `scene.json`、`animation_timeline.json` 和 `decomposition_report.json`。
- `scripts/validate_run_assets.py` 新增：
  - `--require-layered`
  - `--fail-on-decomposition-warnings`
  - layer PNG 尺寸与 `box` 一致性检查。
- Remotion 支持同一 layer 多个事件，例如先 `fade_up` 后 `highlight`。
- `write_visual_prompts.py` 和 prompt 模板加入“可拆解构图”要求：对象之间留白、禁止重叠、箭头不压文字。
- README、AGENTS、skills、checks 改为 `codex_image_gen_png_layers` 主路径。

### 后续规则

- `full_slide` 只能作为拆层来源和对照备份，不是合格生产动画的唯一图层。
- 只有一个主体 group、图层 box 重叠严重、或未检测到内容时，应回到视觉稿生成阶段，不能靠 Remotion 修补。
