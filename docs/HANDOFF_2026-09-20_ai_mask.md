# AI Mask 优化交接｜2026-09-20

工作包来源：`outputs/ai_mask_optimization_handoff_20260920.zip`（解包后 `AGENT_START_HERE.md` + `docs/01..05` + `fixtures/case_01..16` + `scripts/evaluate.py`）。
执行顺序：W0 → W1 → W2 → W3 → W4 → W5（当前到此），W6/W7 按失败数据触发，W8 收尾。

## 0. 一句话结论

按旁白分组的准确率已经从「线上默认（版面框开启）」的 **group recall 0.6303 / ownership IoU 0.5206** 提升到 **0.7316 / 0.6843**，越界像素下降 19.2%，缺组的案例从 12 个降到 6 个，需要复核断言通过的案例从 3/16 提升到 7/16；同时 DocLayout 的固定开销从「每页 0.5–0.8 秒」降到「整个任务只付一次」，重复标注同一张图不再跑模型。W0–W5 已提交，W6/W7/W8 未做。

## 1. 提交链与代码位置

| 提交 | 工作包 | 内容 |
| --- | --- | --- |
| `595b23b` | W0–W2 | 基准隔离运行器、阶段计时与显式降级原因、像素事实与分组假设分离、版面框候选绑定 |
| `be3a020` | W3 | 原子对象分批匹配；取消版面框对独立墨岛的强制融合 |
| `28bdb7a` | W4 | 归属证据分层（model/rule/completion/manual）+ 像素/语义双门禁 |
| 本次 | W5 | DocLayout 会话进程内复用、`doclayout_device_mode`、GPU 验证与熔断、版面框缓存、P50/P95 阶段报表 |

W5 主要文件：`ai_mask_doclayout.py`（会话/设备/缓存）、`ai_mask_engine.py`（设置项与 `_detect_layout` 接线）、`ai_mask_service.py`（降级日志带真实设备）、`checks/ai_mask_benchmark/runner.py`（阶段百分位）、`checks/test_ai_mask_doclayout_devices.py`（新增 14 个 mock 用例）。

## 2. 环境事实（后续验证前必须先核对，很多结论依赖它）

- 本机 onnxruntime 1.30.0 的可用 Provider 只有 `['AzureExecutionProvider', 'CPUExecutionProvider']`，**没有 CUDAExecutionProvider**。因此 CUDA 路径只能用 mock 验证，**真实 GPU 收益未测量**（不是「已验证无用」，是「未执行」）。
- 随仓模型存在且可跑：`tools/doclayout/doclayout_yolo_docstructbench_imgsz1024.onnx`，CPU 上单页 load≈0.6–0.8s、infer≈1.0–1.8s。
- `scipy / cv2 / skimage / numba` 均未安装，且本轮不允许自动装依赖 → W7 只能走零新增依赖的 numpy 重写路线。
- 本轮唯一对全局环境的改动：在 `.venv` 里装了 `pytest>=8.0.0`（已在 `requirements-dev.txt` 中声明）。没有改驱动、没有改全局 Python。
- 跑基准时本机内存负载 91–93%、可用提交内存约 1.0–1.8 GB。这直接导致了第 5 节记录的 `MemoryError`。

## 3. 准确率证据（16 图离线集，真模型、无旁白模型调用）

评分口径：`checks/ai_mask_benchmark/runner.py` 调用生产标注链，`truth` 来自 fixture 的答案文件；评分器**不做 group_id 最优置换匹配**，归属按 ID 直算。

| 方案 | group recall | ownership IoU | correct ownership | ink recall | 受保护白底 | 重叠像素 | 越界像素 | 复核断言通过 | 缺组案例 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 旧代码 + 版面框关（`baseline_layout_off`） | 0.7316 | 0.6843 | 0.6885 | 0.9697 | 1.0000 | 0 | 46682.1 | 7/16 | 6 |
| **旧代码 + 版面框开（`baseline_layout_on`＝线上默认）** | **0.6303** | **0.5206** | **0.5737** | 0.9697 | 1.0000 | 0 | 46682.1 | **3/16** | **12** |
| W3 + 版面框开 | 0.7316 | 0.6843 | 0.6885 | 0.9697 | 1.0000 | 0 | 37741.4 | 7/16 | 6 |
| W4 + 版面框开 | 0.7316 | 0.6843 | 0.6885 | 0.9697 | 1.0000 | 0 | 37741.4 | 7/16 | 6 |
| W5 + 版面框开 | 与 W4 **逐项相等**，且 32 个（案例×轮次）mask 指纹 0 处不一致 | | | | | | | | |

