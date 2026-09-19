# 阶段 D 真实盲测证据（11 页全过门）

运行方式：隔离实例 `:8011`（快照 DB + `PPT_STUDIO_RUNS_DIR`，禁用 one-click），
`.venv/Scripts/python.exe start_server.py` 加载阶段 D 代码，系统 python 驱动
`drive_ai_mask_validation.py` 走 API-only 盲测（`on` = 开启细粒度检测），
导出真实 Manifest RLE 后用 `ai_mask_benchmark.py` 门限评分。算法只读洗白后的
`visual_draft`，不回读 `labels.png` / `group_*.png` 标注。

## 门限与结果

门限：逐组 precision/recall ≥ 0.99，前景覆盖率 ≥ 0.995，跨组重叠前景像素 = 0。
本次 11 页 **全部过门**（`ALL_PASS true`），逐页：

| 用例 | 过门 | 覆盖率 | 最小组 IoU | 重叠像素 |
| --- | --- | --- | --- | --- |
| 01_separated | ✅ | 0.9999 | 0.9962 | 0 |
| 02_gap_8px | ✅ | 1.0000 | 0.9962 | 0 |
| 03_gap_2px | ✅ | 1.0000 | 0.9962 | 0 |
| 04_arrow_bridge | ✅ | 0.9999 | 0.9962 | 0 |
| 05_pale | ✅ | 0.9999 | 0.9962 | 0 |
| 06_dense_15 | ✅ | 1.0000 | 0.9962 | 0 |
| 07_nested | ✅ | 0.9999 | 0.9987 | 0 |
| 08_detached | ✅ | 0.9969 | 0.9898 | 0 |
| 09_pale_nested_combo | ✅ | 1.0000 | 1.0000 | 0 |
| 10_dense_20 | ✅ | 1.0000 | 1.0000 | 0 |
| 11_halo_lines | ✅ | 1.0000 | 1.0000 | 0 |

## 对比：阶段 C（9/11）→ 阶段 D（11/11）

- **05_pale**：C 阶段 precision 0.973（浅底卡片左侧外圈 6383px 被邻近组的
  冻结包络以 48px 抢走，判给 group_002）。D 后逐组 p/r 全 1.0，过门。
- **10_dense_20**：C 阶段整行五张同尺寸卡片被并入一个 rank-0 文本行对象，
  VL 拆分跨组错位导致 group_005/006 空掩码。D 后 20 组逐卡一一对应，
  全 1.0，且不再触发导出器兜底（本目录无 `export_notes_10_dense_20.json`）。
- **08_detached**：D 首轮（`mask_d_islandfix`）因改绑判定纳入“当前拥有者
  成员框距离”，使 VL 的错绑自我保护、正文碎片停错组 → group_003 recall
  跌到 0.759（回归）。定位后把 VL 纠错改绑回路改回“只看冻结包络”，
  成员框距离仅保留在残余补全回路（05 真正需要处），复跑 08 过门、05/10 不回退。

## 归因方法

05/10/08 的确定性根因先在真实运行留存的 `auto_match_before_completion.json` +
`auto_elements.json` 上离线回放 `_complete_component_coverage` /
`_semantic_objects` 复现（无 VL 抖动）：改码后回放证明 05 外圈与 08 正文均
归 `group_003`、10 得 22 个无多卡的语义对象；再以真实 11 页 API 盲测复跑验收。

`checks/test_ai_mask_semantic_protocol.py` 固化三条不变量单测：
岛状卡片行不并入文本行、成员框就近补全归本组、改绑纠错不被错绑拥有者紧邻成员框
自我保护（此测试在改坏的 group_gap 改绑版本下必然失败）。
