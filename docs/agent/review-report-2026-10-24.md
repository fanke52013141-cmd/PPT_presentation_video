# Agent 全功能开放改造：独立审查报告与优化计划（2026-10-24）

> 审查对象：`main@a80be8a`（feat(agent): 全功能开放第二至五批，API 2.7.0）
> 审查方式：静态代码审查 + 动态门禁验证 + 机械化干跑 + 文档完备性评估
> 审查范围：`agent_api/`、`agent_contract/`、`agent_client/`、`mcp_server/`、`cli/pptctl.py`、
> `agent_*_service.py`、`scripts/check_agent_coverage.py`、`scripts/generate_agent_contracts.py`、
> `scripts/run_checks.py`、`.github/workflows/ci.yml`、`docs/agent/*`、认证与限流中间件

---

## 一、总体结论（TL;DR）

| 审查问题 | 结论 |
|---|---|
| 1. 改造是否存在 bug | **未发现会导致错误结果的 P0 功能缺陷**。基线非常健康（750 项回归全通过、230 个能力 dispatch 参数绑定干跑零问题、无服务级 Depends 违规）。发现 **3 项 P1**（scope 模型 fail-open 与权限提升链、幂等键永久烧毁、错误码退化）与若干 P2 |
| 2. 对接规范是否完备 | **协议语义层面基本完备**（发现/调用/幂等/任务/传输均有口径），但存在 **1 项上手阻断缺口**：接入指南完全没有认证章节（令牌申请、scope、账号绑定、限流均未文档化），且工作流食谱、错误恢复手册未开始（P6-6 已知） |
| 3. 功能修改能否同步触发 Agent 修改 | **防漂移链条是本次改造最扎实的部分**：路由↔登记↔能力↔HTTP/invoke 同源↔文档快照五层双向门禁且已接入 CI。缺口集中在**处理器内部逻辑变更**（G1，无门禁）与**版本递增纪律**（G4，纯人工） |

**一句话**：契约底座与防漂移门禁的质量超出一般项目水准；当前最值得投入的是
安全模型收口（scope fail-open）、幂等恢复路径、以及把"如何接入"写进文档。

---

## 二、基线健康度（审查中实际执行的验证）

| 验证项 | 命令/方法 | 结果 |
|---|---|---|
| Agent 专项回归 | `python -m pytest checks/agent/ -q` | **750 passed**（75.9s） |
| 覆盖登记门禁 | `python scripts/check_agent_coverage.py` | 通过（决策最新） |
| 快照一致性 | `python scripts/generate_agent_contracts.py --check` | 通过（三份生成物同步） |
| dispatch 参数绑定干跑 | 对 230 个可调用能力静态解析 handler 签名 × input_model 字段 | **0 问题**（无 "Missing adapter binding" 类 500 风险） |
| Depends 违规扫描 | 全部 domain_routes 扫描非 `get_db` 的服务级 Depends 默认值 | 0 违规（规范 §6.5 落实） |
| 二进制能力泄漏检查 | transport≠json 且 mcp_enabled 的能力 | 0 个（MCP 工具面干净） |
| 行数门禁 | routes.py 151 物理行 | 逻辑行 ≤150，测试通过 |
| 错误处理器作用域 | `register_agent_error_handlers`（agent_api/__init__.py:16） | HTTPException 转换仅作用于 `/api/agent/v1/`，不影响 Web 路由 |

---

## 三、问题一：改造中的缺陷

### P1-1 scope 模型 fail-open：空/非法 scopes 静默发放全量权限

- **位置**：`account_service.py:17-23`（`_safe_scopes`）
- **现状**：创建 Agent 令牌时，`scopes` 为空或全部非法时**回退为全量四 scope**
  （`project:read,project:write,pipeline:write,artifact:read`）。
- **后果**：调用方本想创建受限令牌（如只读），因拼写错误或传空而得到完全权限令牌，
  且不会有任何提示。安全默认应当 fail-closed。
