# 全项目 UI/代码审查交接文档（2026-09-06）

> 本文档是自包含的审查交接材料：任何 agent 读完本文档即可了解审查进度、全部已发现问题、未完成部分的执行方案，并继续后续审查。所有问题均来自子代理的静态只读审查，附带 `file:line` 证据；**每条在动手修复前建议先做一次现场 spot-check**（打开对应文件核对行号与语义）。

---

## 1. 背景与审查方法

- 被审查项目：本仓库（FastAPI + SQLite + 原生 JS 无构建的 PPT 视频生产管线，约 319 个 Python 文件、36 个前端文件、147 个检查脚本）。
- 触发需求：用户要求对整个项目做「UI 布局交互 + 代码」审查，要求 (a) 罗列 UI 布局交互问题、(b) 代码问题分级、(c) 每条附带影响。
- 方法：按 8 条审查线拆分，用 general-purpose 子代理执行只读审查；每条输出 P0–P3 分级 + file:line 证据 + 影响 + 修复建议。
- 分级口径：**P0** = 数据丢失/损坏、安全漏洞、功能不可用；**P1** = 明显功能缺陷或明确违反 AGENTS.md 架构规则；**P2** = 健壮性/可维护性/潜在 bug；**P3** = 轻微/风格。

### 给接手 agent 的环境注意事项（重要）

1. **子代理并发额度受限**：一次只派发 1 个子代理；出现 `model concurrency limit exceeded` / `captcha verify failed` / `Model request failed` 时等待 1–3 分钟重试即可，不要同时派 2 个以上。
2. **Git Bash 下没有 `python` 命令**，运行 Python 用 `py -3`（例如 `py -3 scripts/generate_agent_contracts.py --check`）。
3. 审查全程只读：除实机 UI 验证（§7）外，不得修改/创建/删除文件，不得运行有副作用的命令。
4. 输出格式保持统一：P0–P3 分组 + `file:line` + 证据 + 影响 + 一句话修复建议。

---

## 2. 审查进度总览

