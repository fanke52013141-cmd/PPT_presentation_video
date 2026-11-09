# AI Mask 智能分割增强方案（SAM2 + 自动能力探测）

文档日期：2026-11-09
适用范围：PPT_presentation_video 现有 AI Mask 自动标注与手动勾画能力
关联模块：`ai_mask_engine.py`、`ai_mask_component_detection.py`、`ai_mask_doclayout.py`、`ai_mask_config.py`、`static/mask_editor.js`

---

## 一、核心结论

不新增独立的"业务模式"，而是在现有 AI Mask 流程内做一次**分割引擎层增强**，并配套**自动能力探测 + 分级回退**：

- 检测到可用的 GPU 推理后端（首选另一台机器上的 ComfyUI + SAM2）时，自动使用智能分割，获得不依赖背景颜色的语义级精确蒙版。
- 检测不到、显存不足或调用失败时，静默回退到现有纯 CPU 确定性方案（`detect_elements`），用户流程不中断、结果不缺失。
- 对用户呈现为"算力来源/分割引擎"的状态标识，而不是一套需要重新学习的新工作流。

判断依据：

1. 用户的最终产出（reveal 视频、勾画标注、PPTX）没有变化，变化的只是"蒙版从哪来、准不准"，属于底层实现，应对用户透明。
2. 外部项目（image-to-layered-psd）是一份文档型 Skill，不含模型和可执行代码，其遮挡补全、背景重建、原生文字层、PSD 分层等约七成能力，是为"输出可编辑 PSD 给人二次编辑"服务的，本项目的视频 reveal 场景用不上。
3. 现有两个痛点（自动标注在复杂背景/对象贴合时失效、手动勾画定位难）根因是同一个：缺少通用语义分割能力，而不是缺一个模式。

---

## 二、外部项目的可借鉴点：取什么、不取什么

### 2.1 取（四点）

1. **通用分割能力**：用 SAM2 这类不依赖背景颜色、不假设对象之间有间隙的 promptable 分割模型，补强现有基于背景色距离 + flood fill + 连通域的确定性算法。
2. **"先冻结语义计划，再执行分割"的编排纪律**：在任何像素级分割之前，先确定对象清单、遮挡关系和分割目标并冻结，分割阶段只消费已确认的计划，不临时推断。
3. **非对称所有权门禁 + 双状态验收**：宁可多带经确认属于底层背景的安全带，也不漏掉对象像素；最终同时做"原位重合成"和"对象移开/单独显示"两种检查，避免原位看着一样、单独使用才暴露错误。
4. **证据像素与生成像素分离的合规思想**：原图实际像素属于事实证据，AI 生成内容必须明确标注为推测。本方案第一阶段不引入生成，仅吸收该约束思想。

### 2.2 不取（明确排除，避免过度投入）

- 被遮挡对象的生成式补全（视频 reveal 不需要把对象"移走"再补洞）。
- 背景重建（元素按 mask 揭示，不需要重建移开后的背景）。
- 原生文字层重建（本项目文字走现有 OCR 与 annotation 路径，不输出可编辑 PSD 文字节点）。
- 分层 PSD 导出与回读验收。

只有当未来确认要把"可编辑分层 PSD/设计源文件"做成独立交付品类时，才重新评估这部分能力并单独立项。

---

## 三、优化定位：精准改哪一部分

### 3.1 唯一核心改造点：分割引擎路由

`ai_mask_engine.py` 的 `_annotate_project` 中，当前对每张幻灯片在第 631 行直接调用：

```text
elements = detect_elements(image_path, slide_dir, settings, layout_boxes, layout_record)
```

这是全流程**唯一的分割入口**。改造方式是把这一行替换为一个引擎路由函数：

```text
elements = segment_elements(capabilities, image_path, slide_dir, settings, layout_boxes, layout_record)
```

由路由函数根据能力探测结果，决定走智能分割还是确定性分割，并把智能分割的输出**对齐到与 `detect_elements` 完全相同的返回契约**，从而保证下游零改动。

