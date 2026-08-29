# 代码审查报告（2026-08-29）

> 只读审查，未修改任何生产代码。本报告为唯一产出物。

## 1. 审查元信息

| 项 | 值 |
| --- | --- |
| 审查基线 | `main` @ `88912ee`（fix: 阶段四代码质量优化 L-01~L-03, M-06），工作区干净（仅未跟踪 `.zcode/` 会话目录） |
| 环境 | Windows 11 (10.0.26200) / Python 3.13.0 (`py`) / Node v24.11.0 / Git Bash |
| 代码规模 | 顶层 Python 模块 99 个（约 31,136 行）；`static/*.js` 30 个（约 11,574 行）；`scripts/*.py` 30 个；`checks/` 测试 99 项；Remotion TypeScript 工程 1 个 |
| 覆盖方式 | ① 服务层/路由层 37 个文件（约 1.5 万行）由深度审查代理逐文件阅读并系统性 grep 验证；② 其余范围（组合根、安全、数字人子系统、前端、验证套件）由主审查逐行/逐项自查；③ 代理的最重发现（本报告 H-02、H-03、M-03、M-07、L-02）已由主审查逐条回读源码交叉复核确认 |

最近提交史显示 `2e4ce04` → `88912ee` 是一轮此前审计的修复系列（C-01~C-02、H-01~H-05、M-01~M-05、L-01~L-03）。本次审查是对该修复系列的验证与新一轮独立审查。

## 2. 执行摘要

**总体结论：代码库架构健康度高，AGENTS.md 模块边界契约执行情况优秀——但当前 HEAD 存在 1 项发布门禁红灯、2 项数据损坏级缺陷（契约文件非原子写入、Mask 清单锁外读改写）和 9 项应尽快处理的 Medium 问题。**

统计：High 3 项、Medium 9 项、Low 14 项、正面发现 13 项。

- 组合根 `server.py` 完全纯净：0 个顶层业务函数、0 个路由装饰器、20 个 router 全部显式注册且失败即 raise，无 `SimpleNamespace`/`server_module`/`register_*routes` 回潮。
- 全部依赖注入为冻结 dataclass（与 AGENTS.md 签名逐字吻合）；视频任务以 SQLite 为唯一事实源，`_UNSET` 哨兵精确区分"不更新 error"与"清空 error"。
- 全仓（含 scripts）**无任何 `shell=True`**；所有子进程走有界/可杀进程树封装。
- 安全基线扎实：`app_security.py` 的令牌 + CSRF 自定义头 + Origin 白名单设计质量高；密钥仅经环境变量传输。
- 风险集中在三处：**上传通道的内存读取模式**、**两个核心 JSON 工件的持久化/并发写缺陷**、**数字人（Step 9）新特性带来的契约漂移**——最后者已导致 AGENTS.md 要求的 `node checks/test_visible_flow.js` 在 HEAD 上失败。

## 3. 必需验证套件执行结果

AGENTS.md "Required Validation" 逐条实测：

| 命令 | 结果 |
| --- | --- |
| `py -m compileall -q *.py scripts checks` | ✅ 通过 |
| `node --check` 全部 30 个 `static/*.js` | ✅ 全部通过 |
| `node checks/test_visible_flow.js` | ❌ **失败**（期望 `[1,2,3,5,6,8]`，实际 `[1,2,3,5,6,9,8]`）→ H-01 |
| `py -m pytest checks/test_database_migrations.py checks/test_invalidation_service.py -q` | ✅ 13 passed |
| `py -m pytest checks/test_source_runtime_safeguards.py -q` | ✅ 通过（同批执行） |
| `py checks/test_reveal_mask_integrity.py` 等 5 个 reveal/音频检查脚本 | ✅ 全部通过 |
| `npx tsc --noEmit -p tsconfig.json`（scripts/remotion） | ✅ 通过 |

追加执行的守护测试（超出 AGENTS.md 最低要求）：

