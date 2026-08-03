# 全流程审核、测试结果与优化方案（2026-08-03）

## 1. 审核结论

本次已使用真实浏览器和真实本地服务，从空项目开始完整走通以下人工审核主路径：

```text
创建空文章项目
-> 导入文章
-> 手工建立分镜
-> 上传并确认 Slide 图片
-> 确认静态整页 Mask 状态
-> 生成并确认真实 TTS 音频
-> 导出图片型 PPTX
-> 使用 Remotion 渲染 MP4
-> 刷新页面并重新打开项目
-> 重启服务并恢复任务、视频和 PPTX 记录
```

结论：用户不依赖文本模型和生图模型时，人工审核主路径能够从开头正常走到结尾，并生成可播放 MP4 和可打开 PPTX。

本机没有配置文本模型和生图模型凭据，因此“输入话题自动生成文章”“AI 自动分镜”“AI 生图”“一键全自动生成”没有执行真实供应商调用。端到端工具现在会在创建项目和调用供应商前明确报告缺失项，不再运行到中途才失败。

## 2. 测试环境

| 项目 | 结果 |
| --- | --- |
| 服务地址 | `http://127.0.0.1:8000` |
| 操作系统 | Windows |
| 测试项目 | `e20a6927_115305` |
| 项目模式 | 手动审核模式 |
| 文本模型凭据 | 未配置 |
| 生图模型凭据 | 未配置 |
| TTS | MiniMax，真实调用成功 |
| FFmpeg / FFprobe | 可用 |
| Remotion | npm 安装、TypeScript 检查、真实渲染均成功 |

运行数据位于 `runs/e20a6927_115305`，受 `.gitignore` 保护，不进入 Git 提交。

## 3. 自动化基线

| 检查 | 结果 |
| --- | --- |
| `python scripts/run_checks.py --level full --with-remotion` | 通过 |
| 全量 pytest（修复前基线） | `259 passed`，1 条第三方弃用警告 |
| 全量 pytest（修复后发布门禁） | `263 passed`，1 条第三方弃用警告 |
| Remotion `npm ci` | 235 个包，0 个漏洞 |
| Remotion TypeScript | `tsc --noEmit` 通过 |
| 浏览器控制台 | 0 个 error，0 个 warning |

唯一自动化警告来自 FastAPI/Starlette `TestClient` 对 httpx 的第三方弃用提示，不影响当前运行结果。

## 4. 用户流程测试矩阵

| 阶段 | 操作 | 预期 | 实际结果 |
| --- | --- | --- | --- |
| 创建项目 | 只填写名称和描述，文章留空 | 允许创建，进入文章编辑 | 通过 |
| Step 1 | 粘贴约 300 字中文文章并保存 | 写入唯一文章源，解锁分镜 | 通过 |
| Step 2 | 添加 1 页，填写标题和完整演讲稿 | 生成有效 Visual Contract | 通过 |
| Step 3 | 上传项目参考图片 | 归一化为 1920×1080，允许确认 | 通过 |
| Step 4 | 不创建 Mask，按静态整页方式确认 | 允许静态 Slide 进入旁白 | 通过，产生 2 条预期警告 |
| Step 5 | 自动初始化旁白，调用 MiniMax TTS | 音频可加载、可确认 | 通过，12.933 秒 |
| Step 6 / PPTX | 点击生成 PPTX | 持久化任务和产物记录 | 通过，1 页，723,968 字节 |
| Step 6 / MP4 | 点击生成 MP4 | Remotion 完成渲染 | 通过，约 143.1 秒 |
| MP4 媒体 | 浏览器加载输出视频 | 1920×1080、音视频轨完整 | 通过，13.376 秒，H.264 + AAC |
| 页面刷新 | 刷新后从项目库重新进入 | 显示 100%，恢复输出记录 | 通过 |
| 服务重启 | 停止并重新启动 FastAPI | 任务与产物从 SQLite 恢复 | 通过；同时发现并修复历史错误残留问题 |

## 5. 产物检查

逐阶段执行了：

```powershell
python scripts/check_smoke_artifacts.py --run-dir runs/e20a6927_115305 --stage step1
python scripts/check_smoke_artifacts.py --run-dir runs/e20a6927_115305 --stage step2
python scripts/check_smoke_artifacts.py --run-dir runs/e20a6927_115305 --stage step3
python scripts/check_smoke_artifacts.py --run-dir runs/e20a6927_115305 --stage step5
python scripts/check_smoke_artifacts.py --run-dir runs/e20a6927_115305 --stage step6
python scripts/check_smoke_artifacts.py --run-dir runs/e20a6927_115305 --stage step7
python scripts/check_smoke_artifacts.py --run-dir runs/e20a6927_115305 --stage step8
```

全部阶段无 `FAIL`。Step 5 至 Step 8 的两条 `WARN` 是本次明确选择静态整页 Slide、未绘制 Mask 所产生，属于允许的产品路径。

附加验证：

- `scripts/validate_reveal_scene.py`：1 页通过。
- `scripts/validate_run_assets.py`：1 页通过。
- PPTX 使用 `python-pptx` 重新打开：1 页，16:9。
- MP4 使用 FFprobe 检查：H.264 视频轨、AAC 音频轨、1920×1080、13.376 秒。
- 视频 `.render.json` 侧车存在，管线版本为 `exact_rle_mask_with_manual_corrections_v5`。
- MP4 和 PPTX 在服务重启后仍可列出、加载和下载。