### 3.2 两个体验改造点

1. **手动勾画智能化**：在 `static/mask_editor.js` 工具栏新增"智能选区"工具，用户点击或框选对象后由 SAM2 自动给出贴合边缘的蒙版，现有画笔/橡皮降级为微调手段，复用现有 strokes、autosave、flush 机制。
2. **自动结果 QA 门控增强**：吸收外部项目的非对称所有权检查和双状态验收，补强现有质量门（见 7.4）。

### 3.3 明确不动的部分

以下链路全部复用，不重写：

- 多模态语义匹配（`vision_matcher` / `ai_mask_semantic_matcher.py`）
- 分配与清洗（`ai_mask_assignment.py` 的 clean、consolidate、rebind、complete 全流程）
- 蒙版应用（`ai_mask_manifest_apply.py` 写 `reveal_manifest.json`）
- reveal 场景构建、Remotion props、渲染与 PPTX 导出

---

## 四、目标架构

### 4.1 分层结构

```text
                         _annotate_project（现有编排，保持不变）
                                  │
                                  ▼
                    segment_elements（新增：分割引擎路由）
                                  │
        ┌─────────────────────────┼──────────────────────────┐
        ▼                         ▼                          ▼
 DeterministicProvider     ComfyUIProvider            LocalWorkerProvider（预留）
 现有 detect_elements       HTTP 调用 ComfyUI + SAM2     独立 worker 本地推理
 纯 CPU、零依赖             远程/局域网，GPU 加速         onnxruntime/torch
        │                         │                          │
        └─────────────────────────┴──────────────────────────┘
                                  │
                                  ▼
              统一元素契约（element_id / bbox / mask_rle=row_runs_v1）
                                  │
                                  ▼
        现有 fallback → vision_matcher → assignment → apply（全部复用）
```

### 4.2 关键设计原则

1. **Provider 抽象**：定义统一的分割接口，输入图像路径、设置、布局框，输出与 `detect_elements` 同构的 payload。新增后端只加实现，不改编排。
2. **输出契约强一致**：智能后端返回的每个元素必须包含现有字段（`element_id`、`bbox`、`center`、`area`、`position`、`mask_rle`、`source_ink_rle`、`ocr_text` 等），RLE 编码统一为 `row_runs_v1`，`canvas` 与各类 pixel count 字段齐全。
3. **依赖注入**：探测与后端能力通过现有 `AiMaskEngineDependencies` 风格注入，不引入对 server 模块的反向依赖，不破坏现有模块边界。
4. **主应用保持轻量**：主 Python 环境不安装 torch、不内置模型权重，智能推理全部放在独立后端（ComfyUI 或独立 worker）。

### 4.3 技术核心：DocLayout 出框 + SAM2 精分割 + 现有 VLM 绑定

SAM2 本身是"可提示分割"（给点/框出蒙版），不具备语义、也不自动决定"该拆成几个对象"，若直接用全自动 mask 容易切得过碎。因此采用三段式组合：

```text
DocLayout-YOLO（已有）：输出候选对象框
        │  作为 box prompt
        ▼
SAM2（新增）：对每个框精确分割，输出贴合轮廓
        │  转成统一 element 契约
        ▼
VLM 语义匹配 + assignment（已有）：把元素绑定到 visual_groups / narration_beats
```

这样 SAM2 职责单一（框内精确轮廓），既规避无语义导致的过碎问题，又最大化复用现有 DocLayout 与语义绑定能力。DocLayout 漏框或无框时，回退到 SAM2 点提示或确定性 `detect_elements`，保证不丢元素。

---

## 五、自动能力探测与分级回退（重点）

### 5.1 探测顺序（capability cascade）

路由在每次运行开始时做一次探测（结果可缓存，并在失败时失效）：

