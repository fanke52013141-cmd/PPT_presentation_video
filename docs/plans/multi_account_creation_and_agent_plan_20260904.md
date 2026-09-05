# 多账号创作与 Agent 对接完整方案

日期：2026-09-04

## 1. 方案结论

采用“创作账号上下文 + 版本化创作配置 + 项目配置快照”的组合方案：

1. 创作账号是用户切换的工作空间，账号拥有自己的项目、模型连接、凭据和默认创作配置。
2. 新建项目时读取当前账号的默认配置，并将解析后的完整配置写入项目目录快照。
3. 项目开始创作后不再依赖当前账号或可变默认配置，避免切换账号后改变进行中的任务。
4. Agent、MCP、CLI 不共享进程级“当前账号”；每个 Agent Token 固定绑定一个账号，切换账号通过切换 Token/profile 完成。
5. 旧项目和旧 JSON 记录统一归入 `default` 账号，保持兼容。

这个方案保留了原有“配置包/连接版本化”的优点，又提供了比每次手动绑定更顺手的账号切换体验。账号切换负责选择工作空间，配置绑定负责冻结项目运行输入，两者职责不混淆。

## 2. 已完成的代码改造

### 2.1 数据层

- 新增 `migrations/0012_creative_accounts.sql`：创建 `accounts`、`agent_tokens`，并为 `projects` 增加 `account_id`。
- 旧项目自动回填到 `default`。
- `Account` 保存状态和默认创作配置包/版本。
- Agent Token 只保存 SHA-256 哈希、账号、名称、权限和使用时间，不保存明文 Token。

### 2.2 请求上下文和 Web 切换

- 新增 `account_context.py`，使用 `ContextVar` 保存请求级账号上下文，避免并发请求互相污染。
- Web 端按以下顺序选择账号：`X-PPT-Account-ID`、HttpOnly Cookie、`default`。
- 新增 `account_routes.py`：账号列表、当前账号、创建账号、选择账号、设置默认配置、创建 Agent Token。
- 首页新增“创作账号”下拉框和创建账号入口；切换账号后重新加载项目列表。
- 账号默认配置在设置时校验配置包确实属于目标账号，防止未来创建项目时才失败。

### 2.3 创作运行链路

- `project_service.py` 创建项目时使用当前账号的默认配置，并写入不可变 `planning/project_config.json` 快照。
- 项目、配置包、模型连接、凭据均按账号过滤。
- 一键编排、TTS、视频渲染、PPTX 导出等后台任务显式携带账号 ID，worker 恢复上下文后再读写数据库。
- Agent 幂等键在非 `default` 账号下增加账号作用域，避免不同账号使用相同 key 互相重放。
- 对已经有项目快照的任务，预检查优先使用快照，不再因其他账号的全局密钥缺失而误阻断。

### 2.4 Agent / MCP / CLI 同步

- Agent API 认证支持账号 Token；Token 失效或账号停用时拒绝请求。
- `GET /api/agent/v1/identity` 返回 `account_id`、账号名、scopes 和 authenticated 状态，用于每次连接自检。
- `project.create` 已贯通 `mask_enabled`、`config_package_id`、`config_package_version`、`config_overrides`。
- Agent 项目查询、SSE、产物查询、diagnostics 统计都按账号隔离。
- AgentClient 新增 `get_identity()` 并透传项目配置参数。
- MCP 新增 `identity.get`，并透传项目配置参数。
- CLI 新增 `pptctl identity`，项目创建增加配置包、版本、覆盖项和 Mask 参数。
- `agent_contract/capabilities.py`、请求/响应模型、API 版本和能力矩阵保持同步；当前 API 版本为 `1.4.0`。

## 3. 日常使用流程

### Web

1. 打开 `http://127.0.0.1:8000`。
2. 点击顶部“创作账号”右侧的 `＋` 创建账号。
3. 切换到新账号。
4. 在该账号下创建或导入创作配置，并将其设为默认配置。
5. 新建项目；项目会自动采用该账号默认配置并生成项目快照。
6. 切换到另一个账号后，只显示另一个账号的项目和配置。

### Agent / MCP / CLI

一个 Token 只绑定一个账号，建议为每个账号保存一个独立 profile。连接后先调用 identity：

```powershell
$env:PPT_AGENT_API_KEY = '<该账号 Token>'
python -m cli.pptctl identity
python -m cli.pptctl project create --name "账号项目"
```

MCP stdio 服务使用同一组 `PPT_AGENT_API_URL`、`PPT_AGENT_API_KEY` 环境变量。切换账号时切换对应 profile 的 Token，然后重新启动对应 Agent/MCP 进程；不要在正在运行的任务中修改全局环境变量。

## 4. 验收测试矩阵

| 范围 | 验证内容 | 结果 |
| --- | --- | --- |
| 全仓回归 | Python 全部测试 | 821 passed，1 warning |
| Agent | API、认证、契约、MCP、CLI、E2E | 417 passed，1 warning |
| 账号重点 | 项目、配置包、模型连接、凭据双账号隔离 | 通过 |
| 数据库 | 迁移和迁移校验 | 13 项相关检查通过 |
| 前端 | 可见流程、模块质量、账号选择器存在 | 通过 |
| Remotion | TypeScript `--noEmit` | 通过 |
| Mask/音频 | Mask 完整性、流水线隔离、视觉失效、音频确认和尾部填充 | 全部通过 |
| Agent 契约 | 能力矩阵生成检查、diff 空白检查 | 通过 |
| 真实 HTTP | 两个账号分别创建项目、identity、项目列表、跨账号 GET 404、diagnostics 计数、CLI identity | 通过 |

真实 HTTP 双账号测试使用的是临时账号和项目，测试结束后已删除；当前数据库只保留原有 `default` 账号，未保留测试 Token 或项目。

## 5. 仍需用户验收或生产化的项目

以下不是当前本机多账号基础链路的阻塞项，但在正式对外部署前应继续完成：

1. 账号管理接口目前属于本机可信管理面，尚未接入管理员会话/RBAC；公网部署前必须增加管理员权限边界。
2. 当前凭据默认存储适配器仍是本地 JSON；正式多用户环境应替换为 Windows Credential Manager、系统 Keyring 或 Secret Manager。
3. 需要补充“复制配置到另一个账号”的显式 API/UI；复制时默认不复制凭据。
4. `settings` 中的历史全局设置仍保留兼容回退；新项目应逐步迁移到账号级模型连接和配置包。
5. 需要使用两套真实且不同的文本、生图、MiniMax TTS 凭据完成小规模供应商 E2E；本地自动化测试不伪造或提交密钥。

## 6. 验收建议

建议用户按以下顺序验收：

1. Web 创建两个账号 A/B，分别创建项目，切换账号确认列表隔离。
2. 给 A、B 分别设置不同默认配置，分别新建项目，检查项目详情中的配置来源不同。
3. 修改 A 的默认配置，再打开旧项目，确认旧项目快照不变。
4. 分别为 A、B 创建 Agent Token，运行 `pptctl identity`，确认身份不同。
5. 使用 A Token 创建项目后，用 B Token 查询该项目，必须返回 404。
6. 在 MCP 初始化后调用 `identity.get` 和 `project.create`，确认工具与 API 返回账号一致。
7. 在有真实供应商凭据的环境，分别跑一套小项目生成并检查最终 MP4/PPTX、音频和产物列表。
