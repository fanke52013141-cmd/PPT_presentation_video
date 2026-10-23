# Agent 全功能开放：详细开发计划

日期：2026-10-23。状态：实施中，第一批基础改造已验证。依据：`openness-and-evolution-plan.md` 及用户明确的“无需兼容旧规范、无旧项目迁移”要求。

实施进度：第一批已进入开发验证。已建立 262 个业务 HTTP 入口的覆盖决策目录、独立能力指纹、发现与 invoke、MCP 固定入口和 CLI 动态调用。项目/文章纵向调用已加入隔离集成测试。P0 的完整字段/后台功能盘点、P1 的全部领域拆分和 P2–P6 仍待后续完成；不能视为全功能开放。实际接入见 `current-contract-guide.md`。

本批验证：Agent 专项回归 445 项通过；之后补充的空指纹边界随动态调用测试 17 项通过。仓库 canonical quick 检查、Ruff、生成文档/快照一致性及 diff 空白检查通过。测试使用隔离数据库和 runs 目录，未启动第二个生产服务器，也未运行真实付费生成。

第二批进度：已实现 operation.get/list/cancel 及 CLI 精确等待；TTS 接入现有异步持久任务，视频/一键提交返回可寻址 ID；一键状态增加逐次运行历史；项目与旁白编辑使用数据库 CAS 并保留 no-op 版本；幂等重放绑定契约和目标资源，未知结果/过期键不自动重执行。P2 的全领域版本推进、其余同步生成任务持久化、上传/确认/删除幂等及资源传输仍待补齐，当前不宣称 P2 全部完成。

## 1. 本期决定与完成定义

1. 当前 Agent 契约可以直接替换；不建设双版本服务、旧字段别名、旧 MCP 工具兼容层、旧 SDK 回归或 90 天迁移窗口。
2. 继续复用现有业务服务、权限和持久化机制。无需兼容旧规范不等于重写系统，也不授权删除本地数据或重写已应用 SQL migrations。
3. 只承诺当前契约。Agent 通过发现入口获得实时 Schema、行为说明和可执行动作。过期请求在产生副作用前被拒绝。
4. Web UI 与 Agent 是两个客户端，操作相同业务对象并触发相同校验与下游失效。
5. 本期覆盖所有有业务意义的 UI 操作和适合自动化的管理操作。纯展示行为可以豁免；业务缺口不得用“UI 专用”豁免。
6. 完成标准是独立 Agent 能完成八步工作流并处理中断、编辑和重试，而不是工具数量达到某个值。

本计划只安排开发，不代表以下接口已经存在。新增文件名为推荐目标，实施时遵循仓库路径注册和模块边界规则。

## 2. 实施依据与关键调整

已检查的源码包括 `agent_contract/{capabilities,models,schema,versions,operations}.py`、`agent_api/{routes,auth,errors}.py`、`mcp_server/tools.py`、`agent_client/client.py`、Agent 测试及 `scripts/run_checks.py`。

- 已有能力注册表、发现接口、31 项已生成能力及双向路由检查，应在其上扩展。
- MCP 工具定义来自注册表，但 `mcp_server/tools.py` 的 `_dispatch` 仍按能力 ID 分支调用客户端方法。只增加注册项不足以保证无需修改客户端就支持新能力。
- 共享客户端有手写业务方法。应以统一动态调用为必需路径，手写快捷方法作为可选薄封装。
- 现有 Schema 生成器按已知参数名推导路径字段。应改为显式传输绑定，覆盖查询、路径、请求体、上传和下载。
- 现有 `quick_checks()` 已执行文档生成一致性检查，CI 已调用统一全量检查入口；不新增平行 CI 体系。
- 当前已有字段覆盖检查，但主要针对项目模型。需要向各领域和业务功能全集扩展。

## 3. 目标模块与单一职责