读表要点：

1. 相对线上默认，**分组准确率提升是真实的**：recall +16.1%、ownership IoU +31.4%、correct ownership +20.0%、缺组 12→6、复核断言 3→7。
2. 现在「版面框开」和「版面框关」的**分组准确率已经相同**，版面框剩下的净收益只有越界像素 46682→37741（−19.2%）。这是 §7 里 `doclayout_enabled` 默认值决策的关键事实：默认开不再是为了分组，只是为了少 19% 越界像素，而代价是每页约 1.0–1.8 秒 CPU 推理。
3. 仍未修好的硬骨头：`case_02/03`（recall 0.6667）、`case_06_nested`（0.5000、缺 2 组、越界像素 574688，单案例最差）、`case_08_repeated`（版面框关时 recall 0.2000）。
4. 覆盖率一直不是问题：`ink_recall 0.9697`、`重叠像素 0`、`受保护白底 1.0` 在所有臂都相同——像素契约始终满足 ≥99.5% 前景覆盖、零未分配组件、零跨组重叠。**准确率的损失全部在归属层，不在像素层。**

## 4. W4 交付的语义（已验证为纯增量）

W4 不改任何分组决策：16 案例 A/B 与 W3 逐项相同，且所有 mask RLE 指纹逐字节一致。它新增的是**可追溯性与门禁拆分**：

- 每个元素的归属来源被标记为 `model / rule / completion / manual`（`ASSIGNMENT_SOURCE_*` in `ai_mask_contracts.py`），每组记录 `assignment_source`、`element_origins`、`model_ownership_ratio`。
- 质量门禁拆成两个独立事实：`quality.pixel_contract_passed`（像素契约）与 `semantic_quality.narration_contract_passed`（旁白归属契约），`quality.passed` 仍是两者与，消费方无感。
- 「只有规则/覆盖闭合器支撑」的组记入 `unconfirmed_group_ids`，**但只在 `model_participated` 为真时才报警/路由复核**——否则没配视觉模型的机器会因为一个页面级事实被逐组刷出满屏复核（第一版就是这么把复核从 10 涨到 16、断言从 7 掉到 1，已修）。
- 完成器永远不能抬高置信度：`confidence_before_completion` 快照 + `confidence_capped`。
- 大组件被强制闭合（面积占比 ≥0.2）单独升级为 `forced_large_component_completed` 告警。
- 回滚开关：`provenance_review_routing`（关掉后保留全部诊断证据，只是不再据此路由复核）。

验收测试：`checks/test_ai_mask_provenance.py`（17 例）。

## 5. W5 交付与实测

实现内容：

- `doclayout_device_mode = auto|cpu|cuda`（默认 `auto`），`normalize_settings` 归一，非法值回落 `auto`。
- 会话按「模型 SHA（读不到则用路径）+ Provider 列表」在进程内缓存，同模型跨页只创建一次；`session_reused` 显式上报。
- `cpu` 模式**立即**只用 `CPUExecutionProvider`，不做任何 GPU 探测。
- GPU 必须被证明才算数：先看 `session.get_providers()` 是否真绑定了 CUDA，再喂一个 `[1,3,64,64]` 全零张量做冒烟推理。绑定失败、创建抛错、冒烟抛错（含 OOM）三类都写进 `_GPU_BREAKERS`，本进程后续页面直接走 CPU，且失败的会话会从缓存里剔除。
- 版面框按 `(图片SHA, 模型身份, 输入尺寸, conf/iou/min_area, 坐标声明, 实际Provider)` 缓存（LRU 32）。**没有图片 SHA 就不读也不写缓存**——猜身份不如重算。
- 复用的会话关闭 CPU 内存池（`enable_cpu_mem_arena=False`）：实测常驻内存 270MB→154MB，推理耗时不变。
- 每页记录 `device_mode / requested_providers / actual_providers / device_reason / session_reused / layout_cache_hit`，降级日志 `ai_mask_layout_degraded` 也带这三件设备事实。**报告的是实际跑的 Provider，不是「检测到 NVIDIA」。**

单页真实测量（本机 CPU，1920×1080，同模型）：

| 场景 | 总耗时 | 说明 |
| --- | --- | --- |
| 第 1 页 | 1610 ms | load 589 + infer 1018 |
| 第 2 页（不同图） | 1018 ms | 复用会话，只付推理 |
| 第 2 次标注同一张图 | 0 ms | 会话复用 + 版面框缓存命中，模型完全不跑 |

