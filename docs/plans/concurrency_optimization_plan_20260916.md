# 自动生成链路并发优化方案

编制日期：2026-09-16
依据：`docs/audits/concurrency_review_2026-09-16.md`（审核结论 + 已确认口径）
范围：自动生成链路的**上游请求预算与并发治理**（生图、TTS、大模型）。不含视频渲染、前端、Agent HTTP 限流。

## 实施状态（2026-09-16 完成）

| 阶段 | 状态 | 主要产物 |
| --- | --- | --- |
| Phase 1 治理器 + 生图接入 | ✅ 已完成 | `generation_governor.py`、`checks/test_generation_governor.py`（15 项）、`checks/test_image_gateway_budget.py`（3 项集成） |
| Phase 2 TTS 成本模型 + 共用闸门 | ✅ 已完成 | `tts_service.py`、`tts_provider_service.py` |
| Phase 3 同步端点验证 | ✅ 已完成（**实测结论：不切换**） | `scripts/compare_tts_endpoints.py` |
| Phase 4 可观测与收尾 | ✅ 已完成 | `GET /api/diagnostics/generation-governor`、系统设置新增网关额度字段 |
| Phase 5 持久化令牌桶 | ✅ 已核实**不需要** | — |

**验证结果**：全量 `pytest` **950 passed / 4 failed**，4 个失败与改动前的 pristine HEAD 基线**完全一致**（`test_database_initialization`、`test_pptx_frontend`、`test_step2_reveal_intent`、`test_upload_bounded_reads`），**零回归**。
`AGENTS.md` Required Validation 的 compileall / node --check / visible-flow / 迁移 / safeguards / agent 契约 / reveal 与音频脚本检查 / `tsc --noEmit` 全部通过。

**实施中发现并修复的两个额外缺陷**（均由新增测试抓出）：

1. **ToAPIs 的 429 是以 HTTP 状态码返回的**，而 httpx 默认不对 4xx 抛异常。
   原实现的退避重试只捕获异常，因此真实的限流会绕过 AIMD 直接上抛成硬失败。
   已在 `_governed_image_request` 中同时处理"抛出的异常"与"限流状态码"（429/503）。
2. **收紧 `tts.concurrency` 校验会破坏历史配置包**：本地已有配置包存着旧默认值 10，
   校验收紧到 1–4 后项目创建直接返回 400。已改回 1–10 —— 项目值只是**请求上限**，
   真正的约束由全局闸门在运行期取 `min(全局, 项目)` 承担（见下方不变量 I2）。

## 一、目标与不变量

### 目标

| # | 目标 | 可验证的判据 |
| --- | --- | --- |
| G1 | 上游请求速率**永不超发** | 任意并发组合下，对同一网关的实测 RPM ≤ 配置值 |
| G2 | 额度耗尽时**排队而不是失败** | 不出现"降档到 1 就抛错中断整条流水线" |
| G3 | 提高吞吐（生图） | 单项目生图从 5–6 张/分提升到 ≥20 张/分 |
| G4 | 降低请求成本（TTS） | 每页上游请求数从 4+ 降到 1（同步端点路线） |
| G5 | 多账号/多项目**公平** | 先到先服务，不出现后启动项目饿死先启动项目 |
| G6 | 可观测 | 能看到每个网关的令牌余量、在飞数、排队长度、等待时长 |

### 不变量（不得破坏）

- **I1**：`generation_governor.py` 必须独立于 FastAPI、数据库 wiring、应用模块（对齐 `AGENTS.md` 的边界规则）。
- **I2**：项目级配置继续有效，作为**子配额**；生效值 = `min(全局, 项目)`。不得让项目配置放大全局额度。

  实现位置：

  | 位置 | 钳位方式 |
  | --- | --- |
  | `one_click_orchestrator.py` 生图阶段 | 线程池 `max_workers = min(项目配置, 12)`；全局并发与速率由治理器负责 |
  | `tts_service.synthesize_tts_resumable` | `worker_count = min(tts.concurrency, 待合成页数, tts_gateway_max_concurrency)` |
  | 治理器 | 令牌桶按 `(资源, 网关)` 共享，与项目无关 |

  因此**项目配置偏大不会超发**（运行期会被钳位），这也是保留
  `tts.concurrency` 1–10 校验上界、不做兼容性破坏性收紧的原因。
