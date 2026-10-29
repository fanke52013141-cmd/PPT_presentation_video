# 一键流程、标注与素材验收（2026-10-29）

用户明确要求真实演练。所有真实写入均在独立临时数据库、data 和 runs 中执行，通过 Agent 发现契约并 invoke；没有修改用户默认供应商，也没有启动第二个同数据服务实例。付费调用不在 pytest 中执行。

## 一键真实演练

- 文本：现有 volcengine / doubao-seed-2-1-turbo-260628。
- 默认生图 codex2api 的真实请求返回 403 / SUBSCRIPTION_EXPIRED；自动尝试一次后停止，未将认证失败当可重试错误无限请求。
- 仅在演练副本切换为已保存的 ToAPIs / gpt-image-2-vip 凭据与 endpoint 后，从失败阶段继续。
- TTS：MiniMax / speech-2.8-hd；视频：生产 Remotion。
- 成功项目：`5615d696_212153`；最终 operation：`pipeline:fbe26e252956`。
- 页数：规则请求一页，模型实际规划两页；按实际两页完成，不能把规则提示当成供应商调用数量硬上限。
- 结果：分镜 → 图片 → 图片确认 → 旁白/音频 → 音频确认 → Remotion，`succeeded / 100`。此路径为整页展示，未启用数字人。
- MP4：21.766667 秒、2,044,039 bytes；SHA-256 `82a7e3f847bc995457a53b85126ffc1aa9fb761468a3b6927f827256b061f654`。
- 本地交付：`outputs/rehearsal-20261029/final.mp4`。文件与运行证据保持忽略，不提交运行数据。

## 标注完整人工编辑路径

在同一真实项目第一页添加区域勾画，完成 patch → prepare → confirm → preview export → download。

- 确认 revision 2；timeline_built / timeline_changed 为 true。
- 真实 Remotion 标注预览下载：200、988,216 bytes、11.7 秒。
- SHA-256 `5d46a70f4c5b3248fdb17fe0e3df48b6da4040a5583d0071db1134ba61d80f7e`。
- 本地交付：`outputs/rehearsal-20261029/annotation-preview.mp4`。
- 确定性测试补齐文字布局纠正、冲突与重复保存、编辑笔迹和构建帧 PNG 读取。自动 OCR/AI 规划的真实供应商效果未由人工编辑路径代替验收。

## 素材验收与实际修复

`checks/agent/test_style_media_acceptance.py` 验证参考图上传、画布归一、读取、单张删除、全部删除；IP 上传、替换、读取、删除及跨项目隔离。

发现并修复：

1. path 参数全部按字符串建模，参考图删除把字符串传入整数业务比较并崩溃。Schema 与动态参数模型共用数值类型定义，覆盖参考图 index、标注 stroke_index/frame_index 与配置 version；整数不再进入字符串路径检查，零帧索引合法。拒绝数字字符串、布尔及小数，要求客户端按新契约传整数。
2. 编辑笔迹下载遗漏必需的 revision 查询参数；补入能力请求模型。
3. 同值文字纠正仍写文件、更新时间戳；现在返回无变化并保持文件原样。

API 升至 2.9.0；受影响能力版本与 behavior_version、发现、快照、矩阵和接入指南同步。未新增旧参数类型别名。

## 覆盖与边界

新增 14 项 complete：一键 run/status，标注文字纠正/两类笔迹/预览导出下载，项目参考图上传读取删除清空，IP 上传读取删除。
当前 **214 complete、47 partial、1 exempt**。风格反向分析、模板完整链、自动 OCR/AI 标注质量和数字人仍按各自证据验收。

演练还发现并修复：未指定配置包且账号无默认配置时，项目创建的 config_overrides/config_package_version 被忽略。现在明确返回 400，且不创建项目，附两项回归；project.create 升至 version 1.6 / behavior_version 2。项目全字段仍按独立场景验收；本次成功演练通过隔离副本设置切换供应商。

## QA 与验证

ffprobe 验证两部 MP4 可读；抽查成片 3 秒与 15 秒画面，主体、文字和字幕可见。此为两页短流程验收片，不作为 3–6 分钟正式作品验收；未进行完整主观听音评审。
详细本地元数据、文件哈希位于 `outputs/rehearsal-20261029/evidence.json`。最终全量检查结果在验收进度文档记录。