1. **ComfyUI 后端探测（首选）**
   - 对配置的端点依次尝试：用户配置地址 → 本机 `http://127.0.0.1:8188` → 记忆中的局域网地址。
   - 调用 `GET /system_stats`，确认服务在线、返回设备信息（设备名、`vram_total`、`vram_free`），并确认 SAM2 节点与工作流可用（可通过已保存的 API 工作流或节点清单校验）。
   - 做一次最小 smoke run（小图分割），验证"能真正出蒙版"，而不仅是端口可连。
2. **本地独立 worker 探测（预留）**
   - 复用 `ai_mask_doclayout.py` 的范式：检查 onnxruntime `get_available_providers()` 是否含 `CUDAExecutionProvider`，并要求真实绑定 + smoke run 通过；仅"可用列表里有 CUDA"不算数。
3. **确定性兜底**
   - 以上都不可用，直接使用现有 `detect_elements`，纯 CPU、零依赖、必定可运行。

### 5.2 硬件门槛与模型档位映射（规划锚点，需以实测校准）

> 2026-11-09 更新：已确认目标 GPU 机器为 RTX 5080（16GB 显存，Blackwell 架构），
> 四个 SAM2.1 档位均无压力，代码默认档位定为 `large`（safetensors）。该机器的
> ComfyUI 安装、节点、权重、局域网监听与防火墙的具体操作见
> `docs/sam2_comfyui_5080_deployment.md`。Blackwell 需新版 ComfyUI 与匹配的
> PyTorch/CUDA 运行时，具体版本以 5080 机器实测为准，本文件不写死版本号。
> 下方阈值表保留为通用规划锚点，5080 的真机 smoke 数据待部署后回填。

通过 `nvidia-smi`（`--query-gpu=name,memory.total,driver_version`）或 ComfyUI `/system_stats` 获取显存，按可用显存选择 SAM2 档位，为 1920×1080 输入和并发预留余量：

- 显存 ≥ 8GB：可跑 `hiera-large`，全档位，复杂图优先。
- 显存 6–8GB：`hiera-base-plus`（约 8080 万参数）。
- 显存 4–6GB：`hiera-small`（约 4600 万参数，权重约 185MB，运行内存约 1.5GB 量级）或 `hiera-tiny`（约 3900 万参数，fp16 权重约 126MB）。
- 显存 < 4GB、无独立显卡或驱动不满足：不启用智能分割，走确定性方案。

档位选择应自动向下兼容：目标档位加载失败时自动降一档，直到回退确定性方案。具体阈值在真机 smoke 后写入配置，不依赖未经实测的承诺。

### 5.3 设备模式与断路器（复用现有范式）

- 设置项沿用 `auto / cpu / cuda` 语义（参考 `doclayout_device_mode`）：
  - `auto`（默认）：按 5.1 自动探测与回退。
  - `cpu`：立即旁路，强制走确定性方案，不做任何 GPU 尝试。
  - `cuda`：要求验证 CUDA 绑定 + smoke run 通过，否则整轮回退 CPU。
- **失败断路器**：复用 `ai_mask_doclayout.py` 的 `_gpu_breakers` 思路。某后端一旦出现加载失败、连续超时或 smoke 不通过，记录失败原因并在本进程内对该后端短路，避免"一次失败导致每页都空等一轮"。断路器状态可随时间或手动重置。
- **运行中降级**：单次分割调用失败/超时，不阻断任务，立即对该页改用确定性方案，并在结果中如实标记实际使用的引擎与原因。报告的是"实际运行的后端"，不是"检测到 NVIDIA"。

### 5.4 对用户透明的呈现

- 在 AI Mask 运行结果与设置页显示当前引擎状态，例如：智能分割（ComfyUI / 设备名 / 档位）、确定性分割（CPU）、以及降级原因。
- 不强制用户理解模型与硬件，默认 `auto` 即可；高级用户可手动指定模式或后端地址。

---

## 六、模型下载说明（当前电脑是否需要下载）

### 6.1 主应用与当前无硬件电脑