- **I3**：现有质量门语义不变（`pause_on_image_generation_failure` / `pause_on_tts_failure` 仍能把失败降级为 `paused`）。
- **I4**：现有校验范围不回退（`creation_config_service.py` 的边界校验只放宽、不取消）。
- **I5**：提供 kill switch，可一键退回当前行为。

## 二、决定方案形态的两个关键事实

### 事实一：生图的 HTTP 在**本进程**，可以逐请求精确扣令牌

`image_workflow_service.generate_slide_image`（`:719-943`）在 worker 线程内直接调用
`ai_provider_service.generate_toapis_image_response`（`:315-415`），三个请求点全部在进程内：

| 请求点 | 位置 | 次数 |
| --- | --- | --- |
| 上传参考图 | `ai_provider_service.py:339-352` | 每张 1 次（≤3） |
| 提交任务 | `:364` | 1 次 |
| 轮询状态 | `:382-408` | 每 5 秒 1 次 |

→ **生图可以做"精确计量"**：每次 httpx 调用前取一个令牌，调用后释放并发许可。

### 事实二：TTS 的 HTTP 在**子进程**里，父进程无法拦截

`tts_provider_service.run_tts_command_with_retries`（`:304-389`）通过
`_deps().run_subprocess(...)`（`:320`）启动 `scripts/minimax_tts.py` 子进程，
**4 次请求（上传/提交/轮询/取回）全部发生在子进程内**（`scripts/minimax_tts.py:773-784`）。

父进程只能控制两件事：

1. **什么时候启动这一页**（现有的 `_TtsLaunchThrottle`，`:641-645`）；
2. **子进程的轮询间隔**（通过环境变量 `MINIMAX_TTS_POLL_INTERVAL_SEC`，已在 `tts_service.py:669` 实现）。

→ **TTS 只能做"成本预留"**：启动一页前，按预估总请求数一次性扣掉令牌；轮询间隔由全局预算反推。
这是本方案最重要的设计约束——**不能假设所有资源都能逐请求计量**。

## 三、核心设计

### 3.1 新模块 `generation_governor.py`（约 250–320 行）

```python
"""进程级上游请求预算与并发治理。独立于 FastAPI / database / 应用模块。"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable, Iterator


@dataclass(frozen=True)
class GovernorDependencies:
    """冻结依赖：全局设置读取 + 诊断日志。"""
    get_bounded_int_setting: Callable[..., int]
    write_log: Callable[..., None] = lambda *_a, **_k: None


@dataclass(frozen=True)
class ResourceBudget:
    """一个上游网关的额度。key 不含 api_key —— 额度是网关全局的。"""
    key: tuple[str, str]        # ("image"|"tts"|"llm", gateway_host)
    max_concurrency: int
    requests_per_minute: int
    max_wait_sec: float


class GovernorTimeout(RuntimeError):
    """排队超过上限。调用方应视为"可重试的忙"，而不是永久失败。"""


class GenerationGovernor:
    # --- 两种获取方式，对应两类调用点 ---------------------------------
    @contextmanager
    def request(self, key, *, cost=1, timeout_sec=None) -> Iterator[None]:
        """短时一次性 HTTP 调用：先扣令牌，再占并发许可。用完自动归还两者。"""

    @contextmanager
    def job(self, key, *, reserved_cost, timeout_sec=None) -> Iterator[None]:
        """长时任务（TTS 子进程）：先扣预留令牌（起搏提交），再占并发许可，
        许可持有到任务结束。"""

    # --- 成本模型辅助 -------------------------------------------------
    def tts_page_cost(self, *, fixed_cost, expected_duration_sec) -> tuple[int, float]:
        """返回 (预留令牌数, 建议轮询间隔秒)。间隔由全局轮询预算反推。"""

    # --- 诊断 ---------------------------------------------------------
    def snapshot(self) -> list[dict[str, Any]]: ...


def configure_generation_governor(deps: GovernorDependencies) -> GenerationGovernor: ...
def get_generation_governor() -> GenerationGovernor: ...
def reset_generation_governor() -> None: ...   # 测试用
```

### 3.2 内部实现要点

**令牌桶（RPM）**

- `capacity = requests_per_minute`，按 `rpm/60` 每秒补充，`time.monotonic()` 计时；
- `acquire(cost, deadline)` 阻塞等待，直到令牌足够或超时；
- 支持 `cost > 1`（TTS 成本预留一次扣多个）。