| 测试 | 结果 |
| --- | --- |
| pytest: test_app_security / test_config_export_security / test_config_import_limits / test_image_upload_limits / test_architecture_size_boundaries | ✅ 18 passed |
| `node checks/test_frontend_quality.js`、`test_ai_mask_auto_state.js`、`test_mask_zoom_coordinates.js` | ✅ 通过 |
| pytest: test_css_source_of_truth.py | ✅ 通过 |

## 4. 发现清单

严重级别定义：**High** = 发布门禁失败或可导致数据损坏；**Medium** = 安全/一致性/契约缺陷，应尽快修；**Low** = 债务与打磨项。

### High

**H-01 必需验证套件在 HEAD 上失败：`checks/test_visible_flow.js:8`**
- 证据：`static/flow.js:41-47` 新增可选步骤 9（数字人讲解，`optional: true`，位于步骤 6 与 8 之间），`VISIBLE_FLOW_STEPS` 变为 `[1,2,3,5,6,9,8]`；而 `checks/test_visible_flow.js:8` 仍断言 `assert.deepEqual(flow.VISIBLE_FLOW_STEPS, [1, 2, 3, 5, 6, 8])`。
- 实测输出：`AssertionError ... actual: [1,2,3,5,6,9,8], expected: [1,2,3,5,6,8]`。
- 影响：AGENTS.md 列为发布前必跑的命令红灯。更隐蔽的是**断言失败掩盖了其后的 `mapClientPointToCanvas` 坐标映射断言**——该断言在本轮完全未执行，其正确性当前无证据。
- 建议：更新测试期望（或明确可选步骤不计入 `VISIBLE_FLOW_STEPS` 基线的口径），确认后续断言恢复执行。

**H-02 `visual_contract.json` 非原子写入，同文件双写风格不一致**（已交叉复核）
- 证据：`storyboard_service.py:866-867`（`finalize_step2_contract`）与 `:1009-1010`（`update_step2_result`）使用裸 `open(contract_path, "w") + json.dump`；而同模块 `repair_step2_result`（:980）、空分镜路径（:1030）及 :422/:451/:606/:645 均用 `write_json_atomic`（:27 已导入）。
- 影响：`visual_contract.json` 是图片/Mask/旁白/渲染全链路的唯一输入，进程崩溃或断电可产生截断文件；与 AGENTS.md 原子生命周期要求不一致。
- 建议：两处改为 `write_json_atomic(contract_path, ...)`。

**H-03 `refresh_reveal_semantic_blocks` 对 `reveal_manifest.json` 锁外读取、锁内回写，存在丢失更新窗口**（已交叉复核）
- 证据：`mask_manifest_service.py:407-408` 在锁外 `read_text` 读入 manifest 与 contract，经长段处理后 `:451-452` 在 `reveal_lock_for(project)` 内整体回写。对照 `get_step5_result`（:483）已正确在锁内读。
- 影响：Step 5 工作区并发（如 `update_step5_draft` :652 锁内保存草稿/手动 Mask）时，语块刷新基于过期快照整体覆盖，**静默丢失用户刚保存的 Mask 编辑**。锁为按 run_dir 的可重入 RLock（`project_runtime_service.py:31-32`），把读取移入锁内无死锁风险。
- 建议：manifest/contract 读取移入 `reveal_lock_for` 块内。

### Medium

**M-01 上传端点"先无界读入内存、后校验"模式，且一处完全无上限**（合并复核）
- 无界读取 + 事后校验（数字人 3 处，校验前全量载入 RAM）：
  - `digital_human_routes.py:258-259`（视频，2GB 上限）、`:315-316`（头像，500MB）、`:360-361`（工作流 JSON，1MB）；
  - 另 `storyboard_background.py:260`、`image_style_reverse_service.py:261`（12MB 上限，先读后检）。