- **建议**：空 scopes 时要么拒绝创建（422），要么默认最小集 `project:read`；
  至少在响应中显式回显实际授予的 scopes（当前已回显，但创建方未必核对）。

### P1-2 声明了 7 种 scope 却只强制 4 种 → 权限提升链

- **位置**：
  - 授予侧允许 7 种：`account_service.py:18-21`（含 `config:read/write`、`account:manage`）
  - 强制侧只有 4 种：`agent_api/auth.py:142-155`（中间件）与
    `agent_contract/discovery.py:28-33`（`required_scope`）——两处逻辑同源，仅按
    method/path 推导 `project:read` / `project:write` / `pipeline:write` / `artifact:read`
- **后果**（同账号内的能力越宽，不跨账号）：
  - 持 `project:write` 的令牌可**管理账号**（`accounts.create/delete`）、
    **铸造新令牌**（`accounts.agent_token.create`——结合 P1-1 可自我升级为全量令牌）、
    **读写供应商凭据**（`credentials.create/update`，可写入 LLM/生图服务的 API Key）。
  - `config:*` 与 `account:manage` 三种 scope 可被授予但从不被检查：只授予这三种的令牌
    反而在所有请求上被 403（授了没用的权限），模型语义自相矛盾。
- **建议**（二选一，需产品决策）：
  1. **落地细粒度 scope**：`required_scope()` 从能力的域前缀推导（如 `accounts.*` →
     `account:manage`、`credentials.*/settings.*` → `config:write`），中间件与 dispatch
     共用同一函数（现在就是共用的，改一处即可），并把 `accounts.agent_token.create`
     单独提到 `account:manage`。
  2. **收缩声明**：`_safe_scopes` 删除三种未强制 scope，文档明示"当前 scope 仅四种粗粒度"。
  无论哪种，`accounts.agent_token.create` 都不应低于 `account:manage`。

### P1-3 幂等键"永久烧毁"：无副作用的校验失败也不可重试

- **位置**：`agent_idempotency_service.py:187-216`（`_resolve_existing`）+
  各适配器的 `except Exception: idempotency.finalize(claim.record_pk, False, None)`
  （如 `agent_api/domain_routes/project.py:179-181`、`images_ext.py:80-82`）
- **触发链**：`project.create` 携带幂等键 → 本地校验失败（如非法 `course_id`，零副作用）→
  记录标记 `failed` → 客户端修正参数后**同键重试** → 命中
  `OPERATION_OUTCOME_UNKNOWN`，永远无法用该键成功，只能换新键。
- **影响面**：所有接入幂等框架的能力（project.create/update/delete、source.set、
  pipeline.run/resume、image.generate、image.regenerate、video.render、tts.synthesize）。
- **设计权衡说明**：对**付费/外部副作用**能力（image.generate 等），失败后禁止重试是
  正确的保守取向（供应商可能已扣费成功）。但对**纯本地校验失败**，这是纯粹的可用性缺陷。
- **建议**：
  1. 区分失败类别：适配器在**进入业务服务前**的失败（请求模型校验、资源 404、
     CAS 预检失败）调用 `finalize(claim.record_pk, False, None, retryable=True)`，
     记录标记为 `failed_retryable`，重试同键时允许重新执行（指纹一致前提下）。
  2. 错误信息明确指示：`OPERATION_OUTCOME_UNKNOWN` 的 `repair_actions` 增加
     `{"action": "retry_with_new_key"}`，让外部 Agent 知道出路。
  3. 顺带修复同源问题：**卡死的 `in_progress` 记录无恢复路径**——
     `STALE_IN_PROGRESS_HOURS = 1`（`agent_idempotency_service.py:34`）目前只影响
     错误码（`OPERATION_IN_PROGRESS` → `OPERATION_OUTCOME_UNKNOWN`），超过阈值的
     悬挂记录永远占用该键。建议超过 stale 阈值后允许"归档旧记录 + 新键或显式接管"，
     否则进程崩溃一次就永久少一个可用键。