| 模块 | 计划职责 |
|---|---|
| `agent_contract/capabilities.py` | 能力聚合入口和唯一稳定 ID 注册表 |
| 新增 `agent_contract/domains/` | 按领域维护能力声明与请求/响应模型，避免继续扩大单文件 |
| 新增 `agent_contract/features.py` | 功能全集、业务来源、能力映射、豁免与验收场景 |
| `agent_contract/schema.py` | 统一 Schema、传输绑定、标准化与契约摘要 |
| `agent_contract/versions.py` | 当前协议版本、目录指纹、单能力指纹、行为版本 |
| 新增 `agent_api/dispatch.py` | 唯一能力调用分发与通用检查，使用显式 handler 注册 |
| 新增 `agent_api/domain_routes/` | 分域 HTTP 路由和业务服务适配，原 routes.py 收敛为聚合 |
| 新增 `agent_api/discovery.py` | 发现、检索、详情及当前身份可用能力 |
| 新增 `agent_workflow_service.py` | 项目状态、允许动作、阻塞原因、变更预检的聚合读取 |
| 新增 `agent_operation_service.py` | 统一任务 ID 查询与底层持久任务适配，不复制任务终态 |
| `agent_client/` | 动态发现、通用调用、缓存、错误、轮询和二进制传输 |
| `mcp_server/`、`cli/` | 呈现和参数转发，不拥有业务逻辑或另一份参数 Schema |
| `checks/agent/` | 覆盖、传输、语义和端到端验证 |

业务仍在 storyboard、image、mask、annotation、TTS、video 等 source-owned services 中。新增聚合服务使用窄依赖，不导入 server、数据库路由依赖或完整应用命名空间。`server.py` 只配置依赖和注册路由。

## 4. 新契约的具体形态

### 4.1 能力描述

每个能力条目至少有以下字段；不可提供的策略要明确声明 unsupported，而不是含糊省略：

| 字段组 | 字段示例与用途 |
|---|---|
| 身份 | `id`、`domain`、`description`、`contract_revision`、`behavior_revision` |
| 数据 | `input_schema`、`output_schema`、`examples` |
| 传输 | path/query/body/file 的显式绑定、响应种类、MCP/CLI 呈现方式 |
| 执行 | `handler_key`、`required_scopes`、`execution_mode`、`idempotency_policy` |
| 前置条件 | 条件类型、资源要求、项目状态限制；条件求值由业务规则提供 |
| 影响 | `effects`、`invalidates`、费用/外部调用声明、可取消性 |
| 并发 | revision 对象范围、是否要求 `expected_revision` |
| 恢复 | 错误码、重试条件、修复动作、所需用户决策 |
| 覆盖 | `feature_ids`、责任模块、测试场景 ID |

目录指纹用于发现变化；单能力指纹用于准确校验调用，避免一个无关能力更新导致全部操作失效。行为变化即使 Schema 不变，也必须递增 behavior_revision。

### 4.2 稳定发现与调用入口

沿用 `/api/agent/v1` 作为本次统一实现的路径命名空间即可，路径名称不代表保留旧规范。

| 建议接口/能力 | 职责 |
|---|---|
| `GET /meta` | 协议、构建、实例、目录指纹及入口信息 |
| `GET /capabilities` | 按领域、关键词、权限过滤，分页返回摘要 |
| `GET /capabilities/{capability_id}` | 返回完整契约、单能力指纹及例子 |
| `POST /invoke` | 按能力 ID 调用当前契约；统一 JSON 业务调用入口 |
| `project.state` | 项目状态、资源版本、阻塞项、允许动作 |
| `project.change_preview` | 基于指定修改内容计算影响，不产生业务写入 |
| `operation.get/list/cancel` | 查询准确任务、列举任务、请求取消 |
| `resource.upload/get` | 受控上传与资源获取；二进制走专用传输 |

通用调用携带 `capability_id`、`expected_contract_revision`、`arguments`，写入按策略携带幂等键和资源 revision。expected_contract_revision 缺失的写入拒绝执行；读取也应携带，避免响应解释错误。

调用顺序：身份与作用域 → 能力与契约检查 → 输入校验 → 幂等重放判定 → 资源归属/版本与前置条件 → 执行 → 结果校验与记录。已完成幂等重放不因它自己造成的资源版本变化而失败；契约不一致时返回明确错误，不重新执行。具体原子性在阶段 P2 用并发测试验证。

