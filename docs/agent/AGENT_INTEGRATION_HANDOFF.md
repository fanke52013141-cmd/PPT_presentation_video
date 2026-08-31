# Agent 开放架构 — 交付文档 (Handoff)

## 概述

本次交付将 PPT 视频制作软件开放给 AI Agent，实现了完整的 **Agent API + MCP Server + CLI + 能力注册表** 四层架构。所有现有 Web UI 功能通过统一的版本化接口暴露给外部 Agent，不修改任何已有业务逻辑。

---

## 架构总览

```
                         ┌──────────────────────┐
                         │  Capability Registry  │  ← 单一事实来源
                         │  agent_contract/      │
                         └──────────┬───────────┘
                                    │
              ┌─────────────────────┼──────────────────────┐
              ▼                     ▼                       ▼
    ┌─────────────────┐  ┌──────────────────┐   ┌──────────────────┐
    │   Agent API     │  │   MCP Server     │   │   CLI (pptctl)   │
    │  /api/agent/v1  │  │  mcp_server/     │   │   cli/           │
    └────────┬────────┘  └────────┬─────────┘   └────────┬─────────┘
             │                    │                       │
             ▼                    ▼                       ▼
    ┌─────────────────────────────────────────────────────────────┐
    │              Existing Source-Owned Services                 │
    │  project_service · one_click_orchestrator · pipeline_services │
    │  article_service · image_workflow · tts · video_render       │
    └─────────────────────────────────────────────────────────────┘
```

### 设计原则

1. **单一事实来源**: `CapabilityRegistry` 定义所有能力的 API 路径、MCP 工具名、CLI 命令、Pydantic 模型，三端自动同步
2. **不重复业务逻辑**: Agent API 路由仅做请求映射和错误包装，全部委托给现有服务
3. **版本化契约**: 所有接口在 `/api/agent/v1/` 前缀下，带 SHA-256 契约哈希用于兼容性验证
4. **统一操作模型**: 长运行任务统一返回 `OperationResult`（含 `operation_id`、`status`、`progress`），替代异构的 `task_id/job_id/run_id`
5. **检查点系统**: 6 个审查关卡支持人在环路 (human-in-the-loop) 工作流
6. **零外部依赖**: `AgentClient` 仅用 Python 标准库 (urllib)，MCP Server 工具从注册表自动生成

---

## 文件结构

### 新增包

```
agent_contract/           能力注册表 + 统一模型 + 版本管理
├── __init__.py
├── models.py             所有 Pydantic 请求/响应模型
├── capabilities.py       17 个能力定义（单一事实来源）
├── operations.py         OperationResult 统一操作状态 + 检查点定义
├── artifacts.py          制品信息模型 + 资源 URI 构建
└── versions.py           版本号 + 契约哈希计算

agent_api/                版本化 Agent API 路由层
├── __init__.py           router 导出 + 错误处理器注册
├── errors.py             统一错误类 (AgentAPIError 体系)
└── routes.py             17+ 个端点，全部委托给现有服务

agent_client/             统一 HTTP 客户端 (标准库实现)
├── __init__.py
├── client.py             AgentClient — 所有 API 调用封装
└── polling.py            轮询辅助 — wait_for_completion 等

cli/                      CLI 运维工具
├── __init__.py
└── pptctl.py             pptctl 命令行入口

mcp_server/               MCP Server (工具 + 资源 + 展示器)
├── __init__.py
├── server.py             MCP Server 入口
├── tools.py              工具定义从注册表自动生成
├── resources.py          MCP 资源 URI 模板
└── presenters.py         结果展示格式化

checks/agent/             契约测试 + 端到端测试 (57 个测试)
├── __init__.py
├── test_capability_registry.py   注册表完整性测试 (22)
├── test_mcp_contracts.py         MCP 工具契约测试 (9)
├── test_cli_contracts.py         CLI + 客户端契约测试 (14)
└── test_agent_e2e.py             Agent API 端到端测试 (12)

scripts/
└── generate_agent_contracts.py   自动生成能力矩阵文档

docs/agent/
├── capability-matrix.md          自动生成的能力矩阵
└── AGENT_INTEGRATION_HANDOFF.md  本文档
```

