# Agent 全功能开放：交接文档（2026-10-23）

> 本文是 Agent 对接（AI 全功能开放）项目的**完整交接状态**，覆盖已完成工作、
> 待完成工作、技术决策与验证方式。历史批次记录见 `AGENT_INTEGRATION_HANDOFF.md`，
> 计划依据见 `development-plan.md`，对外接入口径见 `current-contract-guide.md`，
> 逐条覆盖状态见 `feature-coverage.md`。

---

## 一、现状速览（TL;DR）

| 指标 | 数值 |
|---|---|
| Agent API 版本 | **2.7.0**（bootstrap 协议 `1`） |
| 已注册能力 | **273 项**（HTTP / MCP / CLI 三通道同源） |
| 业务入口覆盖决策 | **262 项全部完成：175 complete / 86 partial / 1 exempt / 0 pending** |
| Agent 专项回归 | **750 项通过**（含 18 项全域表面 + 10 项 mock 全流程 + 3 项真 socket 传输） |
| 发布门禁 `--require-complete` | **仍预期失败**（86 项 partial 未清零前不得宣称全功能开放） |
| 未提交工作区 | 四批改动（资源读取 / Step 1–2 / 全域开放 / 本批验收），建议分四次提交 |

**一句话结论**：契约底座（发现、调用、指纹、幂等、任务寻址、版本控制）已全部
建成并验证；八步工作流的全部分步操控能力已注册并有隔离场景验收；剩余 116 项
partial 是**验收类型缺口**（真实供应商、外部引擎、上传客户端、真实生成资产），
不是实现缺口。

---

## 二、系统架构现状

```
外部 Agent
  ├─ HTTP  → /api/agent/v1/**（273 条路由，含 34 条 binary/file_upload 专用传输）
  ├─ MCP   → 固定三工具 ppt_capabilities_search / ppt_capability_describe / ppt_capability_invoke
  └─ CLI   → python -m cli.pptctl（capability list/show、invoke、operation wait、artifact download）

统一入口层（本项目的 Agent 面）
  agent_api/routes.py            聚合路由组合（≤150 行门禁）
  agent_api/dispatch.py          唯一 invoke 分发 + HANDLERS 显式注册（dotted-path）
  agent_api/discovery.py         目录/详情/ETag 条件刷新/传输声明
  agent_api/errors.py            统一错误结构（CONTRACT_CHANGED/REVISION_CONFLICT/…）
  agent_api/rate_limit.py        Agent 网关限流（120 req/60s，SQLite 持久）
  agent_api/domain_routes/       分域适配器（13 个模块，HTTP 与 invoke 共用同一函数）

契约层
  agent_contract/capabilities.py 能力聚合注册表（273 项）
  agent_contract/registry.py     AgentCapability/CapabilityStatus 数据类
  agent_contract/domains/        18 个域模块：模型 + 能力声明（每 Schema 只定义一次）
  agent_contract/models.py       唯一导出入口（__all__ 从域模块收集，≤150 行门禁）
  agent_contract/versions.py     AGENT_API_VERSION / 契约哈希 / meta
  agent_contract/schema.py       输入/输出 JSON Schema 生成
  agent_contract/features.py     功能目录与覆盖校验

聚合服务（窄依赖，不 import server）
  agent_workflow_service.py      project.state 只读观测 + change_preview 变更预检
  agent_operation_service.py     operation.get/list/cancel 精确任务寻址
  agent_idempotency_service.py   幂等键登记/重放/冲突（7 天重放、墓碑）
```

业务算法仍在 source-owned 服务（storyboard_*、image_*、mask_*、narration_*、
tts_*、video_*、pptx_* 等）中，Agent 适配器只做信封翻译，不复制业务规则。

---

## 三、已完成工作

### 3.1 按批次时间线（全部在同一系列工作区内，建议分四次提交）

#### 批次①：基础改造（API 2.2.0，已验证）
- 262 个业务 HTTP 入口全部登记进 `config/agent_features.json`，未登记即检查失败
  （`scripts/check_agent_coverage.py`）。
- 独立能力指纹（每能力一个 `contract_revision`，无关能力更新不互相污染）。
- 统一发现入口（`GET /meta`、`GET /capabilities`、`GET /capabilities/{id}`、
  `POST /invoke`）+ MCP 固定三工具 + CLI 通用调用。
- 项目/文章纵向切片验证；过期契约在副作用前拒绝（409 `CONTRACT_CHANGED`，
  `executed=false`）。