- 主应用环境**不安装 torch、不下载任何模型权重**，保持现有轻量结构。
- 当前这台不具备 GPU 硬件条件的电脑：**无需下载任何模型**，`auto` 模式探测不到可用后端，会自动走原有确定性方案，行为与现状一致。

### 6.2 模型在推理后端那一侧

- 走 ComfyUI 路线：在安装 ComfyUI 的那台机器上安装 SAM2 节点，模型权重放置于 `ComfyUI/models/sam2/`，重启 ComfyUI 后生效。下载与存储都发生在 ComfyUI 所在机器，不影响当前电脑。
- 权重规格（按需选择，不必全量下载）：
  - `sam2.1-hiera-tiny`：约 3900 万参数，fp16 权重约 126MB，适合低显存/快速验证。
  - `sam2.1-hiera-small`：约 4600 万参数，权重约 185MB，精度与速度平衡，推荐作为默认起步档位。
  - `sam2.1-hiera-base-plus`：约 8080 万参数，复杂场景。
  - `sam2.1-hiera-large`：容量最大，需 8GB 以上显存。
- 内网/离线环境：支持手动下载权重后直接放入 `models/sam2/`，不要求后端机器联网。

### 6.3 ComfyUI 调用链（工程实现）

- 预先在 ComfyUI 中搭建并导出一份 API 格式的 SAM2 分割工作流（输入图像 + box/point 提示，输出蒙版）。
- 主程序通过 `POST /prompt` 提交工作流，`GET /history` 轮询任务状态，`GET /view` 取回蒙版图像，再将二值蒙版编码为统一的 `row_runs_v1` RLE，组装成元素契约。

---

## 七、文件级改造清单（分阶段落地）

### 阶段 0：能力探测与配置基础

- 新增 `ai_mask_segmentation_backend.py`（建议命名）：
  - 定义 `SegmentationProvider` 抽象接口与 `segment_elements` 路由函数。
  - 实现 ComfyUI 探测（`/system_stats`、节点/工作流校验、smoke run）、断路器、档位选择与结果缓存。
- 修改 `ai_mask_engine.py`：
  - `DEFAULT_SETTINGS` 与 `normalize_settings` 新增四个设置项：`segmentation_device_mode`（auto/cpu/cuda）、`comfyui_base_url`（可逗号分隔多候选）、`sam2_tier`（tiny/small/base_plus/large）、`sam2_workflow_path`（留空用内置模板）。
  - 原 `detect_elements(...)` 调用替换为 `segment_elements(capabilities, ...)`，智能路径失败自动回退。
- `ai_mask_config.py` 无需改动：读写逻辑遍历 `DEFAULT_SETTINGS`，新键自动覆盖并支持配置包导入导出。
- 新增工作流模板 `config/sam2_segmentation_api.json`（DownloadAndLoadSAM2Model→LoadImage→Sam2Segmentation→Mask To Image→SaveImage），权重按 `sam2_tier` 动态注入。
- 手动智能选区：`mask_editor_routes.py` 新增 smart-selection 路由调用 `run_smart_selection`；前端 `mask_editor.js` 新增点选模式，`mask_workspace.js` 语块卡片与 `index.html` 新增按钮和操作条。

### 阶段 1：手动勾画智能选区（先做，见效最快）

- 修改 `static/mask_editor.js`：
  - 新增"智能选区"工具按钮与状态（区别于现有画笔/橡皮），支持点击（正提示点）、可选负提示点和框选。
  - 调用后端新增的智能选区 HTTP 接口，取回贴合蒙版后渲染到当前语块，仍允许画笔/橡皮微调，复用现有 strokes 序列化与 autosave/flush。
- 后端新增对应路由（在现有 mask editor 路由体系内），把点/框转给 ComfyUI SAM2 工作流并返回蒙版；后端不可用时按钮禁用并提示，不影响纯手工勾画。

### 阶段 2：自动引擎路由与 ComfyUI Provider

