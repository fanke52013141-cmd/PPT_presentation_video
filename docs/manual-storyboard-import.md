# 手动分镜：给 AI 的说明与导入 TXT

在第 2 步「批量导入分镜」中：

1. 点击「下载模板（含说明）」，把整个 `手动分镜模板.txt` 连同原文章或演讲稿发给 Agent / AI。
2. AI 根据材料输出分镜，最终内容仅为一个标准 JSON 数组。
3. 将输出保存为 UTF-8 的 `.txt` 文件后上传。

给 AI 的说明包含填写规则与完整示例，不能直接上传。导入器不会提取说明中的 JSON，也不会去掉代码围栏或注释。

## 一页只有一份完整演讲稿

| 字段 | 用途 |
| --- | --- |
| `main_title` | 本页显示的标题 |
| `narration` | 本页真正要朗读的完整演讲稿 |
| `segments` | 按出现顺序排列的画面与演讲稿映射 |
| `segments[].speech_segment` | 从整页演讲稿摘取的连续原文；指定讲到哪一段时显示对应画面 |

`speech_segment` 是原演讲稿的引用，不是另写一份演讲稿。全部片段按顺序拼接后必须还原整页 `narration`，不遗漏、不重复；换行与空白不影响拼接校验。同一页不能用重复片段绑定不同画面，否则后端的演讲稿去重会破坏映射。

第一个 segment 使用 `role: "title"`，只填写 `role` 和 `speech_segment`。标题文字从 `main_title` 自动取得，类型自动为文字。它对应开场或引出主题的那一段话，不要求机械朗读标题。

后续至少一个正文 segment 使用 `role: "content_body"`：

- 文字：`visual_type: "text"`，`screen_text` 填实际显示的文字。
- 画面元素：`visual_type: "picture"`，`visual_description` 描述插图、图表、流程图或场景。
- 两种类型都必须填写 `speech_segment`。需分时出现的独立视觉单元分别填写。

页数和正文元素数量由原材料决定，示例中的数量不构成限制。示例内容仅用于说明结构，不能替代用户材料。

## 唯一标准格式

导入仅使用上述字段。不接受 `title_speech_segment`、内部 ID、时间戳或说明字段；导入器确定性生成内部映射数据。非法类型、标题缺失或不在首位、片段缺失、重复片段、拼接不一致及额外字段会提示失败，不静默丢弃演讲稿。

无 `role` 的旧版 `segments`、独立的 `title_speech_segment`、`main_title + narration` 简式、`type` 字段及类型别名不再接受。正文类型必须为 `visual_type: "text"` 或 `visual_type: "picture"`。

唯一默认来源为 `static/storyboard.js` 的 `STEP2_BATCH_TEMPLATE` 和 `STEP2_BATCH_AI_GUIDE`；下载文件的说明直接引用标准 JSON 示例，页面仅保留一个下载按钮。
