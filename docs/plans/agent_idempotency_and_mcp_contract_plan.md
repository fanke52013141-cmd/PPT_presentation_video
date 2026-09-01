# Agent 接口层强化方案：幂等持久化 + MCP 契约协商

日期：2026-09-01
状态：待评审
关联：`docs/agent/AGENT_INTEGRATION_HANDOFF.md` 已知限制第 1、4 条

---

## 0. 现状诊断（根因）

### 0.1 幂等与乐观锁

| 层 | 现状 | 证据 |
| --- | --- | --- |
| 契约模型 | 字段已定义，从未被执行 | `agent_contract/models.py:44/85/100/118/144/161/167/184/195` |
| API 路由 | 完全忽略这两个字段 | `agent_api/routes.py` 各 handler 无任何引用 |
| 数据库 | `Project` 无 `revision` 列，无幂等表 | `database.py:34-56`，migrations 仅到 0005 |
| AgentClient | 7 个方法不透传 `idempotency_key`，2 个不透传 `expected_revision` | `agent_client/client.py:112-220` |
| MCP `_dispatch` | 同样不透传 | `mcp_server/tools.py:62-119` |

后果：Agent 对创建项目、TTS、视频渲染做网络重试时（超时后重发是 Agent 的标准行为），**同一副作用会被执行多次**——重复建项目、重复提交渲染作业、重复扣 API 配额。`expected_revision` 缺失意味着并发修改丢失更新无法被检测。

### 0.2 MCP 契约协商

`mcp_server/server.py:112` 的 `_handle_initialize` 返回 `get_contract_hash()`——这是 **MCP 进程自己 import 的 `agent_contract` 算出的 hash**，不是运行中 API 服务的 hash。AgentClient 有现成的 `get_meta()`（client.py:256）但初始化时从未调用。

后果：MCP stdio 进程常驻（Agent 会话期间不重启），而 API 服务升级重启后，两边 capability registry 可能已不同版本。MCP 把旧参数 schema 报给 Agent、或用旧参数调新 API，错误只在具体调用时以含混的 400 暴露，无法在握手期拦截。

---

## 1. 方案一：幂等持久化

### 1.1 目标与非目标

**目标**
1. 同一 `(scope, project_id, idempotency_key)` + 相同请求内容 → 重放首次成功响应，不重复执行副作用；
2. 同一 key + 不同请求内容 → `409 CONFLICT`；
3. `expected_revision` 乐观锁：版本不匹配 → `409 CONFLICT` 并返回当前 revision；
4. 进程崩溃后遗留的 in-flight 记录可被识别与恢复。

**非目标**
- 不做跨进程分布式锁（单机 SQLite，`BEGIN IMMEDIATE` 已足够串行化写入）；
- 不覆盖 Web UI 路由（`/api/projects/**` 不变，仅 Agent API 层生效）；
- 不为只读 GET 端点做幂等（天然幂等）。

### 1.2 数据库变更

新增 `migrations/0006_agent_idempotency.sql`（连续编号、一次性应用、checksum 保护，符合 `database_migrations.py` 既有机制）：

```sql
ALTER TABLE projects ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS agent_idempotency_records (
    scope VARCHAR NOT NULL,               -- capability id，如 "project.create"
    project_id VARCHAR NOT NULL DEFAULT '',
    idempotency_key VARCHAR NOT NULL,     -- 调用方提供，1..200 字符
    request_fingerprint VARCHAR(64) NOT NULL,  -- sha256(规范化请求体)
    status VARCHAR NOT NULL DEFAULT 'in_progress',  -- in_progress/succeeded/failed
    response_json TEXT,                   -- 成功时存完整响应（含 operation_id/job_id）
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (scope, project_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_agent_idempotency_records_project
    ON agent_idempotency_records (project_id, created_at);
```

- ORM：`database.py` 增加 `Project.revision` 列与 `AgentIdempotencyRecord` 模型。
- `revision` 从 0 起，每次 Agent 可见变更 +1。**Web UI 路径不递增**（避免 UI 用户被动撞锁），revision 只作为 Agent 侧的版本令牌。
- 0006 是全新迁移，无需在 `_known_migration_already_present` 中加采纳分支（1-5 的分支是给 ledger 出现前的存量库用的）。
- 迁移测试沿用 `checks/test_database_migrations.py` 模式：断言 0006 可应用、幂等重跑安全、checksum 记录正确。