**并发许可（FIFO，修 P1-5 抢占）**

- 用 `deque` 票据队列而不是裸 `Condition.wait()`：
  线程先取号入队，**只有当自己位于队首且有空闲许可时**才能通过。
- 这样修掉当前 `_AdaptiveImageLimiter` 的两个缺陷：
  1. 退避中的 worker 持有槽位不放（`one_click_orchestrator.py:292-310` 的 `finally` 在 `sleep` 之后执行）；
  2. 刚休眠醒来的 worker 抢在等待者之前重获许可（等待者饥饿）。
- 关键约定：**排队等令牌时不持有并发许可**（除 `job()` 的预留阶段），避免"占着槽位空转"。

**退避与恢复（修 P1-1）**

- 429 时按 `retry_after` 或指数退避（上限 60 秒）；
- 连续 `N` 次成功后**逐步回升**并发上限（AIMD），不再"只降不升"；
- 退避 `sleep` 期间**必须释放并发许可**，靠令牌桶本身控制速率。

**预算来源**

```python
BUDGET_SPECS = {
    ("image", "*"): ("image_gateway_requests_per_minute", 500,
                     "image_gateway_max_concurrency", 12),
    ("tts",   "*"): ("tts_gateway_requests_per_minute",   10,
                     "tts_gateway_max_concurrency",    4),
    ("llm",   "*"): ("llm_gateway_requests_per_minute",   0,   # 0 = 不限
                     "llm_gateway_max_concurrency",     8),
}
GLOBAL_MAX_WAIT_SEC_KEY = "generation_queue_max_wait_sec"      # 默认 600
GOVERNOR_ENABLED_KEY = "generation_governor_enabled"          # 默认 1（kill switch）
```

网关标识取端点 `scheme://host`（`urlparse`），例如 `("image", "https://api.toapis.com")`。
**不参与哈希 api_key**：额度是网关全局的，同一网关的不同 Key 必须共用同一份额度。

## 四、配置契约

### 4.1 新增全局设置（`settings` 表，走 `get_bounded_int_setting`）

| 键 | 默认 | 范围 | 说明 |
| --- | --- | --- | --- |
| `image_gateway_requests_per_minute` | 500 | 1–100000 | 生图网关 RPM |
| `image_gateway_max_concurrency` | 12 | 1–64 | 生图网关并发上限（**待压测确认**） |
| `tts_gateway_requests_per_minute` | 10 | 1–600 | TTS 网关 RPM（**实测就是 10**） |
| `tts_gateway_max_concurrency` | 4 | 1–16 | 同时在飞的 TTS 页数 |
| `llm_gateway_requests_per_minute` | 0 | 0–100000 | 0 = 不限（当前 LLM 不是瓶颈） |
| `generation_queue_max_wait_sec` | 600 | 5–3600 | 排队上限，超时抛 `GovernorTimeout` |
| `generation_governor_enabled` | 1 | 0/1 | kill switch |

设置表无白名单（`config_store.update_settings` 直接写键值），新增键不需要迁移。
UI 字段可作为 Phase 4 的可选项；第一版支持设置表 + 环境变量覆盖即可。

### 4.2 项目级配置：保持为子配额

| 项目配置 | 现状 | 调整 |
| --- | --- | --- |
| `automation.image_concurrency` | 默认 5，上限 6（`creation_config_service.py:565-568`） | 上限放宽到 **12**，默认仍 5 |
| `tts.concurrency` | 默认 10，上限 10（`:530-533`） | 上限收敛到 **4**（现值在 RPM=10 下毫无意义且助长超发） |
| `tts.seed_audio_concurrency` | 默认 5，上限 5 | 不变 |
| `tts.requests_per_minute` | 默认 10，上限 600（`:544-551`） | 语义改为"**本项目**可用的上限"，仍受全局 10 约束 |

生效值一律 `min(全局, 项目)`。这样多账号场景下全局额度天然共享，而单账号仍可自我限速。

## 五、分阶段实施

### Phase 1 —— 治理器 + 生图接入（最高优先级，1.5–2 天）

**新增**

- `generation_governor.py`（模块 + 冻结依赖记录）
- `checks/test_generation_governor.py`

**修改**

