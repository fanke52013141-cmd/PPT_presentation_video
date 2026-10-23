# Current contract notice

The current API is 2.1.0 with bootstrap protocol 1. Use
[`current-contract-guide.md`](current-contract-guide.md) for runtime discovery
and generic invocation. Live capability details and the generated
`contract-snapshot.json` are authoritative. The current handoff follows; the
v1.x delivery notes at the bottom are archived and must not be used as current
connection instructions.

---

# Agent 全功能开放改造交接（当前批次，2026-10-23）

> 交接状态：本批"全功能开放基础改造"已完成开发与验证，与本文档在**同一提交中
> 推送至 `origin/main`**（见 git log 中本文件的最新提交）。本节是唯一有效的
> 交接内容；下方 v1.x 章节仅作历史参考。

## 一、目标与总体进度

依据 `openness-and-evolution-plan.md` 与 `development-plan.md`，把项目改造为
外部 Agent 的一等客户端：Agent 通过发现入口获得实时 Schema 与契约指纹，经统一
invoke 调用与 Web UI 相同的业务服务，不重建业务算法、不绕过配额/归属/失效规则。
无旧协议兼容层、无迁移窗口。

阶段状态（P0–P6，详见 `development-plan.md`）：

| 阶段 | 状态 |
| --- | --- |
| P0 功能盘点与覆盖登记 | 🟡 部分：262 个业务 HTTP 入口已全部登记并接入检查；字段级/后台功能盘点待补 |
| P1 契约内核与统一 dispatch | 🟡 部分：发现/指纹/dispatch/invoke 已落地，project+article 纵向切片已验证；全领域模型拆分（`agent_contract/domains/`、`agent_api/domain_routes/`）待做 |
| P2 幂等、版本与可靠任务 | 🟡 部分：operation 寻址、TTS/视频/一键持久任务、项目与旁白 CAS、幂等重放绑定已落地；其余领域写入幂等、资源传输、同步生成持久化待做 |
| P3 动态发现、MCP 与 CLI | 🟡 部分：检索/详情/固定 MCP 工具/CLI 动态调用已落地；ETag 条件刷新与缓存策略待做 |
| P4 状态/预检/确认 | ⬜ 未开始（`project.state`、`project.change_preview`） |
| P5 八步分域能力补齐 | ⬜ 未开始：262 项入口中 249 项 pending、13 项 partial |
| P6 全量门禁与独立 Agent 验收 | ⬜ 未开始：`--require-complete` 严格门禁当前预期失败 |

**结论：当前不是全功能开放状态。** 已开放的是发现协议 + 统一调用 + 精确任务
生命周期 + 项目/文章纵向能力；分域能力按 P5 待逐域补齐。对外口径以
`current-contract-guide.md` 与 `feature-coverage.md` 为准。

## 二、契约基线（推送时实测）

- `AGENT_API_VERSION` **2.1.0**（自 1.9.0 直接演进，无兼容期），bootstrap 协议 `1`。
- 契约哈希 `5dad5233e6fcad65`（按单能力描述确定性计算，`agent_contract/versions.py`）。
- 注册能力 **34 项**（`docs/agent/contract-snapshot.json` 为生成快照）。
- 功能覆盖目录 **262 项**：13 项 partial（已有能力对应）、249 项 pending。
- 路径命名空间仍为 `/api/agent/v1`（`GET /meta`、`GET /capabilities`、
  `GET /capabilities/{id}`、`POST /invoke`）。

## 三、本批交付内容

第一批（契约内核与动态调用）：

- 功能目录与登记门禁：`config/agent_features.json` +
  `scripts/check_agent_coverage.py`（新业务入口不登记即失败）+
  生成的 `docs/agent/feature-coverage.md`；AGENTS.md 与 PR 模板写入强制同步规则。
- 契约指纹体系：单能力指纹（`agent_api/fingerprints.py`）替代整目录哈希粗粒度
  校验；目录指纹用于发现变化；行为与契约版本分离。
- 发现与统一调用：`agent_contract/discovery.py`（目录/详情描述）、
  `agent_api/discovery.py`（HTTP 检索/详情）、`agent_api/dispatch.py`（显式
  handler 注册 + 统一 invoke，含契约校验、输入验证、作用域检查）、
  `agent_api/operation_routes.py`（operation.get/list/cancel HTTP 面）。
- 客户端动态化：`agent_client` 增加 discover/describe/invoke；MCP 固定三工具
  （search/describe/invoke，`mcp_server/bootstrap.py`）；CLI `capability
  list/show` + `invoke`（`cli/discovery.py`）。业务能力更新无需改客户端分支。
