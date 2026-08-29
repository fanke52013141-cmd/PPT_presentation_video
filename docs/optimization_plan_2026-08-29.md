# 优化实施方案（2026-08-29）

依据：`docs/code_review_2026-08-29.md`（审查基线 `main@88912ee`）。本方案为实施蓝图，未改动任何生产代码。

---

## 1. 总原则

1. **小步提交，每步可回滚**：每个发现编号（H-01、M-03……）对应一个独立 commit，commit message 引用审查报告编号，便于回溯与单独 revert。
2. **先测试后改码（关键项）**：H-02 / H-03 / M-03 这类"改动小但后果重"的项，先写失败测试（红），再修（绿），证明修复有效而非碰巧通过。
3. **机械改动合并成批**：L 级债务不逐项开 PR，合并为一次"债务清理批"，靠 grep 守护 + 全量回归兜底。
4. **遵守 AGENTS.md 现行边界**：服务不 commit（调用方提交）、`invalidation_service` 只改文件与状态、路径统一走 `repository_paths.py`、迁移只增不改。
5. **每批收尾跑统一回归门禁**（见 §2）。

## 2. 测试策略与统一验收标准

### 2.1 分层测试手法

| 层 | 手法 | 适用项 |
| --- | --- | --- |
| 静态守护 | grep 断言脚本化进 `checks/`（禁止模式回归） | H-02、L-01、M-06、L-02 |
| 单元测试 | 直接调用函数，构造脏数据/边界值 | H-03、M-03、M-08、L-08~L-13 |
| API 状态码测试 | FastAPI TestClient 构造超限/非法 payload 断言 4xx | M-01、M-02、M-08、L-07 |
| 并发测试 | 双线程 + 事件同步的确定性交错，参照 `checks/test_mask_build_concurrency.py` | H-03 |
| 守护测试 | 断言 import 副作用（`sys.modules` 检查） | M-04 |
| 人工 E2E | 浏览器六/七步全流程 + 渲染 MP4 抽查 | 每批次收尾、M-07、M-05 |

### 2.2 统一回归门禁（每批次完成必跑，全部通过才算批次完成）

```bash
py -m compileall -q *.py scripts checks
for f in static/*.js; do node --check "$f"; done
node checks/test_visible_flow.js          # P0 完成后必须绿
py -m pytest checks/test_database_migrations.py checks/test_invalidation_service.py checks/test_source_runtime_safeguards.py -q
py checks/test_reveal_mask_integrity.py
py checks/test_reveal_pipeline_isolation.py
py checks/test_slide_visual_invalidation.py
py checks/test_audio_confirmation.py
py checks/test_audio_tail_padding.py
(cd scripts/remotion && npx tsc --noEmit -p tsconfig.json)
py -m pytest checks/ -q -p no:cacheprovider   # 全量收尾（P3 批次必须）
```

### 2.3 验收标准通用定义（DoD）

一项修复"完成"当且仅当：
1. 针对它的**新增/修改测试**通过，且该测试在修复前**先红**（行为类修复）；
2. 统一回归门禁**全绿**；
3. 对应的 grep 守护条件满足（若适用）；
4. commit message 引用报告编号。

---

## 3. P0 批次——立即执行（预计 0.5~1 天）

> 重点：1 个发布门禁红灯 + 2 个数据损坏级缺陷。全部是小改动，风险最低、收益最高。

### 3.1 H-01 恢复 `test_visible_flow.js` 绿灯

**怎么改**：
- `checks/test_visible_flow.js:8` 期望值改为 `[1, 2, 3, 5, 6, 9, 8]`（与 `static/flow.js` 的 `VISIBLE_FLOW` 一致，Step 9 为 `optional: true`，位于 6 与 8 之间）。
- **不做**"把可选步骤从 `VISIBLE_FLOW_STEPS` 排除"的方案——`workspace_navigation.js` 依赖完整序列做导航索引，改导出语义牵连面大。
- 同时确认 `checks/test_visible_flow.js` 其余断言（`normalizeVisibleStep(9)`、`resolveProjectVisibleStep` 对 9 的行为）是否需要补用例：补 `assert.equal(flow.normalizeVisibleStep(9), 9)` 与 Step 9 未启用（`digitalHumanEnabled !== true`）时的状态断言。