### 修改的文件

- `server.py`: 新增 Agent API 路由注册 + 错误处理器注册 (约第 910 行)

---

## 17 个能力一览

| 能力 ID | 方法 | API 路径 | MCP 工具 | CLI 命令 | 长运行 |
|---|---|---|---|---|---|
| project.create | POST | /projects | ppt_project_create | project create | 否 |
| project.list | GET | /projects | ppt_project_list | project list | 否 |
| project.get | GET | /projects/{id} | ppt_project_get | project show | 否 |
| project.update | PATCH | /projects/{id} | ppt_project_update | project update | 否 |
| source.set | POST | /projects/{id}/source | ppt_source_set | source set | 否 |
| pipeline.run | POST | /projects/{id}/runs | ppt_pipeline_run | run start | 是 |
| pipeline.status | GET | /projects/{id}/runs/latest | ppt_pipeline_status | run status | 否 |
| pipeline.resume | POST | /projects/{id}/runs/latest/resume | ppt_pipeline_resume | run resume | 是 |
| checkpoint.approve | POST | /projects/{id}/checkpoints/{cp}/approve | ppt_checkpoint_approve | approve | 否 |
| stage.get | GET | /projects/{id}/stages/{stage} | ppt_stage_get | stage get | 否 |
| image.regenerate | POST | /projects/{id}/images/{slide}/regenerate | ppt_image_regenerate | image regenerate | 是 |
| narration.update | PATCH | /projects/{id}/narration/{slide} | ppt_narration_update | narration update | 否 |
| tts.synthesize | POST | /projects/{id}/tts | ppt_tts_synthesize | tts synthesize | 是 |
| video.render | POST | /projects/{id}/videos/render | ppt_video_render | video render | 是 |
| artifacts.list | GET | /projects/{id}/artifacts | ppt_artifacts_list | artifacts list | 否 |
| artifact.get | GET | /projects/{id}/artifacts/{aid} | ppt_artifact_get | artifact get | 否 |
| diagnostics | GET | /diagnostics | ppt_diagnostics | diagnostics | 否 |

## 6 个检查点

| 检查点 | 标签 | 描述 |
|---|---|---|
| storyboard_review | 分镜审查 | 分镜规划完成，等待确认后再生成图片 |
| image_review | 图片审查 | 图片生成完成，等待确认后再进行 Mask 标注 |
| mask_review | Mask 审查 | Mask 标注完成，等待确认后再生成旁白 |
| narration_review | 旁白审查 | 旁白生成完成，等待确认后再合成音频 |
| audio_review | 音频审查 | 音频合成完成，等待确认后再渲染视频 |
| video_review | 视频审查 | 视频渲染完成，等待最终确认 |

---

## 使用方式

### 1. Agent API (HTTP)

```bash
# 获取元信息
curl http://localhost:8000/api/agent/v1/meta

# 创建项目
curl -X POST http://localhost:8000/api/agent/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "测试", "automation_mode": "auto"}'

# 启动流水线
curl -X POST http://localhost:8000/api/agent/v1/projects/{id}/runs \
  -H "Content-Type: application/json" \
  -d '{"stop_at": "image_review"}'

# 查询状态
curl http://localhost:8000/api/agent/v1/projects/{id}/runs/latest
```

### 2. Python 客户端

```python
from agent_client.client import AgentClient

client = AgentClient(base_url="http://localhost:8000")

# 创建项目
result = client.create_project(name="演示", automation_mode="auto")
project_id = result["project"]["project_id"]

# 启动流水线（到图片审查关卡停止）
op = client.start_pipeline(project_id, stop_at="image_review")

# 轮询等待完成
from agent_client.polling import wait_for_completion
final = wait_for_completion(client, project_id, poll_interval=5)
```

