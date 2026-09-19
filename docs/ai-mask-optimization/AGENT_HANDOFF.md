# AI Mask 优化交接说明

这是给实施 Agent 的独立工作包。目标是改进现有 AI Mask 的“按旁白组归属像素”能力，同时保留纯白背景、原图像素、原始坐标、精确 RLE、组间零重叠和手动修正保护。

## 先做什么

1. 阅读 `README.md` 的 P0–P5 和当前基线结果。
2. 在仓库根目录运行：

```powershell
python scripts/ai_mask_benchmark.py selftest --root docs/ai-mask-optimization/validation
python -m pytest checks/test_ai_mask_benchmark_tools.py -q
```

3. 先实现 P1（保留原始组件，取消全图强闭运算造成的不可逆合并），再跑固定测试集。
4. 后续每次只改变一个阶段；不得读取 `labels.png` 或 `group_*.png` 作为算法输入。
5. 完整 AI 标注验证必须用专用测试项目和 `ai_mask_export_benchmark.py` 导出实际 Manifest RLE；不要修改真实用户项目。

## 当前已知基线

- `validation/baseline_r6/report.json`：默认闭运算半径 6。8px/2px 间隔宏 IoU 约 0.33，说明相邻组被过早粘连；浅色和公共边框也失败。
- `validation/baseline_r0/report.json`：关闭闭运算。间隔场景约 0.99，但浅色像素和公共边框仍失败，说明不能只改一个参数。
- 两组基线使用标准答案给固定组件选择最有利归属，只是检测诊断，不是完整 AI 标注准确率。

## 交付要求

- 每个算法版本必须输出版本号、设置指纹、输入图片 SHA256 和阶段耗时。
- 新逻辑必须有针对性单测，并通过现有 AI Mask 测试和本包评分器。
- 低置信度或无法拆分的区域进入人工复核，不得为了覆盖率强行吞并邻组。
- 改 Prompt 时检查真实运行时输入输出契约；模型坐标只能作为局部拆分线索，最终像素边界必须由本地确定性处理完成。
- 生产改动完成后按仓库 `AGENTS.md` 的完整验证命令执行；这份工作包本身不要求启动服务器或调用外部模型。

## 文件边界

- `scripts/ai_mask_benchmark.py`：生成标准图、评分、基线诊断。
- `scripts/ai_mask_export_benchmark.py`：只读导出生产 Manifest 的自动 RLE，不覆盖项目数据。
- `checks/test_ai_mask_benchmark_tools.py`：评分器和导出器安全回归测试。
- `validation/cases/*`：标准图片、标签、逐组答案；固定后不要修改。
- `validation/realistic/generated_stress.png`：无精确答案的生图压力样本，只能人工复核。

不要把 `validation` 下的基准报告当成生产算法最终验收；最终验收需要真实盲测页、实际渲染和人工双评。
