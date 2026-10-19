# 代码审查报告（2026-10-19）

> **修复状态（2026-10-19 同日更新）**：本报告的 P0 全部 6 组与 P1 共 13 项已完成修复并通过全量回归（1603 pytest + 9 个 JS 套件 + compileall + Agent 契约检查）。已修复：CR-1/2/3/4/5/6(部分：undo diff 撤回由保存侧 merge 兜底)/7/8/16/17/19/20(预览轮询退避由 409 自愈+超时替代)/21/24/33/34/35/36/37/38/39 + UX-9（同步预览 409 自愈、6 分钟超时、幽灵弹窗、状态残留）。未修复项保持原文状态（CR-9~15/18/22/23/25~32/40/41 及 P3 列表留待排期）。修复明细见文末「修复记录」。

- **审查模型**：GLM-5.3（4 个并行深度审查代理 + 主代理交叉验证与实测）
- **审查范围**：全仓库 162 个 Python 后端模块 + 43 个前端 JS 模块，重点为勾画标注（annotation）模块与端到端流程衔接
- **验证方式**：静态通读 + 调用关系 grep 交叉验证 + 现有测试套运行（annotation 相关 217 passed / 1 skipped）+ 本地运行实例浏览器实测（实测结论已在条目中标注【实测复现】/【实测未复现】）
- **基线**：commit `0a90052`，工作区 clean

## 一、总体评价

架构纪律性强：模块边界（AGENTS.md 铁律）在抽查中基本得到遵守；失效体系（impact_registry + invalidation_service + 哈希门禁）设计成熟；音频五元哈希确认、v6 raw pair 双哈希、99.5% 覆盖率门槛、配额键 `(resource, gateway)` 等关键安全点全部核实到位。前端竞态防护（projectId + navigationVersion 双快照 + 迟到响应丢弃）高于平均水平。

主要风险集中在四处：**① Step 5 主 CTA 按钮疑似无事件绑定（流程断点）；② 图片 provenance 与旁白失效两套口径互相矛盾（narration-only 编辑后渲染被拦死）；③ 勾画保存链路的三个工作丢失/死锁路径；④ 一键完成时步骤状态被错误降级**。勾画模块与 Remotion 渲染端的双端契约架构（共享采样器）是亮点，但预览/成片 props 组装存在两套实现，且存在一个已发生的三端采样副本漂移实例。

## 二、问题清单

### P0 / P1 —— 阻断或数据丢失风险（建议本迭代修复）