- **完全无上限**：`project_style_routes.py:391` 风格参考图上传仅有张数限制（1-3 张）与非空检查，**无单文件字节上限、无 MIME 校验**。
- 正确示范（修复系列已落地的 `read(MAX+1)` 有界模式）：`ip_character_service.py:232`、`global_image_style_service.py:654`、`image_workflow_service.py:595`、`digital_human_service.py:681`。
- 影响：Starlette 先将任意大小请求体 spool 到磁盘（可被填满），随后全量进内存——2GB 视频上传即 2GB 内存峰值，且在拒绝前发生。
- 建议：统一改为有界读取/流式截断；参考图入口补 12MB + `image/*` 校验（对齐仓库既有 12MB 标准）。

**M-02 头像大小双限制不一致（500MB vs 200MB），错误码与提交说明均不一致**
- 证据：主应用路由 `MAX_AVATAR_UPLOAD_BYTES = 500MB`（`digital_human_routes.py:44-45`，超限 413）；请求经 `DigitalHumanClient.upload_avatar`（`digital_human_client.py:59-68`）代理至独立服务，其上限 `MAX_AVATAR_BYTES = 200MB`（`digital_human_service.py:54-56`，超限 400）。
- 提交 `88912ee` 声称 "L-02: MAX_AVATAR_BYTES 500MB→200MB"，但只改了服务侧，路由侧未动：300MB 头像被主应用放行、被下游以不同状态码拒绝。
- 建议：以 200MB 为准统一两处（或路由直接引用服务侧单一常量）。

**M-03 `repair_step6_result` 变更旁白但不清除音频确认**（已交叉复核）
- 证据：`narration_service.py:200-210` 经 `sync_narration_beats_to_contract(project)` 改写 beats 后直接返回，无任何 invalidation 调用；而 `update_step6_result`/`annotate_step6_narration` 均经 `handle_step_navigation` → `complete_stage(6)` → `clear_audio=True`（`invalidation_service.py:61-64`）。
- 影响：违反 AGENTS.md "Editing narration clears audio confirmation"；可导致以旧音频渲染新分镜。
- 建议：`changed` 为真时补等价失效调用。

**M-04 `start_server.py` 顶层 `import server`，pytest 收集期触发完整组合根副作用**
- 证据：`start_server.py:16` 顶层 `from server import app`；`checks/test_start_server_security.py:7` 在收集期 `from start_server import ...` → 连带执行整个 `server.py`（`init_db()`、`ensure_active_image_style_storage()`、20 个 router 注册、任务恢复）。
- AGENTS.md 明文禁止："End-to-end entrypoints must not import `server` at module import time ... so test discovery cannot mutate live job recovery state."。
- 建议：`from server import app` 移入 `main()`；`_is_loopback_host` 等下沉到无副作用小模块供测试导入。

**M-05 AGENTS.md 六步契约与 Step 9（数字人）漂移**
- 证据：AGENTS.md 全篇仍声明 "six user-visible steps" 且映射表无数字人；代码中已存在 Step 9 与 4 个生产文件（`digital_human_routes.py` 780 行、`digital_human_service.py` 924 行独立微服务、`digital_human_client.py`、`static/digital_human_panel.js`）；`server.py:138` 应用描述仍是"本地手绘线稿风"（UI 事实源已是 Soft Pastel Studio）。
- 影响：AGENTS.md 是本仓库治理核心，漂移会使后续贡献者按错误契约开发——H-01 即其直接后果。
- 建议：更新 AGENTS.md（六步 + 可选数字人增强口径）、补 Step 9 工件映射、修正描述字符串。

**M-06 Step 3 风格模板存储业务逻辑落在路由模块，违反 AGENTS.md 归属契约**
- 证据：`project_style_routes.py:552-859` 内实现 `_templates_root`/`_read_templates`/`_write_templates`/`_builtin_style`/`save_step3_template`/`apply_step3_template`/`delete_step3_template` 全套持久化逻辑，路径计算绕过 `repository_paths.py` 唯一路径源；该文件达 859 行（路由层最长）。
- AGENTS.md 明文："storage, reference generation, reverse analysis, and templates live in normal `project_*_service.py` / `*_store.py` modules"。
- 建议：迁移至 `project_style_template_service.py` / store，路由只留 HTTP 壳。