**怎么测**：直接运行该测试文件；额外做一次"反向验证"——临时把期望改回旧值确认测试确实会红（防止断言被跳过的假绿）。

**验收标准**：
```bash
node checks/test_visible_flow.js   # 退出码 0，输出无 AssertionError
```
且坐标映射断言（`mapClientPointToCanvas`）确认在执行路径上。

### 3.2 H-02 `visual_contract.json` 原子写入

**怎么改**：
- `storyboard_service.py:866-867`（`finalize_step2_contract`）与 `:1009-1010`（`update_step2_result`）：
  ```python
  # 旧
  with open(contract_path, "w", encoding="utf-8") as f:
      json.dump(contract, f, ensure_ascii=False, indent=2)
  # 新
  write_json_atomic(contract_path, contract)
  ```
- 已确认 `write_json_atomic`（`pipeline_lifecycle.py:77-89`）序列化参数同为 `ensure_ascii=False, indent=2`（额外带换行尾与按路径线程锁 + 4 次重试），是安全的直接替换；`storyboard_service.py:27` 已导入该函数，无需新增 import。
- 写完后紧接的 `write_project_log` / slide_ids 推导逻辑保持不动（它们读的是内存对象，不受影响）。

**怎么测**：
- 新增 `checks/test_storyboard_contract_atomic.py`（或并入现有 storyboard 服务测试）：
  1. 构造最小项目（内存 SQLite fixture，参照 `checks/test_database_migrations.py` 的建库方式）；
  2. 调用 `finalize_step2_contract` → 断言 `planning/visual_contract.json` 可 `json.load` 且与预期 payload 一致；
  3. 断言目录中无残留 `*.tmp`（`write_json_atomic` 正常路径不残留；异常路径重试 4 次后抛出）。
- 新增 grep 守护（并入 `checks/test_source_runtime_safeguards.py` 或新建）：`storyboard_service.py` 源码中不得出现 `open(contract_path, "w"`。

**验收标准**：新测试先红（对旧代码）后绿（对新代码）；grep 守护零命中；回归门禁全绿。

### 3.3 H-03 `reveal_manifest.json` 锁内读取

**怎么改**：
- `mask_manifest_service.py` `refresh_reveal_semantic_blocks`：将 `:407-408` 的 manifest/contract 读取移入 `with _deps().reveal_lock_for(project):` 块，形成"锁内 读→改→写"完整临界区：
  ```python
  with _deps().reveal_lock_for(project):
      manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
      contract = json.loads(contract_path.read_text(encoding="utf-8"))
      ...  # 现有 :409-450 的处理逻辑原样内移
      _deps().write_json_atomic(manifest_path, manifest)
  ```
- 已确认锁为按 run_dir 的可重入 `RLock`（`project_runtime_service.py:31-32`），即使调用方已持锁也无死锁；同文件 `get_step5_result`（:483）已是锁内读，风格对齐。

**怎么测**：
- 新增并发测试（参照 `checks/test_mask_build_concurrency.py` 的 fixture 与线程手法）：
  - 线程 A：循环调用草稿保存路径，写入标记性手动 Mask 数据；
  - 线程 B：循环调用 `refresh_reveal_semantic_blocks`；
  - 用 `threading.Event` 控制交错，最后断言 A 写入的数据**未被 B 覆盖丢失**。
  - 旧代码下该测试应能（多次运行中）复现丢失 → 先红；修复后稳定绿。
- 补一条顺序单测：锁获取必须先于读取（fake lock 记录调用顺序断言），使竞争在单线程下也可判定。

**验收标准**：并发测试稳定通过（连续跑 10 次无失败）；`test_mask_build_concurrency.py`、`test_mask_editor_services.py` 回归通过。

---

## 4. P1 批次——本迭代（预计 2~3 天）

> 重点：上传安全暴露面收敛 + 状态契约补全 + 入口副作用隔离。

### 4.1 M-01 上传统一"有界读取"