16 图 ×2 轮基准（`--layout on`，`w5_layout_on`）实测结果：

| 阶段 | W4 均值 | W5 均值 | W5 p50 | W5 p95 | 结论 |
| --- | --- | --- | --- | --- | --- |
| `layout_load` | 527.0 ms | **56.2 ms** | 0.2 ms | 0.3 ms | −89%，只有整个任务的第一页付会话创建 |
| `layout_infer` | 1036.2 ms | **603.9 ms** | 986.7 ms | 1321.3 ms | −42%，第 2 轮的同图全部命中版面框缓存 |
| `foreground` | 4383.7 ms | 5176.6 ms | 5231.5 ms | 6070.4 ms | W5 未触碰，涨幅是本机内存压力噪声 |
| `components` | 1989.2 ms | 2491.7 ms | 2612.5 ms | 4760.1 ms | 同上 |

- 版面框两阶段合计从约 1563 ms/页 降到约 660 ms/页，**每页省约 0.9 秒**。
- 结果中立性已证：32 个（案例×轮次）组合的 **mask RLE 指纹 0 处不一致**，八项准确率均值逐项相等，`determinism.consistent = true`。
- `foreground + components` 现在占整页约 82%，是 W7 的目标；两臂的这两项差异属于同机不同时刻的噪声（跑基准时内存负载 91–93%），不是受控对比，W7 开工前需要在空闲机器上重跑一次基线。

**W5 发现的问题（必须记录，不要掩盖）**：整臂前两次跑到 `case_04_gap_24` / `case_08_repeated` 时确定性像素阶段抛 `MemoryError`（`_connected_sets`、`_build_atom`→`_bbox_of`）。判别实验：单独跑 `case_08_repeated --layout off` **通过**（6.3s），说明不是像素阶段本身必然 OOM，而是「会话现在会活到像素阶段」叠加本机只剩 ~1.0GB 提交内存把它推过去了。已采取：关闭 CPU 内存池（270MB→154MB 常驻，省约 116MB）后，完整的 16 案例 ×2 轮臂跑通（exit 0）。**未采取：降 `input_size`、跳过版面框、捕获后静默降级——这些都是在掩盖 OOM。** 结论：会话复用带来的峰值内存上升是真实代价，可用内存低于约 3GB 时不要跑整臂；根本解法是 W7 把像素阶段的 Python 元组集合换掉（现在它有崩溃证据，不再只是「慢」）。

验收测试：`checks/test_ai_mask_doclayout_devices.py`（auto/cpu/cuda 三模式、CUDA 可列出但未绑定、CUDA 创建失败、CUDA 冒烟 OOM、CPU 也失败、空检测、推理失败、跨页会话复用、缓存命中不跑模型、缓存按阈值/设备隔离、失败会话不残留缓存、arena 关闭）。

## 6. 剩下应该做什么（按优先级，含触发条件与是否需要你授权）

1. **T1｜W7 像素阶段替换（优先级最高，因为现在有 OOM 证据）**
   证据：W4 臂 `foreground` 均值 4383ms、`components` 1989ms，占整页约 77%；且这两个阶段就是 `MemoryError` 的发生地。
   做法：`ai_mask_component_detection.py` 里 `foreground`（flood fill）与 `_connected_sets`/`_build_atom`（连通域、原子、bbox、row-run）从「Python 元组集合」改为 numpy 行程/label 实现。零新增依赖（scipy/cv2 不在），用「按行行程 + 并查集」实现连通域。
   验收硬条件：随机小图 + 病理图（大连通域、细桥、嵌套洞、贴边、单像素）对旧实现做**逐像素等价**golden 测试；固定 4/8 连通性语义；内部白色保护不变；冷/热耗时都记录。**提速不许用漏像素换。**
2. **T2｜真实业务集 ≥30 页（需要你把图拷进隔离目录）**
   现在所有结论都建立在 16 张合成 fixture 上。需要 ≥30 张真实 Step 3 产物 + 对应旁白契约，放进 `outputs/` 下的独立目录（不能碰 `runs/`、`data/`），再用同一 runner 出双臂报告。