- 纵向切片：project.create/list/get/update/delete、source.set 经统一 dispatch
  端到端验证；过期契约（CONTRACT_CHANGED 409，`executed=false`）、越权、非法
  输入均在业务执行前拒绝。

第二批（可靠任务与幂等）：

- 统一任务寻址：`agent_operation_service.py` 把 TTS `job:<id>`、视频渲染任务、
  一键生产 `pipeline:<run_id>` 映射为可查询/列举/取消的 operation，直接读源任务
  存储，不维护第二份终态；CLI `operation get/list/wait/cancel`。
- 一键运行历史：`one_click_run_store.py` 将每次一键运行完整保存于
  `planning/one_click_runs/<run_id>.json`，进程失联运行报告 interrupted。
- 并发控制：项目元数据与旁白编辑在业务写入前用数据库 CAS 抢占 revision；
  相同内容 no-op 保存不推进版本、不清下游工作。
- 幂等重放收紧：键绑定账号+能力+目标资源+规范化参数+契约指纹；相同键不同输入
  返回 IDEMPOTENCY_CONFLICT；未知结果返回 OPERATION_OUTCOME_UNKNOWN，禁止换键
  盲目重试付费生成；过期键返回 IDEMPOTENCY_EXPIRED。

## 四、验证结果（推送前实测，隔离数据库与 runs 目录，无真实付费调用）

- `python scripts/check_agent_coverage.py`：通过
- `python scripts/generate_agent_contracts.py --check`：通过（矩阵/快照/覆盖同源）
- `python -m pytest checks/agent -q`：**465 passed**（含动态调用、operation
  生命周期、幂等边界、越权与过期契约拒绝场景）
- 新增/变更模块 `compileall`：通过；Ruff/空白检查此前已随批次验证

## 五、接手指引

1. **接入**：按 `current-contract-guide.md`——`GET /meta` 验证 bootstrap 协议 →
   搜索 capabilities → describe 读取 Schema 与 `contract_revision` → `POST
   /invoke`（写操作必须携带刚读取的指纹与幂等键）。二进制与事件流走详情中声明的
   专用传输，不经 invoke。
2. **开发新功能**：先登记 `config/agent_features.json`，再按 AGENTS.md 的
   Agent Contract Synchronization Policy 同步模型/能力/适配/文档/测试；
   `checks/agent/test_feature_coverage.py` 与 `checks/agent/test_dynamic_invocation.py`
   是新增能力时的最小增测入口。
3. **下一步建议（按序）**：① P1 全领域模型拆分 + P2 其余领域写入幂等与资源传输
   （`resource.upload/get`）；② P4 `project.state`/`project.change_preview`；
   ③ 按 P5 表逐域补齐 249 项 pending（建议顺序：Step 1–3 → Step 5 音频 →
   Step 4 Mask → Step 6 标注 → 输出与横向配置）；④ P6 `--require-complete`
   门禁 + 独立 Agent 全流程验收。
4. **红线**：不得为待实现能力宣称 stable；不得绕过 generation_governor；
   不得在 adapter 层复制业务算法；`--require-complete` 通过前不得宣布全功能开放。

---

# Agent 接口层交接文档（v1.x 归档）

> 交接状态：本轮 Agent 接口层增强已全部**提交并推送** —— 对应提交
> `09619b0`（feat: Agent 接口层增强），已合入 `origin/main`，本地与线上一致。
> 本文档用于把已完成的内外部接口层交付内容交接给后续接手者。

## 一、交接概要

PPT Studio 在既有 Web UI 与业务服务之外，交付了一整套**受版本约束的适配层**：Agent API、MCP 服务与命令行工具，统一定义在"能力注册表"（Capability Registry）中，供外部 Agent / 脚本 / 自动化低代码接入。

| 交付项 | 状态 | 说明 |
| --- | --- | --- |
| 能力注册表 | ✅ 已推送 | 22 项 stable 能力，契约哈希 `8cfa3c7b7b47feac`，版本 v1.1 |
| Agent API | ✅ 已推送 | `/api/agent/v1/*`，17+ 端点，含 OpenAPI 自描述 |
| MCP stdio 服务 | ✅ 已推送 | `python -m mcp_server`，工具生成 / 资源 / 协议处理 |
| CLI | ✅ 已推送 | `python -m cli.pptctl`，子命令覆盖全部能力 |
| AgentClient | ✅ 已推送 | 纯标准库 HTTP 客户端，无外部依赖 |
| 测试 | ✅ 已验证 | 406 项 Agent 测试 + 13 项迁移/失效测试 + quick 回归全绿 |

