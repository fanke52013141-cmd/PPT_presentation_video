# 自动生成链路并发与资源抢占审核

审核日期：2026-09-16
审核范围：仅"自动生成"链路（一键生成 + 各步骤自动执行），即大模型调用、生图调用、语音合成。
不覆盖：前端渲染并发、视频渲染（已有全局闸门）、Agent HTTP 限流。

## 一、结论

当前所有**资源闸门的作用域都是"项目"或"一次调用"，没有任何一个闸门的作用域是"上游凭据 / 网关"**。
因此多账号、多项目同时自动生成时，实际并发与每分钟请求量是**各项目配额的线性叠加**：

```text
实际并发   = Σ(每个在跑项目的 image_concurrency / tts.concurrency)
实际 RPM   = Σ(每个在跑项目的 requests_per_minute) + 轮询请求 + 重试请求
```

而唯独"生图"这一路**根本没有 RPM 闸门**（只有并发数），只有被上游打回 429 之后才被动降档。
所以你说的"500/分钟被打爆、互相抢占"不是偶发故障，而是当前设计的必然结果。

## 二、现状矩阵（已核对的代码事实）

| 资源 | 项目级并发 | 项目级 RPM | 进程级全局闸门 | 跨账号/跨项目聚合上限 |
| --- | --- | --- | --- | --- |
| 大模型（Storyboard / Narration / AI Mask） | 无（同步单请求 + Mask 每项目 3 线程） | 无 | 无 | 无 |
| 生图 | 1–6（默认 5） | **无** | **无** | **无上限** |
| 语音合成 | 1–10（Seed Audio 1–5，ComfyUI 固定 1） | 1–600（默认 10，仅 MiniMax） | 仅异步任务路径：`tts_job_workers` 1–4 | **两套闸门互不相通，等于无上限** |
| 视频渲染 | 按项目锁 | — | `max_concurrent_renders` 1–3（`video_render_service.py:76-98`） | 有（这是仓库里唯一做对的范式） |

证据：

- 生图并发：`one_click_orchestrator.py:1184-1193`（`automation.image_concurrency`，默认 5、硬上限 6）；校验见 `creation_config_service.py:565-568`；默认值见 `creation_config_defaults.py:69`。
- 生图限流器：`one_click_orchestrator.py:276-310` `_AdaptiveImageLimiter` —— **在 `_run_pipeline` 内部实例化（:1244）**，即"每个项目一次运行一个实例"。
- TTS 并发与节流：`tts_service.py:550-556`、`:626-645`；`_TtsLaunchThrottle` 在 `synthesize_tts_resumable` 内部新建（`:431-445`、`:641-645`）。
- TTS 进程级闸门：`server.py:726-732`（`tts_job_workers` 默认 1、上限 4）。
- 轮询节奏：`tts_service.py:406-428` `_minimax_poll_interval_seconds` 使用**本项目**的 `worker_count` 与 `requests_per_minute` 计算。
- Mask 并发：`ai_mask_engine.py:481`，每项目 3 线程。
- 仓库内既有限流实现（可复用范式）：`agent_api/rate_limit.py`、`agent_api/rate_limit_store.py`（SQLite 持久化）。
- 历史审核已记录同类问题：`docs/code_review_2026-09-06_handoff.md:207`「主 /api 无速率限制/并发闸门（仅 agent_api 有 rate_limit.py）→ 高成本任务可被无限触发」。

## 三、问题清单

### P0-1 生图没有 RPM 闸门，只有并发闸门

`_AdaptiveImageLimiter` 只能限制"同时在飞几张"，完全无法限制"每分钟发出多少次请求"。
两个账号各跑一个 30 页项目、各 6 并发 = 12 个在飞请求，且请求以最大速率连续发出；
`500/min` 的额度只能靠上游返回 429 来"事后告知"，此时已经产生了失败与重试开销。

**影响**：直接打爆网关额度；失败重试进一步放大请求量（见 P1-4）。

### P0-2 TTS 的进程级闸门只覆盖一半路径，一键生成完全绕过

`server.py:930` 把 `synthesize_audio=synthesize_tts_resumable` 注入 `MediaPipelineOperations`，
`one_click_orchestrator.py:1449-1454` 直接调用它。
而 `TtsAsyncService`（`tts_service.py:894-907`，`max_workers=tts_job_workers`）只被前端"异步合成任务"路径使用（`tts_routes.py:26-32`，`static/narration_audio.js:439`）。

