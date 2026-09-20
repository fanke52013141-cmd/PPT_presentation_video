# HANDOFF 2026-09-20（合并进度）— origin/main W0–W5 线 × 本地阶段 A–D 线

> 前一篇：`docs/HANDOFF_2026-09-20_ai_mask.md`（T1–T8 任务定义、红线、验收门），仍然有效。
> 本文只记录**合并任务（#31）当前进度、已完成决策和剩余步骤**。
> 工作区状态：merge 尚未提交（`git status` 有大量已暂存改动 + 若干未暂存后续修正），HEAD 仍在 `e0df6da`（阶段D）。

## 1. 背景：两条线在合并什么

- **线上（origin/main，595b23b→de909ea）**：W0–W5 工程线——原子对象批处理 VL 协议（`atomic_object_matching`）、像素证据分离检测 v5（`pixel_evidence_separation`）、layout_binding_v2、provenance 审查路由、benchmark runner/metrics、object_graph、doclayout devices 等新测试。
- **本地（b8279c3→e0df6da）**：阶段 E1/A/C/D 算法线——raw/normalized 双图管线、细粒度波前检测器（`fine_grained_detection`）、分页 VL + 截断重试、跨组归属细化（envelope-only 改绑）；11 页真实 API 盲测 11/11 过门。
- 冲突文件 4 个：`ai_mask_engine.py`、`ai_mask_semantic_matcher.py`、`ai_mask_component_detection.py`、`ai_mask_contracts.py`（外加 2 个测试文件断言过时）。

## 2. 已定的整合学说（不要推翻，除非测试证明错了）

1. **调度器只留一个**：采用 origin 的原子批处理（`_plan_object_batches`/`_request_object_batch`/`_merge_batch_results` + `vision_batches` 记账 + 幻觉 ID 拒绝），叠加阶段C不变量：
   - `_plan_atomic_requests`：批数超预算时**扩大批量而不是丢弃对象**（`expanded` 尺寸 = ceil(n/max_requests)，`beyond_budget` 恒空）；
   - 单批 JSONDecodeError → **同批一次全新重试**；动态 `max_tokens = min(24000, 12000 + 600*len(batch))`；
   - 失败语义保留 origin：首批失败或任何超时 → raise（引擎回退确定性先验）；后续批失败 → 记录 `failed_batch_indices`，保留先前批结果。
   - HEAD 的整套分页（`_plan_object_pages`/`_match_page`/`_merge_page_values`/`semantic_objects_v3_paged`）**已删除**，全仓无外部消费者（已 grep 验证）。
2. **检测器双分支**：`fine_grained_detection=True` 走本地 P1 波前检测器（version `auto_elements_v4_fine_grained`，有 layout boxes 时 `layout_binding_skipped=True`）；关闭时走 origin v5 像素证据分离管线（version `auto_elements_v5_box_label_only`，逐字节保持 origin 行为）。缓存身份 = version + source_sha256 + settings_fingerprint + layout_fingerprint。
3. **引擎 slides_out** 取并集：本地 `mask_source`（raw 对来源）∪ origin `layout_detection`/`vision_status`/`cache_hit`/`timing_ms`；`stage_timing_ms`（source_hash/foreground/morphology/components）合并进 per-slide 计时。
4. **Prompt 常量**（本轮刚修完，已验证）：
   - `DEFAULT_METHODOLOGY` == origin v4（本批对象措辞）✔
   - `LEGACY_METHODOLOGY_V3` 已恢复为 origin 字节级一致（第18行 = cluster_member_count 版）✔
   - 新增 `PAGED_OBJECT_FIELD_RULE`（HEAD 分页行）、`CURRENT_OBJECT_FIELD_RULE` 改绑到 v4 行、`LEGACY_METHODOLOGY_V3_PAGED`（= V3 换分页行，字节级可由 replace 重建）✔
   - 验证脚本输出全 True：V3-equal-origin / DEFAULT-equal-origin / PAGEDV3 重建 / DEFAULT 含 CURRENT 行 / 输出结构双常量与 origin 一致。

## 3. 剩余步骤（按序执行）

### 3.1 ai_mask_config.py 迁移登记（下一步，未做）
`read_ai_mask_prompts`：
- import 增加 `LEGACY_METHODOLOGY_V3_PAGED`、`PAGED_OBJECT_FIELD_RULE`；
- 字节相等集合 {…V2, …V2Stored, LEGACY_METHODOLOGY_V3} → 追加 `LEGACY_METHODOLOGY_V3_PAGED`；
- 替换对追加 `(PAGED_OBJECT_FIELD_RULE, CURRENT_OBJECT_FIELD_RULE)`（现有 `(PREVIOUS_OBJECT_FIELD_RULE, CURRENT)` 保留，覆盖自定义编辑过的 cluster 行）。