**怎么改**（6 处，统一模式）：
- 异步路由（`digital_human_routes.py:258、:315、:360`；`storyboard_background.py:260`；`project_style_routes.py:391`）：
  ```python
  # 旧：content = await file.read()          # 无界
  # 新：分块读入，最多 max+1 字节
  content = await file.read(max_bytes + 1)
  if len(content) > max_bytes: → 413
  ```
  注意：`UploadFile.read(n)` 支持按需读取；超限即拒绝，不再全量载入。
- 同步路由（`image_style_reverse_service.py:261`）：`file.file.read(12 * 1024 * 1024 + 1)` 同理。
- `project_style_routes.py:391` 参考图入口**额外补**：单文件 12MB 上限（对齐 `storyboard_background.py` 的 12MB 标准）+ `content_type.startswith("image/")` 校验。
- 可选加固（独立 commit）：新增轻量 ASGI 中间件校验 `Content-Length` 超上限直接 413（对 chunked 无 Content-Length 的场景不完美，但挡住常规超大请求；不引入 body 缓冲）。

**怎么测**：
- 扩展 `checks/test_image_upload_limits.py`：
  - 每个端点一条用例：monkeypatch 上限为极小值（如 1KB）→ 构造 5KB 文件上传 → 断言 413 且**错误响应先于全量读取**（用 monkeypatch 包装 `UploadFile.read` 记录实际读取字节数 ≤ max+1）；
  - 参考图入口：超限 413、非图片 MIME 415/400 各一条；
  - 边界值：恰好等于上限的文件必须成功（防"少读一字节"回归）。

**验收标准**：新用例全绿；六处端点 grep `await file.read()` 无参调用零命中（守护并入 source_runtime_safeguards）；手动 `curl -F file=@大文件` 返回 413。

### 4.2 M-02 头像上限统一 200MB

**怎么改**：`digital_human_routes.py:44-45` 默认值 `500 * 1024 * 1024` → `200 * 1024 * 1024`，注释标注"必须与 `digital_human_service.MAX_AVATAR_BYTES` 保持一致"。
（不采用 routes 直接 import service 常量的方案：`digital_human_service.py` 是可独立运行的微服务模块，import 会拉起其模块级状态。）

**怎么测**：`checks/test_image_upload_limits.py` 新增守护用例：动态读取两个模块常量，断言相等。

**验收标准**：守护用例绿；300MB 头像上传在**路由层**即得 413（而非下游 400）。

### 4.3 M-03 `repair_step6_result` 补失效链

**怎么改**：`narration_service.py:200-210`，`changed` 为真时走与 `update_step6_result` 完全相同的导航失效路径（自带提交）：
```python
if changed:
    from project_runtime_service import handle_step_navigation  # 顶部导入
    handle_step_navigation(project, 6, db)
```
备选：`invalidation_service.complete_stage(project, 6)` + 路由层显式 commit；二选一，**推荐前者**（与 update/annotate 行为逐字节一致，符合"服务不 commit"规则——`handle_step_navigation` 属于 AGENTS.md 认可的 commit-owning transition）。

**怎么测**：
- 扩展 `checks/test_audio_confirmation.py`：
  1. 构造项目：分镜 2 页 + 已生成并**确认**音频；
  2. 手动把 contract 删掉一页（制造 beats 与 contract 的可修复差异）；
  3. 调用 `POST /api/projects/{id}/steps/6/repair`；
  4. 断言：`changed == true` 且音频确认状态被清除（`audio_confirmed` 标志文件/字段复位）。
  旧代码下该用例红（确认状态残留）。

**验收标准**：新用例先红后绿；`test_audio_confirmation.py`、`test_narration_audio_service.py`、`test_narration_tts_routes.py` 回归绿。

### 4.4 M-04 `start_server.py` 延迟导入

**怎么改**：
1. 新建无副作用小模块 `network_guard.py`（仅标准库），迁入 `_is_loopback_host`、`_validate_network_security`；
2. `start_server.py`：删除顶层 `from server import app`，`main()` 内部执行；顶部改 `from network_guard import ...`；
3. `checks/test_start_server_security.py:7` 改为 `from network_guard import ...`；
4. `server.py` 尾部 `from start_server import main as start_main` 保持不变（`__main__` 块内，已合规）。