结论：**同时跑 N 个一键生成，就同时有 N 个 `synthesize_tts_resumable`，每个自带 10 个线程池和自己的节流器**，
`tts_job_workers=1` 对这条路径毫无约束。同步路由 `/steps/7/synthesize`（`tts_routes.py:18-23`）同样绕过。

**影响**：一键生成场景下 TTS 并发 = 10 × 项目数，且与手动任务叠加。

### P0-3 限流的"键"选错了：按项目计量，而额度是按凭据/网关计量的

`_TtsLaunchThrottle(60.0 / tts_requests_per_minute)` 与 `_minimax_poll_interval_seconds(...)`
都以**本项目**配置为准。N 个项目并存时，实际提交速率 = N × `requests_per_minute`，
轮询请求量 = Σ(各项目在飞任务数 / 各自轮询间隔)。

如果 N 个项目共用同一个 `credential_ref`（同一 API Key / 同一网关），上游看到的就是 N 倍流量。
即使不共用 Key，只要额度是网关级（`500/min` 通常是网关级），结论相同。

**根因**：限流器的作用域必须等于"被限流对象的作用域"。当前代码里没有任何一处是按
`provider + endpoint + 凭据` 作为键的。

### P1-1 生图只有被动降档，没有主动限速；且降档不可恢复

`_AdaptiveImageLimiter` 的行为链：

1. 正常跑满 `image_concurrency`；
2. 撞到 429 → 并发 −1（`_reduced_image_parallelism`，`:271-273`）；
3. `_attempts` 单调递增且**成功后不复位**，退避 `min(12, 2^attempts)` 秒（`:259-268`）→ 越跑越慢；
4. 并发**永不回升**，一个 run 内只降不升。

另外 `time.sleep(delay)` 是在 `finally` 释放槽位**之前**执行的（`:292-310`），
即退避中的 worker 仍然占着并发槽 —— 实际吞吐低于 `_limit` 的语义，且先退避完成的 worker
会抢在等待者之前重新拿到许可（等待者饥饿）。

### P1-2 降档到 1 之后再遇 429 会直接判死整个 run

`:299-300` 中 `if self._limit <= 1: raise`。连续 4 次限流后 `_limit` 归 1，第 5 次限流
直接抛出，`one_click_orchestrator.py:1280-1288` 把 `failures[0]` 抛出，
整个生图阶段中断（最终由质量门降级为 `paused`，需人工续跑）。

**影响**：在额度紧张时，越忙的项目越容易被整体中断，而不是"排队等一会儿"。

### P1-3 ToAPIs 的轮询请求也吃额度，但完全没有被计入

`ai_provider_service.py:382-408`：每张在飞图片每 5 秒发一次 `GET /v1/images/generations/{task_id}`。

按 30 张在飞计算：仅轮询就是 **360 请求/分钟**，再加上提交与参考图上传，
已经把 500/min 的绝大部分吃掉 —— 而使用者心里的"500/min"是"500 张图/分钟"。
另外 `:388-389` 把轮询期间的任何 4xx 直接当致命错误抛出，没有区分 429。

### P1-4 生图路径没有任何有界重试；重试还会绕过节流

- 自动路径：重试逻辑只在 `_AdaptiveImageLimiter` 里，`_limit <= 1` 即放弃（见 P1-2）。
- 手动路径：`image_workflow_service.py:719-943` **完全没有重试与限流识别**，
  上游 429 被 `:940-943` 统一包装成 `HTTPException(500, "生成图片失败: ...")` 直接抛给前端。
- TTS 路径：`tts_provider_service.py:304-389` 有 3 次重试，但
  `launch_throttle.wait_for_turn()` 在 `tts_service.py:672-673` 只对**每个 slide 任务**调用一次，
  **重试不经过节流器** —— 上游限流时，重试恰好构成请求放大。

### P1-5 没有全局调度，先启动的项目会被后启动的抢占

没有任何跨项目的排队/公平机制：`_RUNNING` 只按 `project_id` 去重（`:1558-1565`），
不同项目之间零协调。配额紧张时，后启动的项目会与已在跑的项目直接争抢，
不存在"优先级/先来先服务/配额切分"。

### P2-1 同一项目内，一键生成的 TTS 与手动异步 TTS 可以并行