核心约束：**Agent 只是适配层，不直接访问数据库、项目运行目录或 ComfyUI**；所有业务实现复用现有 source-owned 服务与组合根配置。

## 二、架构

```text
Capability Registry + schema builders (agent_contract/)
        ├─ Agent API  (/api/agent/v1)        └─ OpenAPI 自描述
        ├─ MCP tools/resources (stdio)        └─ python -m mcp_server
        └─ CLI (python -m cli.pptctl)
                  ↓
        AgentClient / production service facade
                  ↓
  one_click_orchestrator + existing source-owned services
```

能力清单唯一来源是 `agent_contract/capabilities.py`；输入/输出 Schema 由
`agent_contract/schema.py` 合成 URL 路径参数与请求体。**不得在 MCP、CLI 或文档中
重新手写同一份参数定义**——一致性由 `scripts/generate_agent_contracts.py --check`
强制校验（能力矩阵必须与注册表同源）。

## 三、模块职责（本层新增/所属）

- `agent_contract/` — 能力注册表、Pydantic 请求/响应模型、操作状态与审查阶段、
  版本/契约哈希、产物与 Resource URI、Schema 合成器（纯数据层，无 FastAPI/DB 依赖）。
- `agent_api/` — 版本化路由、错误层级（404/422/409/500）、认证中间件、滑动窗口
  限流、请求链路追踪、幂等服务接线、OpenAPI 自描述文档。
- `agent_client/` — 纯标准库 HTTP 客户端（`urllib`）与轮询工具；URL 构造、请求头
  注入、错误归一化、`idempotency_key` / `expected_revision` 透传。
- `mcp_server/` — JSON-RPC 2.0 stdio 服务；工具定义与处理器自动生成、Resource
  URI 解析与读取、结果展示格式化（图片/文本/link）、合约协商。
- `cli/pptctl.py` — argparse 命令行，子命令覆盖 project/source/run/approve/stage/
  image/narration/tts/video/artifacts/diagnostics/meta/digital-human。
- `database_migrations.py` + `migrations/00NN_*.sql` — 幂等表、`revision` 乐观锁列、
  `review_policy` 列等 schema 演进（并发下可识别既有 schema 避免重复加列）。

## 四、本轮推送包含的功能（相对上次 `db84ccb` 的增量）

1. **OpenAPI 自描述增强**：为每个能力注入完整请求/响应 JSON Schema、路径参数、
   查询参数与请求体；Swagger 使用根 server URL，避免 `/api/agent/v1` 前缀被拼接两次。
2. **限流加固**：令牌改为 SHA-256 哈希后再作客户端键（不再存明文前 64 位）；
   支持 `Authorization: Bearer <key>`、`x-api-key`、`x-agent-token`、URL `token`；
   新增 `trust_proxy_headers` 开关，默认不信任 `X-Forwarded-For`；接入 SQLite
   持久化限流存储。
3. **数字人配置契约统一**：`digital_human_routes` 改为 Pydantic `{"config": {...}}`
   契约，复用网页端同一配置归一化/原子写入函数；MCP、CLI、HTTP 客户端同路径。
4. **认证主变量统一**：`PPT_AGENT_API_KEY` + `Authorization: Bearer`；`PPT_APP_TOKEN`
   仅保留为本地旧脚本兼容回退（MCP 同步此优先级）。
5. **SSE 实时流式**：新增 `pipeline.stream` 能力（`/runs/latest/stream`），pipeline 进度
   可实时推送（含测试覆盖）。
6. **契约/幂等/审查策略全链路**保持并扩卫：优化置锁、幂等 claim/finalize、
   `review_policy`（none / images_and_video / all_stages）在创建→ORM→Summary 全链路透传。

（历史 v1.1.0 能力——正式服务复用、审查点真实编排器状态、幂等性与合约协商、
媒体登记等——详见下文「历史能力清单」。）

## 五、历史能力清单（v1.1.0 已交付并推送）

1. **正式服务复用**：Agent 图片重绘/TTS/视频渲染/旁白修改均使用生产服务（
   `get_project_pipeline_services()`），不再调用不存在的工厂。
2. **审查点作为真实编排器状态**：`stop_at` 支持六个审查阶段；流程在阶段边界持久化为
   `waiting_for_review`，未经匹配审批不能恢复；拒绝会持久化决定与备注并保持暂停。
3. **可发现、可启动的 MCP/CLI**：默认地址 `http://127.0.0.1:8000`、`PPT_AGENT_API_URL`
   可覆盖；`python -m mcp_server` 启动；Tool Schema 含全部必填路径参数；工具失败返回
   `isError: true`；补齐 `artifact get`。