**怎么测**：新增守护测试（并入 `checks/test_source_runtime_safeguards.py`）：
```python
def test_start_server_import_has_no_server_side_effect():
    import subprocess, sys
    code = "import sys; import start_server; assert 'server' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True, cwd=repo_root)
```
（子进程隔离验证，避免本进程已加载 server 的假绿。）

**验收标准**：守护测试绿；`py -m pytest checks/ -q` 收集时间不劣化（可对比前后 `-p no:cacheprovider --durations=10` 首行）；`python start_server.py` 手动启动正常、访问页面正常。

### 4.5 M-05 文档契约同步（与 3.1 同口径）

**怎么改**：
- `AGENTS.md`：六步表后追加一行"可选步骤 9 数字人讲解（internal Step 9，工件 `planning/digital_human_config.json` 等，以 `CONFIG_FILENAME`/`DIGI_DIRNAME` 实际值为准）"；"six user-visible steps" 表述改为"六步 + 可选数字人增强"；
- `server.py:138` 应用描述改为与 Soft Pastel Studio 一致（如 "本地 PPT 演示视频生成系统（Soft Pastel Studio）"）；
- README 若有步骤图/清单同步（改动前 grep 确认）。

**怎么测**：人工核对 + 3.1 的测试作为可执行契约。

**验收标准**：`node checks/test_visible_flow.js` 绿；AGENTS.md 中 "Step 9"/"数字人" 可 grep 到且与 `flow.js` 步骤号、顺序一致。

---

## 5. P2 批次——随数字人特性收尾（预计 2~3 天）

### 5.1 M-06 模板存储逻辑迁出路由

**怎么改**：
- 目标文件已存在：`project_style_template_service.py`（当前 2.6KB，承接主体）+ `project_style_reference_store.py`（存储侧）；
- 迁移内容：`project_style_routes.py:552-859` 的 `_templates_root`/`_read_templates`/`_write_templates`/`_builtin_style`/`_template_detail`/`save_step3_template`/`apply_step3_template`/`delete_step3_template`；
- 路径 `_templates_root` 的 `data_dir / "step3_image_style_templates"` 迁移为 `repository_paths.py` 注册的具名路径（新增常量 + 该文件内引用），消除路由层自算路径；
- 路由只留：请求模型、鉴权、调用 service、异常翻译。

**怎么测**：
- 现有模板相关测试（`grep -l template checks/*.py` 确认清单）迁移 import 路径后必须全绿；
- 新增 grep 守护：`project_style_routes.py` 中 `_templates_root|_write_templates|step3_image_style_templates` 零命中；
- `test_architecture_size_boundaries.py` 若对路由文件有行数上限，迁移后自然满足。

**验收标准**：守护零命中；路由文件行数显著下降；回归门禁全绿。

### 5.2 M-07 数字人合成后颜色复验

**怎么改**：`video_render_service.py`：
- `_apply_digital_human_composite`（:384-403 区段之后）完成后，调用 runner 上的现成方法复验：`self.runner._container_already_bt709(composite_out)`（`remotion_runner.py:450`；若不宜调私有方法，先将其提升为公共 `validate_container_color(video_path)`，`_validate_render_color`（:655）内部复用）；
- 复验失败 → 任务置 `failed`，`error` 写明 "合成后颜色校验未通过"；
- `.render.json` 元数据（:427-433）：`color_validation` 改记合成后校验结果，并新增 `"digital_human_composite": true` 字段。

**怎么测**：
- 单测（扩 `test_persistent_video_jobs.py`）：mock runner.run 成功 + mock 合成输出 → 断言元数据的 `color_validation` 来自合成后文件、复合标记存在；mock 校验失败 → 任务终态 `failed` 且 `error` 非空（符合"成功任务 error=NULL"的反向约束）。
- 人工 E2E：对一个已配数字人的项目真实渲染一次，检查 MP4 可播 + sidecar 字段。

