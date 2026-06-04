---
name: ingest-article
description: Parse an input article into a structured brief for AI science video planning.
---

# Purpose

把输入文章拆成后续分镜可用的结构化信息，包括核心论点、关键证据、术语解释、适合科普化的表达和事实风险。

# Inputs

```json
{
  "article_path": "runs/<run_id>/inputs/article.md",
  "source_links_path": "runs/<run_id>/inputs/references/source_links.md 可选",
  "task_config_path": "config/task.yaml"
}
```

# Outputs

```json
{
  "article_brief_path": "runs/<run_id>/planning/article_brief.json",
  "log_path": "runs/<run_id>/logs/generation_log.md"
}
```

`article_brief.json` 必须包含：

- `article_id`
- `title`
- `core_thesis`
- `audience_fit`
- `key_points[]`
- `terms[]`
- `source_quotes[]`
- `risk_notes[]`

# Procedure

1. 读取文章，保留标题、章节和关键段落。
2. 提炼 1 个核心论点和 5 到 10 个关键观点。
3. 为 AI 初学者重写术语解释。
4. 标记所有可能需要核查的事实和数字。
5. 输出符合 `schemas/article_brief.schema.json` 的 JSON。

# Validation

- `core_thesis` 不为空。
- `key_points` 至少 3 条。
- 每个 `key_points[]` 必须有 `claim` 和 `explain_for_beginner`。
- 不确定信息必须进入 `risk_notes`。

# Failure Handling

- 如果文章过长，先按标题和段落摘要，再进入结构化提取。
- 如果原文信息不足，输出 `risk_notes`，不要补造事实。
- 如果文章不是 AI 主题，也仍按科普视频结构提炼，但标记 `domain_mismatch`。

# Bad Case Tags

- `missing-input`
- `reference-missing`
- `content-misread`

