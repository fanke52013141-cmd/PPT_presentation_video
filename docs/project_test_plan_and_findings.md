# 数字人 + IndexTTS 2.5 项目测试计划与当前审计结果

## 1. 当前结论

当前项目不能判定为“可直接交付”。已完成的自动化基线结果是：

- 初始基线为 `284 passed, 8 failed, 1 warning`；当前 `.venv\Scripts\python.exe -m pytest checks -q` 为 `298 passed`。
- ComfyUI + IndexTTS 2.5 的独立调用已成功，`generic_tts.py --provider comfyui_tts` 也成功生成有效 WAV。
- 但是，使用 ComfyUI TTS 作为项目默认提供方的完整六步流程尚未通过一次端到端验收。
- 8 个失败主要集中在 4 个根因：子进程测试替身失效、One-click 兼容签名、AI mask 辅助函数缺失/改名、字幕默认字体契约不一致。
- 当前 `.venv` 没有安装 pytest，导致项目虚拟环境不能复现测试结果；这是测试基础设施阻塞项。

因此建议先修复测试契约和环境复现问题，再进行一次使用真实 ComfyUI 服务的六步端到端测试；在端到端通过前，不建议删除旧代码或把 ComfyUI TTS 设为生产默认。

> 进度更新：2026-08-30 已完成 P0 测试 seam、One-click 兼容、AI mask helper、字体契约、`.venv` 依赖和 ComfyUI/IndexTTS 预检；`.venv\Scripts\python.exe -m pytest checks -q` 当前为 `298 passed`。ComfyUI TTS 设置页短文本测试、现有项目工件验证、MP4 流检查和数字人 health 校正均通过。恢复型 One-click E2E 已因意外触发云端故事板重算而主动中止，项目状态已恢复；真实六步端到端验收仍待在隔离环境执行。

补充：One-click 预检查已修复本地 TTS provider 的凭据判断，并覆盖 `IndexTTS-2.5`、`Index TTS 2.5` 等常见显示名称；本地 provider 只检查 ComfyUI 工作流存在性，不再要求云端 TTS API Key。

## 2. 测试范围

### 2.1 用户可见流程

| 用户步骤 | 内部步骤 | 主要验证 |
|---|---:|---|
| 1. 新建项目/输入主题 | Step 1 | 项目创建、输入校验、状态持久化 |
| 2. 生成并确认故事板 | Step 2 | 文案生成、重试、确认门禁、恢复 |
| 3. 生成并确认视觉素材 | Step 3 | 图片生成、背景/字幕设置、素材替换 |
| 4. 编辑数字人/遮罩 | Step 4 | 人物图、遮罩、预览、替换规则 |
| 5. 生成视频 | Step 5 | Remotion/ComfyUI、渲染任务、音视频同步 |
| 6. 导出和下载 | Step 6 | 输出文件、下载、历史记录、重启恢复 |

附属范围：TTS 提供方（MiniMax 与 ComfyUI IndexTTS 2.5）、任务队列、数据库、前端状态机、错误恢复、日志、临时文件清理和安全配置。

补充：当前 UI 在六步主流程之后插入了一个可选的“数字人讲解”扩展步骤（内部 Step 9），再进入作品输出（内部 Step 8）。它不应阻塞普通视频/PPTX 输出，但必须单独验证启用、跳过和失败回退。

### 2.2 不在本轮直接删除的内容

旧 TTS/工作流兼容分支、旧 InfiniteTalk/T8 路径、前端兼容桥接和生成的测试 WAV 都先列为“待审计”。必须先用 `rg` 完成引用审计并得到可重复测试证据，不能仅因看起来旧就删除。

## 3. 测试环境矩阵

### 3.1 已知环境

- 项目：`D:\Program Files (x86)\PPT_presentation_video`
- 规范 ComfyUI：`D:\软件\Wan2.2-ReMix-SVI2-V3\Wan2.2-ReMix-SVI2-V3\ComfyUI`
- ComfyUI 地址：`http://127.0.0.1:8188/`
- GPU：RTX 5080
- IndexTTS 2.5 节点：`custom_nodes\BSAI_ComfyUI_IndexTTS-2.5`
- 参考音频：`C:\Users\Administrator\Desktop\PPT可视化项目\教授声音.mp3`
- API 工作流：`data\digital_human\comfyui_tts_workflow.json`
- GUI 工作流：`data\digital_human\IndexTTS25_BSAI_GUI_workflow.json`

### 3.2 必须补齐的环境

