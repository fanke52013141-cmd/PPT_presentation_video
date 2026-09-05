# 多账号创作与 Agent 对接实施交接

日期：2026-09-04

## 本次实现

本次在既有“模型连接 → 版本化创作配置包 → 项目配置快照”基础上增加了创作账号层：

- `accounts` 表保存账号、状态和默认创作配置包版本；
- `projects.account_id` 保存项目归属，旧项目迁移到 `default` 账号；
- 浏览器通过账号选择 Cookie 或 `X-PPT-Account-ID` 建立请求级账号上下文；
- Agent Token 使用哈希保存，并固定绑定账号与 scopes；
- Agent 请求、MCP 请求、CLI 请求和后台 SSE 均不使用进程级可变“当前账号”；
- 账号默认配置在创建项目时解析并写入不可变项目快照，后续切换账号或修改默认配置不会改写已有项目；
- 模型连接、创作配置包和凭据的 JSON 记录按账号上下文过滤，旧记录默认属于 `default`；
- Agent 新增 `identity.get`，CLI 新增 `pptctl identity`，用于确认当前账号；
- `project.create` 的配置包、版本、覆盖项和 `mask_enabled` 已贯通 AgentClient、MCP 和 CLI；
- Agent 幂等键在非默认账号下加入账号前缀，避免两个账号使用相同幂等键互相命中；
- 一键预检查对已有项目快照优先，不再因为其他账号的全局密钥缺失而拒绝已绑定的文本、图片和 TTS 配置。
- Agent diagnostics 的项目数和产物数也按当前账号统计，避免跨账号泄露汇总信息；项目创建后的回查同样带账号过滤。

## 现阶段使用方式

先调用 `POST /api/accounts` 创建创作账号，再调用 `PUT /api/accounts/{account_id}/default-config` 设置默认包。网页调用 `POST /api/accounts/{account_id}/select` 选择账号；Agent 则使用 `POST /api/accounts/{account_id}/agent-tokens` 创建 Token，并把 Token 配置到一个固定的 Agent/MCP/CLI profile。

一个 Agent profile 只对应一个创作账号。需要切换账号时切换 profile，不在正在执行的任务中修改全局环境变量。Agent 可先调用 `GET /api/agent/v1/identity` 检查身份。

## 还需要继续完成

1. 管理接口需要增加基于管理员会话的权限边界；目前本机循环访问仍保留旧版本地信任模式。
2. 账号资源需要增加“复制配置到另一个账号”的显式操作，复制时默认不复制凭据。
3. `settings` 表中的遗留全局设置需要逐步迁移为账号级配置；旧项目仍允许全局回退以保持兼容。
4. 凭据默认 JSON 适配器需要替换为 Windows Credential Manager 或 Keyring。
5. Agent Token 的撤销、轮换 UI，以及 `config:read/config:write` 的细粒度路由权限还需完善。
6. 需要使用两个真实且不同的文本、图片、MiniMax TTS 凭据完成端到端生成验收。

## 验证记录

已通过账号隔离、数据库迁移、项目服务、配置包、模型连接、凭据、Agent E2E、AgentClient、MCP 和契约矩阵测试。当前本地回归结果：

- `python -m pytest -q`：821 passed，1 warning；
- 账号/配置/连接/凭据/Agent 重点回归：46 passed，1 warning；
- `node checks/test_frontend_quality.js`、`node checks/test_visible_flow.js`：通过；
- Remotion `npx tsc --noEmit -p tsconfig.json`：通过；
- `python scripts/generate_agent_contracts.py --check`、`git diff --check`：通过。

真实供应商双凭据生成仍需在具备两套文本、图片、MiniMax TTS 凭据的环境做发布前验收；当前测试不伪造或提交任何密钥。