### 1.3 服务模块：`agent_idempotency_service.py`

按 Runtime Bridge Policy 新建独立模块，**只收冻结依赖记录**：

```python
@dataclass(frozen=True)
class AgentIdempotencyDependencies:
    session_factory: Callable[[], Session]

RETENTION_DAYS = 7          # succeeded/failed 记录保留期
STALE_IN_PROGRESS_HOURS = 1 # 超过此时长的 in_progress 视为孤儿
```

对外四个原语：

| 方法 | 行为 | 提交语义 |
| --- | --- | --- |
| `claim(scope, project_id, key, fingerprint)` | `BEGIN IMMEDIATE` + INSERT；主键冲突时读已有行按状态判定 | **自持 session，立即 commit**（同 `VideoJobStore` 模式；claim 必须先于业务执行落盘，否则长操作期间 claim 不生效） |
| `finalize(key, succeeded, response)` | 写终态 + 响应体 | 自持 session，立即 commit |
| `check_revision(db, project, expected)` | 乐观锁校验 | 不提交（走请求作用域 db，路由统一 commit，符合"API callers own one database commit"） |
| `bump_revision(db, project)` | `revision += 1` | 不提交，同上 |

`claim` 的判定矩阵：

| 已有记录状态 | fingerprint 相同 | fingerprint 不同 |
| --- | --- | --- |
| `succeeded` | 重放：返回存储的响应 + 响应头 `X-Agent-Idempotency-Replay: true` | 409 key 复用 |
| `in_progress` 且未超时 | 409 "operation in progress"（Agent 应转去轮询状态而非重试） | 409 key 复用 |
| `in_progress` 且超时（孤儿） | 视为失败，更新为 failed 后重新 claim 并执行 | 409 key 复用 |
| `failed` | 重新 claim 并执行（失败可安全重试是标准幂等语义） | 409 key 复用 |

request_fingerprint 计算：`payload.model_dump(mode="json")` 剔除 `idempotency_key` 后做 `json.dumps(sort_keys=True, ensure_ascii=False)` 的 sha256。用规范化后的有效值（而非 `model_fields_set`），保证「显式传默认值」与「省略」得到同一指纹。

保留策略：`claim` 时顺手 `DELETE WHERE created_at < now - RETENTION_DAYS AND scope = ?`——机会式清理，**不引入后台线程**（符合仓库无轮询器哲学）。

### 1.4 路由接入（7 个操作）

统一包装模式（以 TTS 为例）：

```python
@router.post("/projects/{project_id}/tts")
def agent_tts_synthesize(project_id, payload, db=Depends(get_db)):
    _resolve_project(db, project_id)
    record = idempotency.claim("tts.synthesize", project_id,
                               payload.idempotency_key, fingerprint(payload))
    if record.replay_response is not None:
        return JSONResponse(record.replay_response,
                            headers={"X-Agent-Idempotency-Replay": "true"})
    try:
        result = services.synthesize_audio()
        response = TtsSynthesizeResult(...).model_dump()
        idempotency.finalize(record.key, True, response)
        return response
    except Exception as e:
        idempotency.finalize(record.key, False, None)
        raise OperationFailedError(...)
```

| Capability | scope | 幂等保护的实际对象 | 重放价值 |
| --- | --- | --- | --- |
| `project.create` | `project.create`（project_id 为空串） | 建项目 | 拿回同一 project_id |
| `source.set` | `source.set` | 文章导入/主题生成 | 不重复触发 LLM |
| `pipeline.run` / `pipeline.resume` | 各自 scope | 一键流程启动 | 拿回同一 run_id |
| `images.regenerate` | `images.regenerate` | 图片重绘 | 不重复扣图片配额 |
| `tts.synthesize` | `tts.synthesize` | 作业提交 | 拿回同一 job_id，可继续轮询 |
| `videos.render` | `videos.render` | 渲染作业提交 | 拿回同一 job_id |