| # | 模块 | 位置 | 问题 | 影响 | 修复建议 |
|---|------|------|------|------|----------|
| CR-1 | 前端·Step 5 | `static/index.html:386`、`static/event_bindings.js:233-240` | 【待复核·高置信】Mask 主 CTA「进入旁白语音」(`step5-btn-confirm-next`) 全仓库无任何 click 监听；`.btn-next-step` 通用处理器的 step5 分支是死代码（该按钮无此类名） | 用户无法通过按钮触发 `saveStep5Masks()`（落盘+构建切层+步骤推进），只能点左侧步骤条硬跳，后端 Step 5 状态与切层产物可能停留草稿态 | 在 event_bindings Step 5 段补绑定；`checks/test_frontend_quality.js` 增加"每个 ws-primary CTA 必须有绑定"守卫 |
| CR-2 | 流水线 | `visual_provenance.py:45-54,105-111` vs `storyboard_contract_diff.py:58-95` vs `invalidation_service.py:163-166` | 图片 provenance 对**整个 slide 条目（含 narration 全文）**做哈希，而失效体系承诺 narration-only 编辑不动图片/Mask | Step 2 只改 `spoken_text` → 状态机认为 3/4/5 仍有效 → Step 8 渲染被 provenance 门 409（`contract_hash_changed`）；用户被迫重新生图，又连带清 Mask；`PUT /impacts/reuse-image`（`project_routes.py:112-140`）只结算台账不刷新 provenance，逃生口无效 | `slide_contract_hash` 改用与 `_visual_slide_input` 相同的视觉投影；reuse-image 端点同步刷新 provenance |
| CR-3 | 勾画·后端 | `annotation_service.py:621-632` | `_op_update` 的 anchor 分支无同值比较：含未变化 anchor 的 patch 会无条件 `modified.append("anchor")` → 已确认条目被重置 draft、`annotation_timeline.json` 被删、Step 8 无谓失效 | 编辑器 autosave 常发全量 target+anchor+timing patch；违反 AGENTS「同值保存必须无操作」；现有同值测试只覆盖 style（`checks/test_annotation_routes.py:669`） | 与 target/style 一致：先 `anchor != target_item.anchor` 比较再 append；补 anchor/status/locked 同值测试 |
| CR-4 | 勾画·后端 | `invalidation_service.py:423-425`、`narration_audio_service.py:466-468`、`tts_service.py:1211` | 音频/讲稿失效调用 `annotation_invalidation` 时不持 `project_artifact_lock`（该模块 docstring 明确要求调用方持锁），而编辑器 patch/confirm 全部持同一锁 | 后台 TTS 完成与用户在勾画编辑器 autosave 并发时 read-modify-write 竞争：后写者覆盖先写者——用户笔迹编辑丢失不可恢复（渲染哈希门只能拦住脏时间轴） | 失效调用外包 `project_artifact_lock(run_dir)`；加交错压力回归测试 |
| CR-5 | 勾画·前端 | `static/annotations_workspace.js:252-258,337-343,144` | 【实测条件成立】422 隔离区无"丢弃"路径：服务端整批原子拒绝，`failedOps` 非空时 flush 直接 return，本页所有后续合法编辑永不再自动保存；「点击重试」永远先重放毒操作必再 422；退出项目时 `failedOps=[]` 静默丢弃 | 可达触发：粗细输 0（前端 `Math.max(0,…)` 允许 0，契约 min=1）、绘制时长 0.01（min 0.05）、quote >200 字关联（`buildAnchor` 无预校验）→ 本页功能死锁 + 最终静默丢失 | 状态条提供"丢弃被拒操作"；按服务端 issue 的 op path 拆分隔离；`buildAnchor` 前端预校验 quote≤200 |
| CR-6 | 勾画·前端 | `static/annotations_editor.js:957-1007`、`annotations_workspace.js:213-214` | 删除→700ms 内撤销：队列残留 `delete ann_x` + 新 `add`，flush 后标注换新 id 且恒为 draft；保存在飞时撤销，成功响应用 `res.items` 整体覆盖本地（闪断+id 漂移），已确认页被无声退回待确认 | 导出门禁回退，用户需重新确认整页 | undo/redo diff 同时撤回矛盾的排队 delete；成功路径 merge 而非整体替换 |
| CR-7 | 一键流程 | `one_click_orchestrator.py:552-602`、`_STAGE_TO_STEP:106-115`、`pipeline_state.py:64-74` | 完成同步用升序 `complete_step` 链且映射表缺 `confirm_images→4`、`tts→7`：终态 4/7 被降为 pending | ① stepper 显示失真；② 下次 resume 的 `effective_start_stage` 被提前，重复重建场景/重新确认音频（自愈但浪费）；与手动流程幂等语义不一致 | 映射表补全 + 完成同步改为"无降级置 completed" |
| CR-8 | 勾画·后端 | `annotation_build.py:154-157` vs `annotation_alignment.py:31,61-93` | `beat_times_from_alignment` 抛 `AlignmentError`（非 `ValueError`），compile 只捕 `ValueError` → `audio_timeline.json` 结构异常时 prepare 直接裸 500 | 预览路径落为未结构化 failed 文本，用户看到原始报错 | except 子句加 `AlignmentError` 或在其内部转 `ValueError`；补异常结构测试 |

### P2 —— 健壮性 / 一致性隐患（建议排期修复）

**勾画模块（后端）**