不得直接信任远端传来的任意 URL 或 handler 路径；动态客户端只调用配置的服务端及声明的受控路径。上传与资源端点同样验证身份、归属和大小限制。

### 4.3 返回与恢复

同步结果包含结果数据及 trace_id、当前资源版本；异步结果明确返回 operation_id，不能用“请求成功”表示生产任务完成。

错误码至少覆盖 `CONTRACT_CHANGED`、`VALIDATION_ERROR`、`REVISION_CONFLICT`、`PRECONDITION_FAILED`、`IDEMPOTENCY_CONFLICT`、`FORBIDDEN`、`RESOURCE_NOT_FOUND`、`RATE_LIMITED`、`UPSTREAM_FAILED`、`OPERATION_INTERRUPTED`。错误结构含 retryable、retry_after、details、repair_actions。

契约变化后先重新发现并重新验证参数；只在明确尚未执行时重新提交。网络超时若执行结果未知，使用原幂等键查询/重放，不能自动生成新键重复付费生成。

## 5. 工作包与验收

### P0 — 全功能盘点与契约基线

**依赖：无。**

- P0-1：利用 `route_inventory.py` 导出有效业务路由；结合 `static/` 模块、后台任务、配置模型整理功能目录。单一路由可能对应多个操作，不能只做路由计数。
- P0-2：逐项标明现有能力、缺失操作、缺失字段、状态反馈、文件输入输出和验收场景。
- P0-3：记录八个可见步骤与内部阶段映射；功能 ID 不使用 Step 数字作稳定身份。
- P0-4：建立本次新规范快照与实施 backlog；旧契约只作现状参考，不作为兼容目标。
- P0-5：在 AGENTS.md 和 PR 模板加入功能变更必须同步 Agent 契约的交付规则。

**主要文件：**新增 features.py、`docs/agent/feature-coverage.md`、`docs/agent/contract-spec.md`；修改生成脚本、AGENTS.md、PR 模板和检查入口。

**验收：**全量功能有唯一 ID 与状态；新业务路由不登记会失败；已知未完成能力显式标 pending，并由最终发布门禁阻断，开发中不得标 stable。字段和无路由业务通过补充目录检查。

### P1 — 契约内核与执行分发

**依赖：P0。**

- P1-1：按领域拆分请求/响应模型，去除仅服务旧 Agent 规范的别名和语义重复字段；消费端同批修改。
- P1-2：实现能力 Schema、显式参数绑定、规范化指纹和行为版本。
- P1-3：建立显式 handler 注册和统一 dispatch；领域 HTTP 与通用 invoke 共用同一执行路径。
- P1-4：扩展统一错误与输出验证；OpenAPI、MCP 工具输入和 CLI 校验使用相同模型。
- P1-5：以 project.create/get/update 和 source.set 做首个纵向切片，不先一次性迁移全部能力。

**主要文件：**agent_contract、agent_api/dispatch.py、domain_routes、errors.py、openapi_docs.py、project/article 服务的必要窄适配。

**验收：**同一操作经 HTTP、MCP、CLI 参数与结果一致；注册能力无 handler 或模型时检查失败；无能力 ID 的任意函数不能被调用；过期契约在调用业务前拒绝。

### P2 — 幂等、资源版本与可靠任务

**依赖：P1；必须先于大规模开放写入。**

- P2-1：审计现有幂等服务的事务边界，补齐创建、生成、上传应用、确认和删除操作的策略。记录执行中、已完成与结果未知，明确过期规则。
- P2-2：定义项目、页面、配置、确认对象的版本粒度；读取和写入均返回 revision，冲突不覆盖其他用户修改。
- P2-3：统一 operation 寻址，复用 local_jobs、视频/TTS/标注等持久状态；需要映射时只存 ID 与来源映射，不维护第二份互相竞争的终态。
- P2-4：为尚未持久化且需恢复的生产操作增加最小持久记录；进程退出标 interrupted，不假装能恢复所有供应商请求。
- P2-5：取消声明按能力区分；复用 exact-operation 协作停止。底层不支持取消时返回明确 unsupported。
- P2-6：轮询为必需能力；事件流在有持久游标/断线补读或明确回退约定后开放，不阻塞基本流程交付。
- P2-7：统一产物资源 ID、哈希、内容类型、下载和上传；大图、音频、Mask 不塞进工具文本返回。

