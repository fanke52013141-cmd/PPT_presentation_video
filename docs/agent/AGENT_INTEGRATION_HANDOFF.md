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

- `idempotency_key`、`expected_revision` 仍仅是接口字段，尚未落地为持久化幂等表和乐观锁；涉及创建、TTS、视频的自动重试前必须先实现。
- `review_policy` / `automation_mode=agent` 尚未持久化为项目级配置；当前应由调用方显式传递 `stop_at`。
- 图片和音频可通过 MCP Resource 获取，但尚未全部登记到 `ArtifactRecord`；后续应建立统一 Artifact Service。
- MCP 尚未在初始化阶段与 `/meta` 的 `contract_hash` 做强制兼容性协商；这是下一项发布前工作。
- Agent 能力应继续维持 `experimental` 使用范围，直至上述持久化和完整临时数据库 E2E 测试完成。
- 项目标准 quick 回归当前在 `checks/test_step_ownership_contract.py` 失败：它从 `project_style_routes.py` 查找已迁移到 `server.py` 的 `step3_image_style_templates`。本次未修改该 Step 3 模块；应在独立修复中更新该历史断言后再将 quick 回归作为绿色发布门槛。

## 本次验证

- `python -m compileall -q ...` 通过；
- `python -m pytest checks/agent -q`：201 通过，1 个第三方弃用警告；
- `python -m cli.pptctl artifact get --help` 通过；
- MCP 模块入口已可由 `python -m mcp_server` 加载。
