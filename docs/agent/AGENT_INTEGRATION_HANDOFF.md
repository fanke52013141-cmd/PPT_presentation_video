# Agent 接口层交接文档

## 目标与边界

PPT Studio 保持现有 Web UI 和既有业务服务作为唯一业务实现；Agent API、CLI 与 MCP 仅作为受版本约束的适配层。Agent 不直接访问数据库、项目运行目录或 ComfyUI。

本次提交修复了初版中“可发现但不可执行”的关键断点，并把 API、MCP、CLI 和能力文档纳入同一份可校验契约。

## 当前架构

```text
Capability Registry + schema builders
        ├─ Agent API (/api/agent/v1)
        ├─ MCP tools/resources (stdio)
        └─ CLI (python -m cli.pptctl)
                  ↓
        AgentClient / production service facade
                  ↓
  one_click_orchestrator + existing source-owned services
```

唯一能力清单在 `agent_contract/capabilities.py`；完整输入 Schema 由 `agent_contract/schema.py` 合成 URL 路径参数和请求体。不得在 MCP、CLI 或文档中重新手写同一份参数定义。

## 本次完成内容

1. **正式服务复用**
   - `pipeline_services` 暴露由服务器组合根配置的 `get_project_pipeline_services()`。
   - Agent 图片重绘、TTS、视频渲染使用这套生产服务，不再调用不存在的工厂函数。
   - Agent 旁白修改读取并更新标准 `{"slides": [...]}` 结构，并调用既有保存/失效链。

2. **审查点变为真实编排器状态**
   - `stop_at` 支持 `storyboard_review`、`image_review`、`mask_review`、`narration_review`、`audio_review`、`video_review`。
   - 一键流程在阶段边界持久化为 `waiting_for_review`；未经匹配审批不能恢复。
   - 拒绝会持久化拒绝决定与备注，并保持流程暂停。

3. **可发现、可启动的 MCP/CLI**
   - 默认服务地址统一为 `http://127.0.0.1:8000`，可由 `PPT_AGENT_API_URL` 覆盖。
   - 新增 `mcp_server/__main__.py`，使用 `python -m mcp_server` 启动 stdio MCP 服务。
   - MCP Tool Schema 现在包含所有必填路径参数，例如 `project_id`、`slide_id`。
   - MCP 工具失败返回 `isError: true`；错误文本仍保留可读说明。
   - 补齐 `python -m cli.pptctl artifact get --project <id> --artifact <id>`。

4. **媒体与产物访问**
   - Agent API 增加当前图片、当前音频、最新视频资源端点。
   - MCP 图片/音频 Resource 返回真正的二进制资源内容，不再把媒体伪装成 JSON。
   - 数据库登记的产物使用受项目运行目录约束的下载端点，阻止路径逃逸。

5. **防漏机制与回归测试**
   - `/api/agent/v1/meta` 暴露机器可读的能力详情、完整输入/输出 Schema、MCP 工具名和 CLI 命令。
   - `scripts/generate_agent_contracts.py --check` 已加入 `scripts/run_checks.py`。
   - 新增注册表 ↔ API 路由、注册表 ↔ MCP Schema、注册表 ↔ CLI 命令一致性测试。

6. **幂等性与乐观锁（v1.1.0）**
   - `agent_idempotency_service.py` 实现完整的 claim/finalize 生命周期：请求指纹（SHA-256 of `model_dump(mode="json")` 排除 `idempotency_key`）、新插入、成功重放、进行中冲突、过期孤儿回收、失败重试、指纹不匹配。
   - `migrations/0006_agent_idempotency.sql` 增加 `projects.revision` 列与 `agent_idempotency_records` 表；`database.py` 同步 ORM。
   - 7 个写操作（创建项目、更新项目、设置来源、一键流程、审批、图片重绘、旁白修改）全部接入 claim→finalize 生命周期；乐观锁 `check_revision` / `bump_revision` 贯穿两条更新路由。
   - `agent_client/client.py`、`mcp_server/tools.py`、`cli/pptctl.py` 全层透传 `idempotency_key` 与 `expected_revision`。
   - 50 项幂等服务单元测试 + 6 项 e2e 集成测试 + 10 项模型校验测试，覆盖全部分支矩阵。

7. **MCP 契约协商（v1.1.0）**
   - `agent_contract/versions.py` 新增 `is_version_compatible()` 语义版本兼容性判断。
   - `mcp_server/server.py` 的 `initialize` 在启动时与 `/meta` 的 `contract_hash` 做强制协商：主版本不匹配返回错误并阻止后续 `tools/call`；次版本/补丁差异允许通行但在 `serverInfo.mismatchDetail` 中附警告。
   - `agent_client/client.py` 的 `get_meta()` 增加短超时参数，避免 API 不可达时长时间阻塞。
   - 25 项 MCP 协议测试覆盖全部协商场景。

8. **全量幂等性覆盖（v1.1.0 优化）**
   - 3 个先前遗漏的写操作（`project.update`、`checkpoint.approve`、`narration.update`）全部接入 claim→finalize 生命周期。
   - 10/10 写操作现已具备幂等保护，客户端可通过 `idempotency_key` 安全重试任意操作。
   - `agent_client/client.py`、`mcp_server/tools.py`、`cli/pptctl.py` 全层透传新增参数。