### 3. CLI

```bash
# 创建项目
python -m cli.pptctl project create --name "测试"

# 导入文章
python -m cli.pptctl source set --project-id {id} --content "文章内容..."

# 启动流水线
python -m cli.pptctl run start --project-id {id} --stop-at image_review

# 查看状态
python -m cli.pptctl run status --project-id {id}

# 审批检查点
python -m cli.pptctl approve --project-id {id} --checkpoint image_review

# 列出制品
python -m cli.pptctl artifacts list --project-id {id}
```

### 4. MCP Server

```python
from mcp_server.server import MCPServer

server = MCPServer(client=agent_client)
# 工具从 CapabilityRegistry 自动生成
tools = server.list_tools()
# 每个工具自动映射到 AgentClient 方法
```

---

## 统一错误处理

所有 Agent API 错误返回统一的 JSON 结构：

```json
{
  "error": {
    "code": "PROJECT_NOT_FOUND",
    "message": "Project 'xxx' not found",
    "details": {}
  }
}
```

错误类型：
- `PROJECT_NOT_FOUND` (404) — 项目不存在
- `VALIDATION_ERROR` (422) — 请求参数校验失败
- `CONFLICT` (409) — 资源冲突
- `OPERATION_FAILED` (500) — 操作执行失败

---

## 契约哈希

当前契约哈希: `3a2c36ae12289051`

哈希由所有能力的 ID、版本、请求/响应模型 schema 计算。任何能力变更都会改变哈希，可用于：
- Agent 启动时验证与服务端的兼容性
- CI 中检测意外的契约变更
- 多版本共存时的版本协商

---

## 测试

### 运行全部 Agent 测试

```bash
python -m pytest checks/agent/ -v
```

### 测试覆盖

| 测试文件 | 测试数 | 覆盖范围 |
|---|---|---|
| test_capability_registry.py | 22 | 注册表完整性、模型一致性、版本哈希 |
| test_mcp_contracts.py | 9 | MCP 工具定义、处理器、契约对齐 |
| test_cli_contracts.py | 14 | CLI 命令、客户端方法、操作状态、制品 |
| test_agent_e2e.py | 12 | Agent API 端到端（FastAPI TestClient）|
| **总计** | **57** | 全部通过 |

### 生成能力矩阵文档

```bash
python scripts/generate_agent_contracts.py
# CI 校验模式
python scripts/generate_agent_contracts.py --check
```

---

## 对现有系统的影响

### 无破坏性变更

- 现有 Web UI 路由 (`/api/projects/*`, `/api/projects/{id}/steps/*`) 完全不受影响
- Agent API 是额外的并行接口层，不修改任何已有路由
- 所有业务逻辑仍由现有 source-owned 服务处理
- `server.py` 仅新增 4 行路由注册代码

### 新增依赖

- `pydantic` — 已在项目依赖中（FastAPI 自带）
- 无其他新增外部依赖

---

## 后续建议

1. **MCP Server 实际启动入口**: 当前 `mcp_server/server.py` 定义了 MCP Server 类和工具注册逻辑，但需要根据实际 MCP 运行时 (如 stdio、SSE) 添加启动入口
2. **CLI 安装脚本**: 可添加 `setup.py` 或 `pyproject.toml` 的 entry_point，使 `pptctl` 可全局安装
3. **WebSocket 实时推送**: 长运行操作目前通过轮询获取状态，可增加 WebSocket 推送
4. **Agent 认证**: 当前 Agent API 复用现有访问控制，可增加 API Key 或 OAuth 认证
5. **能力版本演进**: 当需要变更已有能力时，使用 `deprecated` → `removed` 生命周期，而非直接修改
6. **速率限制**: 对 Agent API 添加速率限制，防止 Agent 过度调用
