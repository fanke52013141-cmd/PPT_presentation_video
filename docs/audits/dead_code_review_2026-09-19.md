# 全仓死代码 / 错误代码 / 过时代码复盘

审核日期：2026-09-19
方法：AST 导入图可达性分析 + 全库字符串级引用复核（含 .py/.js/.md/.json/.html/.bat/.yaml/.sql）
+ ruff（F821/F841/F601/F811/F401/B 规则）+ 前端函数引用扫描。所有删除项均先证明
"全库仅定义处出现一次"，并排除动态派发（getattr 按名调度）与 monkeypatch 接缝。

## 一、发现并已修复的真实错误（不只是冗余）

| 位置 | 问题 | 后果 | 处理 |
| --- | --- | --- | --- |
| digital_human_routes.py `_find_ffprobe` | 使用 `shutil.which` 但文件从未 `import shutil` | 走到该分支必抛 NameError（自定义 ffmpeg 目录场景） | 补 `import shutil` |
| agent_api/routes.py 更新项目路由 | `raise HTTPException(...)` 但该模块只导入 `ValidationFailedError` | Agent 设置 reveal+一键组合时抛 NameError 而不是 400 | 改为 `ValidationFailedError`（与本模块错误约定一致） |
| scripts/minimax_tts.py 元数据 | 合并残留：`speed/volume/pitch` 在同一字典写入两次（str(args.x) 与 str(float(args.x))） | 静默取后者，读者误以为前者生效 | 删除被覆盖的前一组 |
| checks/test_one_click_orchestrator.py `__main__` | 调用了两个已被更名的测试函数 | 直接运行该文件必崩（pytest 收集不执行 main，故长期未暴露） | 改为现存函数名 |
| 7 处 F841 | `res = client.composite(...)`、`out_path = _assert_path_safe(...)` 等赋值后不使用 | 至少 2 处（comfyui 节点查找、数字人工作流 source）是重构后遗留的假逻辑 | 保留调用与校验副作用、删除无效绑定 |

## 二、已删除的死代码（全部经全库引用复核）

### Python（19 个零引用函数/类 + 1 个一次性脚本；1 个误判已恢复）

- agent_contract/artifacts.py `Artifact.to_dict`（无任何 `.to_dict()` 调用方）
- ai_mask_assignment.py `_bounds_area`、`_speech_signature`
- ai_mask_semantic_matcher.py `_overlay_bytes`
- canvas_profile_service.py `read_project_canvas_snapshot`
- config_portability_service.py `_account_private_items`、`_global_model_items`（配置迁移改由 SQL 迁移承担后的遗留）
- creation_config_models.py `ConnectionReference`、model_connection_models.py `ModelConnectionListResponse`、
  model_connection_service.py `ModelConnectionInUseError`（契约收敛后未清理的模型/异常）
- digital_human_routes.py `_full_audio_ready`（config 接口改为内联判定后的遗留）
- mcp_server/presenters.py `present_checkpoint_list`
- project_service.py `validate_target_duration_sec` —— **删除后被发现误删并已恢复**：
  它是 `@field_validator` 装饰器注册的 pydantic 校验器，按名字全库检索找不到调用方，
  但由装饰器机制激活（5 个 target-duration 测试立即报警）。教训：装饰器注册的函数
  不能按"名字零引用"判死。
- scripts/write_visual_contract.py `infer_role`、scripts/write_visual_prompts.py `as_lines`
- step3_image_style_service.py `_step3_style_prompt`
- storyboard_service.py `script_plan_schema_hint`、`visual_plan_schema_hint`（storyboard_planning 已有同名实现）
- video_render_service.py `_mark_task_running`、`validate_remotion_public_assets`
- tools/one_off_bind_xiaxiaohua_tts.py（一次性账号数据修补脚本，任务早已落库，git 历史可查）

### 前端（13 个零引用函数）

- courses.js `libraryRecordLabel`/`isProjectComplete`/`formatLatestOutputTime`
- creation_config_management.js `removeEmptyObject`/`modelProviderLabel`
- digital_human_panel.js `setPositionPreset`/`resetCircle`/`audioReadySlides`
- mask_workspace.js `switchStep5Slide`；project_profile_extension.js `creationConfigChoices`
  （卡片墙改版后的遗留渲染器）；storyboard.js `openStep2GenerationModal`/`step2BodyContentText`
- ui_foundation.js `uniqueNarrationLines`（去重改由 `narrationDedupeKey` 承担）

对应地，`checks/test_frontend_quality.js` 的两条所有权守护同步更新
（移除已不存在的 token/函数名，保留 `narrationDedupeKey` 等仍在使用的所有权断言）。

### 未用导入（约 26 处应用代码 + 约 20 处测试代码）

仅删除纯遗留导入（json/os/sys/shutil/subprocess/tempfile/uuid/yaml/base64/typing 等）
与确认无接缝的具名导入；两处 `import server`（配置工作流依赖的副作用导入）改为显式
`# noqa: F401` 注释保留。两个名字在测试反馈后回滚：`one_click_orchestrator` 的
`DEFAULT_QUALITY_GATES`（测试按源码文本断言其导入以证明质量门接线）与
`test_image_gateway_budget` 的 `RESOURCE_IMAGE`/`BASE_URL`（导入重写脚本误伤，已修复）。
"未用导入"判定对装饰器与源码文本守护不可靠，凡命中即恢复。

## 三、审查后决定保留的部分（避免误删）

- **文档规定的兼容 re-export**：server.py 对 runtime_support/json_llm_service 的再导出、
  storyboard_service 对 storyboard_planning/storyboard_prompt_templates 的再导出、
  ai_mask_engine 对 ai_mask_manifest_apply 私有 helper 的再导出（checks 直接经
  `ai_mask_engine._replaceable_ai_mask` 使用）、repository_paths 路径名再导出。这些是
  AGENTS.md 模块边界策略的一部分，ruff 的 F401 视角看不到跨文件接缝。
- **动态派发**：scripts/check_smoke_artifacts.py 的 `check_step*`（getattr 调度）、
  dataclass `__post_init__`、FastAPI 路由处理函数（32 个 agent 路由全部经装饰器生效）。
- **独立进程入口**：digital_human_service.py（972 行）在导入图中不可达，但由
  launch.bat/start_here.bat 作为 :9001 独立服务启动，保留。
- **多账号/创作包体系**：与"单机自用"方向不完全一致，但属活跃产品功能（远端 12 个提交
  仍在演进），不属于死代码，不做删除；如需下线应作为独立产品决策。
- **1.9 GB `runtime/`、`runs/`、`outputs/`、`.venv/`**：均已被 .gitignore 排除，仓库实际
  跟踪体积约 89 MB；体积专项见 repo_size_review_2026-09-16.md，本次不重复处理。

## 四、验证

修复与删除后重跑 AGENTS.md Required Validation 全集（compileall、node 守护、
pytest 主套件、pytest agent 套件、脚本式检查、契约 --check、Remotion tsc 不受影响），
结果见提交说明。

## 五、遗留建议（本轮未动，供后续决策）

1. 视觉溯源/音频确认的 v2 旧格式读兼容分支：所有旧项目完成一次重新确认/重新生成后可整批删除
   （visual_provenance.py、tts_artifacts.py 内的 legacy 分支）。
2. `one_click` 与手工工作流仍有少量重复的阶段常表，可再收敛到 pipeline_lifecycle。
3. 若确定永久单机使用，可评估把账号（accounts）层折叠为单默认账号，涉及数据库迁移，
   风险与收益都需要单独方案。
