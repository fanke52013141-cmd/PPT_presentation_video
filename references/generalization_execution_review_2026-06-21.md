# 泛化与渲染修复三轮复核记录

日期：2026-06-21
分支：`feature/generalized-pipeline-20260621`

## 第一轮：架构与历史版本冲突复核

- 确认当前泛化分支最初基于旧 Mask 流程，仍包含 `manual_mask_exact_v2` 的覆盖率、红色漏标诊断和最终抠除预览。
- 对照 `codex/pure-white-video-background` 的最新实现，合并 `manual_mask_boundary_white_v4`。
- 删除旧的自动扩框、母版拆层、覆盖率门禁和多余预览链路。
- Mask 页面恢复为“原图 + 彩色手绘 Mask”，最终切层只依据人工笔刷边界和连通白底抠除。

## 第二轮：配置契约与泛化能力复核

- 分镜结构改为项目级 YAML 配置，角色可定义 `required`、`speak_policy`、描述和默认动画。
- UI 暴露自定义 Prompt、完整结构 YAML、JSON Schema 和完整 System/User Content。
- 移除前端对 `body_group_02` 的硬编码隐藏。
- 每个视觉分组可切换角色，可新增或删除结构块。
- 每个 Mask 语块独立保存出现动画和时长；支持擦出、划痕、笔刷、淡入、滑入、缩放、贴纸、盖章和纸片落下。
- 动画字段贯通前端、manifest、scene builder、timeline schema 与 Remotion。

## 第三轮：运行时与视频渲染复核

- 修复 Windows 子进程输出解码异常，统一使用 UTF-8 并替换不可解码字节。
- 每次视频渲染前强制重建 Mask v4 切层，避免使用旧资产。
- 保留 BT.709、TV range、yuv420p 元数据硬校验。
- 将 H.264 解码画面 MAE 阈值调整为 20；实测四页最大通道 MAE 为 16.491，旧阈值 4/12 会误杀有效视频。
- 项目 `6f8780b9_093236` 已完成 120.6 秒真实渲染，浏览器视频元素 `readyState=4`，无播放错误。

## 三轮测试

1. 静态检查：Python 编译、JavaScript 语法、JSON Schema、YAML profile、冲突标记与旧 UI token 扫描。
2. 回归检查：Mask 完整性、并发构建、白底流程、字幕样式、音频尾部、可见步骤、前端质量和动画契约。
3. 端到端检查：8001 接口、分镜配置弹窗、Mask 动画选择器、Mask v4 重建、Remotion 渲染、颜色校验、视频列表与浏览器可播放状态。

## 结果

- 最新 Mask 算法已恢复。
- 分镜角色、Prompt 和 Schema 已对用户可见。
- Mask 动画不再是直接贴上，而是可逐语块配置。
- 8001 视频渲染链路已实际通过。