`TtsAsyncService._active_job`（`tts_service.py:953-962`）只对同项目的**异步任务**去重，
它不知道一键生成正在合成同一批 slide。两者并行会重复向上游付费、并竞争写同一批音频产物
（`slides/<id>/voice.mp3` 等），而 `project_artifact_lock`（`pipeline_lifecycle.py:32-40`）
并未覆盖 TTS 合成路径。

### P2-2 大模型 / AI Mask 同样是纯线性叠加

`ai_mask_engine.py:481` 每项目 3 并发；Storyboard、Narration 是无闸门的同步请求。
你说"大模型还好"，但这是"当前额度够用"，不是"有保护"。一旦多账号同时跑满，
Mask 阶段（多模态 + 图片 payload）会是最先触发上游限流的一环。

### P2-3 编排器状态文件无锁（并发写可丢更新）

`one_click_orchestrator.py:322-344` `_write_json` 是临时文件 + `os.replace`（不会写坏），
但**没有 `pipeline_lifecycle.py:77-106` 那样的按路径写锁**，也没有 read-modify-write 保护。
worker 线程（`:1279`）与 HTTP 线程（`pause_one_click` / 状态接口）并发写同一个
`one_click_status.json` 时，存在丢更新的窗口。此问题此前已记录
（`docs/code_review_2026-09-06_handoff.md:153`），仍未修复。

## 四、根因

> 限流键（scope key）选了"项目"，而被限流对象的 scope 是"上游凭据/网关"。

在单账号单项目时代，两者等价，所以看不出问题。多账号之后两者分离，
于是每一个"局部正确"的限流器都变成了全局配额的**乘法器**。
此外，生图这一路连"局部正确"都没做到 —— 它有并发闸门，没有速率闸门。

## 五、建议方案

### 5.1 新增统一治理模块 `generation_governor.py`

约束（对齐 AGENTS.md 的边界规则）：独立于 FastAPI / 数据库 wiring / 应用模块，只接收冻结依赖。

```python
# 逻辑接口（非最终代码）
GovernorKey = tuple[str, str]        # (resource_kind, gateway_scope)
#   resource_kind: "image" | "tts" | "llm"
#   gateway_scope: 上游网关标识（base_url 的 scheme+host），**不含 api_key**
#   已确认额度是网关全局的，所以同一网关的不同 Key / 不同账号共享同一份额度，
#   必须落在同一个键上；按 Key 哈希分桶反而会各自放行、叠加超发。
#   例：("image", "https://api.toapis.com")、("tts", "https://api.minimaxi.com")

class GenerationGovernor:
    def lease(self, key, *, max_concurrency, requests_per_minute, timeout_sec) -> ContextManager
    # 语义：
    #  1) 先扣 RPM 令牌（令牌桶，平滑到每秒），再抢并发许可
    #  2) 拿不到时【排队等待】，只在超过 timeout_sec 后才抛可重试错误
    #  3) 支持 contextvar 传递"本次请求是一次重试"，重试同样扣令牌
    #  4) 记录 wait_seconds / throttled_count / rejected_count
```

要点：

1. **项目级配置降级为"子配额"**：最终生效值 = `min(全局配额, 项目配额)`。
   新增全局设置（`config_store.get_bounded_int_setting`）：
   - `image_requests_per_minute`（默认 500）、`image_max_concurrency`（默认 8~12）
   - `tts_requests_per_minute`（全局）、`tts_max_concurrency`
2. **进程内先做**：module-level 注册表 + `threading.Lock`，键为 `GovernorKey`。
3. **多进程再补**：数字人独立服务 / `uvicorn --workers>1` / CLI 场景下进程内信号量不足，
   需要持久化令牌桶。可直接复用 `agent_api/rate_limit_store.py` 的 SQLite 模式
   （表 `rate_limit_hits(client_key, ts)`），把 `client_key` 换成 `GovernorKey`。
4. **公平性**：许可按 FIFO 发放；如需账号级公平，按 `account_id` 做权重轮转。

### 5.2 接入点（改动最小、收益最大）