#### 批次②：可靠任务与幂等（API 2.2.0 → 2.3.0 间）
- `operation.get/list/cancel`：TTS/视频/一键持久任务的精确寻址，未知 ID 返回 404
  绝不回退 latest；一键运行历史持久化到 `planning/one_click_runs/<run_id>.json`。
- 幂等框架：键绑定账号+能力+目标资源+规范化参数+契约；7 天重放、过期键墓碑、
  `OPERATION_OUTCOME_UNKNOWN` 禁止盲目重试、`IDEMPOTENCY_CONFLICT` 键冲突。
- `project.delete` 带版本检查 + CAS + 删除后幂等重放；跨账号不可读取重放。
- 项目元数据与旁白编辑使用数据库 CAS（`REVISION_CONFLICT`），相同保存为 no-op。

#### 批次③：资源读取（API 2.3.0）
- 产物精确 ID URI（`ppt://projects/{id}/artifacts/{artifact_id}`），不再用
  "最新视频"替代；`artifact.get` 返回当前 SHA-256。
- 注册表按项目内路径区分同名页文件；单页删除保留其他页登记。
- CLI/AgentClient 有界流式下载（64 KiB 分块、大小上限、可选 hash 校验、
  原子落盘、拒绝跨域重定向）。

#### 批次④：Step 1–2 分域开放（API 2.5.0）
- 文章域 4 能力（设置/结果读写）+ 分镜域 24 能力（模板、规则/Prompt、两阶段
  规划读写、Visual Contract CAS 读写、手动骨架），共 30 个业务入口。
- `storyboard.contract.update` 按 `expected_contract_sha256` CAS；顺手修复
  业务缺陷：CAS 键不再写入合约文件（此前相同内容保存会被误判为变更）。
- P5-B 验收场景全部落地：逐页编辑身份保持、可视化旁白回填、
  合成/no-op/重排/409 冲突、双通道（HTTP=invoke）一致性。

#### 批次⑤：全域开放（API 2.6.0，本批）
- **剩余 221 个业务入口全部完成覆盖决策，pending 清零**；能力总数 63 → 273。
- 新增域能力：Step 3 图片/风格/参考图/模板/IP（46 项）、Step 4 Mask（10 项）、
  Step 5 音频/媒体（14 项）、Step 6 标注（18 项）、Step 7 数字人（13 项）、
  Step 8 输出（16 项）、横向设置/凭据/连接/诊断/课程/配置包/账号（67+ 项）、
  项目影响决策与 AI 模式（7 项）。
- **架构改造**：
  - `AgentCapability` 拆到 `agent_contract/registry.py`，能力声明下沉到
    `agent_contract/domains/*`（每域一个 `CAPABILITIES` 列表），
    `capabilities.py` 只做聚合，避免 3000 行单文件。
  - `transport` 字段（`json` / `binary` / `event_stream` / `file_upload`）：
    非 JSON 传输在发现详情中 `invocable=false`，按详情 method/path 走专用 HTTP，
    不能用 invoke 下载/上传。
  - dispatch 支持 `module:function` 显式 dotted-path handler 注册，
    `routes.py` 只组合路由（守住 150 行门禁）。
- **P4 变更预检落地**：`project.change_preview` 复用提交路径同一差分函数
  （`storyboard_contract_diff.diff_storyboard_contracts`），只读输出受影响页面、
  预期下游失效，不落盘不登记。
- **测试隔离基建**：`repository_paths.DATA_DIR` 支持 `PPT_STUDIO_DATA_DIR`
  环境覆盖，`checks/conftest.py` 会话级隔离——测试不再写入用户真实 `data/`
  （创作配置包、全局风格、模板、凭据等文件型存储全部可安全测试）。
- **顺手修复的真实缺陷**：invoke 直调适配器时 FastAPI 不解析 `Depends` 默认值
  （输出/音频/标注适配器改为函数体内解析服务）；`config.import` 能力 ID 撞名；
  CLI 命令重名；`change_preview` 信封模型错配。
- 新增 `checks/agent/test_domain_surface.py`：18 项全域表面场景，每个标记
  complete 的域能力至少一次真实隔离服务调用。

#### 批次⑥：传输客户端与 mock 全流程验收（API 2.7.0，本批）
- **上传客户端落地**：`agent_client/transfers.upload_file()`（multipart 构造、
  读取前大小上限、结构化错误透传）+ CLI `pptctl image upload`。