- CR-9 `annotation_build.py:110-131`：区域目标与所有动态层不相交时返回 `None` → `target_visibility_unresolved` 阻断整页确认；静态背景上的纯区域目标疑似应视为"始终可见(0.0)"，语义可能颠倒（待产品确认）。同函数对每 item×每层重复 `Image.open+ImageChops.multiply` 无缓存，40 条×20 层时 prepare/confirm 显著变慢。
- CR-10 `annotation_service.py:199-206`：`get_summary` 对 `_readiness` 求值两次、页面最多读 4 遍——summary 接口读写放大明显。
- CR-11 `annotation_ocr_baidu.py:64-66,362-364` + `annotation_jobs.py:232-270`：OCR 限流/配额错误标了 `retryable=True` 但无任何消费方，百度 QPS 超限时整页直接 failed。
- CR-12 `annotation_service.py:784-805`：`export_preview` 在 HTTP 线程同步跑 Remotion 渲染（最长 600s）绕过信号量、不可取消；`record_artifact+commit` 先于 `mark_succeeded`，失败分支出现"artifact 已登记但 job 终态 failed"；服务层自行 `db.commit()` 违反"API 调用方拥有唯一 commit"约定。
- CR-13 `annotation_ink.py:298-335` + `annotation_build.py:207-212`：墨迹帧非原子写（直写无 tmp+rename），复用检查只验文件存在性——进程中途崩溃后截断 PNG 被后续编译复用，直到 Remotion 解码失败才暴露（`validate_timeline` 只 stat 不解码）。
- CR-14 `annotation_jobs.py:435-443`：planner 返回 0 条新增时仍 `revision+1` 重写页面，前端编辑器无谓 409 刷新。
- CR-15 `annotation_target_resolver.py:32-69` + `annotation_build.py:92-95` + `annotation_geometry.py:185-199`：邻词/邻行保护（`compute_side_pads`/`pad_left/right`）**未接入生产路径**，`_deform_ellipse` 收参后全部忽略——docstring 宣称的"最外侧不得圈入邻词"未实现，扁宽词垂直方向外扩约 41%，同行邻词可能被圈入。
- CR-16 `annotation_service.py:663-675`：status/protection 同值保存也会 `modified.append` → 无效 revision 自增 + Step 8 无谓失效（轻于 CR-3）。
- CR-17 `annotation_service.py:419-425`：patch_slide 的 image/narration/beats 哈希在锁外读取，与 CR-4 同窗口下条目级 stale 标记失真。
- CR-18 `annotation_job_store.py:113-138` + `annotation_service.py:1224-1234`：detect 任务 request_key 复用可返回与磁盘现状不符的过时成功结果（仅 preview 有 stale 复核）。

**勾画模块（前端）**

- CR-19 `static/annotation_preview.js:173-174,233`：同步预览准备期间关闭对话框后，准备完成会自动重新 `showModal()`（幽灵弹窗）。
- CR-20 `static/annotations_workspace.js:1096-1103`：任务轮询单次 GET 失败即终止跟踪并置 `activeJob=null`，服务端任务仍在执行；用户重提交产生重复任务（与 Step 8 轮询"网络错误继续重试"策略不一致，`narration_audio.js:607-633` 同病）。
- CR-21 【实测复现】`static/index.html:1825`：`annotation_playback.js` 于 2026-10-06（`6b70e0f`）修改 qStart 量化但版本号仍 `?v=20260929.1`；且 `annotation_player.bundle.js` 为 esbuild 内嵌冻结副本，与源文件、Remotion import 三处消费无一致性校验——**缓存旧版的浏览器编辑层、预览弹窗、渲染三端采样已实际分叉**。
- CR-22 `static/annotations.css:158-165`：`touch-action:none` 只挂 freehand 模式，触屏框选会因页面滚动 pointercancel 丢选区。
- CR-23 `static/event_bindings.js:371-378` + `workspace_navigation.js:255,32-35`：离场保护只查 `pendingOps` 且要求 step-panel-10 可见；conflict/failedOps/deferred 不提示；项目切换时两者被静默清空。
- CR-24 `checks/test_annotation_save_flow.js` 当前失败（`API.getOptional is not a function`，沙箱未打桩新方法 `annotations_workspace.js:387`）——自动保存/冲突/恢复的回归护栏是红的。

**整体流水线（后端）**