### 3.2 刷新过时测试断言（checks/test_ai_mask_fine_grained_detection.py）
- 约 line 93 与 206：`auto_elements_v3_exact_rle_cached` → `auto_elements_v5_box_label_only`（legacy 分支默认版本号变了）；
- 约 line 198：`legacy` 分支（无 fine_grained 开关 + layout boxes）现走 origin binding_v2，元素 id 期望 `["el_layout_001"]` → 实测为单条 `el_auto_001`（按当前管线真实行为核对后再写死）；
- `test_prompt_migrates_cluster_field_rule`（约 line 274）：现语义应为——
  a) stored = `DEFAULT_METHODOLOGY.replace(CURRENT_OBJECT_FIELD_RULE, PREVIOUS_OBJECT_FIELD_RULE)` → 迁移回 DEFAULT（不再有 "page.index"）；
  b) stored = `LEGACY_METHODOLOGY_V3_PAGED` 与 `LEGACY_METHODOLOGY_V3` → 均字节级迁移到 DEFAULT；
  c) 真正的自定义文本不动。
- 若 `test_ai_mask_semantic_batches.py::test_stored_v3_builtin_migrates_but_a_custom_prompt_stays` 仍红，根因一定在 3.1/常量，不在测试。

### 3.3 回归顺序（先小后大）
1. `python -m pytest checks/test_ai_mask_semantic_batches.py checks/test_ai_mask_semantic_protocol.py checks/test_ai_mask_fine_grained_detection.py checks/test_ai_mask_automation.py -q`
2. origin 新测试：`checks/test_ai_mask_provenance.py checks/test_ai_mask_object_graph.py checks/test_ai_mask_doclayout_devices.py checks/test_ai_mask_doclayout.py checks/test_ai_mask_benchmark_metrics.py checks/test_ai_mask_benchmark_runner.py checks/test_ai_mask_services.py checks/test_ai_mask_registration.py`
3. 全部 56+ AI Mask 单测 + `node checks/test_ai_mask_auto_state.js` + `python scripts/run_checks.py` + AGENTS.md「Required Validation」清单。
4. 已知无关噪声：T8 的 `doclayout_enabled` DEFAULT True vs `_bool` fallback False（engine.py normalize 处），功能无害（raw 先 merge DEFAULT），**留待用户决策**，不在本合并处理。

### 3.4 AGENTS.md 措辞同步（合并提交前）
- 「A paged semantic-object vision match retries one truncated or malformed JSON completion…」→ 改为**逐批（per-batch）**重试语义；
- AI Mask 模块清单补 `ai_mask_object_graph.py`（origin 新增，W8/T7 也要这条，可一并做）；
- 检测缓存现在双版本（v4 fine_grained / v5 box_label_only），如提及版本处需准确。

### 3.5 提交合并（本任务终点）
- 显式列路径（含全部 `A`/`M` 文件），中文 commit message 写清两条线的整合学说（调度器归一、检测双分支、prompt 常量迁移链、盲测 11/11 在阶段D线成立）。
- **不 push**；push 需用户明确要求（origin 此前是另一条线推的，合并提交推否要问）。
- 提交前 `git status` 复查暂存清单，确认无 runs/、data/、Temp 盲测目录内容混入。

### 3.6 可选但建议：合并后 11 页盲测复跑
批处理调度器替换分页调度器后，11/11 过门结论**未在合并态下重测**。需要 :8011 隔离实例 + 真实 API 花费——**先征得用户授权再跑**（预算此前只授到阶段D验收）。

## 4. 之后：任务 #32（照原 handoff §6）
- **T1/W7**：像素阶段 numpy 重写（row-run+union-find、零新依赖、逐像素等价 golden 测试、「提速不许用漏像素换」；跑 §8 A/B 基线先，空闲机器 + ≥3GB 空闲内存）。
- **T7/W8**：Agent 契约 §9 字段暴露决策 + AGENTS.md 模块清单 + 全量发布验证（浏览器 Step3→4→5→6 + MP4）。
- **T2/T3/T5/T8**：需用户授权（≥30 页真实数据 / 付费模型调用预算 / CUDA 机器 / 两个默认值决策）。

## 5. 红线（沿袭原文，仍然全部有效）
- 只动 AI Mask 相关文件；不为迎合新算法改 baseline/fixture 答案；未测量收益只标「目标」；
- 真实模型调用需用户授权+预算；不动驱动/全局 Python/不自动装依赖/不碰 data/ 与真实 runs/；
- 测试隔离（Temp DB + `PPT_STUDIO_DB_PATH`/`PPT_STUDIO_RUNS_DIR`；:8011 实例；系统 python 做 HTTP 驱动）；算法盲测不得读 labels.png/group_*.png；
- 1920×1080 纯白外底、精确 RLE 门禁（≥99.5% 覆盖、零跨组重叠、全组件分配）、内白保护、手工笔刷优先不变；
- 依赖显式注入；server.py 不放业务函数；不用 monkey patch；一次绿单元=一个提交，显式路径，中文 message。

## 6. 工作区杂项
- Bash `/tmp` = `C:\Users\Administrator\AppData\Local\Temp`；Write 工具写 `/tmp/...` 会落到 `D:\tmp`。本合并用的临时脚本（det_head.py、det_origin.py、fine_block.py、dv4_*.txt、l3_*.txt、os_*.txt、new_detect_elements.py、assemble_det.py）在合并提交后清理（`D:\tmp` 若在本仓外则不属于仓库内容，但别把脚本混进提交）。
- 合并中给 matcher 的 `_spatial_cluster_objects` 恢复了 origin 版（回滚路径 `atomic_object_matching=false` 专用），`test_call_rollback_still_merges_objects_into_one_clustered_request` 依赖它。