**主要文件：**agent_idempotency_service.py、agent_operation_service.py、agent_contract/operations.py、各 job store、artifact_registry.py、generation_control.py 适配。若改数据库，创建下一条连续 migration，编号实施时确定。

**验收：**相同请求重复提交只产生一个操作；同键不同输入冲突；两个 Agent 编辑同一 revision 只有一个成功；重启仍能查准确任务；两个并发任务不依赖 latest；取消请求不提前宣告终止。

### P3 — 动态发现、MCP 与 CLI

**依赖：P1，写入恢复部分依赖 P2。**

- P3-1：实现目录检索、分页、详情、身份可用性与 ETag/条件刷新；静态契约和项目状态分别缓存。
- P3-2：AgentClient 增加 discover/describe/invoke；基于服务端契约绑定参数，替换 MCP 必须新增 if/elif 才能执行的分支链。
- P3-3：MCP 提供固定 search/describe/invoke 工具及资源获取入口；常用命名工具从同一契约生成。客户端支持目录更新时使用更新机制，不支持时仍可走固定入口。
- P3-4：CLI 增加 capability list/show、invoke、operation wait 和资源传输；命名快捷命令仅薄封装通用客户端。
- P3-5：连接/重连/构建变化刷新目录，CONTRACT_CHANGED 后重新发现；说明哪些错误可自动重试，哪些需重新规划。

**主要文件：**agent_api/discovery.py、versions.py、agent_client、mcp_server、cli/pptctl.py。

**验收：**运行测试中增加一个合法测试能力，无需修改客户端源码或分支表即可发现并调用；模拟缓存未刷新时不误写；MCP 和 CLI 保留结构化错误码；产物可直接获取。

### P4 — 工作流状态、变更影响与确认

**依赖：P1、P2。**

- P4-1：实现 project.state，返回各阶段状态、当前 revision、阻塞项和 allowed_actions；不能只返回一个百分比。
- P4-2：复用现有 pipeline 状态与 invalidation_service 规则。若读取预检需规则抽取，则把纯计算移到业务规则模块，使预检和提交共用，禁止 Agent 层另写一份失效规则。
- P4-3：实现变更预检，输出受影响页面、产物、需要重新生成或确认的内容；预检绑定输入和 revision，提交时再次校验。
- P4-4：确认绑定具体产物哈希/版本；未变更保存为 no-op，保留已有音频确认和下游工作。
- P4-5：数字人禁用可直接输出；标注按保存的启用/跳过决策判断，保持现有八步语义。

**主要文件：**agent_workflow_service.py、pipeline_state.py / lifecycle 现有规则、invalidation_service.py、确认存储和领域适配。

**验收：**预检与实际失效对象一致；旧版本确认拒绝；相同内容保存不失效；替换单页图片不清除无关音频确认；状态返回的动作在未发生并发变更时可实际执行。

### P5 — 八步及横向能力补齐

**依赖：P1–P4 核心完成。每个工作包独立交付契约、适配、测试与示例。**