| 位置 | 改动 |
| --- | --- |
| `one_click_orchestrator.py:1244` | `_AdaptiveImageLimiter` 从"唯一的闸门"改为"项目内子闸门"，外层套 governor 租约；退避策略保留但要把 `_attempts` 在成功后复位、并发支持回升 |
| `image_workflow_service.py:760` 之前 | 真正发请求前 acquire（这样手动单张/批量也受保护）；同时补一个有界重试 + 429 识别 |
| `ai_provider_service.py:382-408` | 轮询间隔改为指数退避（5→10→20→30s 封顶）**并且**每次轮询前 acquire；区分 429 与致命 4xx |
| `tts_service.py:641-645` | `_TtsLaunchThrottle` 提升为 governor 的 per-credential 令牌桶，不再 per-call 新建 |
| `tts_provider_service.py:317-326` | 每次 attempt（含重试）前过闸 |
| `tts_service.py:406-428` | 轮询间隔按**全局在飞任务数**计算，而不是本项目 `worker_count` |
| `server.py:930` + `one_click_orchestrator.py:1449` | 让一键生成的 TTS 与手动异步任务共用同一闸门（或统一走 `TtsAsyncService`） |
| `ai_mask_engine.py:481` | Mask 匹配线程池外层套 governor（`resource_kind="llm"`） |

### 5.3 观测

- governor 的 `wait_seconds` / 降档事件写入 `pipeline.log`（沿用 `write_project_log` 的脱敏路径）。
- 新增只读诊断接口（`diagnostics_routes.py`）暴露各 key 的当前在飞数、令牌余量、排队长度。

### 5.4 回归测试

沿用 `checks/test_mask_build_concurrency.py` 的确定性交错手法，新增：

1. N 个线程/项目聚合请求量不超过全局 RPM 与并发上限；
2. 注入 429 后**不丢任务**（排队等待而非整体失败），且重试也计入额度；
3. 降档后能回升（避免 P1-1 的永久降档）；
4. 一键生成 TTS 与手动异步 TTS 不会同时向同一凭据提交。

## 六、已确认口径（2026-09-16）

| 项 | 确认结果 | 对设计的影响 |
| --- | --- | --- |
| 生图 500/min | **网关全局** | `credential_scope` 不需要按 API Key 哈希；**按"资源种类 + 网关"建一个进程级单例即可**，无需区分账号/Key |
| 生图主力路径 | **ToAPIs 异步任务轮询** | 轮询请求必须计入额度（见 §6.2），这是当前最大的额度漏算 |
| MiniMax RPM | **10/min（真实额度）** | 默认值 10 是对的，但**闸门算法按"1 次请求/页"计量，实际是 4 次/页**（见 §6.1） |
| 额度耗尽行为 | **排队等待** | 限流器语义必须是"阻塞排队 + 超时才报错"，不能是"降档到 1 后抛错" |
| 多进程部署 | 待定（见 §7 说明） | 若确定单进程，进程内令牌桶即足够；否则需持久化 |

### 6.1 TTS：每页真实请求数是 4，但闸门按 1 计量

MiniMax 默认走**异步**端点 `https://api.minimaxi.com/v1/t2a_async_v2`
（`database.py:174`、`tts_provider_service.py:58`、`scripts/minimax_tts.py:40`）。
`scripts/minimax_tts.py:773-784` 的异步流程每页至少发 **4 次**请求：

1. `upload_minimax_text_file` —— 上传文本，1 次；
2. `call_minimax_tts(async_payload)` —— 提交任务，1 次（`:408`）；
3. 轮询 `t2a_async_query_v2` —— 1 次以上（`:416-443`）；
4. `download_minimax_file` —— 取回音频，1 次（`:449`）。

而 `tts_service.py:641-645` 的闸门是：

```python
launch_throttle = _TtsLaunchThrottle(60.0 / tts_requests_per_minute)   # rpm=10 → 每 6 秒一页
```

即按 **10 页/分钟**放行，实际消耗 **≥40 请求/分钟**，是 10/min 额度的 **4 倍**。
再叠加 `_minimax_poll_interval_seconds` 额外索要 60% 的轮询预算（`:406-428`），
以及 `tts_provider_service.py:317` 每页 3 次重试**不过闸**，超发是必然的。

**结论：TTS 现在不是"被限流拖慢"，而是"因为超发而被限流拖慢"。**

### 6.2 生图：轮询把 500/min 吃掉一半以上

ToAPIs 一轮完整生图（`ai_provider_service.py:339-408`）：

| 步骤 | 请求数 |
| --- | --- |
| 上传参考图 | 每张 1 次（最多 3 张） |
| 提交任务 | 1 次 |
| 轮询状态 | 每 5 秒 1 次（`:403`），任务超时上限 600 秒（`:59-60`） |

按生成耗时 60 秒、3 张参考图计算：`1 + 3 + 12 = 16 请求/张` → **500/min 只能出约 31 张/分钟**。
若轮询改为指数退避（5→10→20→40 秒），同样 60 秒只需 4 次轮询：`1 + 3 + 4 = 8` → **约 62 张/分钟**。