3. **T3｜真实模型 A/B 解决归属层残余错误（需要你授权花钱）**
   `case_08_repeated / case_09_pale / case_11_sixteen / case_13_wide` 的失败在归属层，规则已到收益上限，下一步是接真视觉模型做语义消歧。
   预算口径先说清：调用次数 ≈ 页数 × 轮数 × `ceil(对象数/12)`，上限 4 次/页。需要你给网关/模型与额度，**我不会自己买服务或开新账号**。若模型不可用，本项保持「未执行」，不许写成「已验证」。
   红线：基准答案绝不进生产请求，也不许写成硬编码规则（例如绝不把 case_08 的城市名写进代码）。
4. **T4｜`case_06_nested` 容器感知切分（P5）**
   单案例最差（574688 越界像素、缺 2 组）。当前 closing 半径 15 下 16 案例里 15 个检出的组件数已 ≥ 真值组数，只有 case_06 切分不足 → 问题在「一个大组件里塞多个语义对象」，需要按版面框父子/网格做容器内二次切分。**不要**去全局改 closing 半径：半径 2 会把 case_01 过度切成 7 块、case_09 切到 25 块。
5. **T5｜真实 GPU 验收（换机器才能做）**
   在有 `CUDAExecutionProvider` 的机器上跑 `doclayout_device_mode=cuda`，产出 CPU vs CUDA 的版面框差异与下游质量差异报告 + P50/P95。当前机器只能标「未执行」。
6. **T6｜W6 OCR / 高分辨率复检（条件包，暂时不做）**
   触发条件是「失败集中在重复标签、小字、浅色内容且不是工程 bug」。目前 case_08/09/12 有这种味道，但必须先有 T3 的真模型基线，否则无法判断 OCR 的净收益。
7. **T7｜W8 契约同步与完整发布验证**
   - `checks/agent/test_contract_model_parity.py` 里给本轮所有新内部字段做「暴露或明确隐藏」的决定（清单见 §9）。目前这些字段都在 AI Mask 的不透明 payload 字典里，不在 Agent  typed 请求/响应模型中，所以 parity 测试没有报警；W8 要把这个判断显式化。
   - `AGENTS.md` 模块清单补 `ai_mask_doclayout.py`、`ai_mask_object_graph.py`。
   - 跑 §8 的完整发布验证，并**实际用浏览器走一遍 Step 3→4→5→6**，看 Mask 预览、出一个 MP4。
8. **T8｜等你拍的两个默认值决策**
   - `doclayout_enabled` 现在默认 **开**（`ai_mask_engine.py:420` 的 `normalize_settings` 兜底却是 `_bool(..., False)`，两处不一致，需要统一）。依据 §3 读表要点 2：分组准确率已不再受益于它，只省 19% 越界像素，却要为每页付 1.0–1.8s CPU。默认关可以省约 1.83s/页。
   - W7 是 numpy 重写（零依赖）还是允许装 `scipy`（`ndimage.label` 直接可用）。

## 7. 回滚

- W5 行为回滚：`doclayout_device_mode` 设 `"cpu"` → 立刻绕过一切 GPU 探测，用户结果不变；版面框缓存只影响耗时不改结果，异常时把 `detect_with_status` 的 `source_sha256` 传空即禁用。
- 整段版面框回滚：`doclayout_enabled=False`，回到纯确定性 flood-fill 路径（§3 显示分组准确率不降，只多 19% 越界像素）。
- W4 复核路由回滚：`provenance_review_routing=False`，保留诊断证据但不再据此刷复核。
- 提交级回滚：`git revert 28bdb7a`（W4）与本次 W5 提交互相独立，可单独回退。

## 8. 如何验证（可直接复制）

针对性测试（W5/W4/版面框）：

```powershell
.\.venv\Scripts\python.exe -m pytest checks/test_ai_mask_doclayout.py checks/test_ai_mask_doclayout_devices.py checks/test_ai_mask_services.py checks/test_ai_mask_automation.py checks/test_ai_mask_provenance.py checks/test_ai_mask_object_graph.py checks/test_ai_mask_semantic_batches.py checks/test_ai_mask_registration.py -q
.\.venv\Scripts\python.exe -m pytest checks/test_ai_mask_benchmark_metrics.py checks/test_ai_mask_benchmark_runner.py -q
node checks/test_ai_mask_auto_state.js
```

A/B 双臂基准（隔离目录，绝不写你的真实项目）：

```powershell
# 新版本：版面框开/关各一轮，2 次重复以验确定性
.\.venv\Scripts\python.exe -m checks.ai_mask_benchmark.runner --layout on  --repeats 2 --label w5_layout_on  --out outputs/ai_mask_benchmark_results/w5_layout_on
.\.venv\Scripts\python.exe -m checks.ai_mask_benchmark.runner --layout off --repeats 2 --label w5_layout_off --out outputs/ai_mask_benchmark_results/w5_layout_off
```