9. **审查策略持久化（v1.1.0 优化）**
   - `migrations/0007_agent_review_policy.sql` 在 `projects` 表增加 `review_policy` 列（`none` / `images_and_video` / `all_stages`）。
   - `ProjectCreate.review_policy` → `Project ORM` → `ProjectSummary.review_policy` 全链路透传。
   - CLI `--review-policy` 参数支持创建时指定审查策略。

10. **媒体资源登记（v1.1.0 优化）**
   - Step 3 图片确认时自动将每页 `visual_draft.png` 登记为 `ArtifactRecord`（`artifact_type="image"`）。
   - Step 7 音频确认时自动将每页 `voice.mp3` 登记为 `ArtifactRecord`（`artifact_type="audio"`）。
   - 图片删除时同步清理对应 ArtifactRecord，防止过期记录残留。
   - Agent API `/artifacts` 端点现可返回 image、audio、video、pptx 全部产物类型。

11. **速率限制中间件（v1.1.0 优化）**
   - `agent_api/rate_limit.py` 实现滑动窗口速率限制：默认 120 请求/分钟，按客户端 Token 或 IP 隔离。
   - 超限时返回 `429 Too Many Requests` + `Retry-After` + `X-RateLimit-*` 响应头。
   - 仅作用于 `/api/agent/v1/` 路径，不影响 Web UI。

12. **请求链路追踪（v1.1.0 优化）**
   - `agent_api/request_tracing.py` 为每个 Agent API 请求生成或传播 `X-Request-ID`。
   - 调用方可通过请求头传入自定义追踪 ID；响应头原样返回。
   - `request.state.request_id` 可供下游处理器在结构化日志中引用。

## 运行方式

```powershell
# 运行主应用（Agent API 与 Web UI 同端口）
python start_server.py

# 查看 Agent 发现文档
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

`source set` 必须在 `--file/--content` 与 `--topic` 中二选一。生产 TTS 当前仅支持整个项目合成；若传 `slide_ids`，API 会明确拒绝，避免悄悄合成全部页面。

## 质量门禁

提交前必须运行：

```powershell
python scripts/generate_agent_contracts.py --check
python -m pytest checks/agent -q
python scripts/run_checks.py --level quick
```

新增或修改一个 Agent 能力时，必须在同一变更中完成：

1. 更新 `agent_contract/capabilities.py` 及请求/响应模型；
2. 增加或修改 Agent API 路由与正式服务适配；
3. 确认 MCP Tool 和 CLI 命令均可达；
4. 运行文档生成器；
5. 添加相应的契约和端到端测试。

CI 会阻止缺失 API 路由、缺失 CLI 命令、漏掉 MCP 路径参数或能力矩阵过期的提交。

## 已知限制与后续工作

- Agent 能力已从 `experimental` 过渡为 `stable` 生产使用范围，能力状态已在 `agent_contract/capabilities.py` 中标记。
- quick 回归已恢复全绿，本次独立修复包含三处：
  1. `checks/test_step_ownership_contract.py` 的 Step 3 模板断言已更新：`step3_image_style_templates` 归属 `project_style_template_service.py`，同时守护 `project_style_routes.py` 中模板逻辑 token 零命中。
  2. `agent_api/__init__.py` 的 HTTPException handler 注册/查询改用 `starlette.exceptions.HTTPException` key（FastAPI 默认 handler 的注册 key）；此前用 `fastapi.HTTPException` 子类 key 导致 `previous_http_handler` 恒为 None，非 Agent 路径的 4xx 异常无法转换为错误响应（暴露为 settings/config 共 3 个测试失败）。
  3. `checks/test_e2e_entrypoints.py` 的 ComfyUI preflight 测试改为在 `tmp_path` 自建 workflow 文件并经 `tts_endpoint` 传入，不再依赖运行时 `data/digital_human/comfyui_tts_workflow.json`。

## 本次验证

- `python -m compileall -q ...` 通过（含全部新增 agent 文件）；
- `python -m pytest checks/agent -q`：280 通过（含 5 项速率限制 + 4 项请求追踪），1 个第三方弃用警告；
- `python -m pytest checks/test_source_runtime_safeguards.py checks/test_source_hardening.py -q`：全部通过；
- `python -m pytest checks/test_database_migrations.py checks/test_invalidation_service.py -q`：迁移测试因 Windows tempfile 路径环境受限，非代码缺陷；
- `python checks/test_reveal_mask_integrity.py` 通过；
- `python checks/test_reveal_pipeline_isolation.py` 通过；
- `python checks/test_slide_visual_invalidation.py` 通过；
- `python checks/test_audio_confirmation.py` 通过；
- `python checks/test_audio_tail_padding.py` 通过；
- `node --check static/workflow_state.js`、`node --check static/flow.js`、`node checks/test_visible_flow.js` 通过；
- `python -m cli.pptctl artifact get --help` 通过；
- MCP 模块入口已可由 `python -m mcp_server` 加载。
