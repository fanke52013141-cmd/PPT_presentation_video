# Agent 验收推进（2026-10-29）

基线：9dc1963，API 2.8.1。覆盖目录仍为 188 complete、73 partial；本批没有将未验证能力改为 complete。

## 本批修改

- canonical 检查新增 `--level full --require-complete`，覆盖不完整立即失败；禁止 quick 宣称发布验收。
- 三项回归验证发布门禁的失败顺序、成功顺序和参数限制。
- 默认风格提示词测试改为读取内置参考 YAML，不再依赖其他场景保存的全局设置。
- PPTX 任务构造测试注入不执行任务的 executor，避免后台线程抢先改变 queued 状态。

## 检查证据

- Agent 专项：782 passed。
- canonical quick：通过，含覆盖、契约快照、版本纪律和领域检查。
- canonical full 第一轮：2009 passed、9 skipped、1 failed（默认风格测试隔离问题）。
- 修复后第二轮：2012 passed、9 skipped、1 failed（PPTX 测试线程竞态）。
- 两处修复与发布门禁专项：6 passed；ruff 通过。
- 最终全仓库 pytest：2013 passed、9 skipped、4 warnings（125.24 秒）。

## 剩余验收

73 项 partial 仍须逐项补齐业务场景证据，包括标注编辑/确认/导出、数字人、风格参考资产、图片候选与复用、配置及复合操作。
真实供应商和 Worker 的历史阻塞尚未在本批复测，不能据此宣布已解决。
最终发布须通过 `python scripts/run_checks.py --level full --require-complete`。

## 后续图片场景补齐

- 候选应用不再允许 400 也通过；按当前 version 提交，要求成功，检查主图与候选字节一致、候选被移除、音频状态保留。
- 批量删图验证两页主图、raw pair、候选及图片 registry 清理，保留原音频状态，并验证重复删除返回零。
- 对应两项覆盖升级 complete：当前 190 complete、71 partial。旧段落中的 73 是本批开始时基线。
- 上游生图/TTS 被替换，适配、业务持久化、失效及文件读写均真实执行；未增加真实供应商验收声明。
- 能力 Schema 和行为均未改动，不递增 API/behavior_version；同步生成覆盖文档。

## 项目状态 → Mask/标注 → 一键控制

实现证据集中在 `checks/agent/test_state_mask_annotation_acceptance.py`：

- 项目元数据：同值保存保持 revision 和已有文件，旧 revision 写入拒绝。
- 失效决策：reviewed 不清除待办影响；新版本仅重新打开对应页。分镜复用校验当前文章与合约哈希，过期哈希不能确认。
- Mask：草稿同值保存不改文件时间、不动音频；终稿经生产构建生成 animation timeline；修复移除已删页面，保留当前页与音频。
- 标注：版本冲突、业务校验明细、预构建和确认、同值编辑保留确认与时间轴、真实编辑清除旧时间轴、音频变化拒绝旧构建确认。
- 一键控制：真实线程启动及重复启动去重，运行中请求暂停，预检结束后在安全边界暂停，再次启动保留旧 run 的精确历史。只替换预检以控制边界，不调用付费供应商；不冒充完整生成链验收。

实际修复：标注 patch/prepare/confirm 将业务 HTTPException 转为现有类型化 Agent 错误，保留 revision 冲突和校验 issues。三个能力均升级 version 1.1 / behavior_version 2；API 2.8.2；快照、矩阵、覆盖文档与接入指南同步。

新增十项 complete：影响决策、分镜复用确认、Mask 读取/草稿/终稿/修复、标注编辑/预构建/确认、一键暂停。
当前总计 **200 complete、61 partial、1 exempt**。项目管理全字段、图像复用、标注 OCR/预览媒体和一键完整供应商生成等剩余场景不随此次控制链验收自动升级。

目标领域回归 100 passed；包含音频变化拒绝场景的最终新场景专项 6 passed。
最终 canonical full 全部通过：2020 passed、9 skipped、4 warnings（141.96 秒）；包含覆盖、生成契约一致性、版本纪律、ruff、前端检查和领域检查。
严格全开放发布仍受 61 项 partial 阻断，本批不宣称该发布已完成。

## 真实一键 → 标注 → 素材

详情见 `rehearsal-log-2026-10-29.md`。真实一键两页视频与标注预览均成功生成并下载，演练隔离于用户数据；默认图片订阅过期后在副本中切换 ToAPIs，续跑成功。

新增验收：项目参考图与 IP 素材生命周期、标注文字纠正与两类笔迹资源、真实标注预览导出下载、一键完整生成及状态。当前 **214 complete、47 partial、1 exempt**。

实际修复：整数路径参数从 Schema 到调用保持整数（包括零帧）、编辑笔迹补齐 revision 查询契约、同值文字纠正不写文件、无配置包时拒绝无法物化的项目配置覆盖项。API 2.9.0，相关能力版本和生成文件同步。

尚未由本轮证明：真实自动 OCR/AI 标注规划的质量、风格反向分析与模板完整链、数字人。默认 codex2api 仍返回订阅过期；本轮没有修改用户默认连接。

最终 canonical full 通过：**2030 passed、9 skipped、6 warnings，146.41 秒**；覆盖、生成契约、版本纪律、ruff、前端与领域检查均通过。214/47 的覆盖统计保留，严格全开放发布尚未达成。

## 自动标注闭环与提交

用户授权整理提交；上述 API 2.9.0 成果已提交为 `c492d91`。
随后完成真实 OCR → AI 规划 → Qwen 对齐 → 复核确认 → 带标注成片，详见 `automatic-annotation-closure-2026-10-29.md`。
新增修复为豆包标注请求补齐非思考模式，并在 Prompt 中保留候选行信息和连续选择规则；API 2.9.1。
最终 canonical full：**2036 passed、9 skipped、6 warnings，149.04 秒**，全部检查通过。
覆盖仍为 214 complete / 47 partial；此样例证明第二页的真实自动标注链路，不自动代表所有版式、所有供应商或所有剩余能力均已验收。