1. 在项目 `.venv` 中安装 `requirements-dev.txt`，至少包含 pytest；测试不能依赖系统 Python 的偶然安装状态。
2. 固定并记录 Python、PyTorch/CUDA、Node、npm、ffmpeg/ffprobe、ComfyUI commit/版本和模型清单。
3. 准备两个数据集：
   - `fixture-minimal`：少量幻灯片、短文案、短音频，供每次回归。
   - `fixture-real`：真实教授声音、真实图片和目标输出，供发布前验收。
4. 单元测试不得依赖已启动的 ComfyUI、外部 API 或大模型；真实服务只进入集成/E2E 套件。

## 4. 测试分层和执行计划

### P0：启动与预检（每次运行前）

- 启动项目 API，检查健康路由、数据库迁移和静态资源。
- 检查 `ffmpeg`、`ffprobe`、Node/Remotion、ComfyUI `/system_stats` 与 `/object_info`。
- 验证 IndexTTS 节点、模型目录、工作流 JSON 可解析且节点类型存在。
- 验证参考音频能被读取、采样率/声道/时长有效。
- 生成一份带时间戳的 preflight 报告；失败时禁止进入全链路测试。

### P1：单元/服务边界

覆盖 `checks/` 中已有测试，并补齐以下边界：

- 项目、故事板、视觉设置、遮罩、渲染、导出服务的输入/输出契约。
- TTS 提供方别名、凭据优先级、超时、重试、结构化失败。
- 音频确认门禁、音频工件完整性、陈旧工件删除和路径安全。
- ComfyUI 工作流参数注入、响应解析、结果文件复制和异常映射。
- 数据库状态机、重复提交幂等、任务取消和进程重启后的状态恢复。

### P1：组件集成

按边界逐段运行，而不是一开始就跑大模型：

1. Step 1 → Step 2：项目输入保存后生成故事板，刷新页面仍可继续。
2. Step 2 → Step 3：确认门禁、视觉设置保存、图片失败重试。
3. Step 3 → Step 4/5：人物图片、遮罩预览、遮罩替换规则和提示信息。
4. Step 5：Remotion 渲染、音频时长、视频时长、帧率和输出路径一致。
5. TTS：MiniMax mock、ComfyUI mock、ComfyUI 真实服务各跑一套。
6. Step 5 → Step 6：视频完成后导出、下载、历史记录和重新打开。

### P0：完整六步 happy path

使用 `fixture-minimal` 完整执行：

1. 创建项目并输入短主题。
2. 生成故事板并确认。
3. 生成视觉素材并确认。
4. 上传人物图和参考音频，生成/确认遮罩。
5. 将 TTS 提供方切到 ComfyUI IndexTTS 2.5，生成音频并渲染视频。
6. 导出并下载 MP4，重新打开项目验证结果仍可播放。

验收指标：无未处理异常；每一步状态单调推进；失败可重试；刷新/重启后不丢状态；视频存在画面、音频可听、时长和字幕基本一致。

### P0：失败与恢复矩阵

- ComfyUI 离线、端口错误、节点缺失、模型缺失、工作流 JSON 损坏。
- IndexTTS 参考音频不存在、格式损坏、过短、超长或无权限。
- TTS 超时、返回空音频、音频损坏、输出路径不可写。
- 图片/遮罩生成失败、预览超时、视频输出不存在或零字节。
- 用户重复点击、浏览器刷新、API 进程重启、渲染进程被杀。
- 旧工件与新任务混用、任务取消后仍写入最终输出。

每个场景必须验证：HTTP 状态、用户可读错误、数据库状态、日志关联 ID、临时文件清理、再次重试结果。

### P1：前端和浏览器验收

- 六步导航、确认按钮门禁、错误提示、重试按钮、进度轮询、刷新恢复。
- Chrome/Edge 最新版；至少检查 1280×720 和 1920×1080。
- 检查长文案、中文字体、无图片、慢网络、重复点击、浏览器返回键。

### P1：性能、安全和可维护性

- 首次模型加载耗时与后续缓存耗时；单任务 GPU 峰值显存；并发 1/2/3 时队列行为。
- 任务超时、输出目录配额、临时文件回收和日志大小。
- 文件名/path traversal、上传 MIME 与扩展名、外部 URL、命令参数转义、日志脱敏。
- 运行架构边界、模块大小、重复 helper、未使用兼容分支和未引用静态代码检查。

## 5. 当前自动化结果和根因