### P1-4 直接 HTTP 路由的错误码退化为 `HTTP_ERROR`

- **位置**：`model_connection_routes.py:32-40`（`_raise_http_error`，被
  `system_ext.py`/`narration.py`/`video.py`/`project.py` 等约 20 处适配器复用）→
  HTTPException → `agent_api/__init__.py` 的 scoped handler →
  `errors.py:75-86`（`code` 固定 `HTTP_ERROR`）
- **后果**：外部 Agent 通过 method/path 直连（发现详情声明的正规途径）调用时，
  404/409/422 全部变成 `code=HTTP_ERROR`，只能靠解析 `message` 中文文本来区分——
  无法编程化恢复。指南第 31 行自认"统一这些边界错误是后续工作"。
- **建议**：分两步收口——
  1. 让 `_raise_http_error` 直接抛 `AgentAPIError`（带 `NOT_FOUND`/`CONFLICT`/
     `VALIDATION_ERROR` 等机器码），Web 路由层再转 HTTPException（保持 Web 兼容）；
  2. `errors.py` 的 `http_exception_handler` 补齐 `retryable`/`repair_actions`/
     `trace_id` 字段，至少保证信封形状一致（当前缺三个字段）。

### P1-5 未配置认证时 Agent API 对网络完全开放（部署安全）

- **位置**：`agent_api/auth.py:136-137`——`PPT_AGENT_API_KEY` 未设置时所有请求
  匿名放行，且可用 `X-PPT-Account-ID` 头自由切换账号；没有 loopback 绑定校验。
- **现状评估**：这是文档化的"本地/回环默认"（auth.py 模块注释），桌面单机场景合理；
  但若部署到局域网/服务器而忘记设环境变量，273 个能力（含删项目、写凭据）全暴露，
  且**启动时无任何警告**。
- **建议**：服务启动时检测"Agent API 未认证 + 监听地址非 127.0.0.1"→ 打印显著
  警告或直接拒绝启动（提供 `PPT_AGENT_ALLOW_UNAUTHENTICATED=1` 显式豁免）。

### P2 级问题

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| P2-1 | `agent_api/dispatch.py:236-237` | HANDLERS 字面量中 `"connections.get"` **重复注册两次**（值相同，Python 静默覆盖）。当前无影响，但后续单改一行会引入分叉且无测试报警 | 删除重复行；可加一个"无重复键"的单测（用 ast 解析或重构为列表+去重断言） |
| P2-2 | `agent_client/transfers.py:136-150` | `upload_file` 将**整个文件缓冲进内存**（bytearray，上限 1 GiB），与下载路径"不缓冲媒体进内存"的流式设计自相矛盾；数字人视频上传可打满内存 | multipart 分块流式构造（urllib 支持 generator body 或改用 http.client 逐块写） |
| P2-3 | `mcp_server/tools.py:62-67` | `_dispatch` **每次调用现算最新 contract_revision**，与文档口径（current-contract-guide.md:153"命名工具使用本地展示的 Schema 对应的指纹，服务端变化会返回明确错误"）不符：契约变更被静默吸收，不兼容时返回 VALIDATION_ERROR 而非 CONTRACT_CHANGED | 二选一：真正缓存展示时指纹（符合文档），或修改文档说明现算语义。推荐前者（对外部 Agent 更安全） |
| P2-4 | `agent_api/rate_limit.py:47` | 内存模式 `_hits` 字典的键**永不回收**（仅窗口内条目修剪），低速键数泄漏；429 响应体缺 `details`/`repair_actions`/`trace_id` 字段 | 窗口修剪后 `len(hits)==0` 时删键；429 体对齐统一信封 |
| P2-5 | `agent_api/auth.py:71-73` | `?token=` 查询串传令牌（GET）会进入反向代理/访问日志；文档未警示 | 文档明示风险；考虑彻底移除 query token 通道 |
| P2-6 | `agent_contract/versions.py:30,37` | `describe_capability` 在循环内重复 import；`CONTRACT_VERSION` 模块导入时对 273 能力全量 SHA-256（启动开销，且 `get_contract_hash` 被 discovery/dispatch 每请求调用——**无缓存**，每次 invoke 都对全部能力重算一次哈希供指纹比较之外的场景使用） | `get_contract_hash` 结果按 CAPABILITIES 身份缓存（frozenset 版本戳失效） |
| P2-7 | `account_service.py:187-188` | `authenticate_agent_token` 每次请求 `last_used_at` 写库 + commit（写放大；SQLite 单写者下与业务写竞争） | 改为内存节流（如每分钟最多写一次） |
| P2-8 | `agent_api/domain_routes/system_ext.py:97-107` 等 | `agent_import_config_zip` 等适配器 `async def` + `await file.read()` **整包读入内存**，虽有 `_config_import_limit()`，但需确认上限值足够小 | 核对限制值；超限先拒绝（bounded read 模式项目内已有先例 `model_connection_routes.py:28-29`） |
| P2-9 | `one_click_run_store.py:20-22` | 半写文件（崩溃残留）触发 `json.JSONDecodeError` → 被映射为 503 `OPERATION_UNAVAILABLE`（`agent_operation_service.py:80-81`），语义尚可但客户端无法区分"文件损坏"与"服务不可用" | 可接受；如需精确可捕获 JSONDecodeError 单独给码 |