**验收标准**：单测先红后绿；E2E sidecar 字段正确；`video_routes` 轮询终态语义不回归。

### 5.3 M-08 纯层异常语义（规划校验 500 → 400/422）

**怎么改**：
- `storyboard_planning.py`：定义 `class PlanningError(ValueError)`；将 :99/:117/:127/:331/:346 的 `raise HTTPException(500, ...)` 改为 `raise PlanningError(...)`，并**删除该模块对 fastapi 的 import**（纯层回归纯函数）；
- `storyboard_service.py` 调用点（:664、:712 及其余调用 planning 的位置）统一 `except PlanningError as exc: raise HTTPException(400, str(exc))`；
- AI 输出路径（LLM 返回喂给 planning 的位置）单独映射为 502/422，与用户手动编辑（400）区分。

**怎么测**：
- 单测：直接调 planning 函数传缺 `slides`/`narration` 的 payload → 断言抛 `PlanningError`；
- API 测试：TestClient `PUT /api/projects/{id}/steps/2/script/result` 非法 payload → 断言 400（旧代码 500）；
- grep 守护：`storyboard_planning.py` 中 `fastapi|HTTPException` 零命中（并入 source_runtime_safeguards）。

**验收标准**：API 用例先红（500）后绿（400）；`test_generalized_storyboard_and_animations.py` 等回归绿。

### 5.4 M-09 TTS 合成异步化（分两步走）

**第一步（本批，去重 + 结构准备，~0.5 天）**：
- 抽公共 helper：`_load_beats_by_slide(project)`（合并 `tts_service.py:189-199` 与 `:401-412`）、`_bind_reveal_timeline(project, ...)`（收敛 :320-328、:419-427 与 `remotion_runner.py:146-165` 的重复子进程封装）；
- 测试：纯重构，现有 `test_narration_tts_routes.py`/`test_audio_subtitle_duration.py` 回归即验收。

**第二步（单列任务，迁 `local_jobs`，~2 天）**：
- 参照 `pptx_service.py` 范本：POST 立即返回 job_id → worker 线程合成 → `GET .../jobs/{id}` 轮询；SQLite `local_jobs` 表持久化 + 中断标记 `interrupted`；
- 前端 `narration_audio.js` 改轮询（参照 `output_render.js` 的任务轮询实现）；
- 测试：参照 `checks/test_persistent_video_jobs.py` 增 `test_persistent_tts_jobs.py`：提交/轮询/进程重启恢复 `interrupted`/成功后 error=NULL 四类用例。

**验收标准（第二步）**：断网/重启场景下任务状态可恢复；门禁全绿。

---

## 6. P3 批次——债务清理（一次合并 PR，预计 1~2 天）

> 原则：全部为机械改动，靠"grep 守护 + 全量 pytest + node 套件"兜底，不新增行为。

