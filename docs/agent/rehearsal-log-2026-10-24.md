# 真实供应商演练日志（2026-10-24）

> 依据交接文档 5.1 安排的**显式、小额、一次性**真实供应商演练（用户授权）。
> 演练项目：`8adb808a_131549`（Agent 真实供应商演练-2026-10-24，3 页裁剪版）。
> 服务：`start_server.py` 单实例 + API 2.8.0，主服务在本机回环地址。
> 演练过程中发现并修复 2 个适配器缺陷、记录 5 项待修问题（见第四节）。

## 一、演练结果总览

| 指标 | 结果 |
|---|---|
| 覆盖决策 | **complete 175 → 188（+13），partial 86 → 73** |
| 真实供应商验证 | 文本 LLM（豆包/volcengine）✓、生图（ToAPIs）✓、TTS（MiniMax + 豆包音频）✓ |
| 二进制下载真实验收 | 13 项（含 5.9MB MP4、3.6MB PPTX、2.7MB 图片包、3.6MB 配置包） |
| 付费调用总计 | 生图 3 次、TTS 5 次（其中 2 次流程性失败）、LLM 约 10 次（含规划链与失败重试） |

## 二、5.1 真实供应商演练清单（逐项证据）

| 能力 | 结果 | 证据 |
|---|---|---|
| `source.set` 主题路径 | ✅ | 真实 LLM 生成文章（"三分钟看懂智能家居"） |
| `storyboard.script.execute` | ✅ | 24.6s 真实规划，17 页脚本 |
| `storyboard.visual.execute` | ✅ | 93.2s 真实可视化规划 |
| `storyboard.compose` | ✅ | 合约合成（0.6s，无需修复调用） |
| `storyboard.contract.update` | ✅ | 17→3 页裁剪的 CAS 写（基线比对、changed=true） |
| `image.generate` | ✅ ×3 | 每张 47–50s 真实生图（ToAPIs 中转） |
| `image.confirm` | ✅ | 16 页缺图被正确拦截（400 带缺失清单），补齐后通过 |
| `mask.annotate` | ✅ ×2 | 76.6s / 225.9s 真实视觉标注，3 页处理，质量状态 needs_review |
| `mask.result.update` | ✅ | 终稿保存 + `build_assets=true` 触发 Reveal 构建（8.5s） |
| `tts.synthesize` | ✅ | 异步持久任务 succeeded（32s，3 页音频），前两次失败见 4.3 |
| `tts.sync_synthesize` | ✅ | 同步合成成功 |
| `tts.audio.confirm` | ✅ ×2 | 含旁白再标注后音频确认被正确失效、重新合成再确认的完整闭环 |
| `narration.init` / `narration.annotate` | ✅ | 真实 LLM 旁白标注（65.5s） |
| `style.generate` | ✅ | 第二次调用成功（49.7s）；首次暴露业务层解析健壮性问题（4.5） |
| `annotation.jobs.submit` | ✅ | detect_text 任务对 slide_001 执行（百度 OCR 配置在位） |
| `connections.test` | ✅ ×5 | 豆包文本（"好的"）、ToAPIs 生图（真实 PNG）、MiniMax/豆包音频（真实 MP3）全部返回真实输出；codex2api 订阅过期被如实报告为失败 |
| `settings.tts.test` | ✅ | "连接成功，minimax TTS 可以正常合成音频" |
| `settings.llm.test` / `settings.image.test` | 🟡 | 适配器修复 + 类型化 422 验证；真实密钥路径由 connections.test 覆盖（测试载荷需自带密钥，服务端密钥已掩码不可回显） |
| `storyboard.execute` | 🟡 | 同链路三步已真实验证；独立复合路由待专项跑（避免覆盖演练项目合约） |
| `style.references.generate` | 🟡 | 真实调用打通但路由到**已过期的 codex2api 订阅**（403）；环境需切换默认图片供应商 |
| `digital_human.*`（4 项） | 🟡 | `digital_human.health` 返回 200 并如实报告 Worker 未运行（127.0.0.1:9001 拒绝）；维持 partial，原因不变 |

## 三、5.3 二进制下载验收（13 项真实下载）

| 能力 | 实测 |
|---|---|
| `image.get` | 1,015,830B PNG |
| `audio.get` | 306,861B MP3 |
| `video.latest` | 4,718,640B MP4 |
| `video.download` | 5,935,785B MP4（真实文件名 render_20261024_134811_c8abbc.mp4） |
| `subtitles.download` | 1,455B SRT |
| `artifact.download` | 3,645,851B PPTX（精确 artifact ID） |
| `pptx.export.download` | 3,645,851B PPTX |
| `image.download_all` | 2,777,972B ZIP |
| `mask.preview.get` | 933,632B PNG（先 `mask.preview.build`） |
| `annotation.scene_asset.get` | 1,015,830B PNG |
| `settings.config.export.zip` | 3,689,111B ZIP |
| `diagnostics.error_log.latest` | 3,497B JSON |
| `pipeline.stream` | SSE 事件流 3,238B（text/event-stream） |