**抽查中确认无问题的重点区域**（避免误判为未查）：
- 幂等 CAS（`bump_revision`，`agent_idempotency_service.py:292-317`）：UPDATE 带
  revision 守卫，`changed != 1` 回滚并报 `REVISION_CONFLICT`，SQLite 写者先行的
  并发论证正确；
- `operation.list` 分页合并算法（`agent_operation_service.py:86-104`）："只加载前
  offset+limit 个 job"在任意 runs 数量下窗口正确（已有注释论证）；
- 一键运行存储路径安全（`one_click_run_store.py:11-13` run_id 白名单正则 +
  身份双重校验）；
- 下载客户端传输安全（`agent_client/transfers.py`）：同源重定向守卫、
  Content-Length 与流式双重大小校验、SHA-256 校验、原子 `os.replace`；
- 230 个能力的 dispatch 静态绑定全部一致（无签名漂移）。

---

## 四、问题二：Agent 对接规范完备性评估

### 4.1 维度评估表

| 维度 | 状态 | 证据与说明 |
|---|---|---|
| A. 接入引导（从零到首次 invoke） | **严重缺口** | `current-contract-guide.md` 有发现→describe→invoke 四步协议（第 5-27 行），但**无认证章节**：PPT_AGENT_API_KEY 环境变量、`accounts.agent_token.create` 令牌创建流程、scope 语义、`X-PPT-Account-ID` 账号绑定全部未写入（全文 grep 仅第 31/147 行附带提及）。外部 Agent 无法仅凭文档完成鉴权。README 也无 Agent 入口指引 |
| B. 协议语义（版本/revision/幂等/错误） | **基本完备** | CONTRACT_CHANGED 409 语义、幂等键生命周期（7 天重放/墓碑/OUTCOME_UNKNOWN/IN_PROGRESS/CONFLICT）、CAS 语义均有明确口径（guide 第 35-48 行）；错误结构有 `error.code/message/details/retryable/repair_actions/trace_id`。缺口：错误码**全集表**不存在（散落正文），且实际仅部分路径产出机器码（见 P1-4） |
| C. 异步任务模型 | **完备** | operation 生命周期、8 种状态、unknown 语义、cancellation_supported/requested、中断恢复归属（生产者负责）、等待超时不取消服务端，均成文（guide 第 116-139 行）；SSE 断线回退（轮询 operation.list）在交接文档中标注"需明示"但**尚未写入手册** |
| D. 资源传输 | **完备** | ppt:// URI、ID 稳定性口径（同路径更新以新 hash 识别）、CLI/客户端下载参数（hash 校验、max-bytes、原子落盘）成文（guide 第 97-114 行）；上传能力（file_upload 14 项）的传输规范已在 2.7.0 落地并有真 socket 验收 |
| E. 限流与配额 | **缺口** | 120 req/60s、SQLite 持久、429 + Retry-After + X-RateLimit-* 均已实现（`rate_limit.py`），但**对接文档零提及** |
| F. 长流程编排食谱 | **未开始** | 仅有 Step 1-2 的推荐流程（guide 第 66-69 行）；八步全流程编排、checkpoint 审批门禁用法、失败重试策略、SDK 示例属 P6-6，交接文档明确"未开始" |
| G. 三通道一致性 | **完备** | HTTP/MCP/CLI 同源有双向测试断言（`test_transport_contract_sync.py`）；MCP 固定三工具 + 230 命名工具自动注册；CLI 通用 invoke + 专用命令。瑕疵：MCP 命名工具指纹语义与文档不符（P2-3） |
| H. 版本兼容策略 | **部分缺口** | `is_version_compatible`（major 不兼容/minor 兼容）已实现（`versions.py:40-71`）但未对外文档化；无废弃字段策略声明 |