- **真 socket 传输验收**（`checks/agent/test_transfer_client_live.py`）：进程内
  uvicorn + 随机空闲端口，验证有界下载（哈希校验/原子落盘/越界拒绝）、
  multipart 上传（超限拒绝/服务端 422 透传/缺文件错误码）。
- **mock 供应商全流程**（`checks/agent/test_full_workflow_mocked.py`，10 项）：
  替换 LLM/生图/TTS 三个上游（AGENTS.md 模式：mock 供应商、跑真实服务），
  端到端执行 规划→合成→生图→确认→Reveal 构建→异步 TTS 持久任务→音频确认
  →PPTX 导出持久任务→视频产物文件级验收→影响决策闭环，并解锁 30 项验收
  升级（覆盖 145→175 complete）。
- **顺手修复的真实业务缺陷（3 个）**：
  1. `repair_step2_result` 迁移检测恒为 False——`normalize_visual_contract`
     原地修改输入，changed 基线被吞；改为归一化前深拷贝快照。
  2. `get_comfyui_workflow` 上传工作流后 `source` 未赋值必 500。
  3. `settings.update` 适配器信封多套一层导致静默空写。
- **`image.generate` 幂等接入**（1.0→1.1）：同键重放原结果不重复付费生成，
  键冲突 409，与 source.set 同款 claim/replay/finalize 模式。
- **杂项清零**：`config.import`、`accounts.provision`（域模型补齐 6 字段）、
  合约修复迁移场景、`config.export.zip`/`import.zip`、`error_log.latest`、
  数字人工作流上传/读取。

### 3.2 按计划阶段（P0–P6）

| 阶段 | 状态 | 说明 |
|---|---|---|
| P0 功能盘点与覆盖登记 | ✅ 完成 | 262 入口全登记 + 检查门禁；字段/后台盘点由分域适配过程承载 |
| P1 契约内核与统一 dispatch | ✅ 完成 | 域拆分、指纹、双通道同 handler、无 handler 不可调用 |
| P2 幂等、版本与可靠任务 | 🟡 大部分完成 | 已有：幂等框架、项目/旁白/合约 CAS、operation 寻址、TTS/视频/一键持久任务。待做见 5.2 |
| P3 动态发现、MCP 与 CLI | ✅ 完成 | 检索/详情/ETag、固定 MCP 工具、CLI 动态调用 + 精确等待 + 受控下载 |
| P4 状态/预检/确认 | 🟡 基本完成 | `project.state` + `project.change_preview` 已落地；确认由各域 CAS/哈希门禁承载 |
| P5 八步分域能力补齐 | 🟢 覆盖决策完成 | 273 能力全注册；116 项 partial 待分类验收（见第五节） |
| P6 全量门禁与独立 Agent 验收 | ⬜ 未开始 | 依赖 partial 清零（见 5.6） |

---

## 四、能力与覆盖全景

### 4.1 按可见步骤的能力分布

| 可见步骤 | 能力域前缀 | 数量 | 代表能力 |
|---|---|---|---|
| Step 1 文章 | `article.*`、`source.set` | 5 | 直接导入/主题生成、结果编辑 |
| Step 2 分镜 | `storyboard.*` | 28 | 两阶段规划读写、CAS 合约、手动骨架、模板管理 |
| Step 3 图片 | `image.*`、`style.*`、`global_style.*`、`ip.*` | 62 | 生成/上传/候选/确认、风格反推、参考图、模板、IP 角色 |
| Step 4 Mask | `mask.*` | 10 | AI 标注、语义块、草稿/终稿、精确预览 |
| Step 5 音频 | `narration.*`、`tts.*`、`media.*` | 17 | 旁白读写、TTS 任务、音频确认门禁、背景/字幕设置 |
| Step 6 标注 | `annotation.*` | 18 | 设置决策、结构化补丁、OCR/规划任务、预览 |
| Step 7 数字人 | `digital_human.*` | 17 | 配置、任务、合成、上传、工作流模板 |
| Step 8 输出 | `video.*`、`pptx.*`、`subtitles.*` | 20 | 视频集合/变速/删除、PPTX 导出任务、SRT |
| 项目/运行 | `project.*`、`pipeline.*`、`checkpoint.*`、`operation.*` | 25 | CRUD+CAS、一键、检查点、精确任务、变更预检 |
| 横向 | `settings.*`、`credentials.*`、`connections.*`、`course.*`、`config.*`、`accounts.*`、`diagnostics.*`、`generation.*`、`artifacts.*` 等 | 71 | 设置、凭据、模型连接、课程树、配置包、账号、诊断 |