关键点：TTS/视频渲染的 in_progress 窗口是**路由执行时长**（作业提交即返回），不是作业本身时长——渲染几十分钟不影响幂等窗口，Agent 拿到 job_id 后走 `pipeline.status` 轮询。图片重绘是同步执行（约 1-2 分钟），1 小时的孤儿阈值覆盖足够。

### 1.5 乐观锁：`expected_revision`（2 个操作）

- `project.update`（routes.py:222）：`payload.expected_revision is not None and != project.revision` → `ConflictError`，details 带 `current_revision`；成功后 `revision += 1`。
- `narration.update`（routes.py:571）：同一把 `project.revision` 锁（旁白存于 run 目录，项目行是天然版本载体）。
- `ProjectSummary` 增加 `revision` 字段——调用方要先读后写才能用乐观锁，目前响应里无版本可读。
- 契约版本随之 bump（见 1.6）。

### 1.6 契约与各层同步（CI 一致性测试强制）

单一事实源规则要求五处同步，漏一处会被既有契约测试挡下：

1. `agent_contract/models.py`：字段加约束（`idempotency_key: Field(None, min_length=1, max_length=200)`），描述补 409/重放语义；`ProjectSummary` 加 `revision`。
2. `agent_contract/capabilities.py`：受影响 capability 版本 bump `1.0 → 1.1`（project.create/get/update、source.set、pipeline.run/resume、images.regenerate、tts.synthesize、videos.render、narration.update）；`AGENT_API_VERSION` 1.0.0 → 1.1.0（向后兼容的 minor bump）。
3. `agent_api/routes.py`：接入 claim/finalize/revision。
4. `agent_client/client.py`：对应方法增加可选参数并放入 body。
5. `mcp_server/tools.py` `_dispatch`：透传新参数；`cli/pptctl.py`：相关命令加 `--idempotency-key` / `--expected-revision` 旗标。
6. `python scripts/generate_agent_contracts.py` 重新生成 `docs/agent/capability-matrix.md`。

### 1.7 测试计划

| 文件 | 覆盖 |
| --- | --- |
| `checks/agent/test_idempotency_service.py`（新增） | 判定矩阵全分支、指纹规范化（显式默认 vs 省略）、孤儿恢复、机会式清理、自持 session 提交语义 |
| `checks/agent/test_agent_e2e.py`（扩展） | 同 key 同体 → 同 project_id + 重放头；同 key 异体 → 409；失败后同 key 重试 → 重新执行；in_progress 期间重试 → 409 |
| `checks/agent/test_models_validation.py`（扩展） | key 长度边界、revision 非负 |
| `checks/test_database_migrations.py`（扩展） | 0006 应用/幂等/checksum |
| 既有 sync 测试 | 自动强制 MCP/CLI/client 与注册表同步 |

### 1.8 风险与边界

- **崩溃窗口**：claim 落盘后、finalize 前进程死亡 → 记录停在 in_progress，1 小时后被孤儿逻辑接管。可接受（比重复执行安全）。
- **SQLite 写串行**：claim 用 `BEGIN IMMEDIATE`，与渲染作业写入偶发竞争时短暂等待，无死锁路径（单语句短事务）。
- **模块尺寸**：新模块预计 < 300 行，低于 `test_architecture_size_boundaries.py` 阈值；不得把幂等逻辑写进 `server.py` 或路由层。
- **不做** Web UI 侧 revision 递增，避免 UI 用户撞乐观锁。

---

## 2. 方案二：MCP contract_hash 兼容性协商

### 2.1 协商协议

`initialize` 握手时新增协商步骤（`mcp_server/server.py::_handle_initialize`）：

```text
MCP Client                MCPServer                PPT Studio API
    │--- initialize ---------->│                        │
    │                          │--- GET /api/agent/v1/meta -->│   （短超时 5s）
    │                          │<-- contract_hash, agent_api_version --│
    │                          │ 比较：本地 get_contract_hash() vs API hash
    │                          │       semver(API) vs semver(local)
    │<-- result 或 error ------│
```

比较规则：

