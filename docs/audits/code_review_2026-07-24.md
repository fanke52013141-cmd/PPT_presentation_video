# 代码审核与优化报告：2026-07-24

## 审核范围

- 基线提交：`44d6caa`
- 环境：Windows、Python 3.13.5、Node.js 24.12.0
- 后端：FastAPI、SQLAlchemy、SQLite
- 前端：原生 HTML/CSS/JavaScript
- 视频：Remotion/TypeScript
- 审核方法：完整测试、脚本式检查、静态分析、依赖审计、本地服务和浏览器 smoke test

## 发现与处理

### 1. SQLite 默认设置初始化存在并发竞争

严重度：高

原实现对每个默认设置执行“先查询、再插入”。多个服务进程或 worker 同时启动时，都可能在查询阶段判断记录不存在，随后同时插入相同主键，触发：

```text
sqlite3.IntegrityError: UNIQUE constraint failed: settings.key
```

处理：

- 使用 SQLite `ON CONFLICT DO NOTHING` 原子写入默认设置。
- 保留已有用户配置，不覆盖自定义模型、密钥或其他值。
- 保留旧默认值迁移逻辑。
- 新增 8 个并发初始化线程的回归测试。

### 2. 完整检查漏掉脚本式测试

严重度：高

`pytest` 只收集 `test_*` 函数，但 `checks/` 中有 20 个文件只通过 `main()` 执行。原来的 `--level full` 只额外运行 `pytest`，因此大量端到端契约检查并未进入完整质量门禁。

处理：

- 通过 AST 识别没有 pytest 测试函数的 `test_*.py` 文件。
- `--level full` 自动执行所有脚本式检查，再运行 pytest。
- 快速检查中已执行的文件不会重复运行。
- 新增检查器发现逻辑的回归测试。

### 3. 两条发布契约已经与当前实现脱节

严重度：中

- 视频渲染已迁移到 `_render_video_worker`，但安全检查仍只搜索同步 `render_video` 路由。
- Step 2 整页演讲稿输入框现在按项目模式动态决定只读状态，但测试仍要求 HTML 静态包含 `readonly`。
- Step 2 视觉提示词合同语义仍然存在，但测试绑定了旧句子顺序。

处理：

- 分别验证异步 worker 和同步前置校验路由承担的职责。
- 验证手动空分镜可编辑、结构化/自动模式只读的动态逻辑。
- 提示词测试改为验证关键合同字段和逐字还原约束，不再绑定无关文案顺序。

### 4. 渲染任务历史无上限增长

严重度：中

异步渲染任务注册表会永久保留每次渲染的状态、错误和视频列表。长时间运行或大量渲染后，进程内存会持续增长。

处理：

- 只保留最近 100 条任务记录。
- 优先删除最旧的成功/失败记录。
- 进行中的任务永远不会被清理。
- 新增历史上限和活跃任务保留测试。

### 5. 测试产物未被忽略

严重度：低

运行 `pytest-cov` 会生成 `.coverage`，原 `.gitignore` 没有覆盖该文件及 HTML 报告。

处理：

- 忽略 `.coverage`、`.coverage.*` 和 `htmlcov/`。

## 验证结果

- canonical full checks：通过
- pytest：154 passed
- 脚本式 Python 检查：20 个通过
- JavaScript 语法和前端质量检查：通过
- Remotion TypeScript：`tsc --noEmit` 通过
- npm audit：0 vulnerabilities
- pip-audit：未发现已知漏洞
- Bandit 高严重度扫描：无发现
- Ruff 关键错误集（E9/F63/F7/F82）：无发现
- 本地服务：`http://127.0.0.1:8000` 启动成功
- 运行时诊断：142 条路由，关键路由缺失 0
- 浏览器 smoke test：首页、新建项目、文章导入、六步导航、前序步骤门禁正常，控制台无 error/warn

## 仍需关注

1. 当前自动测试对核心 Python 模块的语句覆盖率为 43%，其中 `server.py` 为 40%。主服务文件超过 8,000 行，后续宜按路由领域继续拆分并补行为测试。
2. Python 依赖使用开放式 `>=` 范围，可重现性弱。建议后续增加经过 CI 验证的 constraints/lock 文件，并建立定期依赖升级流程。
3. 当前 FastAPI/Starlette 测试栈产生一条 `TestClient` 弃用警告。功能不受影响，但依赖升级时需要迁移到新测试客户端。
4. 本次环境未配置 LLM、生图和 TTS 密钥，因此没有调用真实外部供应商。离线流程、Mask 构建、手动静态页 E2E、Remotion 类型检查和本地 UI/API 已完成；真实一键生成与最终 MP4 应在具备测试凭据的受控环境中再做一次发布验收。
