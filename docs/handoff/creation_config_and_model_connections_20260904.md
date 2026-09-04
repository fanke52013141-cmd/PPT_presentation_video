# 创作配置包与模型连接开发交接

日期：2026-09-04

## 当前交付

本次交付把多账号创作所需的配置固定链路接入项目：模型连接、凭据引用、创作配置包、项目配置快照、结构化配置编辑器，以及文本/图片/TTS 运行时解析。

项目创建时可以选择配置包和版本。服务端会把解析后的配置保存到项目的 `planning/project_config.json`，并在 `projects` 表记录包 ID、版本和内容哈希。后续配置包新增版本不会改变已经创建的项目。

结构化编辑器位于“系统设置 → 创作配置管理”，可以编辑：

- 文章生成、分镜、可视化、图片生成、AI Mask、旁白 Prompt；
- 各步骤的文本、图片和 TTS 模型连接；
- MiniMax Voice ID、Clone Voice ID、语速、音量和音调；
- 字幕开关、Mask 开关和自动化暂停阶段；
- 图片风格名称与风格提示词。

高级 JSON 编辑仍然保留，结构化表单和 JSON 可以互相同步。编辑已有包时保存为新版本，不覆盖历史版本。

## 运行链路

业务步骤读取项目快照中的配置。快照存在且绑定有效时，运行时解析指定连接的指定 revision 和凭据；绑定存在但失效时返回明确错误，不会偷偷回退到另一个账号的全局配置。没有快照或没有对应绑定的旧项目继续使用原有全局设置。

- 文本：`article_service.py`、`storyboard_service.py`、`narration_service.py`；
- 图片：`image_workflow_service.py`；
- TTS：`tts_service.py`；
- 字幕：`visual_settings_service.py`、`scripts/build_remotion_props.py`、`scripts/remotion/src/Video.tsx`。

模型连接只公开安全元数据。实际密钥由 `credential_store.py` 解析，配置包和项目中只保存 `credential://...` 引用。

## 关键入口

- 配置包服务：`creation_config_service.py`、`creation_config_routes.py`；
- 模型连接服务：`model_connection_service.py`、`model_connection_routes.py`；
- 凭据服务：`credential_store.py`、`credential_routes.py`；
- 项目快照读取：`project_config_runtime.py`；
- 启动组合：`reusable_config_startup.py`、`server.py`；
- 前端管理：`static/creation_config_management.js`；
- 项目创建选择器：`static/projects.js`、`static/project_profile_extension.js`；
- 数据库迁移：`migrations/0011_project_creation_config.sql`；
- 方案说明：`docs/plans/creation_configuration_and_model_connections.md`。

## 验证

已通过：

- 全量 Python 测试：`813 passed`；
- 前端质量检查与可见流程检查；
- Remotion TypeScript 检查；
- Agent 契约检查与能力矩阵生成检查；
- 数据库迁移、项目配置快照、媒体运行时、字幕和安全边界测试。

提交前可重新运行：

```powershell
py -3 -m pytest -q
node checks/test_frontend_quality.js
node checks/test_visible_flow.js
Push-Location scripts/remotion
npx tsc --noEmit -p tsconfig.json
Pop-Location
py -3 scripts/generate_agent_contracts.py --check
```

## 安全与部署注意

当前默认凭据适配器把密钥保存到本地 `data/credentials.json`。该文件不应提交到仓库；正式多用户部署前应替换为 Windows Credential Manager、操作系统 Keyring 或外部 Secret Manager。

目前连接管理已支持创建、查看、复制和归档，后续仍应补充连接编辑/revision 对比、文本/图片/TTS 连通性测试、凭据轮换界面和引用数量展示。

配置包编辑器目前提供结构化字段和高级 JSON，后续可以继续增加 Prompt 完整预览、模板恢复、包导入导出和项目工作区的“本项目配置”修订功能。自动化策略中部分包字段仍需进一步统一到 one-click 任务级检查点，并完成真实供应商的小规模端到端验证。

## 继续开发建议

1. 为模型连接增加编辑、revision 差异和独立测试区。
2. 从现有全局设置生成首个默认配置包，提供幂等迁移。
3. 在项目工作区增加项目配置修订、应用其他配置包和下游失效提示。
4. 将 AI Mask、参考图反推等剩余 Prompt 入口接入项目快照。
5. 用至少两个不同凭据的文本、图片和 MiniMax TTS 连接完成真实多账号验证。
