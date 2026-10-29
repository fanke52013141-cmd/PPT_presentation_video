# 自动标注闭环验收（2026-10-29）

## 需求与验收范围

用户要求先提交既有成果，再集中推进自动标注。既有 API 2.9.0 成果已提交为 `c492d91`。
本轮继续使用独立演练项目 `5615d696_212153` 的第二页；未改用户默认连接或项目。
模型只选择强调点及其讲稿/画面对应关系；OCR、几何、音频定位、笔迹和渲染由现有业务服务负责。

## 真实问题与修复

1. **重要：供应商选项遗漏。** 分镜调用已有豆包非思考模式，自动标注却未传同一选项。真实规划两次各 180 秒超时。共享纯供应商策略后，标注显式请求关闭思考模式；格式回退与 JSON 修复也保留该选项，且每次上游请求仍独立计入 governor。关闭思考后的首次调用 6.5 秒完成。
2. **重要：连续选择上下文缺失。** OCR 候选本有 line_id，模型输入却丢弃它；提示词还未明确禁止跳过中间可见文字。首次快速返回的两条建议因 discontinuous_target / quote_mismatch 被严格拒绝，没有发布错误标注。补齐行结构和连续片段规则后，真实模型产生一条合法建议。
3. 既有码点范围、引用、目标连续性与产物哈希校验保持严格；不通过猜测偏移或填补漏选字绕过质量门。

## Prompt I/O 与最小输入

唯一默认来源：`annotation_prompt_templates.py`；项目覆盖优先于创作包，最后使用内置默认。

| 字段 | 保留原因 |
| --- | --- |
| beats：beat_id、spoken_text | 选择讲稿强调点并验证原文引用 |
| candidates：token_id、text、granularity | 选择已存在的画面文字并尊重字符/整行粒度 |
| candidates：line_id | 新增必要上下文，识别候选属于哪一行 |
| protected_items | 防止覆盖或重复建议人工修改/锁定项 |
| emphasis / max_suggestions | 使用现有密度规则及程序算出的数量上限 |

未加入坐标、多边形、原始 OCR 响应、文件哈希、音频和完整文章。输出继续使用 annotation_plan_v2，严格消费 beat_id/range/quote/目标 ID、分类、优先级、样式和复核信息。

## 完整提示词与迁移

完整增强版默认 Prompt 与组装代码见 `annotation_prompt_templates.py`，标记为 `PromptVersion: annotation_plan_v2.1`。
补充候选阅读顺序、所属行、连续选择要求，以及引用和左闭右开范围的自检规则。有效输入预览复用同一组装入口。
仅与已知上一版内置文本完全一致的存量覆盖内容采用新版；用户自定义文本保留。该识别在读取时完成，不为了预览重写用户文件。

## 真实闭环证据

- 真实百度 OCR：成功，结果保存到 text_layout.json。
- 真实 AI 规划：合法建议 1 条，选中连续七个 OCR 字符“把工具放回原位”，对应讲稿“把用过的工具放回原位”。复核确认二者语义对应。
- 本地 Qwen Forced Aligner：55 个字符时间点，正式 alignment job succeeded；未用均分时间代替。
- prepare → 复核接受 → confirm：成功，笔迹与时间轴生成。
- 项目启用标注后，真实 video.render / operation.get：succeeded，下载成功。
- 第二页事件：start 2.333333 秒，draw_end 2.933333 秒，anchor audio 2.32–3.84 秒，timing_source=qwen_alignment，needs_review=false。
- 成片：`outputs/rehearsal-20261029/automatic-annotations.mp4`，21.766667 秒、2,076,772 bytes。
- SHA-256：`a7a9c2472ea5736969853d8fa59c439eb9195ce72492ccba2c3440e842ae4884`。
- 抽查 16 秒画面，荧光笔落在目标文字上，未遮挡字幕；未进行整段主观听音验收。本片是短流程样例，不代替正式长视频验收。

## 版本、覆盖与检查

API 2.9.1；annotation.jobs.submit 和 annotation.prompts.get 均 version 1.1 / behavior_version 2；发现、快照、矩阵与接入指南同步。
没有新增业务路由。背景请求选项、Prompt 输入和预览的行为影响均纳入本轮审查。现有 214 complete / 47 partial 不因一页样例自动扩大。

新增集成场景 `checks/agent/test_automatic_annotation_chain.py`：受控 OCR/LLM，上层 Agent 调用、真实任务存储、规划、人工修改保护、构建与确认；连续两次规划超时后，已确认页面与时间轴保持原样。
供应商配置及 JSON 修复回归覆盖绑定模型优先、非豆包不传私有参数、每次请求独立治理、客户端关闭。已知内置 Prompt 迁移与自定义保护也有回归。

最终检查结果与后续提交记录见验收进度文档。
