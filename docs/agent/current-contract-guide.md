# 当前 Agent 契约接入

本页描述已实现的 API 2.1.0 接入方式，URL 命名空间仍为 `/api/agent/v1`。旧 Agent 规范无需兼容。功能尚未全部开放，具体缺口见 `feature-coverage.md`。

## 发现与调用

1. 读取 `GET /api/agent/v1/meta`，验证 `bootstrap_version` 为 `1`。
2. 使用 `GET /api/agent/v1/capabilities?q=...&domain=...&offset=0&limit=50` 搜索摘要；继续读取 next_offset，直到为 null。
3. 使用 `GET /api/agent/v1/capabilities/{id}` 读取完整输入/输出 Schema、权限、响应类型和 contract_revision。
4. 根据该 Schema 准备参数，用同一个 contract_revision 调用 `POST /api/agent/v1/invoke`。

```json
{
  "capability_id": "project.create",
  "expected_contract_revision": "从 describe 返回值读取",
  "arguments": {
    "name": "Agent 创建的项目",
    "idempotency_key": "为本次逻辑创建操作生成并保存的唯一键"
  }
}
```

通用调用只支持响应类型为 json 的能力。二进制文件及事件流按详情里的 method/path 通过专用资源传输获取；这些能力返回 invocable=false，不能通过 invoke 下载。

成功结果与领域接口一致，不增加另一层结果包装。错误返回 error.code、message、details、retryable、repair_actions、trace_id。认证和外层请求校验的错误结构仍可能由现有中间件/框架返回，统一这些边界错误是后续工作。

同步项目创建直接返回 project，不再生成无法查询的临时 operation_id。后台任务提交才返回可查询的 operation_id。

CONTRACT_CHANGED 返回 409，details.executed=false，表示未调用业务入口。重新 describe、理解变化并重新准备参数后才能再调用。不要把旧参数配上新指纹直接重试。

网络断连可能意味着操作已经执行。仅对声明支持幂等的操作保留并复用原 idempotency_key，不创建新键盲目重试。发现详情的 idempotency 字段声明支持范围；仍未完成所有领域写入的幂等保证。

支持幂等的写入将键绑定账号、能力、目标资源、规范化参数和当前契约。完成后 7 天内可重放已存响应；过期响应被清理，键墓碑保留并返回 IDEMPOTENCY_EXPIRED。超时的 in_progress、失败记录或损坏的响应不能证明业务没有执行，返回 OPERATION_OUTCOME_UNKNOWN，禁止自动重领。执行中的重复请求返回 OPERATION_IN_PROGRESS；相同键配不同参数/资源/契约返回 IDEMPOTENCY_CONFLICT。

项目元数据及旁白编辑在产生业务写入前，用数据库 compare-and-swap 抢占项目 revision。同一版本并发编辑只有一个成功，冲突返回 REVISION_CONFLICT；重复保存相同内容不推进版本。其他领域和 Web 编辑尚未统一推进该版本，不能据此宣称跨全系统的并发保护已经完成。

## 精确任务与恢复

TTS 通过现有异步服务提交，返回 `job:<job_id>`；视频返回持久化渲染任务对应的 `job:<task_id>`。一键生产返回 `pipeline:<run_id>`。这些 ID 可原样传给以下能力：

| 能力 | 用途 |
|---|---|
| operation.get | 查询指定项目下的精确任务，未知 ID 返回 404，绝不回退到 latest |
| operation.list | 分页汇总持久任务和一键生产历史 |
| operation.cancel | 对指定 TTS/视频任务请求安全停止；其他生产者明确返回 CANCELLATION_UNSUPPORTED |

查询与列表直接读取源任务存储，不维护第二份任务终态。`local_jobs` 的恢复仍由各生产者负责：例如 TTS 将遗留 running 标 interrupted、queued 重新排队。新一键运行的完整历史保存于 `planning/one_click_runs/<run_id>.json`，当前状态文件作为工作区镜像；进程失去 worker 的运行会在精确查询中报告 interrupted。已存在且从未保存过历史的 ID 不会凭空重建。

accepted=true 仅表示接受停止请求。运行中的上游请求或渲染阶段会到安全边界才停止；queued TTS 若成功从队列取消，可直接读到 cancelled。读取 cancellation_supported 与 cancellation_requested 判断当前可控性；任务结束后重复取消返回 accepted=false 及真实终态。

状态包含 queued、running、waiting_for_review、waiting_for_user、succeeded、failed、cancelled、interrupted、unknown。unknown 保留 raw_status，客户端等待工具立即要求检查，不无限轮询。结果不会直接泄露内部任务 payload，只提供状态、错误、时间与产物引用。

```powershell
.\.venv\Scripts\python.exe -m cli.pptctl operation list --project <project_id>
.\.venv\Scripts\python.exe -m cli.pptctl operation get --project <project_id> --operation-id job:<job_id>
.\.venv\Scripts\python.exe -m cli.pptctl operation wait --project <project_id> --operation-id job:<job_id> --timeout 300
.\.venv\Scripts\python.exe -m cli.pptctl operation cancel --project <project_id> --operation-id job:<job_id> --contract-revision <operation.cancel的当前指纹>
```

等待超时只结束本地等待，不会取消服务端任务。一键生产整体暂停、标注/PPTX 等生产者的统一取消、所有同步生成的持久任务化属于后续范围。

## MCP

```powershell
.\.venv\Scripts\python.exe -m mcp_server
```

连接地址由 PPT_AGENT_API_URL 指定，认证优先使用 PPT_AGENT_API_KEY。固定工具为：

- ppt_capabilities_search：搜索运行服务的当前目录。
- ppt_capability_describe：读取当前能力详情。
- ppt_capability_invoke：传入 capability_id、expected_contract_revision 和 arguments。

业务能力更新后，固定工具仍可使用。初始化只验证发现协议，业务版本号变化不要求更新 MCP 代码。常用命名工具使用本地展示的 Schema 对应的指纹，服务端变化会返回明确错误；此时使用固定工具重新发现。

## CLI

```powershell
.\.venv\Scripts\python.exe -m cli.pptctl capability list --domain project
.\.venv\Scripts\python.exe -m cli.pptctl capability show project.create
.\.venv\Scripts\python.exe -m cli.pptctl invoke project.create --contract-revision <describe返回的指纹> --arguments-file create-project.json
```

JSON 参数文件作为 UTF-8 保存。密钥通过环境变量设置。通用 CLI 调用要求明确传入刚读取的指纹；不自动更新过期指纹或自动重试写入。

## 开发与检查

业务入口覆盖决策在 `config/agent_features.json`。新入口或路由变化未登记时检查失败。pending/partial 是待实现范围，不表示已开放。

```powershell
.\.venv\Scripts\python.exe scripts/check_agent_coverage.py
.\.venv\Scripts\python.exe scripts/generate_agent_contracts.py
.\.venv\Scripts\python.exe scripts/generate_agent_contracts.py --check
.\.venv\Scripts\python.exe -m pytest checks/agent -q
```

最终宣布全功能开放前，必须通过 `scripts/check_agent_coverage.py --require-complete`。当前该严格门禁预期失败，原因是分域能力尚待补齐。

当前每项 JSON 能力必须有显式 adapter，adapter 由服务端代码登记，客户端无需增加分支。不能把任意 Python 函数名或 URL 当作外部调用目标。