| 检查 | 不兼容判定 | 处置 |
| --- | --- | --- |
| `contract_hash` 不等 | 契约实质变更（参数/路径/能力增删） | **JSON-RPC error**（code -32000，message 含双 hash 与修复指引） |
| API `agent_api_version` major > 本地 major | 破坏性升级 | 同上 error |
| minor/patch 差异 | 向后兼容 | 正常返回，`serverInfo` 带告警标记 |
| API 不可达（连接失败/超时/401） | 无法协商 | 同上 error，message 指明检查 `PPT_AGENT_API_URL` 与服务状态 |

**严格模式为默认**（对应 handoff「强制兼容性协商」语义）：MCP 客户端收到 error 即视为初始化失败，不会继续 `tools/list`/`tools/call`。开发场景可用 `PPT_MCP_CONTRACT_CHECK=0` 显式关闭（此时 `serverInfo.contractMatch=false` + `mismatchDetail`，且 `tools/call` 拒绝执行并返回明确错误——不会静默降级到拿旧 schema 调新 API）。

协商结果缓存在 `self._contract_state`；`tools/call` 前检查：协商失败或被关闭且不匹配 → 返回 `isError: true`（拦截晚于 initialize 的版本漂移场景可后续按需加定期复检，本期不做）。

initialize 响应扩展（MCP 允许 `serverInfo` 自由扩展，协议兼容）：

```json
{
  "serverInfo": {
    "name": "ppt-studio-mcp",
    "version": "1.0.0",
    "agentApiVersion": "1.0.0",
    "contractHash": "<本地>",
    "apiContractHash": "<API>",
    "apiAgentApiVersion": "<API>",
    "contractMatch": true
  }
}
```

### 2.2 版本兼容辅助

`agent_contract/versions.py`（其 docstring 已声明拥有"version and compatibility management"）新增：

```python
def is_version_compatible(local: str, remote: str) -> tuple[bool, str]:
    """major 不同 → 不兼容；minor/patch 差异 → 兼容并返回告警文本。"""
```

### 2.3 涉及文件

| 文件 | 变更 |
| --- | --- |
| `agent_contract/versions.py` | + `is_version_compatible` |
| `mcp_server/server.py` | `_handle_initialize` 走协商；`_contract_state` 缓存；`tools/call` 守卫；`PPT_MCP_CONTRACT_CHECK` 环境开关 |
| `agent_client/client.py` | `get_meta()` 已存在；为其加独立短超时参数（避免 30s 默认拖住握手） |
| `checks/agent/test_mcp_protocol.py` | mock `AgentClient.get_meta`：匹配→通过；hash 不等→error；major 差→error；minor 差→通过带告警；不可达→error；关闭开关→降级行为 + call 守卫 |
| `docs/agent/capability-matrix.md` | 生成器重跑（无 schema 变化，仅文档补充协商说明） |

### 2.4 边界情况

- **API 启动顺序**：MCP 先于 API 启动 → initialize 报「API 不可达」而非挂起或静默通过；Agent 侧重试 initialize 即可（符合 fail-fast 优于静默错误的原则）。
- **401（app token 不匹配）**：与不可达区分报错，指明 `PPT_APP_TOKEN`。
- **同机同代码**：hash 确定性已有测试保障（`test_capability_registry.py:142`），正常场景零影响。

---

## 3. 实施顺序与工作量

| 项 | 工作量 | 依赖 | 发布门禁意义 |
| --- | --- | --- | --- |
| 方案二（MCP 契约协商） | 0.5–1 天 | 无 | 解锁 handoff「下一项发布前工作」 |
| 方案一（幂等持久化） | 2–3 天 | 无（与方案二正交） | 解锁创建/TTS/视频自动重试安全性 |

建议顺序：**先方案二**（小、独立、立刻消除发布阻断项），再方案一（涉及迁移与五层同步，需要完整回归窗口）。

两项均需通过的质量门禁（AGENTS.md / handoff）：

```powershell
python scripts/generate_agent_contracts.py --check
python -m pytest checks/agent -q
python scripts/run_checks.py --level quick
```

完成后更新 `docs/agent/AGENT_INTEGRATION_HANDOFF.md` 已知限制第 1、4 条状态。
