# OCR 与音频定位环境恢复验证（2026-10-21）

> 后续进展：用户已提供 OCR 凭据并明确暂缓人工听音；真实横竖屏 OCR/推荐/定位链路经过空间复核后完成导出。详见 [真实自动链路记录](automatic-loop-2026-10-21.md)。下文保留恢复时的运行记录。

当前状态：**Qwen 定位环境已恢复，真实定位及自动时间驱动的横竖屏导出通过；OCR 凭据、真实 AI 推荐和独立人工发音精度验收仍待完成。**

## 已完成的运行环境

- 工作器：`runtime/annotation_worker/Scripts/python.exe`，Python 3.12.13。
- 核心依赖：CPU `torch==2.8.0+cpu`、`qwen-asr==0.0.6`、`transformers==4.57.6`、`accelerate==1.12.0`、`nagisa==0.2.11`、`soynlp==0.0.493`、`librosa==0.11.0`、`soundfile==0.13.1`、`sox==1.5.0`。
- 95 个依赖通过 `uv pip check`，完整实际安装记录见 `outputs/annotation-auto-20261021/worker-installed.txt`。
- 模型：`Qwen/Qwen3-ForcedAligner-0.6B`，仍使用代码指定的不可变版本 `c7cbfc2048c462b0d63a45797104fc9db3ad62b7`。
- 默认模型目录 `runtime/annotation_models/`，无须改变应用设置或覆盖解释器路径。主应用 `.venv` 没有安装模型依赖。
- 权重来自官方 Hugging Face，不采用新版本模型或其他定位器。断点下载后与官方该版本 LFS 元数据核对：1,835,544,544 字节，SHA-256 `47831d0e82f96b20e9034dba01a075ee06436654719f6a68289e49f1b65ce0e7`。
- Windows 无符号链接权限，使用普通缓存文件。安装和下载在部署准备阶段进行；正式定位通过既有工作器的 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 及 `local_files_only=True` 执行。

官方模型及 SDK 用法来源：[Qwen 官方模型](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)、[官方定位示例](https://github.com/QwenLM/Qwen3-ASR/blob/main/examples/example_qwen3_forced_aligner.py)。本次严格使用仓库原有固定版本。

## 真实定位与导出

沿用上一轮隔离数据库和真实 MiniMax 音频；未重新合成音频，不把复用数据计作新增供应商调用。只修改隔离项目，将人工区域的触发方式由人工时间改为讲稿锚点 `核心概念`；空间目标仍为人工区域，不冒充 AI 推荐。

通过正式 `align` 任务得到有效字词时间，再走 `PATCH → preview job → confirm → Step 8 render`。两条实际定位任务均为 `succeeded / done / 100 / error=NULL`，每条 21 个有效字词区间。没有写入模拟时间、替换工作器或复用旧模型对齐缓存。

| 样本 | 定位耗时 | 模型预测的音频起点 | 30fps 成片调度起点 | 帧量化误差 |
| --- | ---: | ---: | ---: | ---: |
| 横屏 | 83.19s | 0.640s | 0.666667s | +26.6667ms |
| 竖屏 | 57.85s | 0.560s | 0.566667s | +6.6667ms |

两份预览均标记 `timing_source=qwen_alignment`，按对应 build_id 确认，正式视频成功导出。起笔前、中途、完成三帧的目标区域橙色像素分别为：横屏 `0 → 1480 → 2905`，竖屏 `0 → 1514 → 2990`。实际查看完成帧，围画包围目标，没有盖住第二行正文和字幕。

将成片 AAC 和原始 MP3 分别解码为 16kHz 单声道，进行限制在预期起点前后 250ms 的互相关检查。两个视频都测得额外音轨偏移 +42.6875ms，相关系数分别为 0.995572、0.996001。该偏移被保留记录，没有据此调整或伪造声学标签。

对起笔附近六个真实帧逐帧统计，禁用 FFmpeg 补帧，并以目标 ROI 超过 10 个橙色像素作为可见阈值：横屏首次达到阈值为第 22 帧，竖屏为第 19 帧。扣除实测音轨传输偏移后，分别比送达的模型预测起点晚 50.6458ms、30.6458ms。

这些数据验证应用如何传递和播放模型时间。**它们不证明模型定位与真实发音起点的误差已达标。**

## OCR 与独立精度的缺口

本机设置表、进程/用户/系统环境变量，以及项目凭据注册表和凭据备份中均未找到可用百度 OCR 凭据。未创建账户、编造密钥或把其他模型密钥写作百度凭据。应用设置中对应字段为“勾画标注 · 百度 OCR 密钥”，支持配置所需的 API Key/Secret Key。等待用户在本机设置中填写，密钥不应发到聊天。

由于没有真实 OCR 布局，本轮未执行 AI 自动推荐，也没有拿人工字框替代 OCR 后声称整条自动链路通过。

两条新音频没有匹配哈希的独立人工标签。`evaluate_annotation_alignment` 如实返回 `unlabelled` 两条、P50/P95 为空、`passed=false`。不以模型预测、字幕比例、帧量化误差或音频相关性作为人工真值；两个样本也不足以通过既定至少 100 条的全面精度验收。

盲听入口：[本机标记页](http://127.0.0.1:8017/)。页面不展示预测，音频 Range 请求已验证为 HTTP 206，`/predictions.json` 返回 404。审核服务器只公开 `outputs/annotation-auto-20261021/public/`，保持运行供标记使用。

标记后导出到 `outputs/annotation-auto-20261021/human-labels.json`，可执行：

```powershell
.venv/Scripts/python.exe scripts/merge_annotation_truth.py --predictions outputs/annotation-auto-20261021/predictions.json --labels outputs/annotation-auto-20261021/human-labels.json --output outputs/annotation-auto-20261021/evaluation
```

这会报告两条样本的实测误差；全面验收仍须补齐样本规模和多行、重复词、数字/英文等覆盖。

## 证据与检查

`outputs/annotation-auto-20261021/` 包含：

- `alignment-result.json`、`*-word-alignment.json`、`predictions.json`：真实任务结果与模型测量。
- `auto-timing-result.json`、`transport-result.json`：实际确认、导出、抽帧、音频传输偏移。
- `landscape-qwen-final.mp4`、`portrait-qwen-final.mp4` 及对应关键帧。
- 下载和安装日志、固定版本完整依赖记录、盲听网页及音频副本。
- 本轮验收脚本；运行数据和模型均未提交。

相关 Qwen 映射与缓存回归 `8 passed`，`git diff --check` 通过。未修改业务实现，未重跑或借用旧的全量测试数。未写入用户正式项目，未启动或重启正式应用服务；只保留本地只读盲听审核服务器。

下一步：用户补充有效 OCR 凭据后，复制必要配置到隔离测试库，执行真实 OCR → AI 推荐 → 自动定位 → 预览确认 → 导出，并核验推荐锚点和真实候选 ID；人工标签到位后计算实测误差。在这两个输入到位之前，不标记整体自动勾画验收通过。