| 分组 | 现象 | 影响 | 优先级 | 建议 |
|---|---|---|---|---|
| 子进程测试替身失效 | `mask_preview_service`、`tts_provider_service` 使用 `run_subprocess_killable`，测试却 patch `subprocess.run` | 预览超时、TTS 重试/超时测试无法验证真实契约，出现 `[WinError 2]` 或错误状态 | P0 | 提供统一可注入的 subprocess seam；更新测试只替身该 seam，并保留一次真实 subprocess smoke test |
| One-click 签名不兼容 | `one_click._complete(...)` 现在要求 `db`，旧测试仍按旧签名调用 | 完成态/智能恢复逻辑回归测试直接 TypeError | P0 | 确认新签名是否为正式契约；若是，更新全部调用方和测试；若需兼容，提供薄兼容包装 |
| AI mask 辅助函数缺失 | `ai_mask_engine._replaceable_ai_mask` 不存在 | 仅未校正 AI mask 的替换规则无法被回归验证 | P1 | 查找改名/迁移后的实现；恢复稳定公共 helper 或更新测试契约 |
| 字幕默认值不一致 | 测试期望 `Noto Sans SC`/`noto_sans_sc`，实现返回 `LXGW Marker Gothic`/`lxgw_marker_gothic` | 视觉设置契约不明确，可能造成已有项目显示变化 | P1 | 明确产品默认；若已切换字体则更新契约、迁移和 UI 文案，否则恢复旧默认 |
| 虚拟环境不可复现 | `.venv` 没有 pytest | 本机/CI 无法按项目环境执行测试 | P0 | 安装 `requirements-dev.txt`，锁定依赖并在 CI 中强制使用 `.venv` |
| 测试依赖告警 | FastAPI/Starlette TestClient 与 httpx 出现 deprecation warning | 未来升级可能变成失败 | P2 | 升级/固定兼容版本，或改为显式 ASGI transport 测试 |

原始基线命令：

```powershell
python -m pytest checks -q
# 结果：284 passed, 8 failed, 1 warning
```

## 6. 阻塞性 Bug 判定

以下任一项未解决，发布验收应为“不通过”：

1. P0 测试替身无法拦截实际子进程调用，导致超时/重试/预览逻辑没有可信回归保护。
2. 六步流程使用 ComfyUI TTS 的真实端到端测试未完成或视频无画面/无音频。
3. `.venv` 与 CI 不能稳定重现测试环境。
4. 任务刷新、API 重启、ComfyUI 离线后，项目状态不能恢复或产生不可清理的半成品。
5. 输出文件存在但零字节、无视频流、无音频流，或音视频时长明显不一致。

## 7. 待优化点

### 7.1 测试与架构

- 统一子进程执行接口，传入 runner/clock/timeout，避免业务代码与 `subprocess.run` 绑定。
- 为 ComfyUI 增加显式 preflight 和能力探测，启动时报告节点/模型缺失，而不是执行到中途才失败。
- 将真实模型测试与快速 contract 测试分开；默认只跑快速套件，发布前再跑 GPU 套件。
- 给每个任务增加 correlation ID、阶段耗时、重试次数、输出文件大小和校验摘要。
- 对任务状态机增加幂等键，防止重复点击产生多个渲染任务。

### 7.2 性能与稳定性

- 缓存 ComfyUI 模型加载和工作流能力检查，避免每次请求重复初始化。
- 对上传、生成和渲染设置统一超时、取消传播和磁盘配额。
- 统一临时目录生命周期，任务失败、取消和重启恢复都要清理孤儿工件。
- 对长文案和大图片增加尺寸/时长上限与用户提示。

### 7.3 前端体验

- 所有长任务显示阶段、预计等待、可取消状态和最后一条错误原因。
- 禁用重复提交并在刷新后从服务端状态恢复，而不是仅依赖前端内存。
- 将“音频已确认”“遮罩已确认”“可渲染”做成显式状态，减少隐式门禁。

## 8. 冗余代码审计清单（先审计，后决定是否删除）

1. `comfyui_backend.py` 中 TTS 节点 ID、输入键匹配、旧 T8/通用 fallback 分支：用 `rg` 查所有调用和工作流覆盖率，合并重复路径。
2. `server.py` 中仅做转发的 route/helper：确认 owning module 已完整导出后，再减少重复 re-export；不得破坏启动导入顺序。
3. TTS 兼容别名、旧 provider 参数和默认值：统计数据库历史值、前端提交值、脚本 CLI 值后再迁移。
4. `static/` 中重复的状态同步/轮询桥接：按页面入口和 API 事件做引用图，避免删除仍被 HTML 内联脚本使用的函数。
5. `checks/` 中重复的真实模型测试：抽出共享 fixture，保留少量 smoke test，避免每次回归重复加载模型。
6. `data/digital_human/IndexTTS25_*` 等生成的 WAV/中间文件：视为本地测试产物，加入忽略规则或移到 `runs/`/`outputs/`，不要作为源码提交。

