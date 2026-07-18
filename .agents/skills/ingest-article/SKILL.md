---
name: ingest-article
description: Import and validate the complete article as the single source for slide planning.
---

# Purpose

把用户输入的 Markdown 或纯文本文章完整保存为后续规划的唯一事实来源。该阶段只负责接入、保真和基本可用性检查，不生成文章摘要、不调用 LLM 提炼观点，也不提前设计 Slide。

# Inputs

```json
{
  "article_content": "用户输入的完整文章",
  "project_title": "项目标题"
}
```

# Outputs

```json
{
  "article_path": "runs/<run_id>/inputs/article.md"
}
```

接口为了兼容现有前端，可以按需返回由 `article.md` 现场计算的 `title`、`content` 和短 `summary`；这些字段不是新的持久化产物，业务主数据始终只有 `article.md`。

# Procedure

1. 检查输入不是空字符串或纯空白。
2. 保留原文标题、章节、列表、引文、数字和段落顺序，不做摘要替换。
3. 以 UTF-8 写入 `runs/<run_id>/inputs/article.md`。
4. 文章修改时，仅比较并更新 `article.md`；内容实际变化后再使下游产物失效。
5. 旧项目缺少 `article.md` 但存在 `planning/article_brief.json.content` 时，将完整内容迁移到 `article.md` 一次；不删除旧文件。

# Validation

- `article.md` 存在且内容非空。
- 保存后的文本与用户输入一致。
- 新项目不生成 `planning/article_brief.json`。
- Step 2 直接读取 `article.md`，不读取摘要作为知识来源。

# Failure Handling

- 输入为空时停止并提示用户导入有效文章。
- 旧 brief 不含完整 `content` 时，不使用其 `summary` 代替文章，继续提示缺少文章源。
- 文件无法读取或写入时返回明确错误，不静默创建空产物。

# Bad Case Tags

- `missing-input`
- `empty-article`
- `source-divergence`
- `legacy-migration-failed`
