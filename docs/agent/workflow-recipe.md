# Agent 八步工作流编排食谱（v1，审查报告 2026-10-24 B4）

> 面向外部 Agent 的长流程编排参考：从空项目到视频/PPTX 产物的最小调用序列、
> 等待与恢复约定、编辑回环。所有能力 ID 均可在
> `GET /api/agent/v1/capabilities` 检索；每一步调用前先 `GET
> /capabilities/{id}` 读取 `contract_revision`，同一能力的参数以该详情的
> `input_schema` 为准。完整语义见 `current-contract-guide.md`。

调用约定（所有步骤通用）：

```jsonc
POST /api/agent/v1/invoke
{
  "capability_id": "<id>",
  "expected_contract_revision": "<describe 返回的指纹>",
  "arguments": { "...": "..." }
}
```

409 `CONTRACT_CHANGED`（executed=false）→ 重新 describe → 重新准备参数。
写操作建议都带 `idempotency_key`（语义见指南幂等节：同键重放 7 天；
无副作用失败可同键重试；结果不明时检查状态后换新键）。

---

## 一、主流程（Step 1 → Step 8）

| 步骤 | 能力 | 说明 |
|---|---|---|
| 0. 准备 | `settings.update` | 可选：LLM/生图/TTS 供应商配置（自由载荷信封 `payload`） |
| 1. 建项目 | `project.create` | 返回 `project_id` 与初始 `revision`；此后**所有**项目级 CAS 写操作携带最新 revision |
| 2. Step 1 文章 | `source.set` | 二选一：`content` 直接导入，或 `topic` 走 LLM 生成（同步调用，进程内执行） |
| 3. Step 2 规划 | `storyboard.script.execute` → `storyboard.visual.execute` → `storyboard.compose` | 两阶段 LLM 规划 + 合约合成；手动模式可改用 `storyboard.skeleton.submit`（标题+演讲稿，跳过 LLM）。合成后 `storyboard.contract.get` 读取 `contract_sha256` 基线 |
| 4. Step 2 修改 | `storyboard.contract.update` | 一律携带 `expected_contract_sha256`（CAS）：基线不符 409 零副作用；相同内容保存返回 changed=false |
| 5. Step 3 图片 | `image.generate`（逐页）→ `image.confirm` | 生成支持幂等键与 `expected_version`；确认前可 `image.candidate.apply` / `image.order.update`（带 `order_version` CAS） |
| 6. Step 4 Mask | `mask.annotate` → `mask.result.get` → `mask.draft.update`/`mask.result.update` | 仅 reveal 演示模式项目需要；能力清单见 feature-coverage |
| 7. Step 5 音频 | `tts.synthesize` → 轮询 `operation.get` → `tts.audio.confirm` | **持久异步任务**（见下节）；确认门禁通过后才能渲染 |
| 8. Step 6 标注 | `annotation.summary.get` → `annotation.settings.update` → `annotation.jobs.submit` → `annotation.jobs.get` → `annotation.slide.patch` | 结构化补丁用 `payload` 信封 |
| 9. Step 7 数字人（可选） | `digital_human.config.update` → `digital_human.generate` / `digital_human.slide.generate` | 需外部 Worker 服务在线（`digital_human.health`） |
| 10. Step 8 输出 | `video.render` 或 `pptx.export.create` → 轮询 → `artifact.get` / 专用下载 | 两者都是持久任务；产物用精确 ID URI `ppt://projects/{id}/artifacts/{artifact_id}` |

## 二、异步任务：提交 → 轮询 → 终态

1. 提交类能力（`tts.synthesize`、`video.render`、`pptx.export.create`、
   `pipeline.run`）返回 `operation_id`：`job:<job_id>` 或 `pipeline:<run_id>`。
2. 用 `operation.get`（精确 ID，未知 404 不回退 latest）或 `operation.list`
   轮询。`status` 全集：queued / running / waiting_for_review /
   waiting_for_user / succeeded / failed / cancelled / interrupted / unknown。
3. 轮询建议间隔 2–5 秒；`unknown` 状态说明出现了未识别的 raw_status，
   立即报告而不是继续等待。
4. CLI 便捷等价：`pptctl operation wait --timeout 300`（超时只结束本地等待，
   不取消服务端任务）。
5. **进程中断恢复**：客户端崩溃后用相同幂等键重试提交类调用；
   返回 `OPERATION_OUTCOME_UNKNOWN` 时先 `operation.list` 检查原任务是否已存在，
   再决定换新键重提。
6. **取消**：TTS/视频任务支持 `operation.cancel`；其余生产者明确返回
   `CANCELLATION_UNSUPPORTED`。一键流程暂停用 `pipeline.pause`。
7. **SSE 流**：`pipeline.stream` 是事件流传输，`invocable=false`，按详情
   method/path 直连。断线后的回退约定：**轮询 `operation.list`**——流没有
   持久游标，不做断点补读。

## 三、编辑回环（影响决策）

上游内容修改后，下游产物的失效由影响登记系统驱动：

1. 修改前预检：`project.change_preview`（合约差异只读预检，不落盘）或
   `image.change_preview.get`。
2. 修改上游：`article.result.update` / `storyboard.contract.update` /
   `narration.result.update`（CAS 保护）。
3. 查看影响：`project.impacts.get` 返回受影响页面、下游失效与建议决策。
4. 决策闭环：`project.impacts.reuse_preview` → `project.impacts.decision.update`
   → 需要时 `project.impacts.reuse_confirm` / `image_reuse_confirm`。

## 四、可观测性

- `project.state`：八步_stage 级观测 + 关键文件 SHA-256 + 当前 revision +
  允许动作清单（按令牌 scope 过滤）——**推荐作为编排器的主时钟**。
- `diagnostics.runtime` / `diagnostics.governor`：生成并发与配额观测。
- `operation.list`：跨生产者的任务统一视图。

## 五、最小可运行示例（CLI）

```powershell
python -m cli.pptctl capability show project.create
python -m cli.pptctl invoke project.create --contract-revision <指纹> --arguments-file create.json
python -m cli.pptctl invoke source.set --contract-revision <指纹> --arguments-file source.json
python -m cli.pptctl operation wait --project <id> --operation-id job:<id> --timeout 300
python -m cli.pptctl artifact download --project <id> --artifact <artifact_id> --out video.mp4
```

## 六、已知边界

- LLM 生成类能力（`storyboard.script/visual.execute`、`image.generate`、
  `tts.synthesize` 等）在服务端进程内执行：客户端超时不等于服务端失败，
  恢复语义一律以幂等/operation 规则为准。
- 真实供应商验收（feature-coverage 中 partial 项）仍在推进；调用这些能力
  的结果质量依赖所配置的供应商。
- `checkpoint.approve` 的检查点在 guided/自动模式下由 `pipeline.status` 的
  waiting_for_review 状态驱动。