### 4.2 缺口清单（按外部 Agent 上手影响排序）

| 级别 | 缺口 | 影响 |
|---|---|---|
| S0 | 认证规范缺失（令牌申请/传递方式/scope/账号绑定） | **阻断上手**：外部 Agent 无法完成第一次鉴权调用 |
| S1 | 限流规范缺失（阈值/429 语义/重试建议） | 高频调用会被 429 且不知道为什么 |
| S2 | 错误码全集与恢复动作手册缺失 + HTTP_ERROR 退化（P1-4） | 无法编程化错误处理 |
| S3 | 八步工作流食谱 / SDK 示例未开始（P6-6 已知） | 每个接入方都要自行摸索编排顺序 |
| S4 | SSE 断线回退约定未写入对外文档 | 流消费者可能无限挂起 |
| S5 | 版本兼容/废弃策略未声明 | 升级时无行为预期 |

---

## 五、问题三：功能修改能否同步触发 Agent 修改

### 5.1 已自动化的防漂移链条（评价：完备且已接入 CI）

| 层 | 门禁 | 机制 | 强制点 |
|---|---|---|---|
| L1 | 业务路由 ↔ 登记目录 | `features.py:12-45` 静态 AST 扫描根目录 `*.py` 的 APIRouter 装饰器（不 import server），与 `config/agent_features.json` **双向**比对：未登记的新增路由、已删除路由、装饰器变更（路径/方法/响应模型）均报错 | `scripts/check_agent_coverage.py` → run_checks quick+full |
| L2 | Agent 路由 ↔ 能力注册表（反向） | `checks/agent/test_transport_contract_sync.py:63-94`：每条 `/api/agent/v1` 路由必须是注册能力或显式豁免（历史缺陷曾放过 6 条，已有回归防护） | pytest（CI） |
| L3 | 能力 ↔ HTTP 路由（正向） | 同文件 `:34-47`：每个能力必须存在 (method, path) 完全匹配的有效路由 | pytest（CI） |
| L4 | HTTP ↔ invoke 同函数 | 同文件 `:8-31`：invoke HANDLERS 解析出的函数对象必须与 HTTP 路由 endpoint **是同一个对象** | pytest（CI） |
| L5 | 文档/快照同步 | `scripts/generate_agent_contracts.py --check`：`capability-matrix.md` + `contract-snapshot.json`（273 能力全 Schema+指纹）+ `feature-coverage.md` 三份生成物再生成比对 | run_checks quick+full |
| L6 | 能力 ID 悬空 | `features.py:68-70`：catalog 引用的能力必须存在于注册表 | check_agent_coverage |
| L7 | CI 强制 | `.github/workflows/ci.yml`：push/PR main → `run_checks.py --level full` = quick（含 L1/L5）+ **全量 pytest**（含 L2-L4） | GitHub Actions |

