# 数字人 + IndexTTS 2.5 项目优化实施方案

## 1. 优化目标

本方案针对当前项目的真实问题，目标不是单纯“让测试变绿”，而是把项目变成可重复部署、可诊断、可恢复、可扩展的六步主流程，并兼容其后的可选数字人扩展步骤：

1. 六步流程可以稳定完成，失败时能明确定位到阶段和原因。
2. ComfyUI/IndexTTS 2.5 与 MiniMax 两种 TTS 能通过统一接口切换。
3. 超时、取消、重试、刷新和服务重启不会产生假完成或孤儿文件。
4. 测试在项目 `.venv` 和 CI 中可重复执行。
5. 旧兼容代码经过引用审计后再删除，避免误删仍在使用的路径。

当前基线：`284 passed, 8 failed, 1 warning`；ComfyUI + IndexTTS 2.5 的独立 TTS 调用已成功，但真实六步流程尚未完成验收。

## 1.1 本轮已落地（2026-08-30）

- `mask_preview_service.py` 与 `tts_provider_service.py` 新增可注入的
  `run_subprocess` seam，生产环境仍使用可杀进程树的 runner。
- 遮罩预览、TTS 重试和 TTS 超时测试改为注入 runner，不再错误 patch
  `subprocess.run`；相关专项测试通过。
- `one_click_orchestrator._complete` 支持旧调用方式，数据库 session 存在时仍会同步
  `step_status` 并提交。
- `ai_mask_engine.py` 重新导出 `_replaceable_ai_mask`，恢复兼容调用和回归保护。
- 字幕契约测试已与当前产品默认值同步：`LXGW Marker Gothic`、边距 `110`、黑色文字。
- 可选“数字人讲解”步骤已纳入前端流程测试的显式顺序：`1, 2, 3, 5, 6, 9, 8`。
- 项目 `.venv` 已安装开发测试依赖；当时 P0 阶段全套结果为 `292 passed`。

本轮只修复边界、兼容和测试基础设施，没有删除旧业务分支，也没有切换生产默认 TTS provider。

## 1.2 本阶段继续落地（2026-08-30）

- `comfyui_backend.py` 新增 `inspect_tts_preflight()`：只读检查 ComfyUI
  `/system_stats`、`/object_info`、API 工作流格式、IndexTTS loader/synthesis/save
  节点，并返回结构化错误。
- `scripts/generic_tts.py` 在上传/提交任务前执行上述预检，服务离线、工作流错误或节点缺失
  会立即失败，不再进入长时间轮询。
- `settings_service.py` 的 TTS 连接测试改用统一的可终止 subprocess runner，避免测试接口
  直接调用裸 `subprocess.run`。
- 新增 `checks/test_comfyui_backend.py`，覆盖预检成功、节点缺失、工作流损坏和服务离线。
- 真实 ComfyUI 8188 smoke 已成功生成短文本 WAV。
- 当前 `.venv` 全套回归结果：`298 passed`；Node 可见流程、核心 compileall、Remotion `tsc`
  均通过。

## 1.3 真实运行验证（2026-08-30）

- `inspect_tts_preflight()` 对当前 8188 服务和项目工作流返回成功：服务、`/system_stats`、
  `/object_info`、API 格式和 4 个 BSAI IndexTTS 节点均通过。
- 通过项目 API `/api/settings/test-tts` 以 `comfyui_tts` 进行短文本测试，返回成功并生成有效音频。
- E2E provider preflight 已识别本地 `comfyui_tts`：不再错误要求云端 API Key，而是检查本地服务和工作流能力。
- One-click 编排器现在按归一化后的 TTS provider 执行预检；`IndexTTS-2.5`、`Index TTS 2.5` 等显示名称不会再被误判为云端 provider，也不会错误要求 `tts_api_key`。
- 现有项目 `57103bcb_201258` 的 `/api/projects`、音频状态、视频列表和数字人 health 均可访问。
- 数字人服务 health 的 `active_jobs` 已改为只统计 queued/processing，历史任务另报 `job_count`，避免
  把已完成任务误报为活动队列。
- 已重启 9001 数字人服务使修复生效；运行时 health 返回 `active_jobs=0`、`job_count=26`，
  说明历史任务未再被误计入活动队列。
- `scripts/validate_run_assets.py` 验证该项目 5 个 slide 工件通过；已有 MP4 经 ffprobe 验证包含
  1920×1080 H.264 视频流和 AAC 音频流，时长约 76.5 秒。