### 4.2 覆盖状态统计

- **145 complete**：适配器与业务入口共用同一函数 + 隔离场景验收通过。
- **116 partial**：实现完成、验收有明确缺口，按原因登记（见第五节分类）。
- **1 exempt**：`account_routes.account_select`（Web 会话 Cookie 切换账号；
  Agent 连接经令牌绑定账号，语义不适用——这是显式豁免决定，不是缺口）。
- **0 pending**：没有未决策的业务入口；新业务路由不登记会被
  `check_agent_coverage.py` 阻断。

---

## 五、待完成工作（详细）

### 5.1 真实供应商演练（约 12 项，验收类）——其余已在 2.7.0 用 mock 供应商验收

适配器已实现并有确定性路径验证，但完整验收必须跑一次真实 LLM/多模态调用。
**受 AGENTS.md 约束，开发过程中禁止执行付费生成**，需安排一次显式的
真实供应商演练（费用可控：每能力 1–2 次调用）：

| 能力 | 业务入口 |
|---|---|
| `storyboard.script.execute` | 演讲稿规划生成 |
| `storyboard.visual.execute` | 可视化规划生成 |
| `storyboard.compose` | 合约合成（含原子性修复调用） |
| `storyboard.execute` | 遗留一键复合路由 |
| `image.generate` | Step 3 单页图片生成 |
| `style.generate` / `style.references.generate` / `style.references_legacy.generate` | 风格生成/参考图生成 |
| `mask.annotate` | AI Mask 自动标注 |
| `narration.annotate` | 旁白 AI 标注 |
| `tts.sync_synthesize` / `tts.synthesize` | 同步/异步 TTS |
| `article` 主题生成（`source.set` 主题路径） | 主题生成文章 |
| `annotation.jobs.submit` / `annotation.preview.export` | OCR/标注规划引擎、预览导出 |
| `digital_human.generate` / `digital_human.slide.generate` / `slide.compose` / `audio.export` | 数字人生成链（4 项） |
| `settings.llm/image/tts.test`、`connections.test` | 连接诊断（5 项） |

### 5.2 上传方向（2.7.0 已完成：客户端 + CLI + 真 socket 验收，14 项已升级 complete）

`binary` 下载已有受控流式实现（`agent_client/transfers.py`）；**multipart 上传
客户端尚未实现**。服务端适配器已就位并有路由，需要：

1. `agent_client/transfers.py` 增加 `upload_file()`：multipart 构造、大小上限、
   服务端校验错误透传、原子性（失败不留半文件）。
2. CLI `artifact upload` / `image upload` 命令。
3. 涉及能力：`image.upload`、`style.references.upload`、
   `style.templates.create_with_references`、`style.reverse.generate(-legacy)`、
   `ip.upsert`、`global_style.reference.update`、`media.background_image.upload`、
   `digital_human.video.upload` / `avatars.upload` / `workflow.upload`、
   `settings.comfyui_workflow.upload`、`connections.reference_audio.upload`、
   `settings.config.import.zip`。

### 5.3 二进制传输领域验收（约 15 项剩余；多数已在 2.7.0 随全流程验收）

下载客户端已实现，但各领域的下载端到端验收需要真实产物：
`video.download`、`pptx.export.download`、`subtitles.download`、
`audio.get`、`image.get`、`video.latest`、`artifact.download`、
`image.candidate.get`、`image.recovery.overlay`、`image.download_all`、
`style.references.get`、`style.references_legacy.get`、
`style.templates.reference.get`、`mask.preview.get`、
`annotation.scene_asset.get` / `editor_ink.get` / `ink.get` / `preview.download`、
`digital_human.slide_video.get` / `composite_video.get` / `audio.file` / `video.uploaded.get`、
`global_style.reference.get`、`ip.image.get`、`media.background_image.get`、
`settings.config.export.zip` / `export.secrets.zip`、`diagnostics.error_log.latest`。

### 5.4 需真实生成资产的场景（约 20 项剩余；多数已在 2.7.0 用 mock 资产验收）

这些能力的确定性路径（读空状态、前置拒绝、CAS 拒绝）已验证，但完整场景需要
一个**已有生成图片/Mask/音频的项目**。建议：用 5.1 的真实演练产出一个
完整项目后，跑一遍这批场景（清单见 `feature-coverage.md` 中 reason 含
"requires generated project assets" 的条目），典型包括：

