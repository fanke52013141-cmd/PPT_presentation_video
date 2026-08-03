# 测试基线（2026-07-30）

## 环境

- Windows / PowerShell
- Python：`py -3.13`
- Node.js：系统当前可用版本
- 原项目分支：`main`

仓库文档中的 `python` 命令在当前机器不可用，因此 Python 基线统一使用 `py -3.13`。这只影响命令入口，不影响测试内容。

## 改造前基线

| 检查 | 结果 |
| --- | --- |
| `py -3.13 -m compileall -q server.py scripts checks` | 通过 |
| `node --check static/workflow_state.js` | 通过 |
| `node --check static/flow.js` | 通过 |
| `node checks/test_visible_flow.js` | 通过 |
| 五项生产链路脚本检查 | 通过 |
| `py -3.13 -m pytest checks -q` | 151 通过，1 条第三方弃用警告 |
| Remotion `npx tsc --noEmit -p tsconfig.json` | 未执行：`scripts/remotion/node_modules` 尚未安装 |

五项生产链路脚本检查：

- `checks/test_reveal_mask_integrity.py`
- `checks/test_reveal_pipeline_isolation.py`
- `checks/test_slide_visual_invalidation.py`
- `checks/test_audio_confirmation.py`
- `checks/test_audio_tail_padding.py`

## PPTX 垂直切片验收基线

新增功能至少必须验证：

1. 未完成分镜、图片缺失、非 16:9、图片来源失效时禁止导出。
2. 依照 `visual_contract.json` 顺序生成页面。
3. 每页只有一张铺满 16:9 画布的已确认图片。
4. 先写入 `.part`，重新打开校验后再原子替换为 `.pptx`。
5. PPTX、侧车元数据、数据库产物记录保持一致。
6. 导出任务可轮询，刷新页面后仍可从 SQLite 恢复状态。
7. 分镜或图片变化后，历史 PPTX 标记为“输入已变化”，但仍可下载。
8. 删除 PPTX 时同时删除侧车元数据和数据库记录。

## 改造后结果

| 检查 | 结果 |
| --- | --- |
| `py -3.13 -m pytest checks -q` | 194 通过，8 条已有第三方弃用警告 |
| Python `compileall` | 通过 |
| `node --check static/workflow_state.js` | 通过 |
| `node --check static/flow.js` | 通过 |
| `node checks/test_visible_flow.js` | 通过 |
| `node checks/test_frontend_quality.js` | 通过 |
| Remotion `npx tsc --noEmit -p tsconfig.json` | 通过 |
| `npm audit --audit-level=high` | 0 个漏洞 |
| PPTX 重新打开与页数校验 | 通过 |
| PPTX 全页渲染 | 2/2 页通过 |
| PPTX 溢出检测 | 通过 |
| 浏览器生成、轮询、刷新恢复与下载入口 | 通过 |
| 视频任务启动恢复：`running` → `interrupted` | 通过 |
| 视频任务中断提示浏览器回归 | 通过 |
| 编号迁移顺序、重复启动 no-op、checksum 防篡改 | 通过 |
| 旧版迁移标记表无损接管 | 通过 |
| 失败迁移的结构与 ledger 原子回滚 | 通过 |
| 下游失效矩阵与单页图片作用域隔离 | 通过 |
| `sitecustomize.py` 退休且 Python 启动无全局 monkey patch | 通过 |
| Manifest 分组对齐、手工 Mask 保留与空分镜清理 | 通过 |
| Step 8 有界子进程与异常 JSON 兼容处理 | 通过 |
| AI Mask 配置、任务和显式路由拆分，旧 `_register(server_module)` 退役 | 通过 |
| AI Mask 语义匹配器显式注入，导入时 monkey patch 退役 | 通过 |
| Project Profile / Step 3 图片风格显式 Router，8 个 runtime 注册模块退役 | 通过 |
| Pipeline 门面改用五组显式操作依赖，不再接收完整 `server` 模块 | 通过 |
| PPTX 显式 Router、窄依赖服务与启动任务恢复，整模块注册退役 | 通过 |
| Step 8 视频渲染服务与显式 Router 拆分，旧 Worker、全局任务表和死 JobStore 退役 | 通过 |
| Step 8 内部职责拆分为编排器、VideoJobStore、VideoArtifactService 与 RemotionRunner | 通过 |
| Step 2 分镜服务与显式 Router 拆分，24 条原有路径保持不变 | 通过 |
| Step 6 旁白与 Step 7 TTS 服务/Router 拆分，11 条原有路径保持不变 | 通过 |
| 项目生命周期服务/Router 拆分，空文章项目创建与安全删除回归 | 通过 |

安装 Remotion 基线依赖时发现 `postcss 8.5.15` 的高危路径遍历公告。已通过锁文件补丁升级到 `postcss 8.5.25`，同时将传递依赖 `nanoid` 更新到 `3.3.16`；TypeScript 编译和完整回归均通过。

真实本地数据库在首次切换到编号迁移器前已备份为 `data/projects.pre_numbered_migrations.db`（`data/**` 不进入 Git）。迁移后 ledger 为 0001–0003，原项目数据保持不变。