**验证**：在 `main@a80be8a` 上实际运行 L1、L5 门禁均通过；L2-L4 随 750 项回归通过。
新增业务路由而不同步 `agent_features.json`、或新增能力而不挂路由、或改 HTTP 不改
invoke——都会在 CI 立即失败。**"结构层"的同步触发是真实有效的。**

### 5.2 绕过所有门禁的场景（缺口）

| # | 场景 | 严重度 | 说明 |
|---|---|---|---|
| G1 | **业务处理器函数体内部逻辑变更** | 高 | 门禁只比对路由装饰器（`features.py:62` 精确比对 `ast.unparse(装饰器)`），函数体改动不触发任何 Agent 侧审查。能力上的 `behavior_version` 字段存在但**无门禁强制递增**。例：`project_service.create` 的字段语义变化、某个服务改了错误码——Agent 契约面静默漂移 |
| G2 | 子目录包中的业务路由 | 中（潜伏） | `features.py:19` 只 `glob("*.py")` 扫描**仓库根目录**。当前所有业务路由都在根目录（成立），但一旦有人建 `routes/` 包即整体逃逸门禁 |
| G3 | 跨文件共享 router 的装饰器 | 中（潜伏） | `routers` 字典只识别**本文件**的 `APIRouter(...)` 赋值（`features.py:22-27`）；`from x import router` 再挂装饰器的路由不被扫描。当前无此写法 |
| G4 | 契约变更但版本号未递增 | 中 | `contract_revision` 是内容哈希（自动变），但 `AGENT_API_VERSION`/能力 `version` 递增纯靠人工纪律（交接文档决策 §6.1）。快照比对只保证"再生成一致"，不校验"变了内容就该升版本" |
| G5 | 本地门禁无钩子 | 低 | `.git/hooks/` 仅 Qoder 追踪器；全靠 CI。若 GitHub 未配分支保护，直接 push main 的失败提交已经落在主干上 |
| G6 | 能力无 feature 反向覆盖 | 低 | capabilities 存在但不被任何 feature 条目引用不会被 L1 报错（由 L2/L3 间接兜底——能力必须有路由、路由必须有登记，实际闭环，可接受） |

### 5.3 结论

**结构性修改（路由/能力/Schema/信封）→ 自动同步触发：已达成**，且质量高。
**行为性修改（业务逻辑）→ 靠人工纪律：未达成**（G1/G4），这是"功能修改同步触发
Agent 修改"的最后一段空白。

---

## 六、优化计划

### 第一阶段：安全与幂等收口（建议本周，1-2 人日）

| 项 | 内容 | 验收标准 |
|---|---|---|
| A1 | 修复 `_safe_scopes` fail-open（P1-1）：空/全非法 scopes → 422 拒绝创建，或默认仅 `project:read` | 新增单测：空 scopes 创建被拒/最小化 |
| A2 | scope 模型决策落地（P1-2）：推荐方案 b 先行——`_safe_scopes` 收缩到 4 种已强制 scope，`accounts.agent_token.create` 的 `required_scope` 特判为 `account:manage` 并同步实现；文档同步声明 | 持 project:write 令牌调用 `accounts.agent_token.create` 返回 403；existing 测试全绿 |
| A3 | 幂等可恢复性（P1-3）：① 无副作用失败标记 `failed_retryable` 允许同键重试；② `OPERATION_OUTCOME_UNKNOWN` 的 `repair_actions` 增加 `retry_with_new_key`；③ stale in_progress（>1h）允许显式归档后重新领键 | 同键校验失败→修正→重试成功的新增测试；崩溃遗留键可恢复 |
| A4 | 部署安全警告（P1-5）：未认证 + 非 loopback 监听 → 启动告警（或拒绝 + 豁免开关） | 启动日志含警告的冒烟断言 |

### 第二阶段：对接规范补全（建议下周，2-3 人日）