- 图片：候选应用、单页/全删、确认门禁、几何复用、排序 CAS（`order_version`）
- Mask：Manifest 读写、草稿保存、预览构建、修复
- 标注：结构化补丁、文字布局补丁、准备/确认、导出预览
- 项目影响：复用确认（`reuse_confirm`）、影响决策、图片复用确认
- 输出：变速、视频/PPTX 删除、导出任务执行/重试
- 数字人：`jobs.get`（404 路径已被外部连接挡住，需真实服务）

### 5.5 P2 收尾（实现类，按 development-plan §P2）

- **幂等/版本扩面**：CAS 与幂等键目前覆盖项目元数据、旁白、合约、项目删除；
  其余领域（图片、Mask、标注、设置等）尚未统一推进项目 revision，不能宣称
  跨全系统并发保护。
- **同步生成任务持久化**（P2-4）：`storyboard.script/visual.execute`、
  `style.generate`、`narration.annotate`、`image.generate` 等同步 LLM 调用
  仍是请求内执行，进程退出即丢失，尚无持久记录与 interrupted 标记。
- **`image.regenerate` 幂等键**：请求模型已有 `idempotency_key` 字段，
  服务端语义待对齐统一幂等框架。
- **取消声明扩面**：`operation.cancel` 目前支持 TTS/视频；一键暂停走
  `pipeline.pause`；标注/PPTX 等生产者的统一取消待补（现返回明确的
  CANCELLATION_UNSUPPORTED）。
- **事件流**（P2-6）：`pipeline.stream`（SSE）无持久游标/断线补读，
  按计划不阻塞交付，但接入手册需明示回退约定（轮询 `operation.list`）。

### 5.6 P6 全量门禁与独立 Agent 验收（未开始）

1. **partial 清零**：完成 5.1–5.4 后，把对应条目升级 complete（每项需真实
   验收证据），`python scripts/check_agent_coverage.py --require-complete`
   通过后才可宣称全功能开放。
2. **独立 Agent 验收**（P6-5）：一个只拿到连接方式、认证和 bootstrap 入口的
   独立 Agent（不读仓库、不调内部 Web 路由）完成八步工作流 + 中断/编辑/重试
   场景，留操作记录与产物证据。
3. **文档收尾**（P6-6）：工作流食谱、错误恢复手册、SDK 示例
   （不嵌入会失效的固定参数全集）。
4. **门禁常态化**：quick 检查已含覆盖登记与快照一致性；
   `--require-complete` 接入 `scripts/run_checks.py` 全量级作为发布门禁。

### 5.7 小额收尾杂项

- `creation_config.import`（导入契约校验需代表性配置包载荷）。
- `accounts.provision`（需有效 source_package_id 的预置场景）。
- `storyboard.contract.repair`（旧合约迁移场景：需构造 legacy schema 合约）。
- `account_routes.account_select` 保持 exempt（决策：Web 会话语义，
  Agent 经令牌绑定账号）——若未来 Agent 多账号切换有需求再重审。

---

## 六、关键技术决策与约定（新会话必读）

1. **无旧协议兼容**：当前契约直接替换，不加旧字段别名/迁移窗口。契约变化 =
   版本递增（additive 为 minor）+ 重新生成文档快照，同一变更集内完成。
2. **每 Schema 只定义一次**：请求/响应模型在各 `agent_contract/domains/*.py`
   定义，`models.py` 只是显式导出入口（`__all__` 从域模块收集）。
   能力声明也在域模块（`CAPABILITIES` 列表），`capabilities.py` 聚合。
3. **HTTP 与 invoke 同函数**：每个能力的 Agent HTTP 路由和 invoke 调用解析到
   同一个适配器函数（`test_transport_contract_sync` 双向断言）。
4. **自由载荷用 `payload` 信封**：业务自校验的整段载荷（标注补丁、Manifest、
   设置等）用 `FreeFormRequest { payload: dict }`，字段规则不复制到契约层；
   结构稳定的小载荷（CAS 基线、AI 模式）用显式字段模型。
5. **invoke 适配器禁止 `Depends` 服务默认值**：invoke 直调不解析 FastAPI
   依赖默认值，服务实例必须在函数体内 `get_xxx_service()` 解析
   （`db`/`request` 除外，dispatch 显式传入）。
6. **响应模型即校验契约**：invoke 输出经 `cap.response_model.model_validate`；
   异构业务响应用 `BaseModel` + 描述说明关键字段，稳定形状用显式模型
   （所有字段给默认值，避免业务加键导致 500）。