**M-07 数字人合成发生在颜色校验之后，`.render.json` 颜色元数据描述的是合成前视频**（已交叉复核）
- 证据：`video_render_service.py:384-403` `runner.run(...)`（内含 bt709 校验，`remotion_runner.py:70-74`）之后才执行 `_apply_digital_human_composite`，`os.replace(composite_out, result.output_path)` 替换成片；`:427-433` 元数据仍记录 `color_standard: bt709_tv_yuv420p` 与合成前的 `color_validation`。
- 影响：启用数字人时最终 MP4 未复验，sidecar 颜色声明可能失实。
- 建议：合成后重跑容器颜色校验，或在元数据中标注 composite 状态。

**M-08 纯层校验函数对用户手动编辑返回 500，HTTP 语义混乱**
- 证据：`storyboard_planning.py:99,117,127,331,346` 抛 `HTTPException(500)`；这些纯函数被手动编辑接口复用（`storyboard_service.py:664,712`）——用户 PUT 缺 `slides`/`narration` 的合法格式错误会得到 500。
- 建议：纯层抛领域异常（`PlanningError` 等），由 service 映射 400/422；AI 输出问题（502/422）与用户输入问题（400）分离。

**M-09 TTS 合成在 HTTP 请求内同步跑完全部 slide，且存在成对重复代码**
- 证据：`tts_service.py:156-358` 约 200 行逐页同步合成 + 末尾子进程；对比视频/PPTX 已用持久化后台任务。重复块 A：`tts_service.py:189-199` 与 `:401-412` 完全相同；重复块 B：`bind_reveal_timeline` 调用出现 3 处（`tts_service.py:320-328`、`:419-427`、`remotion_runner.py:146-165`）。
- 影响：合成需数分钟，客户端断连后无法像视频任务那样轮询恢复。
- 建议：长期迁 `local_jobs` 后台任务；短期抽公共 helper。

### Low