维持 partial 的下载项与原因：`image.candidate.get`（生成时未带 preview，无候选图）、
`image.recovery.overlay`（无历史归档）、`style.references*.get`（参考图生成路由到过期
订阅）、`annotation.preview.download` / `annotation.ink.get` / `annotation.editor_ink.get`
（需完整勾画准备→确认链）、`global_style.reference.get` / `ip.image.get` /
`media.background_image.get`（需上传资产——multipart 上传另有
`test_transfer_client_live.py` 真 socket 验收）、`digital_human.*`（Worker 未运行）、
`settings.config.export.secrets.zip`（需 Web access token 确认）。

## 四、演练发现的真实缺陷与待修项

### 已在本变更集修复（附回归测试）

1. **`settings.llm/image/tts.test` 适配器信封错配**：直接把自由载荷 dict 传给期望
   pydantic 模型的服务。llm/image 被 service 的 try 吞成静默 `success=false`（HTTP 200），
   tts 在 try 外访问属性直接 500。修复：与 Web 路由同构，先 `model_validate`，
   校验失败返回类型化 422（含缺失字段明细）。
2. **`connections.test` 调用不存在的服务函数**：`connection_service.test_saved_model_connection`
   不存在，恒 500。修复：与 Web 路由同源，经
   `model_connection_test_service.test_saved_connection`（存储密钥真实调用供应商）。

### 记录待修（未在本变更集处理）

3. **`mask.result.update` 非原子性（P1）**：`update_step5_result` 先写
   `reveal_manifest.json` 再构建资产，构建失败不回滚——空/非法 manifest 落盘且返回
   500，项目进入损坏状态（本次演练两次踩中，靠
   `scripts/write_reveal_manifest_template.py` 重建基线恢复）。建议：先构建后落盘，
   或构建失败时回滚 manifest 写入。
4. **`video.render` 前置门禁失败返回 500**：音频未确认是 4xx 语义（前置条件不满足），
   当前包装成 `OPERATION_FAILED` 500。建议映射为 409 + 可操作错误码。
5. **错误信封未类型化残留**：`narration.annotate` 的 "Initialize step 6 first"（400）、
   `image.confirm` 的缺失页清单（400）、`annotation.preview.export` 的 revision 冲突
   （409，message 是 repr 的 dict）仍走 HTTP_ERROR 兜底。
6. **`style.generate` 业务层解析健壮性**：doubao-seed-2.0-pro 返回的
   `negative_prompt_rules` 形状不符导致解析失败（重试通过）。建议按提示词优化策略
   收紧输出契约或在解析层做形状归一。
7. **`mask.annotate` 在 reveal manifest 缺失时裸 500**：前置条件缺失应为 409 并
   指引"先完成 Step 3 确认"。

### 环境事项（非代码缺陷）

8. **默认图片供应商 codex2api 订阅已过期**（403 SUBSCRIPTION_EXPIRED）：影响
   `style.references.generate` 等按 settings 默认值解析供应商的链路；`image.generate`
   所用连接（ToAPIs 16:9）正常。**建议用户将默认图片供应商切换到可用连接。**
9. 数字人 Worker（LatentSync，127.0.0.1:9001）未运行：4 项 `digital_human.*` 维持 partial。

## 五、流程顺序备忘（对外食谱的依据）

真实执行确认的数据依赖顺序（与 `workflow-recipe.md` 对齐）：

```
source.set → storyboard.script.execute → storyboard.visual.execute
→ storyboard.compose →（合约 CAS 修改走 contract.update）
→ image.generate(逐页) → image.confirm（构建 reveal manifest）
→ mask.annotate → mask.result.update(build_assets=true)（构建 animation_timeline）
→ narration.init → narration.annotate（注意：此后音频确认会失效，需重新合成）
→ tts.synthesize → operation.get 轮询 → tts.audio.confirm
→ video.render / pptx.export.create → 轮询 → 产物下载
```

关键教训：**旁白标注会失效已确认的音频**（上游编辑失效下游，属正确行为）——
编排器应在旁白定稿后再触发 TTS。

## 六、验证

```powershell
python -m pytest checks/agent/ -q          # 778 passed
python scripts/check_agent_coverage.py     # 通过
python scripts/generate_agent_contracts.py --check   # 通过
python scripts/check_contract_version_discipline.py  # 通过（契约未变）
```