| 工作包 | 必须交付 | 主要业务模块 | 验收场景 |
|---|---|---|---|
| P5-A 项目/课程/配置 | CRUD、课程章节归属、画布、配置包及覆盖项 | project/course/creation_config 服务与路由 | 创建课程章节项目并读回有效配置；跨账号访问拒绝 |
| P5-B Step 1–2 | 文章导入/生成/编辑；演讲稿与可视化规划；页面增删排序、映射与模板/Prompt | article、storyboard_*、visual_contract_service | Agent 修改一页并保存有效契约，其他页身份保持正确 |
| P5-C Step 3 | 风格、参考图、IP、上传、单/批生成、候选应用、删除排序及确认 | image_workflow、project_style_*、IP 及 image prompt 服务 | 上传后应用候选；保持 raw pair/hash 规则；单页失效正确 |
| P5-D Step 4 | 自动 Mask、分组/映射、精确 RLE 与修正数据、动画、预览/确认 | ai_mask_*、mask_manifest_service、mask_preview_service | 自动分组后做局部修正并预览；保存与 Web 编辑语义一致 |
| P5-E Step 5 | 旁白、TTS 标记、声音、字幕、合成/重试、资源读取/确认 | narration_*、tts_*、visual_settings | 修改旁白使旧音频确认失效校验生效；新音频确认后通过 |
| P5-F Step 6 | 标注决策、OCR、规划、结构化编辑、时间线、预览/确认 | annotation_* | 开启、编辑和跳过三种路径均可完成；版本冲突可恢复 |
| P5-G Step 7 | 配置、健康、生成任务、结果资源 | digital_human_* | 禁用不阻塞输出；启用失败可解释且能查询任务 |
| P5-H Step 8 | 视频/PPTX/字幕导出、任务管理、下载/删除/变速 | video_*、pptx_*、subtitle_export | 输出产物可下载；删除同步清理 registry 和视频 sidecar |
| P5-I 横向配置 | Prompt、模板、模型/声音配置、连接诊断、日志与凭据引用 | settings、credential、diagnostics、各配置服务 | 配置改后下一次操作生效；返回脱敏，凭据通过受控写入管理 |

Mask/标注的坐标系统、归一化规则、文本索引单位和补丁语义必须写入 Schema。坐标非法或索引过期拒绝执行，不能靠 Agent 猜像素与比例。重用 annotations_core 对应的业务语义并做跨端一致性测试。

所有生成请求仍经过 generation_governor；不能因 Agent 通道新增而绕过 gateway-global 配额、进程锁或调用次数预算。一般使用本地单进程架构，不扩展为分布式任务系统。

### P6 — 强制同步门禁与独立 Agent 验收

**依赖：各阶段持续加入检查，最终完成依赖 P5。**

- P6-1：快检包含目录完整性、Schema 合法性、handler/route/transport 双向一致性、生成文档和契约快照一致性。
- P6-2：全检包含实际服务适配与领域场景，覆盖权限、版本、幂等、恢复和下游失效，不只 mock dispatch 返回固定成功。
- P6-3：契约差异检测要求同步版本和说明；行为不改 Schema 也有行为版本及场景检查。自动化不能证明所有语义等价，PR 审查保留行为影响项。
- P6-4：接入 `scripts/run_checks.py`，继续由现有 CI 执行。具体 pytest 文件先按本计划新建，避免引用不存在的测试作为已完成证据。
- P6-5：独立 Agent 只收到连接方式、认证和 bootstrap 入口，不读仓库、不调用内部 Web 路由，完成验收流程。
- P6-6：更新接入手册、能力矩阵、工作流食谱、错误恢复说明。SDK 示例不嵌入一份会失效的固定参数全集。

**验收：**新增能力遗漏模型/适配/文档/场景会被阻断；已知业务 pending 能力为 0；独立 Agent 验收有操作记录和产物证据。基础 CI 模拟付费供应商；真实供应商演练作为独立显式运行项，失败与协议失败分开报告。

## 6. 最终场景矩阵

| 场景 | 要验证的结果 |
|---|---|
| 全流程 | 创建项目→文章→规划→图片→Mask→音频→标注决策→可选数字人→视频/PPTX |
| 精细编辑 | 删除/新增/重排页，修改一页旁白、图片、Mask 或标注，读回正确且仅影响相关资源 |
| 可选路径 | 静态整页、Mask reveal、标注启用/跳过、数字人启用/禁用、双画布 |
| 动态新增 | 服务新增能力后，同一客户端经发现调用成功，不增加分支代码 |
| 契约变化 | 缓存旧 Schema 的写入副作用为 0；刷新后按新参数执行 |
| 网络未知结果 | 提交后断连，使用同一幂等键获得原操作，无重复上游生成 |
| 并发修改 | 两个编辑者提交相同 revision，冲突方重读而不是覆盖 |
| 进程重启 | 已持久化任务仍可查；中断任务状态明确，不误报成功或永久 running |
| 审查有效性 | 旧图片/音频版本不能被确认，no-op 保存不清空有效确认 |
| 权限与资源 | 列表、能力调用、任务、上传下载均校验账号；日志不输出密钥 |
| 停止 | 指定 operation 停止不影响另一个任务；停止请求与真正取消区分 |
| 产物 | 音视频、PPTX 和预览可取回；删除与 sidecar/registry 保持一致 |