- **L-01 服务层端点函数残留 `Depends(get_db)` 死耦合**：`storyboard_service.py`（17 处，:530/:557/:590/:597/:613/:650/:658/:669/:699/:707/:717/:747/:918/:936/:964/:988/:1063）、`narration_service.py:14,18,107,163,200,390,507`、`tts_service.py:12,16,156,360,375,390`。实际调用全部由 `*_routes.py` 显式传参，默认值永不生效（`server.py` 确认无双注册）；与 mask/image/step3 服务的"零 FastAPI 耦合"契约不一致。建议统一改纯 `db: Session` 必填参数。
- **L-02 跨层导入绕过真实归属**：`image_workflow_service.py:41` `from storyboard_service import read_prompt_template`，真实归属 `storyboard_prompt_templates.py:84`，经 service 导入会连带拉起其模块级注入全局。（已交叉复核）
- **L-03 `ALLOWED_VIDEO_MIMES` 含 `application/octet-stream` 通融项**：`digital_human_routes.py:47-50`，任何声明为 octet-stream 的文件均过 MIME 关（大小上限仍生效）。已知权衡，建议以扩展名白名单复核。
- **L-04 数字人面板 `innerHTML` 字符串拼接**：`static/digital_human_panel.js:633,645,740,749`。当前插值均为服务端枚举与数字，风险低；与 `escHtml` 规范不一致，易被复制出漏洞。
- **L-05 数字人独立服务无令牌认证**：`digital_human_service.py:596-624`（`:9001`）仅有 localhost Origin 守卫 + 白名单 CORS。本地单用户威胁模型内可接受；绑定非回环地址前需补认证。
- **L-06 跨模块调用下划线私有函数**：`project_style_routes.py` 13+ 处（:101,:110,:135,:192,:256,:268,:338,:360,:388,:414,:447,:466,:751,:758）及 `storyboard_service.py` 等调用 `_save_step3_style`/`_write_normalized_manifest`/`_generate_image_style_with_llm`/`_references_dir` 等。建议补公开包装收窄。
- **L-07 HTTP 状态码一致性**：体积超限多返回 400 而非 413（`image_workflow_service.py:596-599,615-616`）；全仓无 415。属一致性债务。
- **L-08 `_deps()` 未配置时返回可用默认值而非快速失败**：`mask_manifest_service.py:57-74` 默认 `repo_root=Path(".")`、`python_executable="python"`；对照 `mask_preview_service.py:50-53` 直接 raise。配置遗漏会表现为诡异子进程失败。
- **L-09 `_safe_unlink` 的 `.deleted` 兜底永不清理**：`video_artifact_service.py:52-56` 重命名为 `.deleted` 并注释"下次删除时清理"，但 `delete_video`（:480-528）无扫描清理逻辑，文件长期滞留并脱离 registry。
- **L-10 全局风格 `style_tokens.yaml` 直写非原子**：`global_image_style_service.py:398-405` 裸 `open+yaml.safe_dump`（同模块 :571 已用 `write_json_atomic`）；`read_style_tokens_data`（:109）对缺失无兜底。
- **L-11 零散死代码与样板重复**：`storyboard_service.py:849-855` 与 :860-865 首尾重复赋值（前段死代码）；`remotion_runner.py:397,437` 函数内重复 `import json as _json`，:370-408 与 :410-448 两个 ffprobe 探测近乎重复；`one_click_orchestrator.py:424-427` try/except pass 死代码，`_run_pipeline`（:552-776）约 220 行可拆；项目查询样板 `db.query(Project).filter(...).first()` 重复 38 处（storyboard 16 / image 13 / narration 5 / tts 4），`_project_or_404` 在 4 个路由文件各写一份。
- **L-12 跨线程释放非重入锁的脆弱写法**：`video_render_service.py:470-473` worker 线程 `finally` 中释放请求线程获取的锁（:185 获取）。当前时序成立，但依赖隐式协作；建议记录持有者或改由获取方管理。
- **L-13 零散防御缺失**：`video_artifact_service.py:171` `target.stat()` 无 try（与删除竞态时 500）；`narration_service.py:140` `s["slide_id"]` 遇脏 contract KeyError → 500。
- **L-14 未跟踪目录 `.zcode/` 未入 `.gitignore`**：会话运行时数据，按"runtime data is never committed"精神应忽略。

## 5. 正面发现