- CR-25 `tts_service.py:1316-1375`：`confirm_tts_audio` 只查文件存在+mtime，不校验语音配置新鲜度，且写入**新** `tts_runtime` + 旧音频哈希——改音色后不重合成直接确认可把旧音色音频"洗净"为最终成品（API/Agent 路径可绕过前端提示）。
- CR-26 `storyboard_service.py:1362-1377` + `invalidation_service.py:157`：手动保存校验失败的合约仍把 step2 置 completed，且跳过 manifest/beat 同步——带无效合约进入 Step 3；compose 路径有质量门而手动 autosave 路径没有。
- CR-27 `step3_image_style_service.py:64-79` + `project_style_reference_service.py` + `one_click_resume_policy.py:89-104`：图片风格/参考图变更**零失效登记**（无 impact 规则、无 step stale），但一键恢复把风格文件 mtime 视为图片失效输入——手动流程零提示、一键却全量重生成，两边口径矛盾。
- CR-28 `article_service.py:382-399`：重复导入相同文章无 no-op 检查（`update_step1_result` 有），无条件降级 step2，违反 no-op 原则。
- CR-29 `ai_mask_service.py:61`：AI Mask 全程持 `reveal_lock_for`（分钟级），期间 Mask 编辑器 draft 保存/preview 阻塞等待。
- CR-30 `video_render_service.py:992-1007`：数字人合成失败连带删除已成功的 Remotion 成品 MP4，重试需整段重渲染。
- CR-31 `database.py:227-242`：`LocalJob` 用本地时区时间戳，其余表用 UTC；`video_render_service.py:1285-1304` 混用 `.timestamp()` 与 `time.time()` 计算 elapsed。
- CR-32 `invalidation_service.py:383-400`：视频背景变更把 `current_step` 拉回 3，用户在 Mask 步改背景被跳回图片步（失效范围本身正确）。

**前端共享层**

- CR-33 `static/narration_audio.js:563-571,664-673`：TTS 运行中切换项目/退出工作区后，Step 6/7 四个按钮永久禁用（finally 的 ownership guard 跳过恢复；`resetProjectScopedAsyncUi` 不重置这些持久 DOM 按钮）。
- CR-34 `static/workspace_navigation.js:19-38`：【实测复现】切换项目不重置 `state.slides`/`activeSlideIndex`/`step2ContractSha256`（后者由 storyboard.js 动态挂载、未在 `createWorkflowState` 声明）——A 项目分镜残留可导致 B 项目 Step 3 用 A 的 slide_id 提交生图；B 项目首次保存合约带 A 的 sha 必 409；实测还观察到隐藏面板残留 A 项目文章文本。
- CR-35 `static/workspace_navigation.js:20-24` 等：切项目清 autosave 定时器但不 flush——Step 2/5/6 最后 ≤700ms 编辑丢失（Step 5 的 `flushStep5Draft`、Step 6 的 `flushStep6Autosave` 均存在但未接线；annotations 模块的"离开即 flush + beforeunload"是全站唯一完整范式，可作为模板）。
- CR-36 `static/mask_editor.js:1029-1041`：`saveStep5Masks` HTTP 200 但 `res.success===false` 时乐观置 completed 的状态不回滚、无提示，假状态随后被写回草稿。
- CR-37 `static/mask_editor.js:982-986` + `mask_workspace.js:608-618`：请求在途时退出工作区 → finally 无条件 `renderStep5Workspace()` 在 null manifest 上崩溃（未捕获 TypeError）。
- CR-38 `static/one_click_extension.js:32-41`：`STAGE_TO_STEP` 缺 `annotation`/`digital_human` 映射（`visibleStages` 含这两个阶段）——一键进入勾画/数字人阶段时 stepper 无"进行中"标记、不自动导航，用户看到流程"卡在 TTS"。
- CR-39 `static/output_render.js:105-108`：Step 8 轮询 `res.success===false` 时停轮询但不隐藏 loading、不复位按钮——面板卡在"视频渲染中"。
- CR-40 `static/article.js:295-327`：`submitStep1` 无迟到响应守卫（同文件 `generateStep1Article` 有）——导入在途切项目会把 A 的导入结果写进 B 的 Step 1 视图并触发导航；`state.currentProject.id` 无空值保护。
- CR-41 `static/ui_foundation.js:28-46`：`showToast` 吞掉全部 success/info 消息（用户裁决策略），但几十处死调用未清理（"文章已复制"、"分镜已保存"等永不出现），且【实测】"创建项目成功"零反馈与此叠加——用户无法确认操作是否生效。