涉及真实数据库的测试统一使用 checks/conftest.py 的隔离目录。重启测试使用专属临时数据与端口，禁止针对正在运行的用户服务器启动第二实例。

## 7. 依赖顺序与交付批次

```text
P0 盘点与规则
  → P1 契约内核与首个纵向切片
    → P2 可靠写入与任务
    → P3 动态发现与客户端
    → P4 状态/预检/确认
      → P5 分域补齐
        → P6 全流程验收与发布
```

P3 的只读发现可以在 P2 期间实施；P4 的规则整理也可提前。P5 各领域只在公共模型冻结后按模块拆分，不能由多人同时修改 capabilities 聚合入口、models、dispatch 和 migrations。共享文件由集成负责人统一合入。

建议分成六个可评审批次：①目录和新规范；②契约内核及项目/文章切片；③可靠任务和动态客户端；④状态、预检及 Step 2–3；⑤Mask/音频/标注/数字人/输出与横向配置；⑥缺口清零与独立 Agent 验收。每批必须可测试，不将所有验证留在最后。

工作量在 P0 盘点后按缺失能力、现有任务持久化覆盖和配置暴露范围估算；本计划不把未经验证的天数当交付承诺。若分期上线，只公布已通过验收的能力，并明确部分开放状态，不能提前称“全系统开放”。

## 8. 后续每次功能开发的固定流程

1. 修改功能目录条目，说明新增/调整/删除操作及 Agent 影响；纯展示变更记录理由。
2. 修改业务规则和唯一请求/响应模型，更新能力与行为版本。
3. 同步 handler、状态/预检、必要的幂等/取消/资源规则。
4. 从注册表生成发现数据、工具定义、OpenAPI、文档和快照。
5. 增补至少一个实际行为场景；功能纯展示且无协议影响时不机械增加测试。
6. 运行目标领域测试、Agent 检查，再运行仓库要求的最终检查。
7. 发布同一构建内的服务与契约；客户端刷新目录。协议基础入口变动须明确要求客户端升级。

PR 必填：feature IDs、capability IDs、输入/输出及行为变化、失效影响、测试证据、生成文件状态。完成定义由 CI 与代码审查共同执行，不能只靠勾选“Agent 已同步”。

## 9. 本次明确不做

- 历史 Agent 协议、旧字段、旧工具别名、旧 SDK 兼容和旧项目迁移。
- 对任意客户端永久零升级的承诺。
- 任意代码执行、SQL 控制台、内部文件系统无限制访问。
- 重写现有生成算法、改为多机服务、将全部业务搬进 Agent 路由。
- 为本计划删除数据、修改已应用迁移或现在就执行付费生成。

## 10. 第一批可直接执行的任务单

- [ ] 建立 feature 目录及当前能力差距表，覆盖全部可见步骤和横向模块。
- [ ] 固定新契约模型、错误结构、指纹规则、参数绑定和 bootstrap 入口。
- [ ] 增加功能/路由/字段登记检查，并接入现有 quick/full 检查。
- [ ] 更新 AGENTS.md 与 PR 模板，写入持续同步规则。
- [ ] 完成 project.create/get/update 与 source.set 的统一 dispatch 纵向切片。
- [ ] 使用通用 AgentClient 和固定 MCP invoke 完成创建项目、导入、读取结果。
- [ ] 验证过期契约、越权、重复请求与非法输入不会产生额外副作用。

第一批结束后，应能证明“功能注册一次、各通道一致使用、变更会被检查”，再进入全领域扩展。