| 文件 | 改动 |
| --- | --- |
| `server.py` | 在组合根 `configure_generation_governor(...)`，注入 `get_bounded_int_setting` 与日志回调 |
| `ai_provider_service.py:339-352` | 每次参考图上传前 `governor.request(image_key)` |
| `ai_provider_service.py:364` | 提交任务前 `governor.request(image_key)` |
| `ai_provider_service.py:382-408` | 轮询改为**指数退避**（5→10→20→40→60 秒封顶）且每次轮询前 `governor.request(image_key)`；区分 429（退避重试）与致命 4xx |
| `image_workflow_service.py:719-943` | 覆盖手动 Step 3 单张/批量路径（补上有界重试 + 429 识别，修 P1-4 的手动路径裸奔） |
| `one_click_orchestrator.py:226-310` | `_AdaptiveImageLimiter` 降级为"项目内子闸门"：保留并发上限，去掉"降档不可恢复"和"归 1 即抛错"，外层套 `governor.request` |
| `one_click_orchestrator.py:1184-1193` | `maximum=6` → `12`；默认值随配置 |
| `creation_config_service.py:565-568` | `image_concurrency` 上限 6 → 12 |
| `static/creation_config_management.js:559` 附近 | 前端 input 上限同步（需确认对应 DOM 的 max 属性） |

**验收**

1. 单项目 30 页，实测网关 RPM ≤ 500 且**零 429**；生图速率 ≥ 20 张/分。
2. 3 个账号同时跑 30 页项目，**合计** RPM ≤ 500（这是当前完全做不到的）。
3. 人为把 `image_gateway_requests_per_minute` 设为 20，流水线变慢但**不中断**（回归 G2）。
4. `checks/test_generation_governor.py`：多线程聚合不超限、FIFO 顺序、超时抛 `GovernorTimeout`。

### Phase 2 —— TTS 成本模型 + 共用闸门（1 天）

**修改**

| 文件 | 改动 |
| --- | --- |
| `tts_service.py:641-645` | 删除 per-call 的 `_TtsLaunchThrottle`，改用 `governor.job(tts_key, reserved_cost=...)` |
| `tts_service.py:625-637` | 轮询间隔改由 `governor.tts_page_cost(...)` 从**全局**预算推导，再经 `:669` 的 env 传给子进程 |
| `tts_service.py:626` | `worker_count` 上限受 `tts_gateway_max_concurrency` 约束 |
| `tts_provider_service.py:317-326` | **每次 attempt（含重试）前** `governor.request(tts_key)`（修 P1-4：重试不过闸） |
| `server.py:930` + `one_click_orchestrator.py:1449-1454` | 一键生成的 TTS 与手动异步任务共用同一 governor（修 P0-2：`tts_job_workers` 管不到一键路径） |
| `tts_service.py:882-907` | `TtsAsyncDependencies.max_workers` 语义并入全局预算；`tts_job_workers` 降级为"项目级排队深度" |
| `creation_config_service.py:530-533` | `tts.concurrency` 上限 10 → 4 |

**成本模型（关键）**

异步端点每页固定 3 次（上传 + 提交 + 取回），加轮询：

```python
fixed_cost = 3
poll_budget = max(1, rpm - inflight * fixed_cost)       # 剩余给轮询的额度
poll_interval = max(8.0, 60.0 * inflight / poll_budget) # 全局推导，不是 per-project
reserved_cost = fixed_cost + ceil(expected_duration_sec / poll_interval)
```

以 `rpm=10`、`inflight=2` 为例：`poll_budget = 10 - 6 = 4` → `poll_interval = 30s`；
预估 40 秒完成 → `reserved_cost = 3 + 2 = 5`。
**即每页真实占用 5 个令牌，10/min 额度下最多 2 页/分钟**——这才是真实上限。
当前代码按"1 页 = 1 请求"放行 10 页/分钟，超发 4 倍。

**验收**

1. `rpm=10` 下跑 30 页，实测 RPM ≤ 10，**零 429**，且总时长可预测（≈ 15 分钟）。
2. 一键生成与手动异步任务同时提交时，两者**共享**同一额度（不叠加）。
3. 注入一次 429，验证重试也扣令牌、且任务最终成功（回归 G2）。

### Phase 3 —— 同步 TTS 端点验证（0.5 天，独立开关）✅ 已完成实测

`scripts/minimax_tts.py:203-204` 的 `is_async_endpoint()` 只认 `t2a_async_v2`；
端点改为 `https://api.minimaxi.com/v1/t2a_v2` 即自动走同步分支（`:785-788`），**每页 1 次请求**。

