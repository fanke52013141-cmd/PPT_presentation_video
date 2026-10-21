# 回归基线校正（2026-10-21）

基线 commit：`a0566a8`。此前未提交的工作保留，本次仅修正确定性测试口径和清理未使用导入，不修改生产 AI Mask 算法。

## 确定性失败根因

逐项比较前一轮失败用例在两个全新目录生成的 `auto_elements.json`：`case_02_gap_4`、`case_05_fragments`、`case_09_pale` 的差异只存在于 `stage_timing_ms` 和 `stage_timings_sec`，其余字段全部一致，包括原图摘要、设置、元素 ID、边界框、逐元素精确 RLE、残余元素及像素计数。

旧测试已经排除毫秒计时，却遗漏细粒度检测新增的秒级计时，因而把预期的运行耗时波动误报为像素不确定性。

测试现只排除四个明确的耗时字段：`detect_seconds`、`elapsed_ms`、`stage_timing_ms`、`stage_timings_sec`；其余完整载荷仍逐项参与哈希比较。新增回归证明：仅改变耗时不会失败，改变 RLE 像素端点仍能检出差异，归一化比较也不修改原始结果。

## Lint 清理

16 处问题均为 F401 未使用导入，已从 9 个文件清理：

- `ai_provider_service.py`、`annotation_service.py`、`annotation_timeline.py`。
- `checks/test_annotation_bcd.py`、`checks/test_image_list_cache.py`、`checks/test_planning_error_mapping.py`、`checks/test_visual_provenance.py`。
- `scripts/seed_annotation_acceptance.py`、`scripts/watch_annotation_truth.py`。

未改变 lint 配置、排除规则或生产模型/请求响应契约。

## 设置脱敏自检修复

标准 full 首次运行已通过 AI Mask 的 12 项基准/运行器检查，随后在 `check_runtime_settings_mask.py` 遇到 `KeyError`。原因是自检循环覆盖全部注册密钥，但固定测试数据只有旧字段，漏掉了两个 OCR 密钥。正式设置接口对已有值的脱敏与占位符保护行为正确。

自检改为从 `SETTINGS_SECRET_KEYS` 构造完整的虚拟密钥数据，并验证所有密钥都不会被占位符覆盖。新增回归覆盖未来注册密钥，以及 OCR 密钥未脱敏时自检仍失败且不打印密钥值。设置服务相关 10 项测试通过，生产设置接口未改动。

## 验证范围

- `.venv/Scripts/python.exe -m ruff check .`：通过，零问题。
- 定向比较口径回归：1 passed。
- AI Mask 基准/运行器定向组合：12 passed（标准入口复跑 124.97 秒）；包括原先失败的三组图片新目录确定性检查。
- 设置脱敏自检：通过；包含新增回归的设置服务组合：17 passed。
- `scripts/run_checks.py --level full`：退出码 0，标准 full 入口通过（包含 quick、独立脚本检查及全量 pytest）。
- 该入口最后的全量 pytest：**1636 passed、1 skipped、2 warnings，290.25 秒**。警告为第三方弃用提示和 ZIP 重复文件名的预期测试提示，无失败。

标准 full 入口在执行前已指定临时 `PPT_STUDIO_DB_PATH` 和 `PPT_STUDIO_RUNS_DIR` 并初始化隔离数据库，脚本式检查及 pytest 均不使用真实项目数据。本轮不包含真实供应商调用、正式服务重启或发布。