- 未执行会产生云端费用的完整 One-click 真实生成；完整六步 E2E 仍需在隔离项目中明确选择
  provider 后执行。
- 曾尝试对已有项目做恢复型 One-click E2E，但实现会重新进入故事板并调用云端模型；已主动中止，
  并将该项目状态恢复为已完成。后续必须使用 mock/隔离项目或显式确认后再跑真实 E2E。

## 2. 优先级和变更原则

| 优先级 | 含义 | 发布要求 |
|---|---|---|
| P0 | 阻塞正确性、数据安全或发布 | 必须完成并有自动化测试 |
| P1 | 影响主要流程稳定性或维护成本 | 发布前完成，或有明确接受风险 |
| P2 | 性能、体验、可观测性改进 | 可分批上线 |
| P3 | 清理、风格和低风险重构 | 最后处理 |

变更原则：小步提交、每步可回滚；业务模块不直接启动服务器；测试替身和真实服务使用不同测试层；不在本轮直接删除未审计代码或模型。

## 3. 总体目标架构

```text
routes/API
   ↓ 只做参数校验、鉴权、响应映射
application/orchestrator
   ↓ 管理阶段状态、幂等、重试和取消
domain services
   ├─ project/storyboard/visual/mask
   ├─ narration_audio_service
   └─ tts_provider_service
          ├─ MiniMax adapter
          └─ ComfyUI IndexTTS adapter
   ↓
infrastructure
   ├─ subprocess runner（唯一子进程入口）
   ├─ ComfyUI client/health probe
   ├─ artifact store
   └─ structured logging/metrics
```

核心规则：

- `server.py` 只做 composition root 和路由挂载。
- `tts_provider_service.py` 统一 provider 别名、默认值、凭据、命令、重试和超时。
- `narration_audio_service.py` 只负责音频生成、确认门禁、时长和音视频同步。
- `comfyui_backend.py` 只负责 ComfyUI API/工作流调用和结果解析，不再复制 TTS 决策逻辑。
- 所有外部进程通过同一个可注入的 runner 执行。

## 4. P0 阶段：先解除当前阻塞

### P0-1 统一子进程执行 seam

**现状**：`mask_preview_service.py` 和 `tts_provider_service.py` 直接导入 `run_subprocess_killable`；现有测试 patch `subprocess.run`，因此 mock 没有拦截到真正调用，预览超时、TTS 重试/超时测试都失真。

**实施**：

1. 在 `runtime_support.py` 暴露稳定的 `SubprocessRunner` 接口（命令、超时、环境、cwd、取消信号）。
2. `mask_preview_service.build_step5_mask_preview` 和 TTS provider 函数通过参数或构造器接收 runner，默认使用生产 runner。
3. 测试注入 fake runner，按调用序列返回成功、超时、非零返回码和异常。
4. 只保留一个超时语义：建议超时统一映射为 `returncode=124` + `timed_out=True`，由上层转换成 504/结构化失败。
5. 增加一次真实 subprocess smoke test，避免 fake runner 与生产实现长期漂移。

**验收**：

- 遮罩预览成功/超时测试稳定通过。
- TTS 第 1、2 次失败，第 3 次成功时，重试次数和日志准确。
- TTS 超时时返回结构化错误，不产生最终音频文件。
- Windows 下路径含空格时仍能运行。

### P0-2 修复 One-click 完成态兼容

**现状**：`one_click_orchestrator._complete(project, status, db, video=None)` 已要求 `db`，旧调用/测试仍按旧签名调用，出现 `TypeError`。

**实施**：

1. 确认 `db` 是否是正式必需依赖；若是，更新所有调用方、测试和类型定义。
2. 若必须兼容旧插件/脚本，增加薄包装函数，内部统一转到新签名，避免在业务逻辑里分支。
3. 将“完成状态写库、输出校验、事件通知”拆成可测试的小函数。
4. 增加重复完成调用、视频缺失、数据库提交失败三类测试。

**验收**：完成态、智能恢复和重复回调不再抛签名错误，数据库状态与输出文件一致。

### P0-3 恢复 AI mask 稳定公共 helper

**现状**：测试使用 `ai_mask_engine._replaceable_ai_mask`，当前模块中不存在该函数，导致“仅替换未校正 AI mask”的规则没有回归保护。

**实施**：

1. 用 `rg` 找到当前实际的 mask 状态判断逻辑，确认是否改名或散落在调用方。
2. 提取纯函数 `is_replaceable_ai_mask(mask)`，明确状态枚举：AI 未校正、AI 已校正、锁定、手动、缺失。
3. 统一所有调用方使用该函数，保留旧私有名称的短期兼容别名（如确有外部引用）。
4. 用参数化测试覆盖每个状态和缺失字段。