### P3 —— 可维护性 / 次要（择要）

- `annotation_geometry.py:111-182` 三个手调模板 + `_pick_template` + `_push_outside_protection` 为死代码/被忽略参数，测试反而固化了"模板被忽略"现状；`annotation_timeline.py:100-118` `_resolve_hold_end` 无调用方。
- `annotation_service.py:790,1061` 直接访问 `self._job_manager._deps.*` 私有字段；`annotation_prompt_templates.py:101-114` 存储层内 lazy import HTTPException 抛 409/422/413，违反分层精神。
- 勾画磁盘增长无 GC：`annotation_ink/build_<id>_` 随每次重确认累积、`preview_exports/*.mp4` 无删除路由。
- `annotation_runtime.py:79` run_dir 反查失败静默回退全局模型（无日志）。
- Agent 契约：annotation 无 capability 条目也无"刻意隐藏"的显式 parity 决策（若刻意，按 AGENTS 同步政策应补测试声明）。
- `static/flow.js` 的 unlock/impact 函数生产不可达（导航完全自由，仅 aria-disabled 拦数字人）——两套语义并存应在 docs 写明。
- 少量 innerHTML 插值未过 escHtml（`images.js:497,877,893`、`narration_audio.js:520-521` 的 URL/slideId，服务端生成值，纵深防御级别）；index.html 残留 4 处内联 handler。
- `tts_service.py:771-786` 确认运行时解析全表扫库（项目多时状态接口热点）。

## 三、勾画模块专项结论

### 3.1 与 Remotion 渲染端（AnnotationOverlay）契约一致性

**架构正确**：浏览器预览、Remotion 渲染、编辑层共享同一 UMD 采样器（`static/annotation_playback.js`，`AnnotationOverlay.tsx:9` 直接 import）。逐项核对通过：起点量化（`ceil(x*fps-1e-7)/fps` 双端等价）、栅格帧契约（`frames_needed` 与 `rasterFrameIndex` 时间基准一致、首帧空白/末帧完整有测试锁定）、每笔时序（`draw_start/end_offset_sec` 优先消费）、ink 字段替换双路径（预览 `annotation_preview_export.py:33-37` 与正式 `build_remotion_props.py:578-615` 均重写为 `{kind,frames,fps,canvas}` 且缺帧报错）、层序（overlay 在场景之上字幕/数字人之下、`pointerEvents:none`）、不透明度合成约定一致。

**两个隐患**：① 预览与正式导出是两套 props 组装实现（预览缺 `audio_tail_padding_sec` 等字段，目前靠 Remotion 默认值兜底，将来会悄然分叉）——建议预览复用 `build_slide` 组装函数；② 后端产出的 `start_frame/draw_end_frame/anchor_audio_start_sec/target_ready_sec` 渲染端完全不消费（自算量化），量化逻辑若单侧漂移不会被察觉。另见 CR-21 的**已发生**三端副本分叉实例。

### 3.2 实测补充（浏览器实测，本地真实实例）

- 同步预览假死【2/2 复现】：`annotation_preview` 任务服务端 succeeded（22:39:48、22:41:14 两次），前端分别卡在"检查同步 25%""构建画面 10%"不弹窗、不更新；「停止预览准备」按钮点击无效；重试不复用已成功任务、从头重建。与 CR-19/CR-20/CR-24 同区域，具体根因建议结合 `annotation_preview.js` 的 job 轮询与 `checks/test_annotation_save_flow.js` 红测一并排查。
- AI 勾画 plan 任务实测 6 分钟后失败（LLM 两次超时，`annotation_planner.py:98` 的预期错误路径），期间进度恒为 5%、无取消入口——属体验问题（见 UX 报告），代码侧注意 plan 失败的错误文案只保证出现在轮询终态，前端 job 状态条在假死场景下连失败也不会呈现。
- 手动闭环（框选→讲稿选词关联→音频定位→确认本页）实测全部成功；框选产生的「未关联讲稿」标注**会**立即持久化（切页往返不丢）——CR-6/P1-3 担心的 deferred 丢稿在框选路径未复现，`__deferredAdd` 路径（点文字候选新增）仍建议按 CR-23 修复。