| 审查线 | 主题 | 状态 | 结果概要 |
| --- | --- | --- | --- |
| A | 前端模块边界与架构（static/*.js 对照 AGENTS.md） | ✅ 完成 | P1×2、P2×7、P3×7 |
| B | UI 布局与样式（index.html + 9095 行 style.css） | ✅ 完成 | **P0×1**、P1×3、P2×9、P3×6 |
| C | UI 交互行为（XSS/竞态/轮询/错误处理） | ✅ 完成 | **P0×3**、P1×7、P2×8、P3×5 |
| D | 后端架构边界（server.py 组合根 / Runtime Bridge Policy / Agent Contract） | ✅ 完成 | P1×2、P2×7、P3×6 |
| E | 数据持久化与并发（迁移/事务/SQLite/任务状态机） | ✅ 完成 | **P0×1**、P1×2、P2×5、P3×5 |
| F | 安全专项（鉴权/越权/密钥/注入/上传） | ✅ 完成 | **P0×3**、P1×4、P2×6、P3×7 |
| G | 渲染管线一致性（Mask 契约/失效传播/sidecar/锁） | ✅ 完成 | P1×2、P2×5、P3×6 |
| H | Agent 集成面与测试覆盖 | ❌ 未执行（多次因并发额度失败） | 任务书见 §6；部分内容已被 D 线覆盖（见 §6.1） |
| — | 实机启动服务做 UI 布局交互验证 | ⏸ 未执行 | 方案见 §7（推荐下一步做） |

**合计：P0×8、P1×22、P2×47、P3×42（约 119 条，下文统一编号）。**

---

## 3. P0 问题清单（8 条，建议立即处理）

### P0-01【安全】账号体系完全无鉴权，身份由客户端自我声明
- 位置：`account_context.py:55-74`；`account_routes.py:59-66, 86-89`；`server.py:163`
- 证据：`AccountContextMiddleware` 直接信任 `x-ppt-account-id` 头或 `ppt_studio_account_id` cookie，只查库确认账号存在且 active，无任何密码/签名校验；`Account` 模型没有口令字段。`POST /api/accounts/{id}/select` 可切换为任意账号；`POST /api/accounts/{id}/agent-tokens` 可为任意账号铸造 Agent 令牌（同样无鉴权）。
- 影响：任何能访问该端口的主体用一个 HTTP 请求即可冒充任意创作账号并签发长期 Agent 令牌，多账号隔离形同虚设。
- 修复方向：账号引入真实凭据（口令/签名 cookie + 服务端 session）；agent-tokens 铸造端点独立鉴权。

### P0-02【安全】Agent API 默认全放行，令牌校验可选
- 位置：`agent_api/auth.py:39-46, 120-137`；`server.py:990-997`
- 证据：`PPT_AGENT_API_KEY` 环境变量为空（默认）时中间件直接放行所有 `/api/agent/v1` 请求，且用 `x-ppt-account-id` 头即可自选账号身份。
- 影响：默认部署下 Agent API（项目创建、渲染触发、产物下载等全写操作）对本机/网络任意主体开放。
- 修复方向：改为 fail-closed（未配置即拒绝），至少要求存在 DB 令牌才允许访问。

### P0-03【安全】水平越权：多数项目级路由不校验资源归属账号
- 位置：`project_path_service.py:23-28`（`project_or_404` 仅按 `Project.id` 查询，无 `account_id` 过滤）；调用方遍布 `digital_human_routes.py:236,291,305,333` 等 18 处、`article_routes.py:41-76`、`mask_editor_routes.py:42-96`、`image_workflow_service.py:887,934`、`video_artifact_service.py:84-89`。
- 证据：正确实现的对照点是 `project_service.py:552-555` 与 `agent_api/routes.py:118-126`（带 `Project.account_id == get_current_account_id()`）。
- 影响：持有任一账号令牌者，只要知道/遍历项目 ID，即可读写删除其他账号的文章、图片、音频、视频、PPTX 与数字人配置。
- 修复方向：把 `project_or_404` 收敛为统一带 `account_id` 过滤（或在中间件层做资源归属断言）。

### P0-04【前端/数据污染】Step2 自动保存 debounce 定时器跨项目覆盖分镜
- 位置：`static/storyboard.js:639-647, 964-1005`；`static/workspace_navigation.js:52-67`；`static/mask_workspace.js:11-24`
- 证据：`scheduleStep2AutoSave` 的 700ms setTimeout 回调里 `saveStep2Contract` 无任何项目/步骤守卫；`exitWorkspace/enterWorkspace` 只清 Step5 定时器，不清 Step2。回调在 `state.currentProject` 已切到 B、`state.slides` 仍是 A 的窗口期触发时，`PUT /api/projects/B/steps/2/result` 会把 A 的整套分镜写入 B。
- 影响：静默跨项目数据损坏（用户极难察觉的覆盖）。
- 修复方向：离开 Step2/切换项目时 clearTimeout 并 flush；`saveStep2Contract` 开头校验定时器归属项目。

### P0-05【前端/数据污染】Step3 批量生成/上传循环逐次读取实时项目 id
- 位置：`static/images.js:509-537`（生成循环）、`static/images.js:446-473`（上传循环）
- 证据：循环体内 `await API.post(\`/api/projects/${state.currentProject.id}/steps/3/generate\`, ...)` 每次迭代实时取当前项目 id。
- 影响：批量生图/上传是逐张串行长任务；中途切换项目后剩余请求打到新项目，烧配额并污染 B 项目数据。
- 修复方向：循环开始前捕获 projectId，每轮校验不一致即中断。

### P0-06【前端/数据污染】步骤加载函数缺 stale check；`refreshCurrentProjectStatus` 会"复活"已退出项目
- 位置：`static/workspace_navigation.js:136-142`；`static/storyboard.js:9-16`；`static/images.js:102-122`；`static/narration_audio.js:8-19`；`static/output_render.js:82-117`；`static/narration_audio.js:356-417`
- 证据：`workspaceNavigationVersion` 守卫只覆盖导航层自身；各 `loadStepData` 派生加载器 await 后直接写共享状态；`refreshCurrentProjectStatus` 在 await 后无条件 `state.currentProject = project`。正确对照：`loadStep5Data`（mask_workspace.js:576,583）有 projectId 守卫。
- 影响：快速切换项目时旧项目数据渲染到新项目界面；已退出项目被写回 `state.currentProject`，后续保存落错项目。
- 修复方向：所有写共享状态的 async 路径补 projectId/版本号校验（仿 Step5 实现）。

### P0-07【UI】全屏标注模式下弹窗与 toast 被全屏面板整体遮住（功能不可用）
- 位置：`static/style.css:593-601`（全屏面板 `z-index: 4000`）vs `static/style.css:692`（`.modal-overlay z-index: 1000`）、`static/style.css:1470`（toast z=2000）
- 证据：全屏模式下工具栏保留（style.css:6456-6458），「字幕设置/动画设置」按钮直接开弹窗且不退出全屏（event_bindings.js:179-180、mask_editor.js:718、mask_workspace.js:608 无退出全屏逻辑）。
- 影响：核心标注模式内两个设置功能完全不可用且无提示，用户会认为应用卡死。
- 修复方向：全屏面板 z-index 降到弹窗层之下（如 900），或打开这两类弹窗前先退出全屏。

### P0-08【数据层】reveal_manifest.json 存在绕过原子写与项目锁的写者
- 位置：`storyboard_background.py:45-47`（`_write_json` 裸 `write_text`）、`:172-192`（`_patch_manifest`）、`:238-245`（路由 `PUT /api/projects/{id}/storyboard-background`）
- 证据：该文件所有其他写者都走 `write_json_atomic` + `reveal_lock_for`（mask_manifest_service.py:443/655/760、visual_settings_service.py:445-472 等），唯独此模块直接覆盖写且全程不获取锁。
- 影响：断电/崩溃可截断保存精确 RLE Mask 与人工修正笔画的 Manifest（Mask 数据不可再生）；与图片替换/AI Mask 保存并发时无锁读-改-写互相覆盖丢数据。
- 修复方向：改用 `write_json_atomic` 并包在 `reveal_lock_for(project)` 内（小改动）。

---

## 4. P1 问题清单（22 条）

### 安全线（4 条）
| 编号 | 标题 | 位置 | 影响 |
| --- | --- | --- | --- |
| P1-01 | 默认零鉴权 + 网络护栏可显式绕过（`PPT_STUDIO_ALLOW_INSECURE_NETWORK=1` 可放行非回环绑定；令牌为单一静态共享值） | `app_security.py:95-97,121-122`；`network_guard.py:24-35` | 误配即可把整套系统（含 P0-01~03）暴露到局域网/公网 |
| P1-02 | `POST /api/config/export-with-secrets` 在默认（无令牌）部署下可匿名调用，导出全部明文密钥（`verify_access_token` 无令牌配置时恒真） | `settings_routes.py:65-80`；`app_security.py:61-73`；`config_portability_service.py:265-274,354-358` | 一次请求拖走全部 LLM/TTS API key |
| P1-03 | 凭据与密钥全量明文落盘（`data/credentials.json` 明文 JSON；SQLite settings 表明文 key） | `credential_store.py:105-125`；`config_store.py:1-25`；`repository_paths.py:19` | 拿到磁盘访问（或 P1-02 导出）即获得全部第三方 key |
| P1-04 | 数字人合成端点 `base_video`/`output` 为客户端任意字符串，`_assert_path_safe` 允许 REPO_ROOT，可在仓库根目录内任意覆写文件 | `digital_human_routes.py:630-633`；`digital_human_service.py:111-127, 875-898` | 可覆写 `static/index.html`、`data/credentials.json`、源码，造成持久化破坏 |

### 前端架构线（2 条）
| 编号 | 标题 | 位置 | 影响 |
| --- | --- | --- | --- |
| P1-05 | 两个扩展模块的上传是**无条件裸 fetch**，缺 `X-PPT-Studio-Request` 头（api_client.js 对非 GET 统一加；后端对带 Origin 的 /api 非安全方法强制校验） | `static/storyboard_background_extension.js:26`；`static/style_reference_manager_extension.js:42`；后端 `app_security.py:111-120` | 开启访问控制后，参考图上传/反向分析、背景图上传直接 403，功能不可用 |
| P1-06 | courses.js 覆盖 `window.loadProjects`（courses.js:792-797）架空 projects.js 受保护的项目库渲染职责；同一 `#project-list` 存在两套渲染器，生效者由脚本加载顺序决定 | `static/courses.js:792-797` vs `static/projects.js:217` | AGENTS.md 的 projects.js 边界名存实亡；courses.js 加载失败时首页静默回退旧行为，不可预期 |

### UI/CSS 线（3 条）
| 编号 | 标题 | 位置 | 影响 |
| --- | --- | --- | --- |
| P1-07 | 三代视觉系统叠加：文档规定的 Soft Pastel Studio（:root #5365d0，style.css:2919）被后写的 "Quiet Workspace" 层整个覆盖（:root #17191d，style.css:6445-6452,6483-6484），运行期蓝紫文档已失效，同屏出现紫焦点环+黑按钮混色 | `static/style.css:2919 vs 6445-6452`；`docs/ui_style_reference.md:38-56` | 文档与实现双轨失真，后续一切 UI 修改都会改错层 |
| P1-08 | `--font-family` 全仓未定义（3 处使用、0 处定义、无 fallback），整站回退浏览器默认字体；index.html:11 加载 12 个 Google 字体家族但无规则引用 | `static/style.css:26,78,141`；`static/index.html:11` | 排版与设计稿不符，字体下载纯浪费带宽（一行修复） |
| P1-09 | 步骤条 `<li class="step-item">` 无 tabindex/role/键盘事件，键盘与读屏用户完全无法切换步骤（违反 WCAG 2.1.1） | `static/index.html:92-133`；`static/event_bindings.js:81-95` | 唯一的工作流导航对辅助功能用户不可达 |

### 前端交互线（7 条，全部是"生命周期不随项目切换清理"一族）
| 编号 | 标题 | 位置 | 影响 |
| --- | --- | --- | --- |
| P1-10 | Step8 视频渲染轮询退出/切换项目后永不停止；`!res.success` 不终止轮询，404 时每 3 秒弹一次错误 toast（无限刷屏） | `static/output_render.js:30-80` | 渲染中退出后无限空转 + 错误弹窗刷屏 |
| P1-11 | PPTX 轮询同样不随项目/退出清理；守卫分支只 return 不 clearInterval | `static/output_render.js:200-233` | interval 永久泄漏，旧 jobId 轮询新项目 → 每 1.2 秒一次 toast |
| P1-12 | TTS 轮询最长 30 分钟不可取消；每 tick 用实时项目 id 拼 URL；共享按钮保持禁用 | `static/narration_audio.js:419-497` | 切换项目后旧轮询打新项目报错；新项目合成按钮被锁最长 30 分钟 |
| P1-13 | Step2 生成最长 15 分钟持有共享生成按钮禁用态（三段串联请求 timeout 900s） | `static/storyboard.js:307-357` | 切到项目 B 后 B 的 Step2 无法生成分镜 |
| P1-14 | 新建项目无提交锁，双击创建重复项目 | `static/projects.js:288-346`；`static/event_bindings.js:67` | 网络稍慢即产生重复项目 |
| P1-15 | `navigateToStep` await 后直接读 `state.currentProject.step_status`，退出工作区不递增导航版本，退出瞬间空引用异常 | `static/workspace_navigation.js:158-169` | 偶发未捕获异常，步骤面板停留中间态 |
| P1-16 | 数字人 job 轮询最长 2 小时不可取消；模块级 `dhState` 不随项目重置，跨项目写失败态 | `static/digital_human_panel.js:682-720, 13-29` | 旧任务 404 会把"failed"写进新项目 slides 状态；退出后轮询空转 2 小时 |

### 后端架构线（2 条）
| 编号 | 标题 | 位置 | 影响 |
| --- | --- | --- | --- |
| P1-17 | `visual_contract_service.py` import FastAPI `HTTPException`（AGENTS.md 明文要求其独立于 FastAPI），并经 `storyboard_planning.py:12` 传染给自称纯层的规划层 | `visual_contract_service.py:11,40-45`；`storyboard_planning.py:12,20-21` | 共享契约服务无法被脚本/测试轻量复用；纯层边界持续被侵蚀 |
| P1-18 | `_overall_progress` 统计 `status=="completed"` 但阶段状态写的是 `"done"`，**恒返回 0.0**；`GET /api/one-click-statuses` 对真实项目永远 progress 0.0；且被错误 fixture 固化（checks/test_manual_pause_steps.py:135-137 用 "completed" 造数据） | `one_click_orchestrator.py:1707 vs 463,604`；`one_click_routes.py:56-59` | 批量一键生成进度永远为 0，前端/Agent 无法展示进度（小改动，注意同时修测试） |

### 数据层线（2 条）
| 编号 | 标题 | 位置 | 影响 |
| --- | --- | --- | --- |
| P1-19 | 项目删除与视频删除均为"先删文件、后提交数据库"；视频删除入口对"文件已不存在"抛 404 不可重试 | `project_service.py:512-548`；`video_artifact_service.py:534-546` | commit 失败留下幽灵记录；视频场景文件已删、记录未删且重试永远 404，只能删项目兜底（正确对照：pptx_service.py:385-389） |
| P1-20 | `audio_timeline.json` 两处非原子写（裸 open/json.dump），而它是渲染输入指纹（artifact_fingerprint.py:91）与 Remotion 的输入 | `narration_audio_service.py:851-858, 1012-1018` | 崩溃截断→指纹漂移判 stale→重渲染解析失败中断 |

### 渲染管线线（2 条）
| 编号 | 标题 | 位置 | 影响 |
| --- | --- | --- | --- |
| P1-21 | manifest 的 canvas.background 被两处硬编码重置回 `#FEFDF9`（`_prepare_manifest_for_save`、`_project_reveal_canvas`），覆盖用户配置的视频背景；渲染路径构建前会重新同步所以视频正确，**reveal PPTX 导出直接读 manifest 且无同步** | `mask_manifest_service.py:605-610`；`reveal_manifest_service.py:58-66`；`pptx_reveal_export.py:195-197,273` | 配置了非默认背景的项目，导出的 reveal PPTX 背景色与视频不一致（用户可见缺陷） |
| P1-22 | Remotion 渲染失败/超时分支不清理已创建的 `output_path`，残留部分 MP4 被 `list_video_items` 列出（标 legacy）且带下载 URL | `remotion_runner.py:449-459`（对照 `:814-816` 仅颜色校验失败才删）；`video_artifact_service.py:254-267` | 用户可下载到损坏的"视频" |

---

## 5. P2 / P3 摘要（47 + 42 条，按审查线归档）

> P2 = 健壮性/可维护性/潜在 bug；P3 = 轻微/风格。每条保留 file:line，修复时按图索骥。

### D 线（后端架构）P2
1. `one_click_orchestrator.py`（1708 行）六类职责过载（状态存储/审查策略/限流/质量门语义/provider 预检/渲染对账）（:274-308, 813-902, 936-1007, 135-441, 600-615, 667-718）。
2. orchestrator 私有 `_read_json/_write_json`（:311-342）重复共享模块且**无并发保护**——worker 线程与 HTTP 线程并发写同一 `one_click_status.json`，可能互相覆盖丢状态；对照 `pipeline_lifecycle.py:77-102` 的带锁原子写。
3. `_complete` 绕过 `project_runtime_service` 直接 commit（:600-615）。
4. `pipeline_services.py:146-152,218`：`annotate_ai_mask` 绕开注入的 MaskPipelineOperations，且 `_project()` 直接抛 HTTPException（facade 耦合 HTTP）。
5. AI Mask 覆盖率阈值 0.995 双源（`one_click_orchestrator.py:960` vs `ai_mask_contracts.py:8`）。
6. `REVEAL_PIPELINE_VERSION` 字符串四处硬编码（server.py:186、pptx_reveal_export.py:476、scripts/build_reveal_scene.py:49、scripts/validate_reveal_scene.py:14）——与 G-P2-04 同根，收敛到 `ai_mask_contracts.py`。
7. Step2 Prompt 双轨：`/steps/2/prompt-preview`（storyboard_service.py:506-580 + storyboard_routes.py:165-171）与运行时实际 prompt（:742-744）不同源，且前端无调用方。

### D 线 P3
组合根内嵌 Step2 Prompt 正文与 legacy 哈希表（server.py:169-185）；`STEP2_LLM_TIMEOUT_SEC` 双源 240.0（server.py:192 / storyboard_service.py:52）；`json_llm_service.py:10,135-175` 抛 HTTPException；`storyboard_service.py:115-116` 的 lambda-throw 写法；本地残留 .bak×5、`_sandbox_test.txt`、`server_boot.log`（未跟踪）；`execute_step2` deprecated 路由无调用方（storyboard_service.py:1119-1137）。

### A 线（前端架构）P2
1. 三个扩展探测不存在的 `window.state`（顶层 const 不挂 window），恒走第二回退分支：`ai_mask_extension.js:70`、`storyboard_background_extension.js:35`、`style_reference_manager_extension.js:89`（另 flow.js:224）。
2. 四个扩展各自复制 API 传输封装、回退分支缺安全标记头（storyboard_background_extension.js:6,14-26、project_profile_extension.js:19-47、one_click_extension.js:66-85、style_reference_manager_extension.js:14-46）。
3. 共享工具在扩展 IIFE 重复实现：toast×6、esc×3、gcd×2、activeProjectId×2（各处行号见原报告；toast 缺失时静默降级 console.log）。
4. 跨模块魔法全局 `window.__pendingProjectParent`（courses.js:407 写、projects.js:319 清、project_profile_extension.js:370 清、projects.js:297-320 消费）。
5. 扩展用 setInterval 轮询安装 monkey-patch 包装导航函数（flow.js:283-291、style_reference_manager_extension.js:117-121、one_click_extension.js:197-201）。
6. `?v=` 缓存参数落后于文件修改日期（index.html:12、1476、1477、1479、1492、1494）——发版前统一 bump。
7. ownership guard 缺 6 个模块：courses.js、account_management.js、digital_human_panel.js、ip_character_manager.js、flow.js、ai_mask_auto_state.js（checks/test_frontend_quality.js:1-34）。

### A 线 P3
index.html 4 处内联 onclick（:81,685-686,768）；workflow_state.js:108 反向读 digital_human_panel.js:975 写的 `__dhEnabled`；9 个模块各自注册 DOMContentLoaded（settings.js:83 等，违反"唯一启动入口"字面约定）；mask_workspace.js:838 裸全局调 `deleteMaskBox`（实现实为 mask_editor.js:124，guard 归属判定失真 checks/test_frontend_quality.js:672-675）；PPTStudio 桥两种形状并存（workflow_state.js:112-129 frozen vs mask_editor.js:1048-1052 assign）；版本参数混用（flow.js?v=3.0.3 语义版 vs 日期戳）；static/ 下 3 个 .bak（未跟踪）。

### B 线（UI/CSS）P2
1. `!important` 共 1118 处（pastel 层之前仅 69，之后 1049）；`.canvas-wrapper`×6、`.sidebar`×6、`.step8-header`×7 等同选择器反复重定义——样式结果由加载顺序+!important 决定。
2. 已验证 30+ 死选择器：`.player-*` 整块（style.css:8745-8805）、`.step7-audio-card*`、`.system-settings-overview*`（event_bindings.js:24-28 还在绑定已删除 DOM）、`.vn-*` 约 12 个等（清单见原报告）。
3. 步骤条编号硬编码在 HTML（data-step="5"显示4、="9"显示6），flow.js:87-90 `visibleStepNumber()` 动态计算并存；且**无任何 JS 隐藏 data-step="9"**——未启用数字人时步骤条仍显示 7 项，与 AGENTS.md"仅启用时显示"不符。
4. `--border-color`/`--muted-color` 未定义且内联样式无 fallback（index.html:628,631,637,645,647,654,679；projects.js:191,205）→ 弹窗边框/风格卡片分隔失效。
5. 14 个弹窗仅 5 个有 `role="dialog"`；Esc 只对 modal-step3-ai 生效（event_bindings.js:161）；无焦点陷阱。
6. 对比度不足：`#8b94a5` 约 3.1:1（style.css:5515-5519）、`#888` 约 3.5:1（index.html:788,815,818）。
7. 首页内联 `padding: 2rem 4rem`（index.html:62）压过移动端媒体查询（style.css:4122-4125）。
8. 重复 id `dh-slide-status`（index.html:483 与 548）——第二处状态区永远不更新。
9. 遗留草图风格残留（index.html:369,574；style.css:288-296）。

### B 线 P3
JS 生成但无样式的类 5 个（.btn-label、.ai-mask-setting-input 等）；z-index 全表 47 处（step5 草稿提示与 toast 固定同角叠压）；`overflow-x:hidden` 掩盖溢出 + `min-width:max-content`（style.css:4308）；断点 11 种碎片化（600~1100）；遗留死 DOM（#step1-result-box、设置 tabs :699-881、#btn-open-settings）；aria 细节（tablist 无 aria-controls、108 个 label 无 for，其中系统设置弹窗约 25 个为真实问题）。

### C 线（前端交互）P2
1. API 返回的 URL/ID 类字段多处未转义拼入 innerHTML（images.js:201,340,596；narration_audio.js:392；output_render.js:342；storyboard_background_extension.js:245；ip_character_manager.js:186；courses.js:163 等）——当前均为服务端受控值，属加固项。
2. `escapeAttr` 不转义单引号（ai_mask_extension.js:82-84）。
3. （正面确认）用户/模型可控文本主路径转义到位。
4. `initStep6Narration`/`confirmStep3Images` 无提交锁、失败静默（narration_audio.js:21-30；images.js:643-650）。
5. 旁白保存裸 fetch 无超时，挂起时 `step6AutoSavePromise` 永不 settle 阻塞后续保存（narration_audio.js:293-316）。
6. 空 catch 吞错 6 处（storyboard.js:7-8、images.js:86,109-110、mask_workspace.js:574-580、digital_human_panel.js:79-81,167-169）。
7. select_menus.js 500ms 永久轮询 + body 全量 MutationObserver（:146-158）。
8. 共享确认弹窗并发调用互相覆盖回调（ui_foundation.js:41-75）。

### C 线 P3
原生 confirm() 双轨 5 处；删除语块无确认（mask_editor.js:124-137）；ip_character onclick 赋值式绑定；event_bindings.js:83-86 无空值保护；one_click followActiveStage 强行拉走用户当前步骤（one_click_extension.js:99-116）。

### F 线（安全）P2
1. CSRF 防护仅在 Origin 头存在时生效（app_security.py:108-120）。
2. 数字人视频/头像上传整体读入内存（默认 2GB/200MB 上限，digital_human_routes.py:42-44,307,365）→ 本地 DoS。
3. legacy 环境变量令牌（PPT_AGENT_API_KEY）scopes 为空集跳过全部 scope 判定（agent_api/auth.py:95-99,138）。
4. 部分端点上传校验仅 Content-Type/扩展名，无 magic bytes（被服务端重命名+PIL 重编码部分缓解）。
5. 主 /api 无速率限制/并发闸门（仅 agent_api 有 rate_limit.py）→ 高成本任务可被无限触发。
6. 日志脱敏仅按键名匹配（project_runtime_service.py:35-47；tts_provider_service.py:278-289）。

### F 线 P3
查询串令牌会进 uvicorn 访问日志（app_security.py:49-58；agent_api/auth.py:70-73）；`verify_access_token` 允许 POST+查询串令牌与全局规则不一致；/docs、/openapi.json 默认暴露（server.py:143）；digital_human run_dir 未走 project_storage 校验（:108,187-194）；CORS allow_credentials=True 配宽来源有风险（server.py:146-159）；账号 cookie 无 Secure 标志（account_routes.py:65）；AccountContextMiddleware 覆盖静态文件请求每次开 DB 会话（server.py:163，性能）。

### E 线（数据层）P2
1. 渲染成功的"记账提交"在数分钟长会话之后，失败即整体判败且产物不入库（video_render_service.py:600-707）——应独立短 session。
2. `write_json_atomic` 兜底路径退化为非原子直接覆盖（pipeline_lifecycle.py:100-106）。
3. 启动期孤儿任务恢复是"全表杀"，假设单进程（video_job_store.py:336-357；pptx_service.py:409-445；server.py:862-870 import 期执行）——多实例/多 worker 会互杀任务。
4. 其余非原子写者：step3_image_style_service.py:43-45、project_style_reference_store.py:30-32、image_style_reverse_service.py:132-134、storyboard_background_render.py:36、ai_mask_component_detection.py:27-35。
5. legacy out.mp4 镜像复制非原子（video_artifact_service.py:319-322,559-566）→ 下载可能拿到截断文件。

### E 线 P3
PRAGMA 只作用于单个连接（database.py:254-261）；UTC naive 与本地时间混用（database.py:30-32 vs 197,224-227）；项目删除不清 `agent_idempotency_records`（project_service.py:537-547）；跨进程 IntegrityError 被归为不可重试（video_job_store.py:164-170）；凭据明文为已知设计残余（控制链完整）。

### G 线（渲染管线）P2
1. 手动 AI Mask 路径对覆盖率门禁只记录不拒绝（ai_mask_engine.py:507-543），渲染链路完全不检查——门禁仅在 one-click 是硬阻断（one_click_orchestrator.py:952-985）。
2. 覆盖率门禁被"强制最近锚点补全"结构性满足，接近恒真（ai_mask_assignment.py:776-834,845-852）——99.5%/零未分配/零重叠退化为二元检查，语义错配仅 warning。
3. 确定性 fallback 匹配写死 confidence 0.86 冒充高置信度，绕过人工复核标记（ai_mask_assignment.py:108-114；ai_mask_manifest_apply.py:57-63,307-308）——模型整体失败时产物显示"AI 已确认无需复核"。
4. pptx_reveal_export.py:476 硬编码管线版本字符串且未被测试固定（对照 checks/test_reveal_pipeline_isolation.py:22,83 只钉了 server.py 与 build_reveal_scene.py）。
5. 调速变体重编码不带 bt709 三参数但 sidecar 整体继承源 sidecar 的颜色声明（video_artifact_service.py:403-427,477-488）。

### G 线 P3
`remotion_runner._render_video` 绕过注入的子进程依赖（:431-439）；scene.json 非原子写（storyboard_background_render.py:35-36）；pptx 双实现细节漂移（notes 读取/备注页数/异常残留临时 PNG，pptx_reveal_export.py:162-169,402-403,409-417）；`_safe_unlink` 改名后可能遗留孤儿 sidecar（video_artifact_service.py:46-64）；背景变更无条件把 current_step 回拨到 3（invalidation_service.py:196）；换图后 manifest 顶层 `ai_mask_annotation` 质量块不清除（invalidation_service.py:113-145）。

---

## 6. 未完成审查线 H 的执行任务书

### 6.1 D 线已确认的事实（接手 agent 不要重复验证，直接采信）

- `py -3 scripts/generate_agent_contracts.py --check` 输出 `OK: docs\agent\capability-matrix.md is up to date`。
- `agent_api/routes.py` 的 28 条路由与 `agent_contract/capabilities.py` 一一对应（`checks/agent/test_transport_contract_sync.py` 强制校验）。
- digital_human 4 个 capability 已注册（capabilities.py:330-379）；account 身份经 `ppt_identity_get` 覆盖（:80-87）；course/creation_config 字段已入 parity 映射表；model_connection/credential/ip_character 无 Agent-facing 路由、不注册属合理决定。
- parity 测试（checks/agent/test_contract_model_parity.py:20-64）会在内部模型加字段时强制登记决策，机制运转正常。

### 6.2 H 线剩余范围（可直接复制的子代理 prompt）

```text
你是资深质量工程审查员，对仓库 C:\Users\Administrator\Desktop\软件\PPT_presentation_video 做一次只读审查。
这是 FastAPI 的 PPT 视频生产管线项目，带外部 Agent 集成面（Agent API / MCP / CLI）。

【硬性约束】绝对不要修改、创建或删除任何文件；只允许 Read/Grep/Glob 和只读 bash 命令。
先读 AGENTS.md 的「Agent Contract Synchronization Policy」和「Required Validation」两节。
注意：以下结论已被前一轮审查确认，不要重复验证，直接采信并跳过：
(a) scripts/generate_agent_contracts.py --check 通过；(b) agent_api 28 条路由与 capabilities 一一对应；
(c) digital_human/account/course/creation_config/model_connection 的注册决策已落实且 parity 测试强制。

请只审查以下剩余范围，每条给 file:line 证据：
1. 测试覆盖缺口全景：对照 AGENTS.md「Required Validation」列出的每条命令，确认对应 checks 文件真实存在且命令可运行（只读校验，不实际跑 pytest 全套）；
   统计关键生产模块的直接测试数量：one_click_orchestrator.py、video_render_service.py、tts_service.py、creation_config_service.py、image_workflow_service.py、digital_human_service.py。
2. 僵尸测试：checks/ 中 import 了不存在模块/路径、或断言已删除行为的测试（用 grep 抽样 import 路径并核对目标文件存在性）。
3. mcp_server/、agent_client/、cli/ 的实现质量与重复度：是否各自实现了业务逻辑（违反单一事实来源），还是都委托给同一 service 层；错误处理与鉴权是否与 agent_api 同标准。
4. CI 配置（.github/）：Required Validation 是否进了 CI workflow，还是只靠手动；workflow 引用的命令/路径是否有效。
5. checks/test_frontend_quality.js ownership guard 的精确缺口：已知 courses.js、account_management.js、digital_human_panel.js、ip_character_manager.js、flow.js、ai_mask_auto_state.js 六个模块无 guard——验证此清单并检查 guard 内部断言是否有误报归属（已知一例：deleteMaskBox 归属判定失真）。
6. agent_idempotency_service.py 与 agent_contract/operations.py 的质量：幂等键设计、CHECKPOINT_STAGES 与实际管线阶段是否一致。

输出（中文）：按 P0/P1/P2/P3 分组。每条必须包含：标题、位置 file:line、证据、影响、一句话修复建议。
只报告有证据的问题。最后 3-5 句总体评价（重点：Agent 集成面与测试保障的可信度）。
```

---

## 7. 实机 UI 验证方案（推荐下一步执行）

静态审查已覆盖大量问题，但以下几条最值得在真实浏览器里复现确认（也是对静态结论的抽验）：

### 启动方式
- 参考 `launch.bat` / `start_here.bat` / `run_local.bat` / `py -3 start_server.py`（端口由 `pick_port.py`/`check_port_free.py` 决定，注意看启动日志实际端口）。
- 首次启动前看 `.env.example` 需要哪些配置；不需要真实 API key 也能打开 UI 外壳与项目库。
- 注意：启动会触发 job recovery（server.py:862-870 会把遗留 active 任务标 interrupted），这是正常行为，验证完正常关闭即可。

### 逐项验证清单（对应静态发现）
| # | 验证点 | 对应问题 |
| --- | --- | --- |
| 1 | 进入任一项目 → 步骤 4（Mask 标注）→ 点「放大标注/全屏」→ 点工具栏「字幕设置」「动画设置」→ 弹窗是否被全屏面板遮住不可见 | P0-07 |
| 2 | 首页新建项目弹窗：双击提交按钮 → 是否创建出两个同名项目 | P1-14 |
| 3 | Tab 键能否把焦点移到步骤条并用回车切换步骤 | P1-09 |
| 4 | DevTools 查 `getComputedStyle(document.body).fontFamily` 是否为设计字体（预期会显示浏览器默认字体） | P1-08 |
| 5 | 未启用数字人功能时步骤条是否仍显示 7 项（含"数字人讲解"） | B-P2-3 |
| 6 | （启用数字人时）面板第④区"位置与缩放精调"下的状态行是否永远空白 | B-P2-8 |
| 7 | 准备两个项目，在 A 项目步骤 2 输入后 0.7 秒内退回首页并进入 B 项目 → 检查 B 的分镜是否被 A 覆盖（**在测试项目上做，避免污染真实数据**） | P0-04 |
| 8 | 渲染过程中退出工作区再进入其它项目 → 观察是否出现每 1~3 秒一次的错误 toast 刷屏 | P1-10/P1-11 |
| 9 | 打开浏览器控制台收集整页错误；Network 面板看是否有 403（若开启访问控制，上传 Step3 参考图/背景图必现） | P1-05 |
| 10 | DevTools 查 `window.loadProjects.toString()` 是否已被 courses.js 覆盖为 CourseTree 版本 | P1-06 |

截图建议存放到 `runs/` 或临时目录（不要提交），报告里附路径。

---

## 8. 后续审核计划（推荐执行顺序）

1. **阶段 1 — 补齐 H 线**：按 §6.2 的 prompt 派 1 个子代理执行（一次只派 1 个，见 §1 注意事项）。
2. **阶段 2 — 实机 UI 验证**：按 §7 清单在浏览器里逐项复现并截图，确认/修正静态结论。
3. **阶段 3 — P0 修复评审**：修复 PR 逐条对照 §3 的 8 条；每条修复后运行对应回归（AGENTS.md「Required Validation」的相关子集 + 该问题的最小复现脚本）。
4. **阶段 4 — P1 分批修复**：建议按"同根因打包"推进：
   - 批次 A（鉴权 fail-closed）：P0-01/02/03 + P1-01/02 —— 同一根因；
   - 批次 B（前端生命周期清理中心）：P0-04/05/06 + P1-10~16 —— 在 `exitWorkspace/enterWorkspace` 建统一清理（清定时器、停轮询、作废在飞请求），所有 async 状态提交补 projectId 校验；
   - 批次 C（数据完整性小修）：P0-08、P1-19、P1-20、E-P2 各非原子写者 —— 统一收敛到 `write_json_atomic` + 锁；
   - 批次 D（UI 一行修复群）：P0-07、P1-08、P1-09、B-P2-4（补 CSS 变量）、B-P2-8（重复 id）；
   - 批次 E（管线一致性）：P1-21、P1-22、G-P2 各条。
5. **阶段 5 — P2/P3 排期**：优先 CSS 五代层合并（B-P2-1/2）与扩展模块传输封装去重（A-P2-2/3），这两项是后续一切 UI 迭代的地基。
6. **阶段 6 — 修复后全量回归**：跑 AGENTS.md「Required Validation」全清单（注意用 `py -3` 替代 `python`；`node --check` 验证前端语法；`Push-Location scripts/remotion; npm install; npx tsc --noEmit; Pop-Location` 为 PowerShell 语法，Git Bash 下用 `cd scripts/remotion && npm install && npx tsc --noEmit -p tsconfig.json`）。

## 9. 修复优先级 Top 10（跨线排序，按 风险×修复成本）

| 排名 | 问题 | 理由 |
| --- | --- | --- |
| 1 | P0-08 reveal_manifest 旁路写者 | 核心资产不可再生，修复约 3 行 |
| 2 | P0-04/05/06 前端跨项目污染族 | 静默损坏用户数据，且用户多项目并行使用概率高 |
| 3 | P0-07 全屏 z-index | 功能完全不可用，修复 1 行 |
| 4 | P0-01/02/03 + P1-01/02 鉴权 fail-closed 族 | 若坚持"本机单用户"定位可降级处理，但多账号代码已存在就应闭环；重点是 fail-closed 默认值 |
| 5 | P1-18 one-click 进度恒 0 | 用户可见的功能 bug + 测试固化，修复小 |
| 6 | P1-05 上传缺请求头 403 | 开启访问控制即功能不可用，修复小 |
| 7 | P1-21 reveal PPTX 背景脱节 | 用户可见输出错误 |
| 8 | P1-19 删除顺序 | 幽灵记录不可自愈 |
| 9 | P1-08 --font-family + P1-09 步骤条键盘 | 一行修复 + 小改，体验收益大 |
| 10 | P1-10~12 轮询清理族 | 稳定性/体验硬伤 |

## 10. 附录：正面确认（避免接手 agent 误报或"误修"）

以下项经本轮审查确认**合规且实现良好**，不要作为问题重报，重构时注意保持：

- **后端边界**：server.py 全文 0 个顶层 def/class（组合根纯度）；24 个 service 模块 0 个 `import server`/`Depends`/`APIRouter`/`get_db` 违规；无 monkey-patch、无 `register_*_routes(server_module)`、无 runtime_project_*；`create_all` 未复活。
- **迁移体系**：migrations/ 0001-0013 连续 + SHA-256 checksum + 单事务执行；invalidation_service 全文无 commit（纪律成立）。
- **任务状态机**：成功清 error=NULL、启动孤儿标记 interrupted、渲染提交幂等（submission_key）、artifact 注册/删除对称（单进程内全部成立）。
- **渲染管线**：渲染前"重建→背景同步→校验→拒绝孤儿资产"链路闭合；build_reveal_scene 无语义重匹配；23 个动画 action 与 TS 契约逐字段一致；颜色门禁（bt709 + ffprobe 回读）在主渲染路径成立；并发锁（按项目 RLock + 渲染锁显式移交 + one-click 原子启动）无死锁。
- **前端**：脚本加载顺序与 AGENTS.md 一致；323 个顶层函数名零冲突；escHtml/showToast 单点定义；用户/LLM 可控文本主渲染路径转义到位；projects/courses 渲染用户内容过 escHtml。
- **安全正面项**：路径穿越防护体系完整（resolve+relative_to 白名单）；subprocess 全列表参数、全仓无 shell=True；secrets.compare_digest；Agent 令牌只存 SHA-256；TTS 密钥环境变量传递 + 输出脱敏；YAML 全 safe_load；静态 mount 仅 static/（runs/outputs 未暴露）；无 eval/exec/pickle/verify=False。
