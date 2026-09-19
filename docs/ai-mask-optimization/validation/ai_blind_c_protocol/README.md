# 阶段C盲测复跑证据（2026-09-20，11 页真实 API）

- 驱动：Temp/ppt_mask_c/drive_ai_mask_validation.py（隔离实例 :8011 + 快照库，输出 mask_c2_protocol）
- 协议变更：分页 VL 截断重试 + 动态 max_tokens；共享容器稀疏元素重绑到叙述标题组（在标题带合并之后执行）；导出器未匹配组逐组导出并记 export_notes.json。
- 结果：11 页中 9 页过门（阶段A基线为 6/8 旧集）。
  - 07_nested：由 fail → pass（title recall 0.3308 → 1.0，容器重绑生效）。
  - 10_dense_20：导出不再整页抛错，cov 1.0；残余失败为 VL 对同构卡片的整体错绑链（group_002..004 各含下一张卡元素）与 group_005/006 未匹配空掩码——归因阶段C后续/阶段D。
  - 05_pale：与首跑数字完全一致（确定性）——归因补全回路 anchor 包络非传递聚类：卡片左列元素距本组种子成员 0~3px，但距冻结包络 181px，被隔壁卡片包络（48px）抢走；修复方向为强制补全用「组内种子成员最近盒距」。
- report.json / annotate_result.json / score_stdout.txt 为本轮真实评分输出。