### 3.3 测试覆盖缺口

1. 并发与锁：无任何测试覆盖"失效写页（持锁）与编辑写页的竞争"（CR-4/CR-17）。
2. 同值保存矩阵不完整：仅 style 有用例，缺 anchor/status.content/protection.locked（CR-3/CR-16）。
3. `audio_timeline.json` 异常结构 → prepare 500（CR-8）无测试。
4. export-preview 全链路（job 记录、commit/mark_succeeded 顺序、token 下载）无路由级测试。
5. `target_visibility_unresolved` 分支（CR-9）无直接单测。
6. OCR 限流重试语义（CR-11）、`_run_plan` 零新增条目（CR-14）、detect request_key 复用遇图片变更（CR-18）均无测试。
7. `checks/test_annotation_save_flow.js` 红测（CR-24）需立即修复——它是 CR-5/CR-6 的唯一回归防线。
8. 前端无"每个 ws-primary CTA 必须有绑定"守卫（CR-1 因此漏网）。

## 四、修复优先级建议

1. **立即**（流程断点/数据丢失）：CR-1（补绑定+守卫）、CR-2（provenance 口径）、CR-3+CR-16（同值保存矩阵）、CR-4+CR-17（失效持锁）、CR-5（422 死锁）、CR-24（修红测）。
2. **本迭代**：CR-6（撤销 id 漂移）、CR-7（一键步骤降级）、CR-8、CR-21（版本号+三端一致性守卫）、CR-33/CR-34/CR-35（切项目一致性：按钮复位+state 重置+flush 接线）、CR-38（一键阶段映射）、同步预览假死根因修复。
3. **排期**：CR-9~CR-15、CR-19/CR-20/CR-22/CR-23、CR-25~CR-32、CR-36~CR-41。
4. **技术债清理**：P3 各项（死代码、私有字段访问、GC、内联 handler 收编）。

---

## 五、修复记录（2026-10-19）

### P0（全部完成）

| # | 修复内容 | 位置 | 测试 |
|---|----------|------|------|
| CR-1 | Step5 主 CTA「进入旁白语音」补绑定（确认→构建切层→navigateToStep(6)）；新增「步骤主 CTA 必须有绑定」质量门守卫 | `static/event_bindings.js`、`checks/test_frontend_quality.js` | 质量门文本守卫 |
| CR-3/CR-16 | `_op_update` 的 anchor/status/protection.locked 三个分支补同值比较：同值保存不再产生 modified、不再重置已确认条目/自增 revision | `annotation_service.py` | `test_same_value_anchor_save_keeps_confirmed_state`、`test_same_value_status_and_lock_save_is_noop` |
| CR-4/CR-17 | 音频/讲稿失效写页改持 `project_artifact_lock`（`audio_artifacts_changed`、`persist_narration_beats`）；`patch_slide` 的 image/narration/beats 哈希读取移入锁内 | `invalidation_service.py`、`narration_audio_service.py`、`annotation_service.py` | 既有 272 项勾画测试全过 |
| CR-8 | `AlignmentError` 改继承 `ValueError`：时间轴结构损坏走 422 结构化错误而非裸 500 | `annotation_alignment.py` | `test_prepare_with_malformed_audio_timeline_returns_422` |
| CR-5 | 422 隔离区新增「丢弃被拒修改」出口（状态条内联按钮+确认弹窗+恢复自动保存）；`buildAnchor` 前端预校验 quote≤200；退出项目时 failedOps 不再静默丢弃（toast 提示） | `static/annotations_workspace.js`、`static/annotations.css` | save_flow 套件 |
| CR-24 | save_flow 红测修复：API 桩补 `getOptional`（缺 handler 时回退 get / 返回 success:false） | `checks/test_annotation_save_flow.js` | 套件转绿 |

### P1（全部完成）

