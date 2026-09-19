# P1 真实 AI 标注盲测（2026-09-19）

在隔离实例（:8011，DB 快照 + 临时 runs，专用测试项目，未触碰真实项目）按
README §5 通过应用 API 完整执行：创建项目 → PUT 分镜契约（按 groups.json 固定分组与旁白）
→ 上传 8 张冻结测试图 → Step3 确认 → POST /steps/5/ai-mask/annotate
（请求级 `settings.fine_grained_detection` 开关，即项目级实验开关）→
`scripts/ai_mask_export_benchmark.py` 导出真实 Manifest RLE →
`scripts/ai_mask_benchmark.py score` 评分。

- `off/`：旧全图闭运算检测（radius 6）+ 新分页匹配器。02/03/04/06/07 的三卡在检测层即被
  粘连成单组件，视觉模型正确输出 `insufficient_visual_groups_for_independent_objects`
  并拒绝硬塞，未匹配组无 RLE，评分器按空掩码计（覆盖率 0）。
- `on/`：P1 细粒度检测 + DocLayout 证据化（p1_v2）。02/03 分组不再误合并；
  06_dense_15 十五组全部匹配（宏 IoU 0.997，覆盖 0.9995，重叠 0）；
  04 箭头桥接页经投影拆分后各组可独立匹配。

两组共同的残余失败与 P1 无关，归因如下（对逐组数字负责，不掩饰）：

1. 生产上传规范化 `process_and_save_image → connected_background_mask`（自适应下限≈240）
   在检测之前就把外连通近白像素洗成 #FFFFFF：标题抗锯齿约 454px（所有页 group_001
   recall≈0.952 即来源于此），05_pale 浅灰底板整片（约 629k px，占其标准前景 89%）被洗白。
   因此 05 的端到端浅色调平测量的是上传门而非检测器；检测器侧以
   `../fine_p1_t254`（冻结原图 + oracle 归属）为准：8/8 通过。
2. 07_nested：VL 把公共外框切片匹配到了 group_002（契约要求归标题组），属语义匹配错误，
   归 P3 局部拆分/复核回路处理。
3. 08_detached：上传洗掉 1.8k 分离小碎片像素 + 残片确定性归属仍有 3% 缺口，
   属 P2 OCR/容器与 P4 边界细化的范围。

结论：P1 的通过条件（2px/8px 不误合并、标题边缘不退化、>120 候选不丢失、
覆盖/重叠门槛、超限报告）在检测层与分页链路上全部满足；端到端浅灰恢复受生产上传
规范化门限制，需要单独决策（是否放宽 `connected_background_mask` 的自适应下限），
不在本次改动范围内。