判据（任何一条不满足就是回归，不要调答案）：

- `summary.mean` 八项指标必须与上一臂一致（W5 是纯性能改动）；
- `determinism.consistent` 为 `true`（同图两次跑出相同 RLE 指纹）；
- `summary.mean.overlap_pixels_all_canvas == 0`、`protected_white_recall == 1.0`；
- `cases_requiring_review`、`cases_with_missing_groups`、`cases_passed_review_assertion` 不得变差；
- 速度看 `summary.stage_ms_percentiles`，`layout_load` 的 p50 应该≈0（只有首屏付），`layout_infer` p50 在 `--repeats 2` 下也应≈0。

跑之前先确认机器可用内存，别在 <3GB 时跑整臂（见 §5 的 `MemoryError`）：

```powershell
python -c "import ctypes;exec('class X(ctypes.Structure):\n _fields_=[(\"a\",ctypes.c_uint),(\"b\",ctypes.c_uint)]+[(\"c%d\"%i,ctypes.c_ulonglong) for i in range(7)]');s=X();s.a=ctypes.sizeof(X);ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s));print('load%',s.b,'availGB',round(s.c3/2**30,2),'commitGB',round(s.c5/2**30,2))"
```

发布级完整验证（W8 必须逐条执行并把未执行的写明原因）：

```powershell
python -m compileall -q server.py runtime_support.py ... ai_mask_config.py ai_mask_engine.py ai_mask_routes.py ai_mask_semantic_matcher.py ai_mask_service.py ... scripts checks   # 完整列表见 AGENTS.md
node --check static/workflow_state.js
node checks/test_visible_flow.js
python -m pytest checks/test_database_migrations.py checks/test_invalidation_service.py -q
python -m pytest checks/test_source_runtime_safeguards.py -q
python -m pytest checks/agent/ -q
python scripts/generate_agent_contracts.py --check
python checks/test_reveal_mask_integrity.py
python checks/test_reveal_pipeline_isolation.py
python checks/test_slide_visual_invalidation.py
python checks/test_audio_confirmation.py
python checks/test_audio_tail_padding.py
Push-Location scripts/remotion; npm install; npx tsc --noEmit -p tsconfig.json; Pop-Location
python scripts/validate_reveal_scene.py --run-dir runs/<run_id> --repo-root .
python scripts/validate_run_assets.py --run-dir runs/<run_id> --repo-root . --require-layered
```

或者一把梭：`python scripts/run_checks.py`（已注册 W4/W5 新测试文件）。

## 9. W8 待做「暴露或隐藏」决定的字段清单

`pixel_evidence_separation`、`layout_binding_v2`、`layout_merge_bound_atoms`、`bridge_pixel_count`、`source_ink_rle`、`layout_binding`、`coordinate_format`、`atomic_object_matching`、`vision_object_batch_size`、`vision_max_requests`、`layout_box_atom_count`、`bound_atom_merge`、`rejected_group_ids`、`rejected_object_ids`、`assignment_source`、`element_origins`、`semantically_confirmed`、`confidence_before_completion`、`confidence_capped`、`assignment_provenance`、`pixel_contract_passed`、`narration_contract_passed`、`unconfirmed_group_ids`、`model_ownership_ratio`、`vision_batches`、`model_participated`、`provenance_review_routing`、`doclayout_device_mode`、`session_reused`、`layout_cache_hit`、`device_reason`、`actual_providers`。

## 10. 红线（后续任何人接手都适用）

- 不得为了迎合新算法修改 baseline/fixture 答案文件。
- 覆盖率 100% 或「检测到 CUDA」都不算成功；必须分别报告语义准确率、mask 处理边界、最终渲染 alpha。
- 未测量的收益只能标成目标，不能写成已达成。
- 真实模型调用需要你的授权 + 先给 `页数×轮数×每页调用` 预算；不买服务、不开账号。
- 不动驱动、不动全局 Python、不自动装依赖、不启服务端、不碰 `data/` 与真实 `runs/`。
- 1920×1080 纯白外底、六步可见流程、精确 RLE（≥99.5% 前景覆盖、零跨组重叠、全组件分配）、内部白色保护、现有生产 Reveal builder、手工笔刷/擦除/已锁定组优先于任何 AI 重跑——全部保持不变。
- 依赖显式注入，`server.py` 不放业务函数，不用 monkey patch。