#### 实测结论（2026-09-16，真实 API 调用，两次独立复现）

用 `scripts/compare_tts_endpoints.py` 对同一段中文旁白跑了两个端点：

| 指标 | 异步 `t2a_async_v2` | 同步 `t2a_v2` |
| --- | --- | --- |
| 上游请求数/页 | ≥4（上传 + 提交 + 轮询 + 取回） | **1** |
| 端到端耗时 | **9.8 – 10.7 秒** | **1.4 – 1.5 秒** |
| `timing_source` | **`provider_sentence_timestamps`** | `estimated_local_audio_ffprobe` |
| 字幕分段数 | 3 | 3 |
| 音频时长 | 5.58 / 6.05 秒 | 5.83 / 5.47 秒 |

**判定：不要切换默认端点。**

同步端点虽然快约 **7 倍**、每页少发 3 次请求，但**丢失了 provider 级句子时间戳**，
字幕时间轴退化为本地估算（`estimated_local_audio_ffprobe`）。这是业务质量回退：
字幕与语音的逐句对齐会漂移。

**因此本方案不修改默认端点**，只交付：

1. 可切换能力（`tts_endpoint` 设置即可，`is_minimax_async_endpoint()` 自动适配成本模型）；
2. `scripts/compare_tts_endpoints.py` 供后续在真实素材上复检；
3. 本次实测记录（上表）。

如果将来 MiniMax 在同步端点上补齐 `subtitle_timestamps`，重跑该脚本通过后即可切换，
届时 TTS 页吞吐还能再提升约 4 倍。

**执行方式**

```powershell
python scripts/compare_tts_endpoints.py --run-dir runs/<run_id> --slide-id slide_001 --out-dir .tmp/tts_compare
```

**收益**：本轮不切换，因此 TTS 的提速来自 Phase 2 的成本模型修正（不再超发、
轮询退避）与一键路径共享全局闸门；页吞吐上限仍由 10 请求/分钟的额度决定。

### Phase 4 —— 可观测与收尾（0.5 天）

| 文件 | 改动 |
| --- | --- |
| `diagnostics_routes.py` | 新增只读 `GET /api/diagnostics/generation-governor`，返回 `snapshot()` |
| `one_click_orchestrator.py` | `write_project_log` 记录每次等待时长与排队次数 |
| `tts_service.py` / `image_workflow_service.py` | 降档、退避、超时事件落 `pipeline.log`（复用脱敏路径） |
| `checks/test_architecture_size_boundaries.py` | 若新增模块需要，登记行数上限 |
| `docs/` | 更新本方案与审核文档的实施状态 |

### Phase 5 —— 持久化令牌桶：**不需要做**（已核实，取消）

方案原本预留"若存在多进程就做持久化令牌桶"。2026-09-16 核实结论：**不需要**。

理由（逐一核对调用方）：

| 可能的第二调用方 | 实际情况 | 是否直连上游网关 |
| --- | --- | --- |
| `cli/pptctl` | 全部通过 `AgentClient(base_url=...)` 走本服务 HTTP | 否 |
| `mcp_server/` | 通过 `agent_client` 走本服务 HTTP | 否 |
| `agent_client/` | 就是本服务的 HTTP 客户端 | 否 |
| 数字人独立服务（`启动数字人服务.cmd`） | 走**本地** ComfyUI / latentsync（`digital_human_service.py:335-413`） | 否 |
| Web 服务 | `启动.bat:55` 为 `python server.py`，**单进程** | 是（唯一） |

既然只有 Web 进程会打生图 / 语音网关，**进程内单例就等价于全局唯一闸门**。
引入 SQLite 持久化令牌桶只会增加复杂度与故障面，收益为零。

**保留的扩展点**：`ai_provider_service.py` 与 `tts_service.py` 都只通过
`generation_governor.get_generation_governor()` 取用治理器。若将来出现第二个
直连上游的进程，只需在 `GenerationGovernor` 内部换成共享存储实现，
调用方代码零改动。

## 六、测试清单

### 新增

`checks/test_generation_governor.py`：