## 6. 本次发现并修复的问题

### P0：真实一键验收脚本已失效

问题：`checks/e2e_one_click_run.py` 在架构拆分后仍调用已经移除的 `server.resolve_media_tool`。脚本会在预检阶段抛出 `AttributeError`，无法承担真实端到端验收职责。

处理：改为直接使用源模块 `scripts.media_tools.resolve_media_tool`，并新增入口回归测试。

### P0：供应商预检发生得太晚

问题：旧脚本先创建项目、调用文章生成，再检查 LLM、生图、TTS、FFmpeg 前置条件。缺少凭据时会留下半成品项目，且用户得到的是中途接口错误。

处理：新增无敏感值的供应商预检，在创建项目和第一次外部调用前一次性报告 `llm_credentials`、`image_credentials`、`tts_credentials` 缺失项。腾讯 TTS 会同时检查 Secret ID 和 Secret Key。

### P1：仅导入端到端工具会触发应用任务恢复

问题：端到端脚本在模块顶层导入 `server`。单元测试只要导入该脚本，就会执行组合根和孤儿任务恢复；若此时另一个本地服务正在渲染，测试进程可能误改任务状态。

处理：把 `server` 改为 `main()` 内延迟导入。检查预检函数和入口模块不再产生应用启动副作用。

### P1：成功任务可能残留历史错误

问题：`VideoJobStore.update(error=None)` 过去表示“不更新错误字段”，导致一个任务先出现中断状态、后又成功完成时，最终数据可能同时出现 `status=succeeded` 和“任务已中断”的错误文本。

处理：为可选字段增加“未传入”哨兵值。调用方省略 `error` 时保持原值，明确传入 `error=None` 时清空错误。视频成功终态现在满足以下不变量：

```text
status = succeeded
stage = completed
progress = 100
error = null
```

已新增回归测试覆盖“中断后成功必须清空旧错误”。

## 7. 后续优化方案

### P0：把两条真实主路径变成发布门禁

1. 保留当前 AI 一键真实验收入口，配置专用低额度测试凭据后按需运行。
2. 新增不依赖 LLM/生图的人工路径自动验收：固定文章、固定 1～2 页分镜、固定本地图片、短音频、PPTX 和短视频。
3. PR 默认运行无外部费用的自动化；发布前或夜间任务运行真实供应商 E2E。
4. 每次保存机器可读 JSON 结果，包含项目 ID、最高阶段、产物指纹、时长和错误阶段。

验收标准：任何路由重构、服务拆分或数据库迁移都不能让这两条入口在运行前崩溃。

### P1：增加跨进程任务所有权和心跳

本次已经修复成功任务残留错误，但“同时启动两个应用进程”仍缺少严格的任务所有权协议。建议：

1. `local_jobs.payload_json` 写入 `owner_instance_id`、进程 ID 和心跳时间。
2. 渲染线程每 5～10 秒更新心跳，而不只在阶段切换时更新。
3. 启动恢复只中断超过租约时间且所有者不可达的任务。
4. 第二个服务实例不得把仍有心跳的任务标记为中断。
5. 增加双服务进程竞争测试。

验收标准：一个服务正在渲染时，另一个测试或服务进程的启动、导入和退出都不会改变该任务状态。

### P1：补齐动态 Mask 的真实视频验收

当前完整主路径验证的是允许的静态整页 Slide。下一轮应使用 2～3 页素材，至少包含：

- 1 页静态整页图片；
- 1 页自动或手工 RLE Mask；
- 1 页多语块、不同 Reveal 动画；
- 字幕分页和高亮；
- 修改图片后旧视频/PPTX 的 stale 标记。

验收标准：覆盖率、零重叠、时间轴绑定、字幕、背景色和失效传播同时通过。

### P1：真实供应商合同测试

为 LLM、生图和各 TTS 供应商建立最小请求合同：

- 连接测试必须验证模型名、认证方式、超时和响应格式；
- 缺少凭据时禁止创建后台任务；
- 401、429、超时和供应商返回空内容时给出可执行提示；
- 日志只记录提供商、模型和错误分类，不记录密钥。

### P2：输出性能与进度

本次 13.376 秒、401 帧视频在已安装依赖的情况下渲染约 143 秒。建议记录各阶段耗时并优化：

- 缓存 Remotion bundle；
- 将编码进度写入持久化任务；
- UI 显示帧进度和预计剩余时间；
- 对静态整页项目启用更快的编码路径；
- 发布基线记录冷启动和热启动两种耗时。

### P2：可访问性和自动化定位

为项目卡片、六步导航、Slide 卡片、任务记录和错误提示增加稳定的 `data-testid` 或明确 ARIA 状态，避免端到端测试依赖文本和 DOM 层级。

## 8. 发布前最终门禁

发布前必须同时满足：

1. 全量 `scripts/run_checks.py --level full --with-remotion` 通过。
2. 新增入口测试和成功终态测试通过。
3. 浏览器重新打开项目后能看到 MP4、PPTX 和 100% 完成度。
4. 成功视频任务的 `error` 必须为 `null`。
5. Git 工作区只包含本次源代码、测试和报告，不包含 `runs/`、`outputs/`、`logs/`、`data/` 或密钥。