而当前一键生成单项目只有 5–6 并发（`one_click_orchestrator.py:1184-1193`），
按 60 秒/张算是 **5–6 张/分钟**，只用到网关额度的 **约 19%**。
**所以现在的速度瓶颈是并发数，不是 500/min 的额度。**

## 七、提速方案（按收益排序）

### 7.1 TTS：把默认端点从异步改成同步 → 每页请求数 4 → 1

`scripts/minimax_tts.py:203-204` 的 `is_async_endpoint()` 只认 `t2a_async_v2`；
把端点改成 `https://api.minimaxi.com/v1/t2a_v2` 即自动走同步分支（`:785-788`），
**一次请求直接返回音频**，无需上传文本、无需轮询、无需取回文件。

- 请求成本：4+ → **1**；同样 10/min 额度下，理论页速从约 2.5 页/分钟提升到 **10 页/分钟**。
- 约束：同步端点文本上限 10,000 字符（异步 50,000，见 `:762`）——单页旁白远小于此，无影响。
- 代价：连接保持时间变长，需要确认 `STEP7_TTS_TIMEOUT_SEC`（`tts_provider_service.py:23` 为 900s）足够。

这是**配置级改动、收益最大**的一项，建议最先验证。

### 7.2 TTS：把 10/min 的预算按"提交 : 轮询"显式切分

若必须保留异步端点（例如需要 `subtitle_timestamps` 精确字幕时间戳——**这一点必须先确认**，
`scripts/minimax_tts.py:452-453` 显示异步路径才有 provider 时间戳），则：

- 每页固定成本 3 次（上传 + 提交 + 取回），10/min 额度下最多 **3 页/分钟**；
- 轮流预算只剩 1 次/分钟 → 轮询间隔必须 ≥ 同时长任务数 × 60 秒。

无论走哪条路，`60.0 / requests_per_minute` 这种"1 请求 = 1 页"的换算都必须改成
"1 页 = N 请求"的成本模型，并由 governor 统一扣令牌。

### 7.3 生图：提高并发 + 轮询退避

1. **轮询指数退避**（5→10→20→40→60 秒封顶）：请求成本降低约 50%，同时释放额度给更多并发。
2. **提高并发**：单项目 5–6 → 12–20（取决于网关的并发上限）；多项目由 governor 统一封顶。
   这一步直接把"5–6 张/分钟"推向"20–30 张/分钟"。
3. **参考图按需**：`max_reference_images` 默认 3（`image_workflow_service.py:808`），
   每多一张就多一次上传请求。风格已固定时可用 1 张。
4. **区分 429 与致命 4xx**：`ai_provider_service.py:388-389` 目前把轮询期的任何 4xx 都当致命错误，
   遇到 429 应该退避重试而不是中断任务。

### 7.4 治理器必须"排队"而不是"降档"

按确认结果，`_AdaptiveImageLimiter` 的"降档 + 不可恢复 + 归 1 即抛错"语义应当废弃，
替换为 §5.1 的 `GenerationGovernor`：先排队等令牌，超时才报可重试错误。
这样 429 只会表现为"变慢"，不会表现为"整条流水线中断"。

## 八、关于"多进程部署"

指的是同一个应用同时存在多个 Python 进程、各自都可能发起上游调用。三种典型形态：

1. **`uvicorn --workers N`** —— Web 服务多进程。本仓库用 `启动.bat:55` 的
   `python server.py` 启动（单进程），`run_local.ps1` / `start_server.py` 需一并确认。
2. **数字人独立服务** —— `启动数字人服务.cmd`、`digital_human_routes.py` 是独立端口/进程，
   如果它也调用同一网关，就不在 Web 进程的限流器管辖范围内。
3. **CLI / Agent / MCP 并发** —— `cli/pptctl`、`mcp_server/`、`agent_client/` 各自是独立进程，
   同一台机器上可同时跑。

**判定方法**：进程内令牌桶（`threading` 实现）只能管住本进程。
如果上述任一形态会与 Web 服务同时打同一个网关，就必须把令牌桶持久化
（复用 `agent_api/rate_limit_store.py` 的 SQLite 模式），否则额度仍会被多进程叠加突破。

**建议**：第一版先做进程内单例（覆盖当前 `python server.py` 单进程形态），
并在治理器里留出 `store` 抽象，后续换成 SQLite 实现时不改调用方。