1. **聚合不超限**：N 个线程各自 `request()`，统计 60 秒窗口内通过次数 ≤ rpm。
2. **并发不超限**：同时进入 `request()` 的线程数 ≤ max_concurrency。
3. **FIFO 公平**：按入队顺序放行（对应用户可见的"先到先服务"）。
4. **排队而非失败**：额度不足时阻塞等待；`timeout_sec` 到期才抛 `GovernorTimeout`。
5. **成本预留**：`job(reserved_cost=5)` 一次扣 5 个令牌；`rpm=10` 下最多 2 个并发 job。
6. **重试也扣令牌**：模拟一次 429 后重试，令牌消耗为 2。
7. **kill switch**：`generation_governor_enabled=0` 时完全透传（不阻塞）。
8. **退避不占槽位**：模拟退避期间，其他线程仍能取得并发许可。

### 需要更新的既有测试

| 文件 | 原因 |
| --- | --- |
| `checks/test_one_click_orchestrator.py:41-78` | `_reduced_image_parallelism` / `_AdaptiveImageLimiter` 语义变更；`maximum=6` → 12 |
| `checks/test_creation_config.py`、`checks/test_creation_config_defaults.py` | 并发边界校验范围变化 |
| `checks/test_project_config_media_runtime.py:288-316` | `_bounded_tts_concurrency`、`_bounded_requests_per_minute` 的边界 |
| `checks/test_tts_provider_service.py:81-95` | 重试路径新增过闸调用 |

### 必跑（`AGENTS.md` Required Validation）

```powershell
python -m compileall -q generation_governor.py ai_provider_service.py image_workflow_service.py `
  tts_service.py tts_provider_service.py one_click_orchestrator.py server.py creation_config_service.py
python -m pytest checks/test_one_click_orchestrator.py checks/test_creation_config.py checks/test_project_config_media_runtime.py checks/test_tts_provider_service.py -q
python -m pytest checks/test_source_runtime_safeguards.py -q
python -m pytest checks/agent/ -q
node checks/test_visible_flow.js
```

外加真机验收：30 页项目的完整一键生成，检查 `pipeline.log` 中的 RPM 与等待时长。

## 七、风险与回滚

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 网关并发上限未知 | 设 12 可能仍然触发 429 | 先压测确认；`image_gateway_max_concurrency` 可在设置中实时下调 |
| 治理器成为单点瓶颈 | 全局串行化导致变慢 | 令牌桶按"网关"而非"进程"分桶；排队不影响已获许可的调用 |
| 排队导致一键生成"看起来卡住" | 用户以为死机 | Phase 4 把等待原因写入 stage message（"等待生图额度，已排队 42s"） |
| TTS 成本预估不准 | 预留过多→变慢，过少→仍超发 | 预留按 `expected_duration` 可配置；观测实际值后校准 |
| 同步 TTS 端点字幕质量退化 | 字幕与语音错位 | Phase 3 设为独立开关，对比验证通过才改默认 |
| 边界规则破坏（I1） | 架构检查失败 | 治理器不 import `server` / `database` / `get_db`；依赖走冻结记录 |

**回滚**：`generation_governor_enabled=0` 即完全退回当前行为（透传模式），无需回滚代码。

## 八、工作量与顺序

| 阶段 | 内容 | 工期 | 累计收益 |
| --- | --- | --- | --- |
| Phase 1 | 治理器 + 生图接入 | 1.5–2 天 | 生图 5–6 → ≥20 张/分；多账号不再互相打爆 |
| Phase 2 | TTS 成本模型 + 共用闸门 | 1 天 | TTS 不再超发；一键盘与手动任务共用额度 |
| Phase 3 | 同步端点验证 | 0.5 天 | TTS 页速 2 → 10 页/分（待质量验证） |
| Phase 4 | 可观测与收尾 | 0.5 天 | 可诊断、可解释 |
| Phase 5 | 持久化（按需） | 1 天 | 多进程安全 |
| **合计** | | **4.5–5 天**（不含 Phase 5） | |

## 九、不在本方案范围内

- 视频渲染并发（`max_concurrent_renders` 已正确，`video_render_service.py:76-98`）。
- Agent HTTP 限流（`agent_api/rate_limit.py` 已存在）。
- 一键生成**跨项目**调度优先级与配额切分（本方案只保证 FIFO 与全局不超发；若将来需要"账号级配额切分"再单独立项）。
- `one_click_orchestrator.py:322-344` 状态文件无锁（属并发写一致性问题，与本方案正交，建议单独修）。
- 仓库体积问题（见 `docs/audits/repo_size_review_2026-09-16.md`）。