**验收**：替换规则可读、状态边界明确，旧项目 mask 不会被误替换。

### P0-4 固定虚拟环境和依赖

**实施**：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest checks -q
```

同时记录 Python、pytest、FastAPI/Starlette/httpx、Node/npm、ffmpeg、ComfyUI 和 PyTorch/CUDA 版本。把测试命令写入项目文档/CI，禁止默认使用系统 Python。

**验收**：新机器按照 README 能完成安装并运行同一套快速测试；`.venv` 结果与 CI 一致。

## 5. P1 阶段：统一 TTS 与 ComfyUI 边界

### P1-1 定义统一 TTS 契约

为 MiniMax 和 ComfyUI 使用相同的输入/输出结构：

```text
TTSRequest:
  text, provider, voice_id, clone_voice_id, reference_audio,
  output_path, timeout_seconds, request_id

TTSResult:
  ok, audio_path, duration_ms, sample_rate, provider,
  attempts, error_code, error_message, metadata
```

要求：

- provider 别名在一个地方归一化，例如 `indextts`、`index_tts_2.5` → `comfyui_tts`。
- 路由不拼命令、不读取 provider 私有凭据。
- 错误码区分 `PROVIDER_OFFLINE`、`MODEL_MISSING`、`TIMEOUT`、`INVALID_AUDIO`、`OUTPUT_WRITE_FAILED`。
- 不把 API key、完整命令行或参考音频敏感路径写入普通日志。

### P1-2 收敛 `comfyui_backend.py`

保留四个职责：连接检查、工作流注入、任务等待、结果解析/复制。将以下内容逐步移出或合并：

- TTS provider 选择和默认值 → `tts_provider_service.py`。
- 旧 T8/通用 fallback → 经过工作流覆盖率验证后保留或删除。
- 重复的节点 ID/输入键推断 → 统一配置表 + 工作流能力探测。
- 结果文件复制 → 统一 `artifact_store`，带大小、扩展名、校验和检查。

工作流注入应在执行前输出“解析到的文本键、参考音频键、保存节点、版本号”，便于发现工作流版本漂移。

### P1-3 ComfyUI preflight

在进入 Step 5 前执行轻量检查：

1. `127.0.0.1:8188` 可达。
2. `/system_stats` 返回 GPU/运行状态。
3. `/object_info` 包含所需节点。
4. 工作流 JSON 可解析，所有节点类型可解析。
5. IndexTTS 2.5 模型文件和参考音频存在且可读。

失败直接阻断并显示安装/修复提示，不等到渲染中途才报错。将检查结果缓存到短 TTL，避免每次 TTS 重复查询。

## 6. P1 阶段：六步流程和状态机

### P1-1 统一阶段状态

建议每个项目阶段至少有：`pending`、`running`、`succeeded`、`failed_retryable`、`failed_terminal`、`cancelled`、`stale`。状态记录：开始/结束时间、request ID、attempt、输入工件摘要、输出工件摘要和错误码。

禁止以下非法状态跳转：

- 未确认故事板直接生成视频。
- 未确认音频直接导出。
- 取消后又把旧任务标记为成功。
- 新任务覆盖仍在运行任务的输出。

### P1-2 幂等和恢复

- 每个阶段使用 `project_id + stage + input_hash` 作为幂等键。
- 重复点击返回已有运行任务，而不是创建第二个任务。
- API 重启后扫描 `running` 状态：能确认输出完整则补记成功，否则标记可重试并清理临时文件。
- 浏览器刷新只从服务端读取状态，不依赖前端内存。

### P1-3 音频/视频工件

最终完成前统一检查：文件存在、大小大于零、可被 ffprobe 解析、包含所需流、时长在阈值内。临时文件使用任务目录隔离，成功后原子移动到最终目录，失败/取消/重启后清理。

## 7. P1 阶段：视觉设置和字体契约

当前实现默认返回 `LXGW Marker Gothic`/`lxgw_marker_gothic`，部分测试仍期望 `Noto Sans SC`/`noto_sans_sc`。

实施步骤：

1. 产品确认唯一默认字体，不允许实现、测试、历史数据各自一套默认值。
2. 在 `visual_settings_service.py` 统一 `font_key → family → fallback` 映射。
3. 对历史项目保留显式字体值；只有缺失字段才使用新默认。
4. 前端显示字体不可用时给出 fallback 状态，不静默换字体。
5. 增加中英文、长字幕、字体缺失和导出渲染测试。

## 8. P2 阶段：性能、可观测性和体验

### P2-1 性能目标

- 记录 TTS、ComfyUI 排队、模型加载、渲染、导出各阶段耗时。
- 测试并发 1/2/3，记录显存峰值、队列长度、失败率。
- 缓存健康检查和模型能力信息；同一进程避免重复加载模型。
- 大图片、长文案、长音频在入口处限制并提示，不让任务运行到中途才失败。

### P2-2 可观测性

每个请求带 `request_id`/`project_id`/`stage`；日志使用结构化字段：`provider`、`attempt`、`elapsed_ms`、`output_size`、`error_code`。敏感值只记录是否存在，不记录内容。

### P2-3 前端体验

- 长任务显示阶段、进度、最近错误、重试和取消。
- 提交按钮在请求期间禁用，服务端仍做幂等保护。
- 音频确认、遮罩确认和可渲染状态显式显示。
- 下载按钮只在服务端确认工件完整后启用。

## 9. P2/P3 阶段：冗余代码处理方案

不直接删除，按以下顺序进行：

1. `rg` 搜索符号、路由、模板、CLI 和数据库历史值的引用。
2. 为候选分支加覆盖率/调用计数，至少经过一次完整六步流程。
3. 将旧路径标记为 deprecated，记录替代入口和移除条件。
4. 删除后运行快速套件、真实 TTS smoke、六步 E2E 和旧项目打开测试。
5. 每个删除动作独立提交，保留可回滚点。

重点候选：

- `comfyui_backend.py` 的旧 T8/通用 fallback 和重复节点 ID 分支。
- `server.py` 中仅转发的重复 helper/re-export。
- TTS provider 兼容别名和旧默认参数。
- `static/` 中重复的轮询/状态同步桥接。
- `checks/` 中重复加载真实模型的测试。
- `data/digital_human/IndexTTS25_*` 生成测试产物，应移到运行目录或加入忽略规则。

## 10. 变更后的测试门禁

### 每次提交

```powershell
.venv\Scripts\python.exe -m compileall <核心模块列表>
.venv\Scripts\python.exe -m pytest checks -q
```

### 每日/合并前

- 架构边界和源代码安全检查。
- TTS mock 套件、音频工件套件、遮罩套件、Remotion 类型检查。
- ComfyUI health/object info 和 IndexTTS 真实 smoke。

### 发布前

- `fixture-minimal` 完整六步真实流程。
- `fixture-real` 使用教授声音参考音频的完整流程。
- ComfyUI 离线、模型缺失、超时、取消、重启恢复矩阵。
- 输出 MP4 的视频流、音频流、时长、画面抽帧检查。
- 无 P0；所有 P1 有通过证据或明确风险签字。

## 11. 回滚和风险控制

- provider 切换采用项目级配置，先在隔离项目验证，不直接修改所有历史项目默认值。
- 保留 MiniMax 作为回退 provider，ComfyUI preflight 失败时不得静默切换并生成“假成功”。
- 数据库迁移先备份，字体和状态字段只新增/兼容读取，不覆盖历史显式值。
- 任何删除前先提交引用审计报告；发现旧项目打不开时立即回滚对应独立提交。
- 模型、工作流和运行产物不提交到源码仓库。

## 12. 推荐落地顺序

1. 安装 `.venv` 测试依赖，固定版本，恢复可重复基线。
2. 统一 subprocess seam，修复 4 个相关失败测试。
3. 修复 `_complete` 签名和 AI mask helper。
4. 明确并统一字体默认值。
5. 收敛 TTS/ComfyUI 契约，加入 preflight 和结构化错误。
6. 加固阶段状态、幂等、取消、重启恢复和工件校验。
7. 完成 ComfyUI IndexTTS 2.5 六步真实流程。
8. 做故障、性能、安全测试。
9. 最后进行冗余代码审计和小步删除。

## 13. 完成标准

优化完成的最低标准是：

- 快速自动化套件全绿，且在 `.venv`/CI 可复现。
- P0 失败场景均有自动化覆盖。
- ComfyUI IndexTTS 2.5 真实六步流程成功生成有画面、有音频、可下载的视频。
- 刷新、重启、取消、重试不会产生错误完成或孤儿工件。
- provider、工作流、模型缺失能在执行前被明确识别。
- 冗余代码均有引用审计、替代路径和回滚记录。