| 项 | 内容 | 验收标准 |
|---|---|---|
| B1 | `current-contract-guide.md` 新增**认证与账号**章节：PPT_AGENT_API_KEY、`accounts.agent_token.create` 全流程（含原始令牌仅返回一次的警示）、scope 表、`X-PPT-Account-ID`（仅限开发模式） | 独立 Agent 仅凭文档完成鉴权首次 invoke |
| B2 | 新增**限流**章节：120 req/60s、429/Retry-After/X-RateLimit-*、幂等请求也应计入限流的提示 | 文档评审 |
| B3 | 新增**错误码全集表**：每个 code × HTTP 状态 × 触发场景 × 建议恢复动作；同步完成 P1-4（`_raise_http_error` → AgentAPIError + `http_exception_handler` 信封补齐） | 表中每个码在代码中有出处（可写一致性测试） |
| B4 | 八步工作流食谱 v1（P6-6 提前）：从 source.set 到 video 产物的最小调用序列 + checkpoint 审批点 + operation 轮询/中断恢复样例 + SSE 断线轮询回退 | 食谱步骤在 mock 全流程测试（test_full_workflow_mocked）中有对应场景映射 |
| B5 | MCP 指纹语义对齐（P2-3）：命名工具缓存 describe 时指纹，变更后返回 CONTRACT_CHANGED 引导重新发现；或改文档。推荐前者 | MCP 测试覆盖"服务端变更后命名工具报 CONTRACT_CHANGED" |

### 第三阶段：防漂移加固与性能卫生（迭代进行，2-3 人日）

| 项 | 内容 | 验收标准 |
|---|---|---|
| C1 | `features.py` 扫描加固（G2/G3）：递归扫描（排除 .venv/checks 等）+ 识别 `FastAPI()` 实例装饰器 + 支持跨文件 router import（对 import 的 router 名记录别名） | 人为构造子目录路由的临时副本验证能被检出（在 /tmp 演练，不入库） |
| C2 | 版本递增门禁（G4）：CI 中对比基线——`git diff` 显示 `contract_hash` 变化而 `AGENT_API_VERSION` 未变 → 失败（additive 变更可放行 minor 递增） | 演练提交触发失败 |
| C3 | 行为变更同步约定（G1）：PR 模板增加"本次是否改动以下行为敏感服务（生成/删除/确认/CAS 语义）→ 是则必须递增对应能力 `behavior_version` 并再生成快照"；为 `behavior_version` 与快照一致性补一条校验（快照已含 behavior_version，`--check` 已比对，缺的是"改了就递增"的提醒机制） | PR 模板合入；交接文档同步 |
| C4 | 上传客户端流式化（P2-2）：multipart 逐块构造 | 1GB 文件上传内存占用 < 100MB 的测试 |
| C5 | 性能卫生：`get_contract_hash` 缓存（P2-6）、令牌 last_used_at 节流（P2-7）、限流键回收与 429 信封对齐（P2-4）、HANDLERS 去重 + 防重复测试（P2-1） | quick 检查通过，含新增单测 |
| C6 | 发布门禁常态化（交接文档 5.6 的既有计划）：`check_agent_coverage.py --require-complete` 接入 full 级（partial 清零后生效）；确认 GitHub 分支保护 require CI | CI 配置评审 |

### 里程碑与依赖

- 第一阶段不依赖任何外部条件，可立即开工；A2 的 scope 方案（b 先行）需要产品确认
  是否近期要细化权限模型。
- 第二阶段 B3 依赖第一阶段 A3 定稿错误码语义；B4 建议结合 5.1 真实供应商演练的
  操作记录一起写（一次产出两份证据）。
- 第三阶段 C2 需要确定基线对比方式（CI 中 `git fetch origin main~1` 或用上一次
  成功构建的快照 artifact）。
- 既有交接文档中的 5.1（真实供应商演练）→ 5.4（真实资产场景）→ P6（partial 清零）
  路线与本计划第三阶段并行不冲突。

---

## 七、附录：本次审查的验证命令

