# 仓库提交范围说明

本仓库只提交可复用的流程、方法论、配置、模板、schema、skill、渲染代码和长期风格参考资产。

## 可以提交

- `AGENTS.md` 中的端到端流程规则。
- `.agents/skills/**/SKILL.md` 中的阶段方法论。
- `config/**` 中的任务、风格、布局、Git 策略配置。
- `schemas/**`、`templates/**`、`checks/**` 中的结构约束、prompt 和审核规则。
- `scripts/**` 中不绑定具体选题的可复用工具和渲染能力。
- `references/style_reference/**` 中长期复用的 Image Gen 风格参考图和背景图。
- `references/iteration_lessons.md` 与 `bad_cases/bad_case_log.yaml` 中经过抽象后的问题、原因、修复方式。

## 不提交

- `runs/**`、`outputs/**`。
- 具体视频、音频、字幕、抽帧截图。
- 某个选题专属的 Image Gen 配图资产，例如 `references/generated_assets/**`。
- `.env`、API key、token 或任何真实凭证。
- 绑定具体题目正文和分镜内容的实验脚本。