4. **媒体与产物访问**：当前图片/音频/最新视频资源端点；MCP 图片/音频返回真实二进制；
   下载端点受项目运行目录约束，防路径逃逸。
5. **幂等性与乐观锁**：`agent_idempotency_service.py` 完整 claim/finalize 生命周期；
   `projects.revision` 列与 `agent_idempotency_records` 表；10 个写操作全部接入，
   客户端可经 `idempotency_key` 安全重试。
6. **MCP 契约协商**：`initialize` 时与 `/meta` 的 `contract_hash` 强制协商，主版本不匹配
   阻止工具调用并给出警告/错误。
7. **审查策略持久化**：`projects.review_policy` 列全链路；CLI `--review-policy` 支持。
8. **媒体资源登记**：Step 3 图片 / Step 7 音频确认时自动登记 `ArtifactRecord`，
   删除图片同步清理，`/artifacts` 返回全部产物类型。
9. **请求链路追踪**：`X-Request-ID` 生成/传播，`request.state.request_id` 供日志引用。

## 五点一、后续增强（当前工作区）

- MCP 服务版本已提升至 `1.1.0`。
- 契约哈希发生漂移但主版本兼容时，MCP 仍允许只读工具继续工作，
  但会阻断所有状态变更工具，并在 `initialize.serverInfo.writeAllowed` 中明确告知客户端。
- MCP 在完成 `initialize` 前对写工具默认拒绝，避免绕过契约协商直接修改项目状态。

## 六、运行方式

```powershell
# 启动主应用（Agent API 与 Web UI 同端口；需先配置 LLM/图片/TTS 凭据）
python start_server.py

# 查看 Agent 发现文档（能力/契约哈希/Schema）
python -m cli.pptctl meta

# 启动 MCP stdio 服务
python -m mcp_server

# 常用 CLI 示例
python -m cli.pptctl project create --name "示例项目" --canvas portrait_9_16
python -m cli.pptctl source set --project <project_id> --content "文章内容"
python -m cli.pptctl run start --project <project_id> --stop-at image_review
python -m cli.pptctl run status --project <project_id>
python -m cli.pptctl approve --project <project_id> --checkpoint image_review
```

环境变量：`PPT_AGENT_API_URL`（API 地址）、`PPT_AGENT_API_KEY`（Bearer 认证）、
`PPT_AGENT_TRUST_PROXY_HEADERS=1`（信任代理头，默认关）。
`source set` 必须在 `--file/--content` 与 `--topic` 中二选一；生产 TTS 当前仅支持
整项目合成，传 `slide_ids` 会被明确拒绝。

## 七、质量门禁（提交 Agent 层变更前必须满足）

```powershell
python scripts/generate_agent_contracts.py --check   # 能力矩阵与注册表同源
python -m pytest checks/agent -q                     # 全量 Agent 契约/E2E/协议测试
python scripts/run_checks.py --level quick           # 全仓快速回归
```

新增/修改一个 Agent 能力时，必须在同一变更内完成：更新注册表与请求/响应模型、
增加/调整 API 路由与正式服务适配、确认 MCP Tool 与 CLI 命令可达、运行文档生成器、
补充契约与端到端测试。CI 会拦截缺路由、缺 CLI 命令、漏 MCP 路径参数或能力矩阵过期
的提交。

## 八、已知限制与后续建议

- MCP 目前只在 `initialize` 时协商契约；长生命周期进程尚无 TTL/周期性重新协商。
  当前实现会在初始化后阻止契约哈希漂移下的写操作，但不会主动发现服务端随后发生的漂移。
- 外部 LLM、生图、IndexTTS、ComfyUI 与数字人服务仍需在具备测试凭据/GPU 的受控环境
  执行一次真实全链路发布验收。
- 后续工程项：继续拆分 `server.py`、提高测试覆盖率、锁定 Python 依赖版本、迁移
  TestClient 的第三方弃用 API（1 条弃用警告）。

## 九、本轮验证结果（本次推送前已跑通）

- `python -m compileall -q`（含全部 Agent 层模块）：通过
- `python -m pytest checks/agent -q`：**406 passed**
- `python -m pytest checks/test_database_migrations.py checks/test_invalidation_service.py
  checks/test_source_runtime_safeguards.py -q`：**13 passed**
- `python scripts/generate_agent_contracts.py --check`：通过（22 项能力，hash `8cfa3c7b`）
- `python scripts/run_checks.py --level quick`：全部通过
  （含 startup hooks / runtime hotfixes / settings mask 自检）