```bash
# 基线回归（750 项）
cd /d/software/PPT_presentation_video && .venv/Scripts/python.exe -m pytest checks/agent/ -q

# 结构同步门禁
.venv/Scripts/python.exe scripts/check_agent_coverage.py
.venv/Scripts/python.exe scripts/generate_agent_contracts.py --check

# dispatch 绑定干跑（本次审查使用的只读校验思路）
# 对每个可调用能力：input_model(cap) 字段 × handler 签名 参数逐一匹配，0 问题
```

> 审查局限说明：本报告基于静态审查 + 现有测试套件 + 机械化干跑，未执行真实付费
> 供应商调用（受 AGENTS.md 约束）。`partial` 状态的 86 项能力的真实上游行为
> （LLM/生图/TTS/数字人）不在本次验证范围内，与交接文档 5.1 的真实演练计划互补。

---

## 八、实施状态（2026-10-24 同日优化落地）

| 计划项 | 状态 | 提交 |
|---|---|---|
| A1 `_safe_scopes` fail-closed | ✅ 已实施 | `fix(agent): 安全收口…` |
| A2 scope 模型（`account:manage` 强制 + 收缩声明，方案 b） | ✅ 已实施 | 同上 |
| A3 幂等可恢复性（failed_retryable + 换键指引） | ✅ 已实施（③ 悬挂键自动接管经评估**放弃**：长任务如视频渲染可能在客户端超时后仍在运行，接管会造成双重执行；以 `OPERATION_OUTCOME_UNKNOWN` + 换新键指引替代，已在指南中成文） | `fix(agent): 幂等可恢复性…` |
| A4 部署守卫 | ✅ 已实施（采用硬拒绝 + `PPT_AGENT_ALLOW_INSECURE_AGENT_API=1` 豁免，与 Web 守卫同姿态） | 同 A1 |
| B1 认证与账号章节 | ✅ 已实施 | `docs(agent): 对接规范补全…` |
| B2 限流章节 | ✅ 已实施 | 同上 |
| B3 错误码全集表 + 类型化错误码 + 边界信封统一 | ✅ 已实施（含指南第 31 行自认的 RequestValidationError 边界欠账） | `fix(agent): 错误码收口…` + docs |
| B4 八步工作流食谱 v1 | ✅ 已实施（`docs/agent/workflow-recipe.md`） | 同 docs |
| B5 MCP 命名工具指纹绑定 | ✅ 已实施（采用绑定展示时指纹方案） | `fix(mcp): 命名工具绑定…` |
| C1 覆盖扫描加固 | ✅ 已实施（**当场证实 G3 是真实缺口**：digital_human_service.py 的 10 条 Worker 路由历史上一致逃逸；确认属独立 Worker 微服务后显式排除） | `feat(agent): 防漂移加固…` |
| C2 版本递增门禁 | ✅ 已实施（`check_contract_version_discipline.py` 接入 quick；局限：主要在提交前本地生效） | 同上 |
| C3 PR 行为敏感面清单 | ✅ 已实施（增强既有 `pull_request_template.md`） | 同上 |
| C4 上传流式化 | ✅ 已实施（http.client chunked 迭代器，真 socket 验收通过） | `fix(agent): 卫生与性能收口…` |
| C5 性能卫生四项 | ✅ 已实施（HANDLERS 去重时**又发现并修复一个真实的静默错路由隐患**：`settings.config.import` 双注册指向不同业务模块） | 同上 |
| C6 `--require-complete` 接入 full 级 | ⏸ 未实施（86 项 partial 未清零前接入会让 CI 常红；维持原计划——partial 清零后接入） | — |
| 附带产出 | AGENTS.md 同步策略表新增 3 行；接入指南 API 版本更新至 2.8.0；契约快照随 `required_scopes` 变化全量再生成 | 各提交内 |

验证基线：Agent 专项回归 **771 项全部通过**（改造前 750 + 新增 21）；quick 门禁
（覆盖登记 / 快照一致 / 版本纪律 / ruff）全部通过。