- 在 `ai_mask_segmentation_backend.py` 实现 `ComfyUIProvider`：提交工作流、轮询、取回蒙版、转换为 `row_runs_v1`、组装完整 `detect_elements` 同构 payload。
- 实现 `DeterministicProvider`：内部直接封装现有 `detect_elements`，保证两条路径输出可互换。
- 结合 DocLayout 框作为 box prompt；漏框时按 4.3 回退。
- 预留 `LocalWorkerProvider` 接口，本期不实现。

### 阶段 3：QA 门控增强

- 在自动分割结果上增加非对称所有权检查（漏检像素 vs 经确认的底层背景安全带）与双状态验收（原位重合成 + 单独显示）。
- 将引擎标识、档位、降级原因写入现有质量报告与项目日志，复用 `write_project_log`。

### 阶段 4：验证与契约同步

- 按项目 `AGENTS.md` 的验证要求，补充前端所有权守卫、源码运行安全检查与相关测试。
- 若新增能力对 Agent 可见（新路由/新设置/新行为），按 Agent Contract 同步策略更新能力模型、版本号与契约文档。

---

## 八、验收标准

1. **契约一致性**：智能分割与确定性分割输出 payload 字段完全同构，下游 assignment、apply、reveal、remotion 无需改动即可消费。
2. **回退可靠性**：后端不可用、显存不足、加载失败、运行超时四类场景下，均能自动降级且不阻断任务，结果中无缺失元素、无空洞。
3. **分割有效性**：在非白底、纹理背景、对象贴合、同色相邻等确定性算法失效场景，智能分割能给出语义正确、边缘贴合的蒙版；元素不重叠、不漏检。
4. **手动体验**：智能选区可通过点击/框选一次成型，微调工作量显著低于纯手工，且结果可被现有 autosave/flush 正确持久化。
5. **可观测性**：每次运行可追溯实际使用的引擎、设备、档位、耗时与降级原因。
6. **零污染**：当前无 GPU 电脑不安装 torch、不下载模型，默认行为与现状字节级一致。

---

## 九、主要风险与应对

1. **ComfyUI 环境依赖风险**：节点/工作流版本不一致可能导致调用失败。应对：固定 API 工作流与节点版本，启动时校验，失败即降级。
2. **SAM2 过碎风险**：全自动 mask 易产生碎片。应对：坚持 DocLayout 框驱动 + 现有 VLM 语义绑定，不依赖无提示全自动分割。
3. **网络/跨机调用风险**：局域网或内网穿透不稳定。应对：短超时 + 断路器 + 确定性兜底，跨网方案与本地地址都可配置。
4. **契约漂移风险**：智能后端字段与现有元素契约不一致会冲击下游。应对：以统一适配器输出，并加契约一致性测试兜底。
5. **范围蔓延风险**：被遮挡补全/背景重建等生成能力容易被顺手加入。应对：本期明确不做，除非 PSD 源文件交付品类正式立项。

---

## 十、排期建议（粗粒度，待真机验证后细化）

- 第一期（阶段 0 + 阶段 1）：能力探测/配置基础 + 手动智能选区，优先交付，快速验证 SAM2 实际效果并积累真实修正数据。
- 第二期（阶段 2）：自动引擎路由 + ComfyUI Provider 全链路打通，实现 auto 模式下的自动分级。
- 第三期（阶段 3 + 阶段 4）：QA 门控增强、契约同步与完整回归。
- 真机门槛（显存阈值、档位映射、单页耗时、成功率）在具备 GPU 的 ComfyUI 机器上通过 smoke 与基准测试后，回填本文件 5.2，再据此确定正式默认值。

---

## 参考来源

- 外部项目说明：https://github.com/tangchengjiao/image-to-layered-psd（README、pipeline、IMPLEMENTATION）
- SAM2 模型规格与硬件参数：Ultralytics SAM2 文档、ISAT-SAM 模型表、HuggingFace SAM2.1 模型说明
- ComfyUI SAM2 接入：NVIDIA Omniverse SAM 工作流指南（模型放置于 `ComfyUI/models/sam2`）、ComfyUI 官方文档