7. **大小门禁**：`agent_api/routes.py`、`agent_contract/models.py` 各 ≤150 行
   （`checks/test_architecture_size_boundaries.py`）；调限额必须在变更说明中
   解释职责边界。
8. **测试隔离铁律**：`checks/conftest.py` 隔离 `PPT_STUDIO_DB_PATH`、
   `PPT_STUDIO_RUNS_DIR`、`PPT_STUDIO_DATA_DIR`、
   `PPT_STUDIO_AGENT_RATE_LIMIT_DB_PATH`；新测试不要绕过这四个变量。
   高频调用测试（>120 次/模块）需在夹具内放宽 `AgentRateLimitMiddleware`。
9. **路径注册表**：所有仓库/数据/运行时路径只出自 `repository_paths.py`；
   消费方可 monkey-patch 模块级名字做兼容，不得自行重算。
10. **能力登记门禁**：新增业务路由不同步 `agent_features.json` 会 fail；
    coverage 取值仅 `pending/partial/complete/exempt`，`complete/partial`
    必须列出能力 ID。

---

## 七、验证命令（交接后先跑这些）

```powershell
# Agent 专项回归（约 20s，738 项）
python -m pytest checks/agent/ -q

# 覆盖决策一致性 + 生成物一致性
python scripts/check_agent_coverage.py
python scripts/generate_agent_contracts.py --check

# 业务回归（改动业务面后）
python -m pytest checks/test_database_migrations.py checks/test_invalidation_service.py -q
python -m pytest checks/test_source_runtime_safeguards.py checks/test_architecture_size_boundaries.py -q
python -m pytest checks/test_storyboard_cas.py checks/test_storyboard_contract_atomic.py checks/test_upstream_edit_invalidation.py -q
python -m pytest checks/test_repository_paths.py checks/test_generalized_settings.py -q

# 前端与仓库统一快检
node --check static/workflow_state.js
node --check static/flow.js
python scripts/run_checks.py --level quick

# 发布门禁（partial 清零前预期失败）
python scripts/check_agent_coverage.py --require-complete
```

带隔离环境的独立探针可用 `TestClient(server.app)`（conftest 已隔离）；
真实服务冒烟走 `start_server.py` 单实例 + `python -m cli.pptctl capability list`。

---

## 八、本次批次变更文件地图

新增：
- `agent_contract/registry.py`、`agent_contract/domains/{freeform,audio,outputs,style,mask,annotations,workspace,accounts}.py`
- `agent_api/domain_routes/{audio,outputs,images_ext,style,mask,annotations,digital_human_ext,workspace,system_ext,accounts}.py`
- `checks/agent/test_domain_surface.py`
- `agent_workflow_service.py` 内新增 `preview_storyboard_change`

修改（要点）：
- `agent_contract/capabilities.py`（聚合 + 传输字段 + 遗留 transport 标注）
- `agent_api/dispatch.py`（HANDLERS 229 项 + dotted-path 解析器）
- `agent_api/routes.py`（+10 域路由器）、`agent_api/discovery.py`（transport 优先）
- `agent_contract/{models,versions}.py`、`agent_contract/domains/{project,images,digital_human,system}.py`（扩展）
- `checks/conftest.py` + `repository_paths.py`（DATA_DIR 隔离）
- `storyboard_service.py`（CAS 键剥离修复）
- `checks/agent/test_{transport_contract_sync,dynamic_invocation,digital_human,repository_paths}.py`（适配新断言）
- `config/agent_features.json`（221 条覆盖决策）、`docs/agent/*`（四份文档再生成/更新）

---

## 九、建议的下一批执行顺序

1. **提交工作区**：按"批次③资源读取 / 批次④Step1-2 / 批次⑤全域开放"分三次
   提交（每次提交前跑第七节命令）。
2. **上传客户端**（5.2）：一个 PR 内完成 transfers 上传 + CLI 命令 + 2 个
   上传场景测试，随后把 14 项上传 partial 升 complete。
3. **真实供应商演练**（5.1）：显式、小额、一次性运行；产出完整项目后顺手
   完成 5.4 资产场景（约 34 项）与 5.3 二进制验收（约 28 项）。
4. **P2 收尾**（5.5）：同步生成持久化 + 幂等扩面。
5. **P6 验收**（5.6）：partial 清零 → `--require-complete` → 独立 Agent 验收
   → 文档收尾 → 宣布全功能开放。