| # | 修复内容 | 位置 | 测试 |
|---|----------|------|------|
| CR-7 | 一键完成同步改为「无降级置 completed」；`_STAGE_TO_STEP` 补 `confirm_images→4`、`tts→7` | `one_click_orchestrator.py` | `test_completion_sync_does_not_downgrade_confirmed_steps` |
| CR-38 | 前端 `STAGE_TO_STEP` 补 `annotation:10`、`digital_human:9`，运行进入这两个阶段 stepper 正确标记/跟随 | `static/one_click_extension.js` | one-click visible progress 套件 |
| CR-21 | `annotation_playback.js` 缓存版本号升级 `?v=20261019.1`；新增三端一致性守卫：源文件 mtime 新于预览 bundle 即报错要求 `npm run build:annotation-preview` 重建 | `static/index.html`、`checks/test_frontend_quality.js` | 质量门 |
| CR-34/33/35 | 切项目一致性：`resetProjectScopedAsyncUi` 复位 `state.slides/activeSlideIndex/step2ContractSha256`（字段补进 `createWorkflowState` 声明）；无条件恢复 Step6/7 四个持久按钮；新增 `flushProjectPendingEdits` 在进出工作区前冲刷 Step2/5/6/勾画 的防抖窗口编辑（`flushStep2PendingSaves` 新增并暴露，`flushStep6Autosave` 暴露） | `static/workspace_navigation.js`、`storyboard.js`、`narration_audio.js`、`workflow_state.js` | 冒烟验证字段/函数就位 |
| CR-36/37 | `saveStep5Masks` 的 `res.success===false` 分支回滚状态并提示；`renderStep5Workspace` 加空 manifest 守卫 | `static/mask_editor.js`、`static/mask_workspace.js` | JS 语法+套件 |
| CR-39 | Step 8 轮询 `res.success===false` 分支复位 loading/按钮并展示错误 | `static/output_render.js` | — |
| UX-9 | 同步预览：409 `stale_preview` 自动丢弃缓存重试一次（自愈死端）；轮询加 6 分钟超时；错误翻译（stale_preview/revision_conflict 人话文案）；关闭对话框递增 generation 修幽灵弹窗；finally 清空状态条文本防残留误读 | `static/annotation_preview.js` | 实测 2/2 弹窗成功 + 全套件 |
| CR-2 | provenance 视觉投影：`visual_slide_input` 公开共享；新增 `visual_slide_entry_hashes/visual_slide_contract_hash/contract_slide_hash_matches`；status/validate_run 双口径接受（新=投影哈希，旧=整条目哈希）；`build_visual_provenance`/拖拽换序写投影哈希；生图 `current_input_version` 改投影（narration 编辑不再触发重生成）；narration-only 迁移函数（三重证据：旧哈希匹配+投影未变+图片字节未变）挂入 `storyboard_contract_changed`（compose/手动两路共用）；reuse-image 端点落账后调 `confirm_reused_slide_image` 对齐渲染门 | `visual_provenance.py`、`storyboard_contract_diff.py`、`invalidation_service.py`、`image_workflow_service.py`、`scripts/validate_run.py`、`project_routes.py` | `test_narration_only_beat_edit_keeps_provenance_valid`、`test_visual_anchor_edit_still_invalidates_provenance`、`test_narration_only_migration_refreshes_legacy_payload`（含洗白防护）等 12 项 |

### 顺带修复的既有红测（与本轮改动无关、HEAD 上已失败）

- `checks/test_planning_error_mapping.py`：FakeProject 缺 `target_duration_sec`（870bfa9 引入的返回体读取）；且「空 slides 报 400」的断言已过时（870bfa9 起允许删空演讲稿）→ 更新为「空脚本清空链路成功」用例。
- `checks/test_storyboard_contract_atomic.py`：kwargs 精确断言补 `previous_contract`（归一化后比较）。

### 验证结果

- `python -m pytest checks/ -q`（除 ai_mask_benchmark）：**1603 passed, 8 skipped**
- 勾画专项 272 项、Agent 契约 423 项、流水线失效/provenance/一键 91 项全过
- 9 个前端 JS 套件全过；`compileall` 全过；`generate_agent_contracts.py --check` 通过
- 服务器已重启加载新代码；浏览器冒烟确认新函数/状态字段全部就位