| 项 | 改法 | 守护/测试 | 验收标准 |
| --- | --- | --- | --- |
| L-01 | 服务层 30 处 `db: Session = Depends(get_db)` → `db: Session`；删除 `from fastapi import Depends`（保留 HTTPException） | grep：`narration_service.py\|tts_service.py\|storyboard_service.py` 中 `Depends` 零命中 | 回归门禁全绿；路由行为不变 |
| L-02 | `image_workflow_service.py:41` 改 `from storyboard_prompt_templates import read_prompt_template` | grep：image_workflow_service 不再 import storyboard_service | 回归绿 |
| L-03 | `digital_human_routes._validate_upload` 对视频类追加扩展名白名单复核（`.mp4/.mov/.mkv/.avi/.webm`） | TestClient 用例：octet-stream + `.exe` 后缀 → 415/400 | 新用例绿 |
| L-04 | `digital_human_panel.js:633,645,740,749` innerHTML 拼接改 escHtml/DOM API | `node --check` + 现有前端质量测试 | UI 手查状态 chips 正常 |
| L-05 | 数字人独立服务：代码注释 + README 标注"绑定非回环地址前必须补令牌认证" | 无自动测试（文档项） | 文档可 grep |
| L-06 | 为被路由调用的 `_` 私有函数在各自 service/store 增公开包装（清单：`_save_step3_style`、`_write_normalized_manifest`、`_generate_image_style_with_llm`、`_references_dir` 等 13+ 处对应的宿主），路由改调公开名 | grep：`project_style_routes.py` 中 `\._[a-z]` 调用零命中 | 回归绿 |
| L-07 | 超限 400 → 413；类型错误 → 415（`image_workflow_service.py:596-599,615-616` 等） | 更新涉及状态码断言的既有测试 | 全量回归绿 |
| L-08 | `mask_manifest_service._deps()` 未配置时改 `raise RuntimeError`（对齐 `mask_preview_service.py:50-53`） | 单测：不配置依赖调用 → RuntimeError | 回归绿 |
| L-09 | `video_artifact_service.delete_video` 前扫描目标目录 `*.deleted` 一并删除 | 单测：预置 .deleted 文件 → 删除动作后消失 | 回归绿 |
| L-10 | `global_image_style_service.py:398-405` 改原子写：dump 到同目录 tmp + `os.replace`（或新增 `pipeline_lifecycle.write_text_atomic`） | grep 守护：该文件无 `open(STYLE_TOKENS_PATH, "w"` | 回归绿 |
| L-11 | 死代码清理：`storyboard_service.py:849-855` 重复赋值段、`remotion_runner.py:397,437` 局部 `import json as _json`、`one_click_orchestrator.py:424-427` try/except pass；新增 `project_path_service.project_or_404(db, project_id)` 统一 helper，替换 4 份 `_project_or_404` 与 38 处查询样板（分两个 commit：先 helper 后替换） | grep 守护 + 全量回归 | 门禁全绿；helper 单测覆盖 404 分支 |
| L-12 | `video_render_service.py:470-473`：锁释放改为获取方持有上下文（`with project_lock:` 包渲染任务投递与 worker 完成等待，或引入持有者 token 校验） | 现有视频任务测试回归 | 回归绿 |
| L-13 | `video_artifact_service.py:171` stat 加 try → 404；`narration_service.py:140` 改 `s.get("slide_id")` + 缺失时 400 | 边界单测各一条 | 回归绿 |
| L-14 | `.gitignore` 追加 `.zcode/` | `git status --short` 不再出现 | git status 干净 |

---

## 7. 执行顺序与依赖关系

```
P0:  H-01 ─┐
     H-02 ─┼─ 互不依赖，可并行；三者完成后跑一次门禁
     H-03 ─┘
P1:  M-01 → M-02（同一测试文件扩展，顺序做）
     M-03（独立）
     M-04（独立）
     M-05（依赖 H-01 定稿的步骤口径）
P2:  M-06、M-08（独立）
     M-07（数字人侧，可与 M-05 同期）
     M-09 第一步随时可做；第二步单列
P3:  全部机械项，最后统一做（避免与 P0~P2 的改动冲突）
```

## 8. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| H-03 移锁后吞吐下降（临界区变长） | 临界区只是 JSON 读 + 内存处理，毫秒级；并发测试同时观察无死锁 |
| M-01 有界读取改动影响分块上传兼容性 | 保留边界值用例（恰好等于上限必须成功）；分批提交六个端点 |
| M-04 移动 import 后启动脚本行为变化 | 保留 `python start_server.py` / `python server.py` 双入口手动冒烟 |
| M-03 失效补全导致"修复后需重新确认音频"被用户感知为行为变化 | 这是 AGENTS.md 契约的正确行为；发布说明中注明 |
| M-09 第二步（TTS 异步化）牵连前端 | 单列任务 + 前端轮询复用 output_render 既有模式，不在本计划强制排期 |

## 9. 工作量汇总

| 批次 | 内容 | 预估 |
| --- | --- | --- |
| P0 | H-01、H-02、H-03 | 0.5~1 天 |
| P1 | M-01~M-05 | 2~3 天 |
| P2 | M-06~M-09（M-09 第二步另计 ~2 天） | 2~3 天 |
| P3 | L-01~L-14 | 1~2 天 |
| 合计 | | **约 6~9 个工作日**（含每批门禁与 E2E） |
