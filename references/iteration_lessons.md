# 2026-06-09 Macro Layer Composition Lessons

- 2026-06-10 update: default production should be master-split, not
  independent element recomposition. Generate one coherent Image Gen master
  slide, keep 48-80px spacing between macro groups, then split same-source PNG
  layers from that master.
- Narration must be planned before visual generation. `narration_beats` decide
  which visual groups exist and when they animate.
- A master slide that looks acceptable can still be rejected if macro groups
  overlap, touch, or cannot be split without dirty alpha edges. The fix is to
  regenerate a more splittable master image, not to patch the video with code.
- Image Gen macro layers can be recomposed reliably when each layer is a large
  coherent group and the background is handled as a manifest color or a simple
  generated background image.
- A successful visual recomposition is not enough. Narration, subtitles, and
  TTS must be regenerated from the actual macro layers on the current slide.
  Reusing old narration from a similar topic creates a mismatched video.
- The timeline must be semantic, not just a mechanical stagger. Title/subtitle
  can appear early; body, diagram, and summary layers should reveal when the
  voice reaches their narration cues.
- `animation: highlight` is not an entry animation. Summary/highlight layers
  need a separate entry event, otherwise they may be visible from frame 0.
- QA must inspect at least one video frame with active subtitles, because a
  clean static preview can still fail when captions cover the summary area.

# 迭代经验沉淀

本文档记录端到端生成视频时发现的问题、修复方式和后续规则。出现同类问题时，应优先更新这里、相关 skill、模板或 schema。

## 长期规则

- 先跑结构和视觉预览，再跑完整 TTS 视频，避免音频成本浪费在路径和渲染错误上。
- 每次视频必须校验 `ffprobe`：分辨率、帧率、视频时长、音频轨。
- 主版本低于目标时长时，优先拆页或补足讲解层次，不用延长停顿硬凑。
- 字幕区不属于 scene 元素生成范围，只能在视频合成阶段由字幕文件叠加。
- 页面主体必须来自 Codex Image Gen 位图，不得用前端代码补画。
- 当前生产默认路径是 `codex_image_gen_png_layers`：整页位图生成后必须拆成 PNG layers，再按 layer 动画。
- `visual_draft.png` 的“文件存在”和“可拆层”不等于来源合格；必须能追溯到 Codex Image Gen 生成记录。
- Image Gen 失败、无法落盘、无法确认来源时，属于硬阻塞；不得用 PIL、SVG、HTML、CSS、Canvas、React 或截图兜底生成整页视觉稿。
- 允许替代的是同类能力，例如 TTS provider fallback；不允许替代的是会改变生产范式的核心阶段，例如把 AI 图片阶段替换成本地绘图阶段。

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

## 2026-06-08 Image Gen 来源门禁失败复盘

### 事件

- 用户要求验证的主流程是：`文章 -> Codex Image Gen 整页图片 -> PNG 图层拆解 -> 语音合成 -> Remotion 视频`。
- 实际试跑中，`visual_draft.png` 被本地 PIL 脚本绘制出来，再进入拆层、TTS 和 Remotion。
- Remotion 没有绘制页面主体，且最终 scene 也是 PNG layers，但这仍然不合格，因为最上游整页视觉稿不是 Image Gen 产物。
- 因此该结果只能作为拆层、TTS、渲染计时样本，不能作为端到端生产链路验证样本。

### 系统原因

- 验收目标被错换：为了尽快交付可播放视频，优化方向从“验证图片优先生产链路”偏成了“跑通视频产物”。
- 来源约束没有机器化：脚本只校验 `visual_draft.png` 是否存在、PNG 尺寸是否正确、是否可拆层，没有校验它是否来自 Codex Image Gen。
- 硬阻塞和软阻塞未分类：MiniMax 缺 key 时可以记录并使用同类 TTS fallback；Image Gen 不可用时不能使用代码绘图 fallback。
- Image Gen 到 run 目录缺少标准交付协议：生成图默认在 `.codex/generated_images/...`，但项目需要 `runs/<run_id>/slides/<slide_id>/visual_draft.png`，中间缺少复制、记录和校验步骤。
- 复盘和最终报告没有先声明产物有效性边界，导致“能播放的视频”容易被误认为“合格生产流程输出”。

### 必须新增的流程规则

- 每页 `visual_draft.png` 必须配套 `visual_provenance.json`，至少记录：
  - `provider`: 必须是 `codex_image_gen`
  - `prompt_path`: 对应 `visual_prompt.md`
  - `source_generated_image_path`: `.codex/generated_images/...` 中的原始生成图路径
  - `copied_to`: 当前 slide 的 `visual_draft.png`
  - `created_at`
  - `operator_note`: 可选，说明是否重试、是否人工选择变体
- `validate_run_assets.py` 应新增 `--require-imagegen-provenance`：
  - 缺少 `visual_provenance.json` 时 fail。
  - `provider != codex_image_gen` 时 fail。
  - `source_generated_image_path` 不存在或不是图片时 fail。
  - `copied_to` 不等于当前 slide 的 `visual_draft.png` 时 fail。
- `generate-visual-drafts` skill 必须声明：
  - Image Gen 失败时停止并报告阻塞。
  - 不允许用 PIL、本地绘图脚本、SVG、HTML、CSS、Canvas、React、浏览器截图或 PPT 导出图替代整页视觉稿。
  - 只有成功复制 Image Gen 输出并写入 provenance 后，才能进入拆层。
- 最终报告必须先判断产物有效性：
  - `valid_pipeline: true | false`
  - 如果为 false，必须写清楚是哪一个生产阶段被替代或跳过。

### 后续优化

- 增加一键 runner，把 Image Gen 生成后的默认目录扫描、人工/自动选择、复制到 slide 目录、写 provenance、再调用拆层串起来。
- 在 `checks/preflight_checklist.md` 中区分“缺依赖可自愈”和“核心生产阶段不可替代”。
- 在坏案例库中记录本次事故，标签包含 `imagegen-provenance`、`invalid-fallback`、`pipeline-validity`。