删除前的最低证据：全仓库引用为零、对应测试已迁移、旧项目可打开、数据库旧值有迁移策略、回滚路径已验证。

## 9. 推荐执行顺序

### 阶段 0：建立基线

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest checks -q
```

同时记录 Python/Node/ffmpeg/ComfyUI/模型版本和 preflight 报告。

### 阶段 1：先解除测试阻塞

- 修复统一 subprocess seam。
- 处理 `_complete` 签名兼容。
- 找回/重命名 AI mask helper。
- 明确字幕字体默认值并同步实现、测试和迁移。
- 清除 deprecation warning。

### 阶段 2：组件回归

运行架构边界、源代码安全、TTS、音频工件、遮罩、视觉设置、Remotion/节点检查，并补齐各段集成测试。

### 阶段 3：真实 ComfyUI 六步流程

在隔离项目中把 provider 切到 `comfyui_tts`，使用 `教授声音.mp3` 和短文案，完整执行 Step 1–6；保存 API 日志、任务状态、音频和 MP4 元数据。

### 阶段 4：韧性/性能/安全

按失败矩阵逐项注入故障，做并发 1/2/3、重启恢复、磁盘配额和路径安全测试。

### 阶段 5：清理与发布门禁

完成引用审计、删除确认、忽略本地产物；重新跑全套测试。只有 P0=0、P1 已有明确接受结论、六步真实流程通过，才标记为可发布。

## 10. 详细测试用例目录

| ID | 用例 | 预期 | 优先级 | 自动化状态 |
|---|---|---|---|---|
| ENV-001 | `.venv` 安装并运行 pytest | 与系统 Python 结果一致或差异有记录 | P0 | 待执行 |
| ENV-002 | ComfyUI health/object info | 服务可达且节点/模型齐全 | P0 | 待执行 |
| ENV-003 | ffmpeg/Remotion/Node 检查 | 版本和命令可用 | P0 | 待执行 |
| TTS-001 | MiniMax 成功 | 返回有效 WAV，凭据不写日志 | P1 | 已有测试 |
| TTS-002 | ComfyUI IndexTTS mock 成功 | 解析结果并复制到项目工件目录 | P1 | 部分已有 |
| TTS-003 | ComfyUI IndexTTS 真实成功 | 使用参考音频生成可播放 WAV | P0 | 组件已通过 |
| TTS-004 | TTS 超时/重试 | 结构化失败，重试次数准确，无孤儿文件 | P0 | 当前被 seam 阻塞 |
| MASK-001 | 遮罩预览成功 | 返回预览和统计信息 | P1 | 当前被 seam 阻塞 |
| MASK-002 | 遮罩预览超时 | 返回 504，任务可重试 | P0 | 当前被 seam 阻塞 |
| FLOW-001 | 六步 happy path | 状态依次推进，输出可播放 | P0 | 未完成 |
| FLOW-002 | 刷新/重启恢复 | 从最后稳定状态继续 | P0 | 部分已有 |
| FLOW-003 | 重复点击/幂等 | 不产生重复任务或覆盖错误输出 | P0 | 待补 |
| FLOW-004 | ComfyUI 离线 | 明确提示、可重试、无假完成 | P0 | 待补 |
| FLOW-005 | 模型/节点缺失 | preflight 阻断并给出安装路径 | P0 | 待补 |
| RENDER-001 | 视频存在画面和音频 | 非零字节，视频流/音频流均存在 | P0 | 待补 |
| RENDER-002 | 音视频同步 | 时长误差在产品阈值内 | P1 | 待补 |
| UI-001 | 六步浏览器流程 | 门禁、进度、错误、下载均正常 | P0 | 手工待执行 |
| SEC-001 | 路径穿越/恶意上传 | 请求被拒绝，服务端路径不越界 | P0 | 待补 |
| PERF-001 | 并发 1/2/3 | 队列受控，显存不失控，失败可恢复 | P1 | 待补 |

## 11. 发布验收签字项

- [ ] P0 自动化测试全部通过。
- [ ] `.venv`/CI 可重现依赖和命令。
- [ ] ComfyUI preflight 通过，节点和模型清单固定。
- [ ] ComfyUI IndexTTS 2.5 六步真实流程通过。
- [ ] 输出 MP4 同时包含可见画面和可播放音频。
- [ ] 离线、超时、取消、重启恢复均通过。
- [ ] 无明文密钥、路径越界和未清理孤儿工件。
- [ ] 冗余代码有引用审计和回滚方案。