1. **`app_security.py`（160 行）设计质量高**：恒时令牌比较、非 GET/HEAD 拒绝查询串令牌并以 303 + HttpOnly Cookie 升级、CSRF 要求 `X-PPT-Studio-Request` 头 + Origin 白名单、豁免路径可配置、幂等安装；18 项配套测试通过。
2. **组合根纯净且失败即崩**：`server.py` 986 行无业务函数/路由装饰器；每个 router 注册块 try/except 后 `raise`，不静默降级。
3. **视频任务持久化契约执行到位**：`video_job_store` 以 SQLite 为唯一事实源（expunge + `_UNSET` 哨兵，`video_job_store.py:124-145`）；成功路径显式 `error=None`（`video_render_service.py:804-808`）；中断恢复 `interrupt_orphaned`；内存 `_tasks` 仅作兼容缓存且有 50 条裁剪。
4. **依赖注入全部为冻结 dataclass**：Storyboard/ImageWorkflow/VisualSettings/VideoRender/RemotionRunner/PptxService（签名与 AGENTS.md 逐字吻合）/OneClick/PipelineOperations 等，grep 零 `SimpleNamespace`/`server_module`。
5. **失效链路完整**：`invalidation_service` 纯文件+状态变更、从不 commit；换图/删图/候选应用/拖拽全部汇聚 `slide_images_changed` → 清 Mask、reveal 产物、音频确认、remotion_props。
6. **路由层薄且异常翻译规范**：`video_routes`/`pptx_routes`/`mask_editor_routes` 的 `_service_call`/`_translate_error`；428（乐观锁）、409（冲突）、404 语义准确；`pptx_export.py` 为范本级实现（readiness 门 + 临时文件 `os.replace` 原子落盘 + 指纹复核）。
7. **纯层分离质量高**：`storyboard_planning/profiles/llm/prompt_templates` 未被 service 重复实现；`visual_contract_service` 写契约前统一拦截 slide_id 路径穿越（:18-44）；`reveal_lock_for` 与 `project_artifact_lock` 为同一按 run_dir 的可重入锁，全链路无嵌套死锁。
8. **子进程卫生**：全仓零 `shell=True`；`run_subprocess_killable` 进程树击杀（`digital_human_service.py:84-97` 明确解决 Windows 只 kill 直接子进程的坑）；`remotion_runner.py` 各阶段独立超时。
9. **路径穿越防护**：`digital_human_service.py:117-131` `_assert_path_safe` 白名单根 + `resolve().relative_to` 实现正确。
10. **迁移链健康**：`migrations/0001-0004` 连续编号，checksum 校验测试通过；无 `create_all`/启动期 ALTER 回潮。
11. **上传正确示范已成主流**：4 处 `read(MAX+1)` 有界模式（含空 400 / 413 / 415 三段式 `_validate_upload`）。
12. **前端契约执行到位**：`index.html` 脚本顺序完全符合 AGENTS.md；`projects.js` 无内联 handler；`test_frontend_quality.js` 所有权守卫通过。
13. **数字人客户端健壮**：`httpx` 持久连接 + `trust_env=False`（附清晰的代理坑位说明）、全调用显式超时、错误统一翻译为 `DigitalHumanUnavailable`。

## 6. AGENTS.md 边界合规矩阵

| 契约 | 结果 |
| --- | --- |
| 服务模块不 `import server` | ✅（唯一命中 `start_server.py` 为启动器 → M-04） |
| 服务模块不拥有 APIRouter / 路由装饰器 | ✅（`*_routes.py` 独占装饰器；Depends 残留 → L-01） |
| 无 `SimpleNamespace` / `server_module` / `register_*routes` 回潮 | ✅ 全仓零命中 |
| 依赖经冻结 dataclass 注入 | ✅ 全部符合 |
| templates/storage 归属 `project_*_service` / `*_store` | ❌ Step 3 模板逻辑在路由模块 → M-06 |
| 纯层（planning/profiles/prompt_templates/llm）不被 service 重复实现 | ✅（但被 service 越层导入 → L-02） |
| 迁移连续编号 + checksum、无 create_all | ✅ |
| 编辑旁白清除音频确认 | ❌ repair 路径缺失 → M-03 |
| 原子写入生命周期 | ⚠️ 大面积符合，`visual_contract.json` 两处直写 → H-02 |
| 渲染前重建/校验资产、`.render.json` sidecar | ✅（数字人合成路径的颜色声明 → M-07） |
| UI 事实源 Soft Pastel Studio | ✅ 代码符合；`server.py:138` 描述漂移 → M-05 |
| 六步可见流程契约 | ❌ Step 9 未入文档与测试 → H-01 / M-05 |

## 7. 修复优先级建议

1. **立即**：H-01（恢复发布门禁绿灯 + 被掩盖断言）；H-02、H-03（两处数据损坏级写缺陷，均为小改动：`write_json_atomic` 替换 + 读取移入锁内）。
2. **本迭代**：M-01/M-02（上传统一有界读取 + 上限统一）、M-03（repair 补失效）、M-04（`start_server` 延迟导入）。
3. **随数字人特性收尾**：M-05（AGENTS.md 七步契约 + 描述字符串）、M-07（合成后颜色复验）。
4. **专项清理批次**：M-06（模板逻辑迁移）、M-08/M-09（HTTP 语义、TTS 后台化）与 L-01~L-14（可合并为一次机械清理：Depends 残留、私有函数包装、死代码、`.gitignore`）。
